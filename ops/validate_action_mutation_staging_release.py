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
ACCESS_PROPOSAL_PATH = (
    ROOT / "docs" / "action_mutation_staging_release_access_proposal.json"
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


def load_access_proposal(path: Path = ACCESS_PROPOSAL_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_access_proposal(proposal: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if proposal.get("schema_version") != "action-mutation-staging-release-access-proposal.v1":
        errors.append("unsupported release-access proposal schema")
    if proposal.get("status") != "PROPOSED_AWAITING_NAMED_HUMAN_REVIEW":
        errors.append("release-access proposal claims approval or execution")
    identities = proposal.get("identities", {})
    prepare = identities.get("prepare", {})
    execute = identities.get("execute", {})
    if prepare != {
        "github_environment": "action-mutation-staging-prepare",
        "github_variable": "AWS_ACTION_MUTATION_PREPARE_ROLE_ARN",
        "required_reviewers": True,
        "actions": [
            "s3:PutObject",
            "iam:PassRole",
            "cloudformation:CreateChangeSet",
            "cloudformation:DescribeChangeSet",
            "cloudformation:DeleteChangeSet",
            "cloudformation:DescribeStacks",
        ],
    }:
        errors.append("prepare identity actions or approval boundary changed")
    if execute != {
        "github_environment": "action-mutation-staging-execute",
        "github_variable": "AWS_ACTION_MUTATION_EXECUTE_ROLE_ARN",
        "required_reviewers": True,
        "actions": [
            "s3:GetObject",
            "cloudformation:DescribeChangeSet",
            "cloudformation:ExecuteChangeSet",
            "cloudformation:DescribeStacks",
            "lambda:GetFunctionConfiguration",
        ],
    }:
        errors.append("execute identity actions or approval boundary changed")
    if identities.get("cloudformation_execution") != {
        "trusted_service": "cloudformation.amazonaws.com",
        "github_variable": "ACTION_MUTATION_CF_EXECUTION_ROLE_ARN",
        "actions": [
            "s3:GetObject",
            "lambda:GetFunctionConfiguration",
            "lambda:UpdateFunctionCode",
        ],
    }:
        errors.append("CloudFormation execution-role boundary changed")
    selectors = proposal.get("resource_selectors", {})
    if selectors != {
        "stack": {
            "name": "glap-stateful-lifecycle-staging",
            "wildcard_stack_name_allowed": False,
        },
        "lambda": {
            "cloudformation_logical_resource_id": "ActionMutationFunction",
            "function_name": "glap-lifecycle-action-mutation-staging",
            "qualified_or_other_function_allowed": False,
        },
        "artifact": {
            "bucket_from_existing_stack_parameter": "ArtifactBucket",
            "key_pattern": "action-mutation/<40-character-git-commit>/glap-action-mutation-<sha256>.zip",
            "other_prefix_allowed": False,
        },
        "cloudformation_execution_role": {
            "role_name": "glap-action-mutation-cloudformation-staging-role",
            "passable_only_to": "cloudformation.amazonaws.com",
            "direct_assumption_by_github_allowed": False,
        },
    }:
        errors.append("release-access resource selectors expanded or changed")
    if proposal.get("github_protection") != {
        "deployment_branch": "main",
        "self_approval_allowed": False,
        "prepare_and_execute_same_approval_allowed": False,
        "environment_creation_by_agent_allowed": False,
    }:
        errors.append("GitHub protected-environment separation changed")
    if proposal.get("proposal_shape") != {
        "executable_iam_policy_document": False,
        "contains_account_id_or_arn": False,
        "review_only": True,
    }:
        errors.append("release-access proposal became executable or identifying")
    if proposal.get("authority") != {
        "repository_proposal_authorized": True,
        "agent_iam_change_authorized": False,
        "agent_github_environment_change_authorized": False,
        "prepare_aws_write_authorized": False,
        "execute_aws_write_authorized": False,
        "deployment_authorized": False,
        "production_change_authorized": False,
    }:
        errors.append("release-access proposal expands protected authority")
    serialized = json.dumps(proposal, sort_keys=True).lower()
    if '"statement"' in serialized or '"effect"' in serialized or '"resource"' in serialized or "arn:" in serialized:
        errors.append("release-access proposal must not contain executable IAM or ARNs")
    required_exclusions = {
        "iam:*", "lambda:UpdateFunctionConfiguration", "lambda:PublishVersion",
        "lambda:UpdateAlias", "scheduler:*", "cloudformation:CreateStack",
        "cloudformation:DeleteStack", "cloudformation:UpdateStack", "s3:DeleteObject",
    }
    if set(proposal.get("explicitly_excluded_actions", [])) != required_exclusions:
        errors.append("release-access exclusions changed")
    return errors


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
    if contract.get("schema_version") != "action-mutation-staging-release.v4":
        errors.append("unsupported schema_version")
    if contract.get("status") != (
        "RELEASE_WORKFLOW_IMPLEMENTED_AWAITING_AWS_WRITE_AUTHORIZATION"
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

    release_workflow = contract.get("release_workflow", {})
    if release_workflow != {
        "workflow": ".github/workflows/release-action-mutation-staging.yml",
        "prepare_script": "ops/prepare_action_mutation_staging_release.ps1",
        "execute_script": "ops/execute_action_mutation_staging_release.ps1",
        "trigger": "workflow_dispatch_only",
        "prepare_environment": "action-mutation-staging-prepare",
        "execute_environment": "action-mutation-staging-execute",
        "cloudformation_execution_role_variable": "ACTION_MUTATION_CF_EXECUTION_ROLE_ARN",
        "implemented": True,
        "executed": False,
    }:
        errors.append("prepare/execute workflow contract is incomplete or expanded")

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
    access_relative_path = contract.get("release_access_proposal")
    if access_relative_path != "docs/action_mutation_staging_release_access_proposal.json":
        errors.append("release-access proposal is not linked")
    else:
        access_path = root / access_relative_path
        if not access_path.is_file():
            errors.append("release-access proposal is missing")
        else:
            errors.extend(validate_access_proposal(json.loads(access_path.read_text(encoding="utf-8"))))

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
    if blockers.get("prepare_execute_workflow_implemented") is not True:
        errors.append("implemented prepare/execute workflow is not recorded")
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

    release_path = root / ".github" / "workflows" / "release-action-mutation-staging.yml"
    prepare_path = root / "ops" / "prepare_action_mutation_staging_release.ps1"
    execute_path = root / "ops" / "execute_action_mutation_staging_release.ps1"
    if not all(path.is_file() for path in (release_path, prepare_path, execute_path)):
        errors.append("prepare/execute workflow implementation is missing")
        return errors
    release = release_path.read_text(encoding="utf-8")
    prepare = prepare_path.read_text(encoding="utf-8")
    execute = execute_path.read_text(encoding="utf-8")
    if "workflow_dispatch:" not in release or "  push:" in release or "  schedule:" in release:
        errors.append("release workflow must remain manual-only")
    for environment in (
        "environment: action-mutation-staging-prepare",
        "environment: action-mutation-staging-execute",
    ):
        if environment not in release:
            errors.append("release phases do not use separate protected environments")
    if "AWS_ACTION_MUTATION_PREPARE_ROLE_ARN" not in release or "AWS_ACTION_MUTATION_EXECUTE_ROLE_ARN" not in release:
        errors.append("release phases do not use separate role variables")
    if release.count("ACTION_MUTATION_CF_EXECUTION_ROLE_ARN") != 2:
        errors.append("release phases do not pin the same CloudFormation execution role")
    if "git merge-base --is-ancestor" not in release:
        errors.append("release workflow does not require the requested commit on main")
    combined_release = (release + "\n" + prepare + "\n" + execute).lower()
    for forbidden in ("update-function-code", "cloudformation deploy", "aws iam "):
        if forbidden in combined_release:
            errors.append("release workflow bypasses CloudFormation ownership or IAM authority")
    required_prepare = (
        "s3api put-object",
        "cloudformation create-change-set",
        "--use-previous-template",
        "--role-arn $CloudFormationRoleArn",
        '"cloudformation", "describe-change-set"',
        "cloudformation delete-change-set",
        'logicalresourceid -ne "ActionMutationFunction"',
    )
    if not all(value.lower() in prepare.lower() for value in required_prepare):
        errors.append("prepare phase lacks the exact upload/change-set fail-closed contract")
    required_execute = (
        '"s3api", "head-object"',
        '"cloudformation", "describe-change-set"',
        "cloudformation execute-change-set",
        "cloudformation wait stack-update-complete",
        '"lambda", "get-function-configuration"',
        'executionstatus -ne "AVAILABLE"',
        'rolearn -ne $cloudformationrolearn',
    )
    if not all(value.lower() in execute.lower() for value in required_execute):
        errors.append("execute phase lacks revalidation or post-update verification")
    return errors


def main() -> int:
    errors = validate_contract(load_contract())
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    print(
        "PASS: Action mutation release workflow is bounded and AWS writes remain "
        "human-gated and unexecuted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
