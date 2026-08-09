"""Validate the proposed narrow Action mutation staging release boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "action_mutation_staging_release_contract.json"
EXPECTED_AUTHORITY = {
    "workflow_implementation_authorized": True,
    "iam_change_authorized": False,
    "artifact_upload_authorized": False,
    "change_set_creation_authorized": False,
    "change_set_execution_authorized": False,
    "operational_action_mutation_authorized": False,
    "production_change_authorized": False,
}
EXPECTED_CHANGE = {
    "action": "Modify",
    "logical_resource_id": "ActionMutationFunction",
    "resource_type": "AWS::Lambda::Function",
    "replacement": "False",
    "scope": ["Properties"],
}
EXPECTED_PHASES = [
    ("plan", False, False),
    ("prepare_change_set", True, True),
    ("execute_change_set", True, True),
    ("verify_and_canary", True, True),
]


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(contract: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "action-mutation-staging-release.v1":
        errors.append("unsupported schema_version")
    if contract.get("status") != (
        "PLAN_WORKFLOW_IMPLEMENTED_AWAITING_AWS_AUTHORITY_REVIEW"
    ):
        errors.append("release must remain plan-only and blocked on AWS authority review")
    if contract.get("business_timezone") != "Australia/Sydney":
        errors.append("business timezone must remain Australia/Sydney")
    if contract.get("evidence_boundary") != "SYNTHETIC_STAGING_ONLY":
        errors.append("release evidence must remain synthetic staging only")
    if contract.get("authority") != EXPECTED_AUTHORITY:
        errors.append("release contract expands or omits protected authority")

    ownership = contract.get("cloudformation_ownership", {})
    if ownership.get("logical_resource_id") != "ActionMutationFunction":
        errors.append("CloudFormation logical owner changed")
    if ownership.get("artifact_parameter") != "ActionMutationArtifactKey":
        errors.append("mutation artifact parameter changed")
    if ownership.get("direct_update_function_code_allowed") is not False:
        errors.append("direct Lambda code update must remain prohibited")

    design = contract.get("selected_design", {})
    if design.get("kind") != "EXISTING_STACK_PREVIOUS_TEMPLATE_PARAMETER_ONLY_CHANGE_SET":
        errors.append("selected release design changed")
    if design.get("use_previous_template") is not True:
        errors.append("release must use the previous stack template")
    if design.get("changed_parameters") != ["ActionMutationArtifactKey"]:
        errors.append("only the mutation artifact parameter may change")
    if design.get("fail_closed_on_unexpected_change") is not True:
        errors.append("unexpected change-set entries must fail closed")
    if design.get("allowed_changes") != [EXPECTED_CHANGE]:
        errors.append("change set is not limited to one non-replacing Lambda modification")

    plan_workflow = contract.get("plan_workflow", {})
    if plan_workflow != {
        "workflow": ".github/workflows/plan-action-mutation-staging.yml",
        "script": "ops/plan_action_mutation_staging_release.ps1",
        "trigger": "workflow_dispatch_only",
        "aws_access": "READ_ONLY_INSPECTION",
        "implemented": True,
    }:
        errors.append("plan workflow contract is incomplete or expanded")

    phases = [
        (
            phase.get("id"),
            phase.get("aws_write"),
            phase.get("human_approval_required"),
        )
        for phase in contract.get("release_phases", [])
    ]
    if phases != EXPECTED_PHASES:
        errors.append("release phases or human approval gates changed")

    blockers = contract.get("current_blockers", {})
    if blockers.get("repository_deployer_policy_includes_mutation_function") is not False:
        errors.append("repository deployer-policy gap is hidden")
    if blockers.get("actual_aws_permissions_reviewed") is not False:
        errors.append("contract cannot claim unrecorded AWS permission review")
    if blockers.get("narrow_workflow_implemented") is not True:
        errors.append("implemented plan workflow is not recorded")

    rollback = contract.get("rollback", {})
    required_rollback = (
        "previous_artifact_parameter_required",
        "previous_code_sha256_required",
        "same_single_resource_guard_required",
        "package_rollback_requires_zero_edit_events",
    )
    if not all(rollback.get(field) is True for field in required_rollback):
        errors.append("rollback evidence or single-resource guard is incomplete")
    if rollback.get("audit_event_deletion_allowed") is not False:
        errors.append("rollback cannot delete audit evidence")
    if rollback.get("schema_column_drop_allowed") is not False:
        errors.append("rollback cannot drop assignment columns")

    template = (root / "infrastructure" / "stateful-lifecycle-staging.yaml").read_text(
        encoding="utf-8"
    )
    if "  ActionMutationFunction:" not in template:
        errors.append("stateful stack no longer owns ActionMutationFunction")
    if "  ActionMutationArtifactKey:" not in template:
        errors.append("stateful stack lacks the mutation artifact parameter")
    deployer = (
        root / "ops" / "configure_stateful_lifecycle_deployer.ps1"
    ).read_text(encoding="utf-8")
    if "ActionMutationFunctionName" in deployer or "ActionMutationRoleName" in deployer:
        errors.append("repository policy changed without updating the reviewed blocker")
    workflow = (
        root / ".github" / "workflows" / "plan-action-mutation-staging.yml"
    ).read_text(encoding="utf-8")
    script = (
        root / "ops" / "plan_action_mutation_staging_release.ps1"
    ).read_text(encoding="utf-8")
    if "workflow_dispatch:" not in workflow:
        errors.append("plan workflow is not manually triggered")
    if "  push:" in workflow or "  schedule:" in workflow:
        errors.append("plan workflow cannot run on push or schedule")
    if "contents: read" not in workflow or "id-token: write" not in workflow:
        errors.append("plan workflow permissions are incomplete")
    if "-InspectAws" not in workflow or "AWS_STAGING_ROLE_ARN" not in workflow:
        errors.append("plan workflow lacks bounded read-only staging inspection")
    required_read_calls = (
        "sts get-caller-identity",
        "cloudformation describe-stacks",
        "cloudformation list-stack-resources",
        "lambda get-function-configuration",
    )
    if not all(command in script for command in required_read_calls):
        errors.append("plan script lacks required read-only ownership checks")
    script_calls = {
        (service.lower(), operation.lower())
        for service, operation in re.findall(
            r"&\s+aws\s+([a-z0-9-]+)\s+([a-z0-9-]+)", script, re.IGNORECASE
        )
    }
    expected_calls = {
        ("sts", "get-caller-identity"),
        ("cloudformation", "describe-stacks"),
        ("cloudformation", "list-stack-resources"),
        ("lambda", "get-function-configuration"),
    }
    if script_calls != expected_calls:
        errors.append("plan script AWS calls differ from the exact read-only allowlist")
    if re.search(r"(?m)^\s*aws\s+[a-z0-9-]+\s+[a-z0-9-]+", workflow):
        errors.append("workflow must delegate all AWS CLI calls to the allowlisted script")
    if "[switch]$InspectAws" not in script or "Packaged files: 2" not in script:
        errors.append("plan script lacks opt-in AWS inspection or narrow packaging")
    forbidden_commands = (
        "s3 cp",
        "create-change-set",
        "execute-change-set",
        "delete-change-set",
        "update-function-code",
        "cloudformation deploy",
        "aws iam ",
    )
    workflow_and_script = (workflow + "\n" + script).lower()
    if any(command in workflow_and_script for command in forbidden_commands):
        errors.append("plan workflow contains an AWS write or IAM command")
    if "[switch]$Apply" in script:
        errors.append("plan script cannot expose an Apply switch")
    return errors


def main() -> int:
    errors = validate_contract(load_contract())
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    print("PASS: Action mutation plan workflow is manual, read-only, and human-gated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
