"""Validate the plan-only Action assignment staging rollout package."""

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
    if contract.get("status") != "PLAN_ONLY_BLOCKED_RELEASE_PATH":
        errors.append("rollout must remain plan-only with the release-path blocker visible")
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

    release_paths = contract.get("release_paths", {})
    if release_paths.get("action_mutation_lambda") != "BLOCKED_NARROW_RELEASE_PATH_REVIEW":
        errors.append("narrow mutation release-path blocker is hidden")
    if release_paths.get("candidate_design_contract") != (
        "docs/action_mutation_staging_release_contract.json"
    ):
        errors.append("candidate mutation release design is not connected")
    if release_paths.get("operations_api") != "EXISTING_MANUAL_PLAN_FIRST_WORKFLOW":
        errors.append("Operations API release must remain manual and plan-first")
    if release_paths.get("internal_frontend") != "EXISTING_MANUAL_PLAN_FIRST_SCRIPT":
        errors.append("internal frontend release must remain manual and plan-first")
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

    role_script = (root / "ops" / "verify_operations_roles_staging.ps1").read_text(
        encoding="utf-8"
    )
    runtime_script = (root / "ops" / "verify_operations_staging.ps1").read_text(
        encoding="utf-8"
    )
    if "RequireActionAssignment" not in role_script or 'Action-Status "operator" "EDIT"' not in role_script:
        errors.append("four-role verifier lacks the opt-in EDIT contract")
    if "RequireActionAssignment" not in runtime_script or "Assign & edit" not in runtime_script:
        errors.append("runtime verifier lacks the opt-in assignment fingerprint")
    return errors


def main() -> int:
    errors = validate_contract(load_contract())
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    print("PASS: Action assignment rollout is ordered, plan-only, and rollback bounded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
