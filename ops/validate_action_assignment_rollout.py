"""Validate the completed Action assignment staging canary package."""

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
    if contract.get("status") != "CANARY_COMPLETE_VERIFIED":
        errors.append("rollout must expose the verified completed canary state")
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
        "DEPLOYED_VERIFIED_2026_08_23_FUTURE_WRITES_REQUIRE_APPROVAL"
    ):
        errors.append("response fix deployment evidence or future approval boundary is hidden")
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
        "response_serialization_fix_deployed": True,
        "response_serialization_fix_observed_on_sydney_date": "2026-08-23",
        "response_serialization_fix_release_git_commit": "08b21e378aa2dedd51fef5c98009c9f482cb2d1b",
        "response_serialization_fix_prepare_run_id": 32623784739,
        "response_serialization_fix_execute_run_id": 32624244648,
        "response_serialization_fix_stack_final_status": "UPDATE_COMPLETE",
        "stable_retry_http_status": 200,
        "stable_retry_idempotent_replay": True,
        "stable_retry_request_id_row_count": 1,
        "stable_retry_current_edited_count": 1,
        "stable_retry_assignment_match_count": 1,
        "stable_retry_approver_event_count": 0,
        "approver_decision_observed_on_sydney_date": "2026-08-23",
        "approver_decision": "APPROVE",
        "approver_edit_event_count": 1,
        "approver_approve_event_count": 1,
        "approver_reject_event_count": 0,
        "approver_complete_event_count": 0,
        "approver_distinct_named_actor_count": 2,
        "approver_current_approved_count": 1,
        "approver_assignment_match_count": 1,
        "complete_observed_on_sydney_date": "2026-08-25",
        "complete_event_count": 1,
        "complete_named_actor_count": 1,
        "complete_current_completed_count": 1,
        "complete_assignment_match_count": 1,
        "complete_outcome_count_before_continuation": 0,
        "complete_reconciliation_passed": True,
        "complete_protected_identifiers_printed": False,
        "complete_production_effect": False,
        "pending_outcome_observed_on_sydney_date": "2026-08-25",
        "pending_outcome_workflow_run_id": 32803181376,
        "pending_outcome_workflow_result": "PASS",
        "pending_outcome_actual_calendar_count": 1,
        "pending_outcome_current_pending_count": 1,
        "pending_outcome_unobserved_count": 1,
        "pending_outcome_simulated_count": 1,
        "pending_outcome_due_date_rule_match_count": 1,
        "pending_outcome_reconciliation_passed": True,
        "pending_outcome_protected_identifiers_printed": False,
        "pending_outcome_production_effect": False,
        "evidence_refresh_frontend_git_commit": "adfd2a5656a217f2eac792853d8fd2d947741732",
        "evidence_refresh_frontend_deployed": True,
        "evidence_refresh_frontend_observed_on_sydney_date": "2026-08-23",
        "evidence_refresh_read_only_verifier_passed": True,
        "evidence_refresh_interaction_canary_executed": True,
        "evidence_refresh_interaction_canary_observed_on_sydney_date": "2026-08-24",
        "evidence_refresh_interaction_canary_observation": (
            "NAMED_HUMAN_UI_OBSERVED_AND_READ_ONLY_BACKEND_RECONCILED"
        ),
        "evidence_refresh_interaction_canary_action_status": "EDITED",
        "evidence_refresh_interaction_canary_auto_refresh_observed": True,
        "evidence_refresh_interaction_canary_backend_reconciled": True,
        "evidence_refresh_interaction_canary_reconciled_on_sydney_date": "2026-08-24",
        "evidence_refresh_interaction_canary_edit_event_count": 1,
        "evidence_refresh_interaction_canary_distinct_action_count": 1,
        "evidence_refresh_interaction_canary_distinct_request_count": 1,
        "evidence_refresh_interaction_canary_distinct_actor_count": 1,
        "evidence_refresh_interaction_canary_named_actor_count": 1,
        "evidence_refresh_interaction_canary_valid_assignment_count": 1,
        "evidence_refresh_interaction_canary_current_edited_count": 1,
        "evidence_refresh_interaction_canary_current_assignment_match_count": 1,
        "operator_global_sign_out_completed": True,
        "operator_group_membership_operator_only": True,
        "production_effect": False,
        "future_release_write_authority_approved": False,
    }:
        errors.append("verified mutation release evidence is incomplete or expands authority")
    if release_evidence.get("evidence_refresh_interaction_canary_executed") is not True:
        errors.append("named-human evidence refresh interaction observation is hidden")
    if release_evidence.get("evidence_refresh_interaction_canary_backend_reconciled") is not True:
        errors.append("read-only Evidence refresh backend reconciliation is hidden")
    if release_evidence.get("complete_reconciliation_passed") is not True:
        errors.append("read-only COMPLETE reconciliation evidence is hidden")
    if release_evidence.get("pending_outcome_reconciliation_passed") is not True:
        errors.append("read-only pending Outcome reconciliation evidence is hidden")
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
    if canary.get("stable_request_id_retry_completed") is not True:
        errors.append("verified stable request-ID retry evidence is hidden")
    if canary.get("named_approver_decision_completed") is not True:
        errors.append("verified separate approver decision evidence is hidden")
    if canary.get("named_approver_decision") != "APPROVE":
        errors.append("verified approver decision must remain APPROVE")
    if canary.get("current_action_status") != "COMPLETED":
        errors.append("verified current Action status must remain COMPLETED")
    if canary.get("action_complete_completed") is not True:
        errors.append("verified named-human COMPLETE evidence is hidden")
    if canary.get("action_complete_agent_executed") is not False:
        errors.append("the agent cannot execute Action COMPLETE")
    if canary.get("action_complete_reconciled") is not True:
        errors.append("verified read-only COMPLETE reconciliation is hidden")
    if canary.get("pending_outcome_continuation_completed") is not True:
        errors.append("verified pending Outcome continuation evidence is hidden")
    if canary.get("pending_outcome_reconciled") is not True:
        errors.append("verified read-only pending Outcome reconciliation is hidden")
    if canary.get("current_blocker") != (
        "OBSERVED_OUTCOME_FAILED_CLOSED_SOURCE_FIX_LOCALLY_VERIFIED_NOT_DEPLOYED"
    ):
        errors.append("failed-closed runtime and local-only source-fix maturity must remain visible")

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
    print(
        "PASS: Action assignment and delayed Outcome evidence remain verified; "
        "the downstream Learning source fix is local-only and staging remains "
        "failed closed without standing authority"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
