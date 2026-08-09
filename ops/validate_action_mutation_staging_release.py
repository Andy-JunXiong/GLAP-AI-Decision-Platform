"""Validate the proposed narrow Action mutation staging release boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "action_mutation_staging_release_contract.json"
PROPOSAL_PATH = (
    ROOT / "docs" / "action_mutation_staging_read_permission_proposal.json"
)
EXPECTED_AUTHORITY = {
    "workflow_implementation_authorized": True,
    "read_permission_human_approved": True,
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


def load_permission_proposal(path: Path = PROPOSAL_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_permission_proposal(proposal: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(proposal) != {
        "schema_version",
        "status",
        "purpose",
        "runtime_evidence",
        "requested_capability",
        "approval_scope",
        "explicitly_excluded_actions",
        "proposal_shape",
        "authority",
    }:
        errors.append("read-permission proposal contains unexpected fields")
    if proposal.get("schema_version") != (
        "action-mutation-staging-read-permission-proposal.v1"
    ):
        errors.append("unsupported read-permission proposal schema")
    if proposal.get("status") != "APPROVED_FOR_NAMED_HUMAN_APPLICATION":
        errors.append("read-permission proposal approval state changed")

    evidence = proposal.get("runtime_evidence", {})
    if not (
        evidence.get("github_actions_run_id") == 31297032412
        and evidence.get("git_commit")
        == "35e2d467e25b35bd2bc9f92527bbdc817503966a"
        and evidence.get("observed_on_sydney_date") == "2026-08-09"
        and evidence.get("oidc_session_established") is True
        and evidence.get("denied_action") == "lambda:GetFunctionConfiguration"
        and evidence.get("aws_write_observed") is False
    ):
        errors.append("read-permission proposal runtime evidence changed")

    capability = proposal.get("requested_capability", {})
    selector = capability.get("resource_selector", {})
    if capability.get("identity_boundary") != "EXISTING_GITHUB_STAGING_OIDC_ROLE":
        errors.append("read-permission proposal changes the identity boundary")
    if capability.get("actions") != ["lambda:GetFunctionConfiguration"]:
        errors.append("read-permission proposal is not limited to one read action")
    if not (
        selector.get("stack_name") == "glap-stateful-lifecycle-staging"
        and selector.get("logical_resource_id") == "ActionMutationFunction"
        and selector.get("resource_type") == "AWS::Lambda::Function"
        and selector.get("resolve_physical_resource_read_only_at_review_time")
        is True
        and selector.get("wildcard_allowed") is False
    ):
        errors.append("read-permission proposal is not exact-resource bounded")

    if proposal.get("approval_scope") != {
        "approved_on_sydney_date": "2026-08-09",
        "approving_authority": "HUMAN_REPOSITORY_OWNER",
        "approved_action": "lambda:GetFunctionConfiguration",
        "approved_resource_selector": (
            "CLOUDFORMATION_LOGICAL_RESOURCE_ACTION_MUTATION_FUNCTION"
        ),
        "application_actor": "NAMED_HUMAN_ONLY",
        "agent_application_allowed": False,
        "prepare_or_execute_release_approved": False,
    }:
        errors.append("read-permission approval scope expanded or became ambiguous")

    shape = proposal.get("proposal_shape", {})
    if shape != {
        "executable_iam_policy_document": False,
        "contains_account_id_or_arn": False,
        "review_only": True,
    }:
        errors.append("read-permission proposal became executable or identifying")
    if proposal.get("authority") != {
        "proposal_recording_authorized": True,
        "human_application_authorized": True,
        "agent_iam_change_authorized": False,
        "deployment_authorized": False,
        "aws_write_authorized": False,
    }:
        errors.append("read-permission proposal expands protected authority")
    def nested_keys(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [str(key) for key in value] + [
                key
                for nested in value.values()
                for key in nested_keys(nested)
            ]
        if isinstance(value, list):
            return [key for nested in value for key in nested_keys(nested)]
        return []

    if {key.lower() for key in nested_keys(proposal)} & {
        "statement",
        "effect",
        "resource",
        "principal",
    }:
        errors.append("read-permission proposal must not be an executable IAM policy")
    return errors


def validate_contract(contract: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "action-mutation-staging-release.v3":
        errors.append("unsupported schema_version")
    if contract.get("status") != (
        "READ_ONLY_PLAN_VERIFIED_AWAITING_RELEASE_AUTHORIZATION"
    ):
        errors.append("release must remain gated on separate write authorization")
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

    runtime = contract.get("runtime_evidence", {})
    if runtime != {
        "github_actions_run_id": 31298179885,
        "git_commit": "ed475f3a577c3e736bb639e1c05513e7bb80c490",
        "observed_on_sydney_date": "2026-08-09",
        "result": "READ_ONLY_PLAN_PASSED",
        "oidc_session_established": True,
        "repository_contracts_passed": True,
        "unit_tests_passed": 231,
        "drift_checks_passed": 15,
        "aws_write_observed": False,
        "aws_inspection_passed": True,
        "cloudformation_ownership_verified": True,
        "stable_lambda_configuration_verified": True,
        "artifact_upload_observed": False,
        "change_set_created_or_executed": False,
        "lambda_code_updated": False,
        "iam_or_cloudformation_modified": False,
        "production_effect": False,
    }:
        errors.append("runtime evidence is incomplete or overclaims AWS effect")
    proposal_relative_path = contract.get("read_permission_proposal")
    if proposal_relative_path != (
        "docs/action_mutation_staging_read_permission_proposal.json"
    ):
        errors.append("read-permission proposal is not linked")
    else:
        proposal_path = root / proposal_relative_path
        if not proposal_path.is_file():
            errors.append("read-permission proposal is missing")
        else:
            errors.extend(
                validate_permission_proposal(
                    json.loads(proposal_path.read_text(encoding="utf-8"))
                )
            )

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
    if blockers.get("actual_aws_permissions_inspected") is not True:
        errors.append("contract hides the completed AWS read inspection")
    if blockers.get("required_lambda_read_permission_present") is not True:
        errors.append("contract hides the verified Lambda read permission")
    if blockers.get("read_permission_human_approved") is not True:
        errors.append("contract hides the recorded human read-permission approval")
    if blockers.get("live_iam_permission_applied") is not True:
        errors.append("contract hides the named-human IAM application")
    if blockers.get("agent_iam_change_authorized") is not False:
        errors.append("contract cannot grant the agent IAM authority")
    if blockers.get("narrow_workflow_implemented") is not True:
        errors.append("implemented plan workflow is not recorded")
    if blockers.get("release_write_authority_approved") is not False:
        errors.append("read-only verification cannot grant release write authority")

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
    print(
        "PASS: Action mutation read-only plan passed and release writes remain "
        "human-gated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
