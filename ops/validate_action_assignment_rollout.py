"""Validate the partially completed Action assignment staging canary package."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "action_assignment_rollout_contract.json"
EXPECTED_ORDER = [
    "schema_migration",
    "post_migration_validation",
    "action_mutation_lambda_release",
    "operations_api_release",
    "internal_frontend_release",
    "read_only_runtime_verification",
    "four_role_verification",
    "named_human_canary",
]
FORBIDDEN_AUTHORITY = {
    "schema_migration_authorized",
    "lambda_deployment_authorized",
    "api_deployment_authorized",
    "frontend_publication_authorized",
    "operational_action_mutation_authorized",
    "recurring_schedule_authorized",
}
EXPECTED_ROLE_MATRIX = {
    "viewer": [],
    "operator": ["EDIT", "COMPLETE"],
    "approver": ["APPROVE", "REJECT"],
    "administrator": ["EDIT", "APPROVE", "REJECT", "COMPLETE"],
}


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _statement_count(path: Path) -> int:
    sql = re.sub(r"(?m)^\s*--.*$", "", path.read_text(encoding="utf-8"))
    return len([statement for statement in sql.split(";") if statement.strip()])


def validate_contract(contract: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "action-assignment-rollout.v1":
        errors.append("unsupported schema_version")
    if contract.get("status") != "CANARY_PARTIAL_BLOCKED_RESPONSE_FIX_RELEASE":
        errors.append("rollout must expose the partial canary release blocker")
    if contract.get("business_timezone") != "Australia/Sydney":
        errors.append("business timezone must remain Australia/Sydney")
    if contract.get("evidence_boundary") != "SYNTHETIC_STAGING_ONLY":
        errors.append("evidence boundary must remain synthetic staging only")
    authority = contract.get("authority", {})
    for field in FORBIDDEN_AUTHORITY:
        if authority.get(field) is not False:
            errors.append(f"{field} must remain false")
    if contract.get("release_order") != EXPECTED_ORDER:
        errors.append("release order is incomplete or reordered")

    schema = contract.get("schema", {})
    migration = root / str(schema.get("migration_sql", ""))
    validation = root / str(schema.get("validation_sql", ""))
    if schema.get("migration_statement_count") != 2:
        errors.append("migration statement-count contract must remain two")
    if schema.get("validation_statement_count") != 1:
        errors.append("validation statement-count contract must remain one")
    if not migration.is_file() or _statement_count(migration) != 2:
        errors.append("migration must contain exactly two statements")
    if not validation.is_file() or _statement_count(validation) != 1:
        errors.append("post-migration validation must contain exactly one statement")
    if schema.get("additive_only") is not True:
        errors.append("schema migration must remain additive-only")
    if schema.get("automatic_workflow_wiring") is not False:
        errors.append("schema migration must not be automatically wired")
    if schema.get("migration_applied") is not True:
        errors.append("verified staging schema migration evidence is hidden")
    if schema.get("post_migration_validation_passed") is not True:
        errors.append("post-migration validation evidence is hidden")

    release_paths = contract.get("release_paths", {})
    if release_paths.get("schema_plan") != "LOCAL_RENDER_ONLY_NO_AWS_EXECUTION":
        errors.append("schema migration planning must remain local and non-executing")
    if release_paths.get("schema_migration") != (
        "COMPLETED_NAMED_HUMAN_REVIEWED_STAGING_ONLY"
    ):
        errors.append("completed named-human schema migration evidence is hidden")
    if release_paths.get("action_mutation_lambda") != (
        "STAGING_RELEASE_VERIFIED_FUTURE_WRITES_REQUIRE_APPROVAL"
    ):
        errors.append("verified mutation release or future approval boundary is hidden")
    if release_paths.get("response_serialization_fix") != (
        "COMMIT_763A817_PUSHED_NOT_DEPLOYED"
    ):
        errors.append("response fix must remain pushed but not deployed")
    if release_paths.get("candidate_design_contract") != (
        "docs/action_mutation_staging_release_contract.json"
    ):
        errors.append("candidate mutation release design is not connected")
    if release_paths.get("operations_api") != (
        "STAGING_RELEASE_VERIFIED_FUTURE_WRITES_REQUIRE_APPROVAL"
    ):
        errors.append("verified Operations API release or future approval boundary is hidden")
    if release_paths.get("internal_frontend") != (
        "STAGING_RELEASE_VERIFIED_FUTURE_WRITES_REQUIRE_APPROVAL"
    ):
        errors.append("verified frontend release or future approval boundary is hidden")
    release_evidence = contract.get("verified_release_evidence", {})
    if release_evidence != {
        "observed_on_sydney_date": "2026-08-10",
        "git_commit": "bde092750768163e12e70e9649e3e68485483a71",
        "prepare_run_id": 31359941156,
        "execute_run_id": 31360187221,
        "stack_final_status": "UPDATE_COMPLETE",
        "lambda_digest_matches_artifact": True,
        "schema_migration_applied": True,
        "schema_migration_observed_on_sydney_date": "2026-08-13",
        "schema_validation_query_execution_id": "858a5024-1e08-487b-8dd4-b01a0302acca",
        "schema_validation_check_count": 5,
        "schema_validation_failure_count": 0,
        "operations_api_plan_run_id": 31680467442,
        "operations_api_deploy_run_id": 31680885483,
        "operations_api_git_commit": "fb7a3a6f14eb634c34c91d2512d15bce1473c0ca",
        "operations_api_stack_final_status": "UPDATE_COMPLETE",
        "operations_api_artifact_matches_commit": True,
        "internal_frontend_deployment_status": "SUCCEED",
        "internal_frontend_deployed_at": "2026-08-13T18:18:15.521000+10:00",
        "assignment_runtime_verification_passed": True,
        "four_role_verification_passed": True,
        "temporary_role_users_removed": 4,
        "temporary_role_users_remaining": 0,
        "operational_action_mutation_executed": True,
        "canary_edit_observed_on_sydney_date": "2026-08-13",
        "canary_edit_event_count": 1,
        "canary_edit_distinct_request_id_count": 1,
        "canary_edit_distinct_action_count": 1,
        "canary_edit_valid_assignment_count": 1,
        "canary_edit_current_edited_count": 1,
        "canary_edit_request_id_row_count": 1,
        "canary_edit_http_status": 503,
        "canary_edit_failure_category": "DATE_RESPONSE_SERIALIZATION",
        "response_serialization_fix_git_commit": "763a817d578b0d50ca555d53f2609f0c1192b9c1",
        "response_serialization_fix_pushed_to_main": True,
        "response_serialization_fix_deployed": False,
        "operator_global_sign_out_completed": True,
        "operator_group_membership_operator_only": True,
        "production_effect": False,
        "future_release_write_authority_approved": False,
    }:
        errors.append("verified mutation release evidence is incomplete or expands authority")
    if contract.get("role_matrix") != EXPECTED_ROLE_MATRIX:
        errors.append("Action assignment role matrix has changed")
    rollback = contract.get("rollback", {})
    if any(
        rollback.get(field) is not False
        for field in ("drop_columns_allowed", "delete_audit_events_allowed", "rewrite_edited_status_allowed")
    ):
        errors.append("rollback cannot delete or rewrite governed evidence")
    if rollback.get("package_rollback_requires_zero_edit_events") is not True:
        errors.append("package rollback must be gated on zero EDIT events")
    canary = contract.get("canary", {})
    if canary.get("agent_execution_allowed") is not False:
        errors.append("the agent cannot execute an operational Action canary")
    if not all(
        canary.get(field) is True
        for field in (
            "named_signed_operator_required",
            "named_signed_approver_required",
            "stable_request_id_retry_required",
        )
    ):
        errors.append("canary must retain named-human separation and stable retries")
    if canary.get("operator_edit_completed") is not True:
        errors.append("canary must retain the completed operator EDIT evidence")
    if canary.get("stable_request_id_retry_completed") is not False:
        errors.append("stable request-ID retry must remain pending until verified")
    if canary.get("named_approver_decision_completed") is not False:
        errors.append("separate approver decision must remain pending until verified")
    if canary.get("current_blocker") != "RESPONSE_SERIALIZATION_FIX_NOT_DEPLOYED":
        errors.append("canary must expose the undeployed response-fix blocker")

    role_script = (root / "ops" / "verify_operations_roles_staging.ps1").read_text(
        encoding="utf-8"
    )
    runtime_script = (root / "ops" / "verify_operations_staging.ps1").read_text(
        encoding="utf-8"
    )
    schema_plan = (root / "ops" / "plan_action_assignment_schema.ps1").read_text(
        encoding="utf-8"
    )
    if "RequireActionAssignment" not in role_script or 'Action-Status "operator" "EDIT"' not in role_script:
        errors.append("four-role verifier lacks the opt-in EDIT contract")
    if "RequireActionAssignment" not in runtime_script or "Assign & edit" not in runtime_script:
        errors.append("runtime verifier lacks the opt-in assignment fingerprint")
    schema_plan_lower = schema_plan.lower()
    if "[switch]$apply" in schema_plan_lower or "start-query-execution" in schema_plan_lower:
        errors.append("schema plan must not expose an Athena execution path")
    if "migration statements: 2" not in schema_plan_lower or "validation statements: 1" not in schema_plan_lower:
        errors.append("schema plan does not preserve reviewed statement counts")
    return errors


def main() -> int:
    errors = validate_contract(load_contract())
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    print("PASS: operator EDIT is recorded; response-fix release, retry, and approver remain blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
