"""Validate the local-only COMPLETE-to-Outcome canary preparation contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "action_complete_outcome_canary_v1.json"
PHASE_ORDER = [
    "read_only_preflight",
    "named_human_complete",
    "read_only_complete_reconciliation",
    "separately_authorized_pending_outcome_generation",
    "read_only_pending_reconciliation",
    "calendar_wait",
    "separately_authorized_observed_outcome_generation",
    "read_only_outcome_learning_reconciliation",
]
AUTHORITY_FIELDS = {
    "agent_action_mutation_authorized",
    "named_human_complete_authorized",
    "lifecycle_continuation_authorized",
    "aws_write_authorized",
    "deployment_authorized",
    "production_authorized",
    "recurring_schedule_authorized",
    "policy_activation_authorized",
    "model_promotion_authorized",
}
PROTECTED_FIELDS = {
    "action_id",
    "request_id",
    "actor",
    "actor_subject",
    "action_owner",
    "shipment_id",
    "outcome_id",
    "alert_fingerprint",
    "aws_arn",
    "s3_path",
}


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(contract: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "action-complete-outcome-canary.v1":
        errors.append("unsupported schema_version")
    if contract.get("status") != (
        "OBSERVED_OUTCOME_FAILED_CLOSED_SOURCE_FIX_LOCALLY_VERIFIED_NOT_DEPLOYED"
    ):
        errors.append("canary must distinguish the failed runtime gate from the local source fix")
    if contract.get("authority_semantics") != "CURRENT_AND_FUTURE_AUTHORITY_AFTER_OBSERVED_OUTCOME":
        errors.append("authority map must describe only authority after the observed Outcome")
    if contract.get("business_timezone") != "Australia/Sydney":
        errors.append("business timezone must remain Australia/Sydney")
    if contract.get("evidence_boundary") != "SYNTHETIC_STAGING_ACTUAL_CALENDAR_ONLY":
        errors.append("evidence must remain synthetic staging actual-calendar only")

    authority = contract.get("authority", {})
    if set(authority) != AUTHORITY_FIELDS or any(authority.get(key) is not False for key in AUTHORITY_FIELDS):
        errors.append("all mutation, deployment, production, policy, and model authority must remain false")

    source = contract.get("source_capability", {})
    if source.get("rollout_contract") != "docs/action_assignment_rollout_contract.json":
        errors.append("source rollout contract must remain fixed")
    if source.get("required_rollout_status") != "CANARY_COMPLETE_VERIFIED":
        errors.append("source rollout must retain verified completed state")
    if source.get("required_action_status") != "COMPLETED":
        errors.append("canary source Action must remain COMPLETED")
    if source.get("required_audit_counts") != {"EDIT": 1, "APPROVE": 1, "REJECT": 0, "COMPLETE": 1}:
        errors.append("source audit-count completion evidence has drifted")
    if source.get("required_assignment_match_count") != 1:
        errors.append("source assignment must reconcile exactly once")

    if contract.get("phase_order") != PHASE_ORDER:
        errors.append("phase order is incomplete or reordered")
    phases = contract.get("phases", {})
    if set(phases) != set(PHASE_ORDER):
        errors.append("phase definitions do not match the governed order")

    if phases.get("read_only_preflight") != {
        "mode": "READ_ONLY",
        "gate": "EXACT_APPROVED_SOURCE_STATE",
        "verifier": "ops/preflight_action_complete_outcome_staging.ps1",
        "expected_outcome_count_for_action": 0,
    }:
        errors.append("preflight must remain read-only and exact-state gated")

    complete = phases.get("named_human_complete", {})
    if complete != {
        "mode": "NAMED_HUMAN_ONLY_SEPARATE_AUTHORIZATION_REQUIRED",
        "operation": "COMPLETE",
        "allowed_roles": ["operator", "administrator"],
        "actor_source": "SIGNED_IDENTITY_CLAIMS",
        "logical_date_source": "SYSTEM_DERIVED_SYDNEY_DATE",
        "stable_request_id_required": True,
        "same_request_id_retry_only": True,
    }:
        errors.append("COMPLETE must remain a separately authorized, identity-derived, idempotent human step")

    if phases.get("read_only_complete_reconciliation") != {
        "mode": "READ_ONLY",
        "verifier": "ops/reconcile_action_complete_staging.ps1",
        "expected_action_status": "COMPLETED",
        "expected_complete_event_count": 1,
        "expected_named_complete_actor_count": 1,
        "expected_assignment_match_count": 1,
        "expected_outcome_count_for_action": 0,
    }:
        errors.append("completion reconciliation must remain read-only and exact-count gated")

    pending_generation = phases.get("separately_authorized_pending_outcome_generation", {})
    observed_generation = phases.get("separately_authorized_observed_outcome_generation", {})
    for label, phase in (("pending", pending_generation), ("observed", observed_generation)):
        if phase.get("mode") != "NAMED_HUMAN_LIFECYCLE_CONTINUATION_AUTHORIZATION_REQUIRED":
            errors.append(f"{label} Outcome generation must require separate named-human authorization")
        if phase.get("execution_mode") != "OPERATIONAL" or phase.get("time_basis") != "ACTUAL_CALENDAR":
            errors.append(f"{label} Outcome generation must remain operational actual-calendar")
        if phase.get("future_simulation_allowed") is not False:
            errors.append(f"{label} Outcome generation cannot use future simulation")
    if pending_generation.get("logical_date_source") != "SYSTEM_DERIVED_SYDNEY_DATE":
        errors.append("pending Outcome logical date must be system-derived")
    if observed_generation.get("logical_date_gate") != (
        "ON_OR_AFTER_OBSERVATION_DUE_DATE_AND_ON_OR_BEFORE_CURRENT_SYDNEY_DATE"
    ):
        errors.append("observed Outcome date gate must reject early and future evidence")

    pending = phases.get("read_only_pending_reconciliation", {})
    if pending != {
        "mode": "READ_ONLY",
        "verifier": "ops/reconcile_pending_outcome_staging.ps1",
        "expected_outcome_count_for_action": 1,
        "expected_outcome_status": "PENDING",
        "expected_observed_date": None,
        "expected_effect_pct": None,
        "expected_provenance": "SIMULATED",
        "expected_observation_due_date_rule": "COMPLETION_DATE_PLUS_3_DAYS",
    }:
        errors.append("pending Outcome must remain unobserved and explicitly simulated")

    wait = phases.get("calendar_wait", {})
    if not (
        wait.get("mode") == "NO_EXECUTION"
        and wait.get("verifier") == "ops/check_observed_outcome_due_date.ps1"
        and wait.get("observation_lag_days") == 3
        and wait.get("not_before") == "SYSTEM_COMPUTED_OBSERVATION_DUE_DATE"
        and wait.get("future_date_claim_allowed") is False
    ):
        errors.append("calendar wait must retain the three-day due-date gate")

    learning = phases.get("read_only_outcome_learning_reconciliation", {})
    if not (
        learning.get("mode") == "READ_ONLY"
        and learning.get("verifier")
        == "ops/reconcile_observed_outcome_learning_staging.ps1"
        and learning.get("expected_closed_outcome_count_for_action") == 1
        and learning.get("baseline_eligible_outcome_count") == 1
        and learning.get("eligible_outcome_delta") == 1
        and learning.get("expected_eligible_outcome_count") == 2
        and learning.get("minimum_observed_outcomes_for_proposal") == 20
        and learning.get("expected_policy_proposal_count") == 0
        and learning.get("expected_activated_policy_proposal_count") == 0
        and learning.get("automatic_policy_activation_allowed") is False
        and learning.get("real_world_performance_claim_allowed") is False
    ):
        errors.append("Learning reconciliation must remain read-only, synthetic, and review-gated")

    evidence = contract.get("evidence_output", {})
    if evidence.get("aggregate_only") is not True:
        errors.append("canary evidence output must remain aggregate-only")
    if set(evidence.get("protected_fields_must_not_be_printed", [])) != PROTECTED_FIELDS:
        errors.append("protected output field list is incomplete")
    if set(evidence.get("allowed_fields", [])) & PROTECTED_FIELDS:
        errors.append("protected fields cannot be allowed in canary output")

    runtime_preflight = contract.get("runtime_preflight", {})
    if runtime_preflight != {
        "executed": True,
        "observed_on_sydney_date": "2026-08-25",
        "result": "PASS",
        "candidate_action_count": 1,
        "edit_event_count": 1,
        "approve_event_count": 1,
        "reject_event_count": 0,
        "complete_event_count": 0,
        "separated_actor_count": 1,
        "assignment_match_count": 1,
        "outcome_count": 0,
        "protected_identifiers_printed": False,
        "action_mutation_executed": False,
        "lifecycle_continuation_executed": False,
    }:
        errors.append("verified aggregate preflight evidence is incomplete or overclaimed")

    runtime_completion = contract.get("runtime_completion", {})
    if runtime_completion != {
        "authorization_received": True,
        "observed_on_sydney_date": "2026-08-25",
        "execution_actor_boundary": "NAMED_HUMAN_FROM_SIGNED_IDENTITY",
        "agent_execution": False,
        "result": "PASS",
        "current_action_status": "COMPLETED",
        "edit_event_count": 1,
        "approve_event_count": 1,
        "reject_event_count": 0,
        "complete_event_count": 1,
        "named_complete_actor_count": 1,
        "assignment_match_count": 1,
        "outcome_count_before_continuation": 0,
        "protected_identifiers_printed": False,
        "lifecycle_continuation_executed": False,
        "production_effect": False,
    }:
        errors.append("verified named-human COMPLETE evidence is incomplete or overclaimed")

    runtime_pending = contract.get("runtime_pending_outcome", {})
    if runtime_pending != {
        "authorization_received": True,
        "executed_on_sydney_date": "2026-08-25",
        "execution_actor_boundary": "EXPLICIT_PROJECT_OWNER_AUTHORIZATION_VIA_NAMED_GITHUB_SESSION",
        "agent_browser_trigger_assistance": True,
        "workflow_run_id": 32803181376,
        "source_commit": "291fffc",
        "workflow_result": "PASS",
        "execution_mode": "OPERATIONAL",
        "time_basis": "ACTUAL_CALENDAR",
        "logical_start_date": "2026-08-25",
        "logical_date_count": 1,
        "initial_seed_loaded": False,
        "future_simulation_used": False,
        "candidate_action_count": 1,
        "outcome_count": 1,
        "pending_outcome_count": 1,
        "unobserved_outcome_count": 1,
        "simulated_outcome_count": 1,
        "due_date_rule_match_count": 1,
        "observation_due_date": "2026-08-28",
        "observation_due_date_basis": "SYSTEM_COMPUTED_FUTURE_GATE_NOT_OBSERVED",
        "protected_identifiers_printed": False,
        "production_effect": False,
        "deployment_executed": False,
        "recurring_schedule_created": False,
        "observed_outcome_continuation_authorized": False,
    }:
        errors.append("verified pending Outcome evidence is incomplete or overclaimed")

    observation_preparation = contract.get("runtime_observation_preparation", {})
    if observation_preparation != {
        "implemented_on_sydney_date": "2026-08-25",
        "due_date_gate_verifier": "ops/check_observed_outcome_due_date.ps1",
        "outcome_learning_reconciler": "ops/reconcile_observed_outcome_learning_staging.ps1",
        "due_date_check_result": "BLOCKED_AS_EXPECTED",
        "observation_due_date": "2026-08-28",
        "baseline_eligible_outcome_count": 1,
        "expected_eligible_outcome_count_after_observation": 2,
        "minimum_policy_outcomes": 20,
        "expected_policy_proposal_count": 0,
        "external_writes_executed": False,
        "aws_calls_executed": False,
        "observed_outcome_continuation_executed": False,
        "observed_result_claimed": False,
        "policy_activation_executed": False,
        "production_effect": False,
    }:
        errors.append("observation verifier preparation is incomplete or overclaimed")

    runtime_observation = contract.get("runtime_observation", {})
    if runtime_observation != {
        "authorization_received": True,
        "executed_on_sydney_date": "2026-08-28",
        "plan_workflow_run_id": 33149532396,
        "continuation_workflow_run_id": 33149577300,
        "source_commit": "3316627",
        "workflow_result": "PASS",
        "execution_mode": "OPERATIONAL",
        "time_basis": "ACTUAL_CALENDAR",
        "logical_start_date": "2026-08-28",
        "logical_date_count": 1,
        "initial_seed_loaded": False,
        "future_simulation_used": False,
        "lifecycle_check_count": 41,
        "closed_candidate_check_passed": True,
        "latest_outcome_check_passed": True,
        "closed_outcome_check_passed": True,
        "observed_effect_check_passed": True,
        "simulated_provenance_check_passed": True,
        "due_date_rule_check_passed": True,
        "observed_on_or_after_due_date_check_passed": True,
        "observed_by_sydney_cutoff_check_passed": True,
        "eligible_outcome_delta_check_passed": True,
        "eligible_outcome_count": 2,
        "minimum_policy_outcomes": 20,
        "threshold_unmet_check_passed": True,
        "zero_policy_proposal_below_threshold_check_passed": False,
        "proposal_presence": "AT_LEAST_ONE_UNACTIVATED_PROPOSAL_BELOW_THRESHOLD",
        "zero_policy_activation_check_passed": True,
        "reconciliation_result": "FAIL_CLOSED_POLICY_PROPOSAL_PRESENT_BELOW_THRESHOLD",
        "protected_identifiers_printed": False,
        "second_lifecycle_continuation_executed": False,
        "policy_activation_executed": False,
        "production_effect": False,
    }:
        errors.append("observed Outcome runtime evidence or failed-closed Learning result has drifted")

    local_forward_fix = contract.get("local_forward_fix", {})
    if local_forward_fix != {
        "implemented_on_sydney_date": "2026-08-28",
        "proposal_counting_basis": "LATEST_CUTOFF_VERSION_PER_OUTCOME_ID",
        "latest_pending_excludes_earlier_closed": True,
        "same_date_conflicting_versions_fail_closed": True,
        "future_versions_fail_closed": True,
        "repeated_versions_of_one_outcome_trigger_threshold": False,
        "twenty_distinct_outcomes_trigger_threshold": True,
        "stored_proposal_deleted_or_rewritten": False,
        "policy_activation_executed": False,
        "aws_calls_executed": False,
        "deployment_executed": False,
        "production_effect": False,
    }:
        errors.append("local latest-logical-Outcome forward fix is incomplete or overclaimed")

    rollback = contract.get("rollback", {})
    if not (
        rollback.get("delete_audit_events_allowed") is False
        and rollback.get("delete_outcomes_allowed") is False
        and rollback.get("rewrite_action_proposal_allowed") is False
        and rollback.get("forward_fix_only_after_append") is True
    ):
        errors.append("append-only evidence cannot be deleted or rewritten")

    assignment = load_contract(root / str(source.get("rollout_contract", ""))) if (root / str(source.get("rollout_contract", ""))).is_file() else {}
    assignment_evidence = assignment.get("verified_release_evidence", {})
    actual_counts = {
        "EDIT": assignment_evidence.get("approver_edit_event_count"),
        "APPROVE": assignment_evidence.get("approver_approve_event_count"),
        "REJECT": assignment_evidence.get("approver_reject_event_count"),
        "COMPLETE": assignment_evidence.get("complete_event_count"),
    }
    if not (
        assignment.get("status") == source.get("required_rollout_status")
        and assignment.get("canary", {}).get("current_action_status") == source.get("required_action_status")
        and assignment.get("canary", {}).get("action_complete_completed") is True
        and assignment.get("canary", {}).get("action_complete_agent_executed") is False
        and assignment.get("canary", {}).get("action_complete_reconciled") is True
        and actual_counts == source.get("required_audit_counts")
        and assignment_evidence.get("approver_assignment_match_count")
        == source.get("required_assignment_match_count")
    ):
        errors.append("source Action rollout is not the completed and reconciled prerequisite")

    mutation = (root / "lambda" / "glap_action_mutation.py").read_text(encoding="utf-8")
    operations = (root / "lambda" / "glap_operations_api.py").read_text(encoding="utf-8")
    closed_loop = (root / "lambda" / "glap_governed_closed_loop.py").read_text(encoding="utf-8")
    lifecycle_adapter = (root / "lambda" / "glap_lifecycle_athena_adapter.py").read_text(
        encoding="utf-8"
    )
    renderer = (root / "ops" / "render_action_complete_outcome_canary_plan.py").read_text(encoding="utf-8")
    preflight = (root / "ops" / "preflight_action_complete_outcome_staging.ps1").read_text(encoding="utf-8")
    complete_reconciliation = (root / "ops" / "reconcile_action_complete_staging.ps1").read_text(encoding="utf-8")
    pending_reconciliation = (root / "ops" / "reconcile_pending_outcome_staging.ps1").read_text(encoding="utf-8")
    due_date_gate = (root / "ops" / "check_observed_outcome_due_date.ps1").read_text(encoding="utf-8")
    observed_reconciliation = (
        root / "ops" / "reconcile_observed_outcome_learning_staging.ps1"
    ).read_text(encoding="utf-8")
    if '("APPROVED", "COMPLETE"): "COMPLETED"' not in mutation or "A named human actor is required" not in mutation:
        errors.append("mutation implementation no longer preserves approved-to-completed named-human semantics")
    if '"COMPLETE": "actions:complete"' not in operations or 'ZoneInfo("Australia/Sydney")' not in operations:
        errors.append("Operations API no longer preserves COMPLETE permission or Sydney date derivation")
    if "observation_lag_days: int = 3" not in closed_loop or "if as_of_date < due_date" not in closed_loop:
        errors.append("Outcome implementation no longer preserves the three-day pending gate")
    if "minimum_observed: int = 20" not in closed_loop or '"status": "PENDING_HUMAN_REVIEW"' not in closed_loop:
        errors.append("Learning implementation no longer preserves the review-only threshold")
    if not all(
        marker in closed_loop
        for marker in (
            "def latest_outcome_versions(",
            'raise ValueError("Outcome history contains a future version")',
            'raise ValueError("Outcome history contains conflicting versions")',
            "latest_versions = latest_outcome_versions(outcomes, as_of_date)",
        )
    ):
        errors.append("Learning proposal generation lost latest logical Outcome cardinality")
    if not all(
        marker in lifecycle_adapter
        for marker in (
            "outcome_history = [*existing_outcomes, *outcomes]",
            "outcome_history, policy_version, logical_date, minimum_observed",
        )
    ) or "closed_history =" in lifecycle_adapter:
        errors.append("lifecycle adapter filters state before latest Outcome selection")
    renderer_lower = renderer.lower()
    if any(
        token in renderer_lower
        for token in (
            "boto3",
            "requests",
            "urllib",
            "subprocess",
            "invoke-restmethod",
            "invoke-webrequest",
            "write_text(",
            "write_bytes(",
        )
    ) or '"external_writes_executed": false' not in renderer_lower:
        errors.append("redacted renderer must remain local and non-executing")
    preflight_lower = preflight.lower()
    if not all(
        marker in preflight_lower
        for marker in (
            "count(*) as candidate_action_count",
            "current.status = 'approved'",
            "events.complete_event_count = 0",
            "coalesce(sum(outcome_count), 0) as outcome_count",
            "protected identifiers were not printed",
        )
    ):
        errors.append("runtime preflight no longer verifies the exact approved no-Outcome state")
    if "write-host $query" in preflight_lower or any(
        statement in preflight_lower
        for statement in ("insert into", "merge into", "update ", "delete from")
    ):
        errors.append("runtime preflight must remain aggregate-only and read-only")
    complete_lower = complete_reconciliation.lower()
    if not all(
        marker in complete_lower
        for marker in (
            "count(*) as candidate_action_count",
            "current.status = 'completed'",
            "events.complete_event_count = 1",
            "events.named_complete_actor_count = 1",
            "coalesce(sum(outcome_count), 0) as outcome_count",
            "protected identifiers were not printed",
        )
    ):
        errors.append("COMPLETE reconciliation no longer verifies the exact completed no-Outcome state")
    if "write-host $query" in complete_lower or any(
        statement in complete_lower
        for statement in ("insert into", "merge into", "update ", "delete from")
    ):
        errors.append("COMPLETE reconciliation must remain aggregate-only and read-only")
    pending_lower = pending_reconciliation.lower()
    if not all(
        marker in pending_lower
        for marker in (
            "outcome.status = 'pending'",
            "outcome.observed_date is null",
            "outcome.effect_pct is null",
            "outcome.provenance = 'simulated'",
            "date_add('day', 3, candidate.completed_date)",
            "protected identifiers were not printed",
        )
    ):
        errors.append("pending Outcome reconciliation no longer verifies unobserved simulated evidence")
    if "write-host $query" in pending_lower or any(
        statement in pending_lower
        for statement in ("insert into", "merge into", "update ", "delete from")
    ):
        errors.append("pending Outcome reconciliation must remain aggregate-only and read-only")
    due_lower = due_date_gate.lower()
    if not all(
        marker in due_lower
        for marker in (
            "get-sydneybusinessdate",
            "australia/sydney",
            "aus eastern standard time",
            "runtime_pending_outcome.observation_due_date",
            "blocked: observation due date has not been reached",
            "external writes executed: false",
        )
    ):
        errors.append("observation due-date gate must remain system-derived and fail closed")
    if any(token in due_lower for token in (" aws ", "athena", "invoke-restmethod", "invoke-webrequest")):
        errors.append("observation due-date gate must remain local and network-free")
    observed_lower = observed_reconciliation.lower()
    if not all(
        marker in observed_lower
        for marker in (
            "observation due date has not been reached; no aws call was made",
            "partition by outcome.outcome_id",
            "outcome.row_rank = 1",
            "outcome.observed_date >= outcome.observation_due_date",
            "outcome.observed_date <= date '$sydneydatetext'",
            "eligible outcome count advanced by exactly one",
            "policy review threshold remains unmet",
            "no policy proposal exists below the threshold",
            "no policy proposal is activated",
            "protected identifiers were not printed",
        )
    ):
        errors.append("observed Outcome reconciliation must retain temporal, Learning, and policy gates")
    due_gate_position = observed_lower.find("observation due date has not been reached")
    aws_setup_position = observed_lower.find("$awsscope")
    if due_gate_position < 0 or aws_setup_position < 0 or due_gate_position > aws_setup_position:
        errors.append("observed Outcome reconciliation must fail before any AWS setup")
    if "write-host $query" in observed_lower or any(
        statement in observed_lower
        for statement in ("insert into", "merge into", "update ", "delete from")
    ):
        errors.append("observed Outcome reconciliation must remain aggregate-only and read-only")
    return errors


def main() -> int:
    errors = validate_contract(load_contract())
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    print(
        "PASS: the closed simulated Outcome and failed-closed Learning result "
        "are preserved; the latest-logical-Outcome source fix is locally "
        "verified and not deployed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
