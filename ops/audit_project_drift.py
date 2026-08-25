"""Read-only architecture, capability, documentation, and evidence drift audit."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "lambda"))
from glap_temporal_boundary import sydney_business_date  # noqa: E402


SCHEMA_VERSION = "project-drift-contract.v1"
ALLOWED_CAPABILITY_STATES = {
    "IMPLEMENTED_VERIFIED",
    "IMPLEMENTED_STAGING",
    "PARTIAL",
    "BLOCKED_EVIDENCE",
    "NOT_IMPLEMENTED",
}
PROTECTED_MANUAL_WORKFLOWS = (
    ".github/workflows/deploy-stateful-lifecycle-staging.yml",
    ".github/workflows/backtest-multimodal-forecast-staging.yml",
    ".github/workflows/project-drift-audit.yml",
    ".github/workflows/plan-action-mutation-staging.yml",
)


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    category: str
    status: str
    summary: str
    evidence: tuple[str, ...] = ()


def _result(
    check_id: str,
    category: str,
    passed: bool,
    success: str,
    failure: str,
    evidence: Iterable[str] = (),
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=category,
        status="PASS" if passed else "DRIFT",
        summary=success if passed else failure,
        evidence=tuple(evidence),
    )


def load_contract(root: Path) -> dict[str, Any]:
    path = root / "docs/project_drift_contract.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_repository_module(root: Path, relative_path: str) -> Any:
    path = root / relative_path
    module_name = f"glap_drift_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def check_contract(root: Path, contract: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    capabilities = contract.get("capabilities", [])
    capability_ids = [item.get("id") for item in capabilities]
    states = {item.get("state") for item in capabilities}
    baseline_date = str(contract.get("baseline_date", ""))
    try:
        parsed_baseline = datetime.strptime(baseline_date, "%Y-%m-%d").date()
        current_sydney = sydney_business_date()
        baseline_valid = parsed_baseline <= current_sydney
    except ValueError:
        baseline_valid = False

    results.append(
        _result(
            "contract_schema",
            "contract",
            contract.get("schema_version") == SCHEMA_VERSION,
            "The drift contract schema is supported.",
            "The drift contract schema is missing or unsupported.",
            ("docs/project_drift_contract.json",),
        )
    )
    results.append(
        _result(
            "contract_capabilities",
            "contract",
            bool(capabilities)
            and len(capability_ids) == len(set(capability_ids))
            and states <= ALLOWED_CAPABILITY_STATES,
            "Capability IDs are unique and use governed states.",
            "Capability IDs are duplicated or use an unsupported state.",
            ("docs/project_drift_contract.json",),
        )
    )
    results.append(
        _result(
            "contract_calendar_boundary",
            "evidence",
            baseline_valid and contract.get("business_timezone") == "Australia/Sydney",
            "The baseline date respects the current Sydney calendar boundary.",
            "The baseline date is invalid, future-dated, or uses the wrong timezone.",
            ("docs/project_drift_contract.json", "docs/temporal_truthfulness.md"),
        )
    )

    evidence_files: list[str] = list(contract.get("canonical_sources", []))
    for capability in capabilities:
        evidence_files.extend(capability.get("evidence_files", []))
    safe_paths = all(
        path
        and not Path(path).is_absolute()
        and ".." not in Path(path).parts
        for path in evidence_files
    )
    present = safe_paths and all((root / path).is_file() and (root / path).stat().st_size for path in evidence_files)
    results.append(
        _result(
            "contract_evidence_files",
            "evidence",
            present,
            "Every declared evidence file exists and is non-empty.",
            "A declared evidence path is unsafe, missing, or empty.",
            tuple(sorted(set(evidence_files))),
        )
    )
    return results


def check_manual_staging_boundary(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    scheduled: list[str] = []
    for relative_path in PROTECTED_MANUAL_WORKFLOWS:
        text = (root / relative_path).read_text(encoding="utf-8")
        if re.search(r"(?m)^  schedule:\s*$", text):
            scheduled.append(relative_path)
    results.append(
        _result(
            "manual_staging_workflows",
            "architecture",
            not scheduled,
            "Protected staging and audit workflows remain manual-only.",
            "A protected staging workflow contains a recurring schedule trigger.",
            PROTECTED_MANUAL_WORKFLOWS,
        )
    )

    template_path = "infrastructure/stateful-lifecycle-staging.yaml"
    template = (root / template_path).read_text(encoding="utf-8")
    forbidden_resources = ("AWS::Scheduler::Schedule", "AWS::Lambda::Alias")
    results.append(
        _result(
            "isolated_stateful_stack",
            "architecture",
            not any(resource in template for resource in forbidden_resources),
            "The stateful staging stack has no Scheduler or Lambda alias resource.",
            "The stateful staging stack gained a Scheduler or Lambda alias resource.",
            (template_path,),
        )
    )
    return results


def check_stateful_recovery_evidence_boundary(
    root: Path, contract: dict[str, Any]
) -> list[CheckResult]:
    status_path = "CURRENT_DEVELOPMENT_STATUS.md"
    architecture_path = "docs/architecture_current.md"
    infrastructure_path = "INFRASTRUCTURE.md"
    status = " ".join((root / status_path).read_text(encoding="utf-8").split())
    architecture = " ".join(
        (root / architecture_path).read_text(encoding="utf-8").split()
    )
    infrastructure = " ".join(
        (root / infrastructure_path).read_text(encoding="utf-8").split()
    )
    capability = next(
        (
            item
            for item in contract.get("capabilities", [])
            if item.get("id") == "stateful_multimodal_lifecycle"
        ),
        {},
    )
    boundary = str(capability.get("boundary", "")).lower()
    required_run_ids = (
        "32670942817",
        "32671064789",
        "32671484061",
        "32672560594",
        "32682049141",
        "32674455765",
        "32676988757",
        "32728891520",
        "32729202007",
        "32731582185",
    )
    stale_status = (
        "persisted status remains failed",
        "persisted controller status remains failed",
        "cross-gap correction is implemented and locally verified but not deployed",
    )
    passed = (
        capability.get("state") == "IMPLEMENTED_STAGING"
        and all(run_id in status for run_id in required_run_ids)
        and all(run_id in architecture for run_id in required_run_ids)
        and all(run_id in infrastructure for run_id in required_run_ids)
        and "41/41 checks" in status
        and "10/10 fail-closed checks" in status
        and "terminal success" in status
        and "real_world_evidence=false" in status
        and not any(marker in status.lower() for marker in stale_status)
        and "28 lifecycle" in boundary
        and "5 compatibility" in boundary
        and "8 analytics" in boundary
        and "actual-calendar continuation" in boundary
        and "2026-08-24" in boundary
        and "41 checks per date" in boundary
        and "failed closed" in boundary
        and "operational baseline view" in boundary
        and "10-check contract" in boundary
        and "aggregate-only pages publication" in boundary
        and "source coverage equals cutoff" in boundary
        and "without redeploying sql" in boundary
        and "real-world evidence false" in boundary
        and "without seed" in boundary
        and "replay" in boundary
        and "production alias" in boundary
        and "schedule" in boundary
        and "pages" in boundary
        and "action mutation" in boundary
    )
    return [
        _result(
            "stateful_cross_gap_recovery_boundary",
            "governance",
            passed,
            "The recovery, operational baseline, public export, and cutoff/source safeguard remain complete, synthetic, and authority bounded.",
            "The lifecycle recovery, operational baseline, public export, or cutoff/source safeguard is stale, incomplete, or claims a wider authority boundary.",
            (
                "docs/project_drift_contract.json",
                status_path,
                architecture_path,
                infrastructure_path,
            ),
        )
    ]


def check_public_private_boundary(root: Path) -> list[CheckResult]:
    workflow_path = ".github/workflows/pages.yml"
    workflow = (root / workflow_path).read_text(encoding="utf-8").upper()
    private_markers = (
        "GLAP_OPERATIONS",
        "COGNITO",
        "OPERATIONS_API_URL",
        "OPERATIONS_JWT",
    )
    return [
        _result(
            "public_private_configuration",
            "architecture",
            not any(marker in workflow for marker in private_markers),
            "The public Pages workflow contains no private Operations/Cognito configuration.",
            "The public Pages workflow contains a private Operations or Cognito marker.",
            (workflow_path, "docs/ops_snapshot.md"),
        )
    ]


def check_governed_action_outcome_boundary(root: Path) -> list[CheckResult]:
    architecture_path = "docs/architecture_current.md"
    source = (root / architecture_path).read_text(encoding="utf-8")
    normalized = " ".join(source.split())
    required = (
        "Append immutable Action audit event",
        "Generate delayed simulated Outcome",
        "does not command an external carrier, port, or logistics system",
        "not a measurement of real business performance",
    )
    forbidden = (
        "Execute diversion or escalation",
        "Measure cost and in-stock outcome",
    )
    bounded = all(marker in normalized for marker in required) and not any(
        marker in normalized for marker in forbidden
    )
    return [
        _result(
            "governed_action_outcome_claims",
            "architecture",
            bounded,
            "The current architecture records governed Action events and labels delayed Outcomes as simulated.",
            "The current architecture implies external logistics execution or measured real-world outcomes.",
            (architecture_path, "docs/governed_closed_loop.md"),
        )
    ]


def check_audit_automation(root: Path) -> list[CheckResult]:
    ci_path = ".github/workflows/ci.yml"
    workflow_path = ".github/workflows/project-drift-audit.yml"
    ci = (root / ci_path).read_text(encoding="utf-8")
    workflow = (root / workflow_path).read_text(encoding="utf-8")
    command = "python ops/audit_project_drift.py"
    read_only = (
        "contents: read" in workflow
        and "id-token: write" not in workflow
        and "pages: write" not in workflow
        and "actions: write" not in workflow
    )
    hook_path = ".githooks/pre-commit"
    gate_path = "ops/run_pre_commit_checks.py"
    installer_path = "ops/install_project_hooks.ps1"
    hook = (root / hook_path).read_text(encoding="utf-8")
    gate = (root / gate_path).read_text(encoding="utf-8")
    installer = (root / installer_path).read_text(encoding="utf-8")
    staged_gate = (
        gate_path in hook
        and "--worktree" not in hook
        and '"checkout-index", "--all"' in gate
        and '"git", "diff", "--cached", "--check"' in gate
        and "git config --local core.hooksPath .githooks" in installer
        and "git config --local glap.pythonPath $pythonPath" in installer
        and "--global" not in installer
    )
    return [
        _result(
            "drift_audit_automation",
            "automation",
            command in ci and command in workflow and read_only,
            "CI and the manual report workflow run the same read-only drift audit.",
            "Drift automation is missing from CI/manual reporting or gained write permission.",
            (ci_path, workflow_path),
        ),
        _result(
            "pre_commit_drift_gate",
            "automation",
            staged_gate,
            "The versioned pre-commit hook audits the exact staged snapshot before commit.",
            "The pre-commit hook is missing, worktree-only, or not repository-scoped.",
            (hook_path, gate_path, installer_path),
        ),
    ]


def _extract_action_operations(source: str) -> set[str]:
    match = re.search(r"operation\s+not\s+in\s+\{([^}]+)\}", source)
    if not match:
        return set()
    return set(re.findall(r'\"([A-Z_]+)\"', match.group(1)))


def check_documentation_operating_model(root: Path) -> list[CheckResult]:
    agents_path = "AGENTS.md"
    plan_path = "DEVELOPMENT_PLAN.md"
    status_path = "CURRENT_DEVELOPMENT_STATUS.md"
    archive_path = "docs/archive/status/README.md"
    changelog_path = "docs/archive/status/CHANGELOG.md"
    daily_log_path = "docs/archive/status/daily-logs/2026-08.md"
    active_paths = (
        agents_path,
        plan_path,
        status_path,
        archive_path,
        changelog_path,
        daily_log_path,
    )
    present = all((root / path).is_file() for path in active_paths)
    if present:
        agents = (root / agents_path).read_text(encoding="utf-8")
        plan = (root / plan_path).read_text(encoding="utf-8")
        status = (root / status_path).read_text(encoding="utf-8")
        archive = (root / archive_path).read_text(encoding="utf-8")
        role_markers = all(
            marker in agents
            for marker in (
                "## Documentation Operating Model",
                "DEVELOPMENT_PLAN.md",
                "CURRENT_DEVELOPMENT_STATUS.md",
                "docs/archive/status/",
            )
        )
        plan_markers = all(
            marker in plan
            for marker in ("## Product thesis", "## Delivery order", "## P3")
        )
        status_markers = all(
            marker in status
            for marker in (
                "## Current product reality",
                "## Active slice",
                "## Pending validation",
                "## Next Up",
                "### Codex-run validation",
                "### User-reported validation",
                "### Incomplete",
            )
        )
        archive_bounded = "is not current authority." in archive
    else:
        role_markers = plan_markers = status_markers = archive_bounded = False
    legacy_active = (root / "TODO.md").exists() or (
        root / "docs/implementation_roadmap.md"
    ).exists()
    active_handoffs = bool(list((root / "docs").glob("development_handoff_*.md")))
    return [
        _result(
            "documentation_operating_model",
            "documentation",
            present
            and role_markers
            and plan_markers
            and status_markers
            and archive_bounded
            and not legacy_active
            and not active_handoffs,
            "Rules, direction, current truth, and archived history remain separate.",
            "Documentation roles are incomplete, ambiguous, or legacy mixed-purpose files remain active.",
            active_paths,
        )
    ]


def check_action_contract(root: Path, contract: dict[str, Any]) -> list[CheckResult]:
    mutation_path = "lambda/glap_action_mutation.py"
    plan_path = "DEVELOPMENT_PLAN.md"
    status_path = "CURRENT_DEVELOPMENT_STATUS.md"
    mutation = (root / mutation_path).read_text(encoding="utf-8")
    plan = (root / plan_path).read_text(encoding="utf-8")
    status = (root / status_path).read_text(encoding="utf-8")
    actual = _extract_action_operations(mutation)
    expected = set(contract.get("action_contract", {}).get("implemented_operations", []))
    not_implemented = set(contract.get("action_contract", {}).get("not_implemented", []))
    required_fields = set(contract.get("action_contract", {}).get("required_assignment_fields", []))
    fields_implemented = required_fields == {"owner", "due_date"} and all(
        token in mutation for token in ("action_owner", "action_due_date")
    )
    plan_current = "approve/edit/reject/complete" in plan
    status_current = all(
        marker in status
        for marker in (
            "Action assignment canary",
            "named-human `COMPLETE`, and aggregate completion reconciliation are runtime-verified",
            "One pending simulated Outcome passed 6/6 reconciliation",
        )
    )
    return [
        _result(
            "action_operations",
            "function",
            bool(actual) and actual == expected and actual.isdisjoint(not_implemented)
            and fields_implemented,
            "Implemented Action operations match the capability contract.",
            "Action operations differ from the declared capability contract.",
            (mutation_path, "docs/project_drift_contract.json"),
        ),
        _result(
            "action_documentation",
            "documentation",
            plan_current and status_current,
            "Development plan and current status match the Action edit/assignment implementation.",
            "Development plan or current status differs from the Action edit/assignment implementation.",
            (plan_path, status_path),
        ),
    ]


def check_action_assignment_rollout(root: Path) -> list[CheckResult]:
    contract_path = "docs/action_assignment_rollout_contract.json"
    rollout = json.loads((root / contract_path).read_text(encoding="utf-8"))
    authority = rollout.get("authority", {})
    protected_authority = (
        "schema_migration_authorized",
        "lambda_deployment_authorized",
        "api_deployment_authorized",
        "frontend_publication_authorized",
        "operational_action_mutation_authorized",
        "recurring_schedule_authorized",
    )
    schema = rollout.get("schema", {})
    bounded = (
        rollout.get("status")
        == "CANARY_COMPLETE_VERIFIED"
        and rollout.get("business_timezone") == "Australia/Sydney"
        and rollout.get("evidence_boundary") == "SYNTHETIC_STAGING_ONLY"
        and all(authority.get(field) is False for field in protected_authority)
        and schema.get("additive_only") is True
        and schema.get("automatic_workflow_wiring") is False
        and schema.get("migration_applied") is True
        and schema.get("post_migration_validation_passed") is True
        and rollout.get("release_paths", {}).get("action_mutation_lambda")
        == "STAGING_RELEASE_VERIFIED_FUTURE_WRITES_REQUIRE_APPROVAL"
        and rollout.get("release_paths", {}).get("response_serialization_fix")
        == "DEPLOYED_VERIFIED_2026_08_23_FUTURE_WRITES_REQUIRE_APPROVAL"
        and rollout.get("release_paths", {}).get("operations_api")
        == "STAGING_RELEASE_VERIFIED_FUTURE_WRITES_REQUIRE_APPROVAL"
        and rollout.get("release_paths", {}).get("internal_frontend")
        == "STAGING_RELEASE_VERIFIED_FUTURE_WRITES_REQUIRE_APPROVAL"
        and rollout.get("verified_release_evidence", {}).get("stack_final_status")
        == "UPDATE_COMPLETE"
        and rollout.get("verified_release_evidence", {}).get(
            "lambda_digest_matches_artifact"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "schema_migration_applied"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "schema_validation_check_count"
        )
        == 5
        and rollout.get("verified_release_evidence", {}).get(
            "schema_validation_failure_count"
        )
        == 0
        and rollout.get("verified_release_evidence", {}).get(
            "operations_api_stack_final_status"
        )
        == "UPDATE_COMPLETE"
        and rollout.get("verified_release_evidence", {}).get(
            "operations_api_artifact_matches_commit"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "internal_frontend_deployment_status"
        )
        == "SUCCEED"
        and rollout.get("verified_release_evidence", {}).get(
            "assignment_runtime_verification_passed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "four_role_verification_passed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "temporary_role_users_remaining"
        )
        == 0
        and rollout.get("verified_release_evidence", {}).get(
            "operational_action_mutation_executed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "canary_edit_event_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "canary_edit_request_id_row_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "canary_edit_current_edited_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "response_serialization_fix_deployed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "response_serialization_fix_stack_final_status"
        )
        == "UPDATE_COMPLETE"
        and rollout.get("verified_release_evidence", {}).get(
            "stable_retry_http_status"
        )
        == 200
        and rollout.get("verified_release_evidence", {}).get(
            "stable_retry_idempotent_replay"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "stable_retry_request_id_row_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "stable_retry_current_edited_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "stable_retry_assignment_match_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "approver_edit_event_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "approver_approve_event_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "approver_reject_event_count"
        )
        == 0
        and rollout.get("verified_release_evidence", {}).get(
            "approver_complete_event_count"
        )
        == 0
        and rollout.get("verified_release_evidence", {}).get(
            "approver_distinct_named_actor_count"
        )
        == 2
        and rollout.get("verified_release_evidence", {}).get(
            "approver_current_approved_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "approver_assignment_match_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "complete_event_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "complete_named_actor_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "complete_current_completed_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "complete_assignment_match_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "complete_outcome_count_before_continuation"
        )
        == 0
        and rollout.get("verified_release_evidence", {}).get(
            "complete_reconciliation_passed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "complete_protected_identifiers_printed"
        )
        is False
        and rollout.get("verified_release_evidence", {}).get(
            "complete_production_effect"
        )
        is False
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_workflow_run_id"
        )
        == 32803181376
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_workflow_result"
        )
        == "PASS"
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_actual_calendar_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_current_pending_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_unobserved_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_simulated_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_due_date_rule_match_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_reconciliation_passed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_protected_identifiers_printed"
        )
        is False
        and rollout.get("verified_release_evidence", {}).get(
            "pending_outcome_production_effect"
        )
        is False
        and rollout.get("verified_release_evidence", {}).get(
            "evidence_refresh_interaction_canary_executed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "evidence_refresh_interaction_canary_auto_refresh_observed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "evidence_refresh_interaction_canary_backend_reconciled"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "evidence_refresh_interaction_canary_edit_event_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "evidence_refresh_interaction_canary_current_edited_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "evidence_refresh_interaction_canary_current_assignment_match_count"
        )
        == 1
        and rollout.get("verified_release_evidence", {}).get(
            "operator_global_sign_out_completed"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get(
            "operator_group_membership_operator_only"
        )
        is True
        and rollout.get("verified_release_evidence", {}).get("production_effect")
        is False
        and rollout.get("verified_release_evidence", {}).get(
            "future_release_write_authority_approved"
        )
        is False
        and rollout.get("rollback", {}).get(
            "package_rollback_requires_zero_edit_events"
        )
        is True
        and rollout.get("canary", {}).get("agent_execution_allowed") is False
        and rollout.get("canary", {}).get("operator_edit_completed") is True
        and rollout.get("canary", {}).get("stable_request_id_retry_completed") is True
        and rollout.get("canary", {}).get("named_approver_decision_completed") is True
        and rollout.get("canary", {}).get("named_approver_decision") == "APPROVE"
        and rollout.get("canary", {}).get("current_action_status") == "COMPLETED"
        and rollout.get("canary", {}).get("action_complete_completed") is True
        and rollout.get("canary", {}).get("action_complete_agent_executed") is False
        and rollout.get("canary", {}).get("action_complete_reconciled") is True
        and rollout.get("canary", {}).get("pending_outcome_continuation_completed")
        is True
        and rollout.get("canary", {}).get("pending_outcome_reconciled") is True
        and rollout.get("canary", {}).get("current_blocker")
        == "OBSERVATION_DUE_DATE_NOT_REACHED_AND_CONTINUATION_NOT_AUTHORIZED"
    )
    return [
        _result(
            "action_assignment_rollout_boundary",
            "governance",
            bounded,
            "Action assignment, named-human COMPLETE, and the pending simulated Outcome are reconciled; observation remains calendar-gated and separately unauthorized.",
            "Action assignment rollout hides verified evidence or expands deployment, mutation, completion, or scheduling authority.",
            (
                contract_path,
                "docs/action_assignment_staging_rollout.md",
                "ops/validate_action_assignment_rollout.py",
                "ops/reconcile_action_evidence_refresh_staging.ps1",
                "sql/16_action_assignment_validation.sql",
            ),
        )
    ]


def check_action_complete_outcome_canary(root: Path) -> list[CheckResult]:
    contract_path = "docs/action_complete_outcome_canary_v1.json"
    evidence = (
        contract_path,
        "docs/action_complete_outcome_canary.md",
        "ops/validate_action_complete_outcome_canary.py",
        "ops/render_action_complete_outcome_canary_plan.py",
        "ops/preflight_action_complete_outcome_staging.ps1",
        "ops/reconcile_action_complete_staging.ps1",
        "ops/reconcile_pending_outcome_staging.ps1",
        "ops/check_observed_outcome_due_date.ps1",
        "ops/reconcile_observed_outcome_learning_staging.ps1",
        "tests/test_action_complete_outcome_canary.py",
    )
    try:
        validator = _load_repository_module(
            root, "ops/validate_action_complete_outcome_canary.py"
        )
        contract = validator.load_contract(root / contract_path)
        errors = validator.validate_contract(contract, root)
        passed = not errors
        failure = (
            "The local COMPLETE-to-Outcome canary contract drifted: "
            + "; ".join(errors)
        )
    except Exception as error:
        passed = False
        failure = f"The local COMPLETE-to-Outcome canary package is invalid: {error}."
    return [
        _result(
            "action_complete_outcome_canary_boundary",
            "governance",
            passed,
            "The pending simulated Outcome is reconciled and its observed Outcome/Learning verifier is implemented; observation remains calendar-gated and separately unauthorized.",
            failure,
            evidence,
        )
    ]


def check_action_mutation_release(root: Path) -> list[CheckResult]:
    contract_path = "docs/action_mutation_staging_release_contract.json"
    release = json.loads((root / contract_path).read_text(encoding="utf-8"))
    proposal_path = "docs/action_mutation_staging_read_permission_proposal.json"
    proposal_file = root / proposal_path
    proposal = (
        json.loads(proposal_file.read_text(encoding="utf-8"))
        if proposal_file.is_file()
        else {}
    )
    authority = release.get("authority", {})
    design = release.get("selected_design", {})
    ownership = release.get("cloudformation_ownership", {})
    blockers = release.get("current_blockers", {})
    runtime = release.get("runtime_evidence", {})
    proposal_authority = proposal.get("authority", {})
    access_path = "docs/action_mutation_staging_release_access_proposal.json"
    access_file = root / access_path
    access = (
        json.loads(access_file.read_text(encoding="utf-8"))
        if access_file.is_file()
        else {}
    )
    access_authority = access.get("authority", {})
    bounded = (
        release.get("status")
        == "STAGING_RELEASE_VERIFIED_FUTURE_WRITES_REQUIRE_APPROVAL"
        and release.get("evidence_boundary") == "SYNTHETIC_STAGING_ONLY"
        and release.get("authority_scope")
        == "NO_STANDING_FUTURE_WRITE_AUTHORITY"
        and authority.get("workflow_implementation_authorized") is True
        and authority.get("read_permission_human_approved") is True
        and all(
            value is False
            for key, value in authority.items()
            if key
            not in (
                "workflow_implementation_authorized",
                "read_permission_human_approved",
            )
        )
        and ownership.get("direct_update_function_code_allowed") is False
        and design.get("kind")
        == "EXISTING_STACK_PREVIOUS_TEMPLATE_PARAMETER_ONLY_CHANGE_SET"
        and design.get("use_previous_template") is True
        and design.get("changed_parameters") == ["ActionMutationArtifactKey"]
        and len(design.get("allowed_changes", [])) == 1
        and design["allowed_changes"][0].get("logical_resource_id")
        == "ActionMutationFunction"
        and blockers.get("repository_deployer_policy_includes_mutation_function")
        is False
        and blockers.get("actual_aws_permissions_inspected") is True
        and blockers.get("required_lambda_read_permission_present") is True
        and blockers.get("read_permission_human_approved") is True
        and blockers.get("live_iam_permission_applied") is True
        and blockers.get("agent_iam_change_authorized") is False
        and blockers.get("narrow_workflow_implemented") is True
        and blockers.get("prepare_execute_workflow_implemented") is True
        and blockers.get("release_write_authority_approved") is False
        and blockers.get("one_time_release_completed") is True
        and release.get("release_workflow", {}).get("executed") is True
        and runtime.get("result") == "STAGING_RELEASE_VERIFIED"
        and runtime.get("aws_inspection_passed") is True
        and runtime.get("cloudformation_ownership_verified") is True
        and runtime.get("stable_lambda_configuration_verified") is True
        and runtime.get("aws_write_observed") is True
        and runtime.get("artifact_upload_observed") is True
        and runtime.get("change_set_created_or_executed") is True
        and runtime.get("exact_one_resource_change_verified") is True
        and runtime.get("stack_final_status") == "UPDATE_COMPLETE"
        and runtime.get("lambda_code_updated") is True
        and runtime.get("lambda_digest_matches_artifact") is True
        and runtime.get("iam_or_cloudformation_modified") is True
        and runtime.get("rollback_recovery_exercised") is True
        and runtime.get("rollback_resource_skip_used") is False
        and runtime.get("production_effect") is False
        and release.get("read_permission_proposal") == proposal_path
        and release.get("release_access_proposal") == access_path
        and proposal.get("status")
        == "APPROVED_FOR_NAMED_HUMAN_APPLICATION"
        and proposal.get("requested_capability", {}).get("actions")
        == ["lambda:GetFunctionConfiguration"]
        and proposal.get("requested_capability", {})
        .get("resource_selector", {})
        .get("wildcard_allowed")
        is False
        and proposal_authority.get("proposal_recording_authorized") is True
        and proposal_authority.get("human_application_authorized") is True
        and all(
            value is False
            for key, value in proposal_authority.items()
            if key
            not in (
                "proposal_recording_authorized",
                "human_application_authorized",
            )
        )
        and access.get("status") == "PROPOSED_AWAITING_NAMED_HUMAN_REVIEW"
        and access.get("proposal_shape", {}).get("executable_iam_policy_document") is False
        and access.get("proposal_shape", {}).get("contains_account_id_or_arn") is False
        and access_authority.get("repository_proposal_authorized") is True
        and all(
            value is False
            for key, value in access_authority.items()
            if key != "repository_proposal_authorized"
        )
    )
    return [
        _result(
            "action_mutation_release_boundary",
            "governance",
            bounded,
            "The narrow prepare/execute workflow completed one verified staging release; future writes remain separately approved and agent IAM/AWS release authority remains prohibited.",
            "The mutation release expands authority, hides runtime evidence, or broadens the read-permission proposal.",
            (
                contract_path,
                proposal_path,
                access_path,
                "docs/action_mutation_staging_release_access.md",
                "docs/action_mutation_staging_release_rfc.md",
                "ops/validate_action_mutation_staging_release.py",
                ".github/workflows/release-action-mutation-staging.yml",
                "ops/prepare_action_mutation_staging_release.ps1",
                "ops/execute_action_mutation_staging_release.ps1",
            ),
        )
    ]


def check_readiness_contract(root: Path) -> list[CheckResult]:
    contract_path = "docs/production_readiness_contract.json"
    contract = json.loads((root / contract_path).read_text(encoding="utf-8"))
    authority = contract.get("authority", {})
    forbidden_authority = (
        "recurring_schedule_enabled",
        "production_alias_change_authorized",
        "production_table_write_authorized",
        "policy_activation_authorized",
        "model_promotion_authorized",
    )
    bounded = (
        contract.get("status") == "DESIGNED_NOT_DEPLOYED"
        and authority.get("named_human_owner_required") is True
        and all(authority.get(field) is False for field in forbidden_authority)
        and contract.get("business_timezone") == "Australia/Sydney"
        and contract.get("evidence_boundary") == "SYNTHETIC_ENGINEERING_ONLY"
    )
    return [
        _result(
            "production_readiness_boundary",
            "governance",
            bounded,
            "Production-readiness controls remain explicit, plan-only, and authority bounded.",
            "The production-readiness contract claims deployment or expands protected authority.",
            (contract_path, "docs/athena_cost_governance.md", "docs/incremental_refresh_contract.md"),
        )
    ]


def check_temporal_boundary(root: Path) -> list[CheckResult]:
    api_path = "lambda/glap_operations_api.py"
    source = (root / api_path).read_text(encoding="utf-8")
    required = (
        "temporal_scope_id = 'OPERATIONAL'",
        "time_basis = 'ACTUAL_CALENDAR'",
        '"production_effect": False',
    )
    return [
        _result(
            "operations_temporal_boundary",
            "architecture",
            all(marker in source for marker in required),
            "Private Operations queries retain operational-calendar filters and no production forecast effect.",
            "A required operational-calendar or no-production-effect marker is missing.",
            (api_path, "docs/temporal_truthfulness.md"),
        )
    ]


def _canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_a303_outcome_robustness_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "simulator": "docs/a303_outcome_simulator_v1.json",
        "protocol": "docs/a303_outcome_sensitivity_protocol_v1.json",
        "gate": "docs/a303_synthetic_capability_gate_v1.json",
        "result": "docs/a303_synthetic_outcome_robustness_result_v1.json",
    }
    loaded: dict[str, dict[str, Any]] = {}
    try:
        for name, path in paths.items():
            loaded[name] = json.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    simulator = loaded.get("simulator", {})
    protocol = loaded.get("protocol", {})
    gate = loaded.get("gate", {})
    result = loaded.get("result", {})
    coverage = simulator.get("coverage_contract", {})
    simulator_authority = simulator.get("authority", {})
    gate_handling = gate.get("decision_quality_handling", {})
    result_gate = result.get("capability_gate", {})
    unsupported = set(result.get("claim_boundary", {}).get("does_not_support", []))
    simulator_digest = _canonical_digest(simulator) if simulator else ""
    protocol_digest = _canonical_digest(protocol) if protocol else ""
    gate_digest = _canonical_digest(gate) if gate else ""
    frozen = result.get("frozen_inputs", {})
    bounded = (
        simulator.get("schema_version") == "a303-outcome-simulator.v1"
        and simulator.get("outcome_evidence_class") == "SIMULATED_COUNTERFACTUAL"
        and coverage.get("frozen_decision_package_count") == 30
        and coverage.get("expected_attributed_change_count") == 16
        and coverage.get("expected_negative_control_count") == 14
        and coverage.get("human_decision_quality_required_for_simulation") is False
        and protocol.get("design", {}).get("expected_combination_count") == 243
        and protocol.get("design", {}).get("ranges_frozen_before_confirmatory_run") is True
        and protocol.get("simulator", {}).get("sha256") == simulator_digest
        and gate.get("simulator", {}).get("sha256") == simulator_digest
        and gate.get("sensitivity_protocol", {}).get("sha256") == protocol_digest
        and gate_handling.get("human_preference_controls_simulator_eligibility") is False
        and gate.get("integrity_prerequisites", {}).get("negative_controls_must_pass_every_parameter_combination") is True
        and simulator_authority.get("mode") == "LOCAL_READ_ONLY"
        and all(
            simulator_authority.get(field) is False
            for field in (
                "network_access_allowed",
                "operational_writes_allowed",
                "action_mutations_allowed",
                "production_effect",
                "model_promotion_allowed",
            )
        )
        and result.get("coverage", {}).get("attributed_change_count") == 16
        and result.get("coverage", {}).get("negative_control_count") == 14
        and result.get("negative_control_integrity", {}).get("status") == "PASS"
        and result.get("negative_control_integrity", {}).get("non_zero_delta_count") == 0
        and frozen.get("simulator_sha256") == simulator_digest
        and frozen.get("sensitivity_protocol_sha256") == protocol_digest
        and frozen.get("capability_gate_sha256") == gate_digest
        and result_gate.get("synthetic_outcome_robustness") == "NOT_ROBUST"
        and result_gate.get("real_business_outcome_effect") == "NOT_EVALUATED"
        and {
            "REAL_LOGISTICS_PERFORMANCE",
            "EMPIRICAL_CALIBRATION",
            "PRODUCTION_READINESS",
            "MODEL_PROMOTION",
            "POLICY_ACTIVATION",
        }.issubset(unsupported)
        and result.get("operational_mutations") == []
    )
    return [
        _result(
            "a303_synthetic_robustness_boundary",
            "evidence",
            bounded,
            "A303 robustness evaluates all 16 changes and 14 controls independently of human preference; controls remain exact-zero and the current synthetic gate remains NOT_ROBUST.",
            "The A303 robustness corpus, frozen inputs, negative controls, independent evaluation path, result, or authority boundary drifted.",
            (
                *paths.values(),
                "ops/evaluate_a303_outcome_robustness.py",
                "docs/evaluation_architecture.md",
            ),
        )
    ]


def check_a303_outcome_calibration_boundary(root: Path) -> list[CheckResult]:
    policy_path = "docs/a303_outcome_calibration_policy_v1.json"
    simulator_path = "docs/a303_outcome_simulator_v1.json"
    try:
        policy = json.loads((root / policy_path).read_text(encoding="utf-8"))
        simulator = json.loads((root / simulator_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        policy = {}
        simulator = {}
    eligible = policy.get("eligible_evidence", {})
    authority = policy.get("authority", {})
    unsupported = set(policy.get("claim_boundary", {}).get("does_not_support", []))
    bounded = (
        policy.get("schema_version") == "a303-outcome-calibration-policy.v1"
        and policy.get("business_timezone") == "Australia/Sydney"
        and policy.get("simulator", {}).get("schema_version")
        == "a303-outcome-simulator.v1"
        and policy.get("simulator", {}).get("sha256") == _canonical_digest(simulator)
        and set(eligible.get("baseline_observation", []))
        == {"OBSERVED_FACTUAL", "PROSPECTIVE_CONTROLLED"}
        and eligible.get("controlled_pair") == ["PROSPECTIVE_CONTROLLED"]
        and eligible.get("required_time_basis") == "ACTUAL_CALENDAR"
        and isinstance(eligible.get("minimum_baseline_observations"), int)
        and eligible["minimum_baseline_observations"] >= 3
        and isinstance(eligible.get("minimum_controlled_pairs"), int)
        and eligible["minimum_controlled_pairs"] >= 3
        and authority.get("mode") == "LOCAL_READ_ONLY"
        and all(
            authority.get(field) is False
            for field in (
                "network_access_allowed",
                "operational_writes_allowed",
                "action_mutations_allowed",
                "production_effect",
                "model_promotion_allowed",
            )
        )
        and {"MODEL_PROMOTION", "PRODUCTION_READINESS", "POLICY_ACTIVATION"}.issubset(unsupported)
    )
    return [
        _result(
            "a303_outcome_calibration_boundary",
            "evidence",
            bounded,
            "A303 calibration requires actual-calendar factual baselines and prospective controlled treatment pairs while remaining local and authority bounded.",
            "The A303 calibration policy broadened eligible evidence, weakened sample gates, or gained operational, production, or promotion authority.",
            (
                policy_path,
                simulator_path,
                "docs/a303_outcome_calibration_input_v1.schema.json",
                "docs/a303_outcome_calibration_report_v1.schema.json",
                "ops/calibrate_a303_outcome_method.py",
                "docs/temporal_truthfulness.md",
            ),
        )
    ]


def check_a303_v2_guardrail_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "proposal": "docs/a303_v2_eligibility_guardrail_proposal.json",
        "result": "docs/a303_v2_guardrail_development_result_v1.json",
        "source": "docs/a303_synthetic_outcome_robustness_result_v1.json",
        "simulator": "docs/a303_outcome_simulator_v1.json",
        "protocol": "docs/a303_outcome_sensitivity_protocol_v1.json",
        "gate": "docs/a303_synthetic_capability_gate_v1.json",
    }
    loaded: dict[str, dict[str, Any]] = {}
    try:
        for name, path in paths.items():
            loaded[name] = json.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    proposal = loaded.get("proposal", {})
    result = loaded.get("result", {})
    source = loaded.get("source", {})
    frozen = proposal.get("frozen_evaluation_inputs", {})
    validation = proposal.get("validation_boundary", {})
    authority = proposal.get("authority", {})
    anti_abstention = proposal.get("anti_abstention_gate", {})
    candidates = result.get("candidate_results", [])
    bounded = (
        proposal.get("schema_version") == "a303-v2-eligibility-guardrail-proposal.v1"
        and proposal.get("proposal_status") == "DEVELOPMENT_ONLY_PENDING_HUMAN_DECISION"
        and proposal.get("design_classification") == "POST_HOC_CANDIDATE_FROM_V1_ROBUSTNESS"
        and proposal.get("source_result", {}).get("sha256") == _canonical_digest(source)
        and source.get("capability_gate", {}).get("synthetic_outcome_robustness") == "NOT_ROBUST"
        and frozen.get("simulator_sha256") == _canonical_digest(loaded.get("simulator", {}))
        and frozen.get("sensitivity_protocol_sha256") == _canonical_digest(loaded.get("protocol", {}))
        and frozen.get("capability_gate_sha256") == _canonical_digest(loaded.get("gate", {}))
        and anti_abstention.get("minimum_action_opportunity_count", 0) >= 3
        and anti_abstention.get("minimum_distinct_action_scenario_count", 0) >= 3
        and anti_abstention.get("minimum_action_subset_non_negative_pct", 0) >= 90.0
        and anti_abstention.get("negative_controls_must_remain_exact_zero") is True
        and validation.get("same_corpus_result_classification") == "POST_HOC_DEVELOPMENT_EVIDENCE"
        and validation.get("same_corpus_can_satisfy_confirmatory_gate") is False
        and validation.get("new_frozen_holdout_required_before_progression") is True
        and authority.get("mode") == "LOCAL_READ_ONLY"
        and all(value is False for key, value in authority.items() if key != "mode")
        and result.get("proposal_sha256") == _canonical_digest(proposal)
        and result.get("source_result_sha256") == _canonical_digest(source)
        and result.get("slice_conclusion", {}).get("status")
        == "NO_A303_V2_GUARDRAIL_CANDIDATE_PASSES_DEVELOPMENT_GATE"
        and result.get("slice_conclusion", {}).get("human_decision_required") is True
        and len(candidates) == 2
        and all(
            item.get("development_disposition") == "REJECT_OR_FUNDAMENTALLY_REDESIGN"
            and item.get("confirmatory_eligibility")
            == "NOT_ELIGIBLE_POST_HOC_SAME_CORPUS"
            for item in candidates
        )
        and result.get("operational_mutations") == []
    )
    return [
        _result(
            "a303_v2_guardrail_candidate_boundary",
            "evidence",
            bounded,
            "A303.v2 guardrail screening remains post-hoc, anti-abstention, authority bounded, and concludes that neither candidate passes the development gate.",
            "The A303.v2 proposal, anti-abstention gate, post-hoc boundary, failed-candidate result, or authority boundary drifted.",
            (
                *paths.values(),
                "ops/evaluate_a303_v2_guardrail_candidate.py",
                "tests/test_a303_v2_guardrail_candidate.py",
                "CURRENT_DEVELOPMENT_STATUS.md",
            ),
        )
    ]


def check_a303_v1_retirement_boundary(root: Path) -> list[CheckResult]:
    decision_path = "docs/a303_v1_retirement_decision.json"
    robustness_path = "docs/a303_synthetic_outcome_robustness_result_v1.json"
    guardrail_path = "docs/a303_v2_guardrail_development_result_v1.json"
    try:
        decision = json.loads((root / decision_path).read_text(encoding="utf-8"))
        robustness = json.loads((root / robustness_path).read_text(encoding="utf-8"))
        guardrail = json.loads((root / guardrail_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        decision = {}
        robustness = {}
        guardrail = {}
    evidence = decision.get("evidence_basis", [])
    evidence_map = {
        item.get("schema_version"): item
        for item in evidence
        if isinstance(item, dict)
    }
    scope = decision.get("scope", {})
    downstream = decision.get("downstream_effect", {})
    reopening = decision.get("reopening_rule", {})
    authority = decision.get("authority_boundary", {})
    bounded = (
        decision.get("schema_version") == "a303-v1-retirement-decision.v1"
        and decision.get("decision_status") == "HUMAN_DECISION_RECORDED"
        and decision.get("decision_source")
        == "EXPLICIT_HUMAN_PROJECT_OWNER_SESSION_SELECTION_OPTION_1"
        and decision.get("decision") == "RETIRE_A303_V1_FROM_PROGRESSION"
        and scope.get("rule_contract") == "A303.v1"
        and {
            "FURTHER_THRESHOLD_TUNING",
            "NEW_A303_V1_HOLDOUT",
            "PROSPECTIVE_OUTCOME_COLLECTION",
            "A303_V1_CALIBRATION",
            "RULE_OR_POLICY_ACTIVATION",
            "PRODUCTION_PROGRESSION",
        }.issubset(set(scope.get("applies_to", [])))
        and "ORIGINAL_REVIEW_SUBMISSIONS"
        in set(scope.get("does_not_delete_or_rewrite", []))
        and evidence_map.get("a303-synthetic-outcome-robustness-result.v1", {}).get("sha256")
        == _canonical_digest(robustness)
        and evidence_map.get("a303-v2-guardrail-development-result.v1", {}).get("sha256")
        == _canonical_digest(guardrail)
        and downstream.get("a303_v1_development_status") == "RETIRED_FROM_PROGRESSION"
        and downstream.get("a303_v1_calibration_status") == "CLOSED_NOT_APPLICABLE"
        and downstream.get("evaluation_history_status") == "PRESERVED_READ_ONLY"
        and downstream.get("deployed_runtime_change") == "NONE_A303_V1_WAS_NOT_DEPLOYED"
        and reopening.get("a303_v1_may_be_reactivated") is False
        and reopening.get("fundamentally_new_rule_requires_new_version") is True
        and reopening.get("new_explicit_human_authorization_required") is True
        and authority.get("scope") == "REPOSITORY_LOCAL_DEVELOPMENT_DIRECTION"
        and all(value is False for key, value in authority.items() if key != "scope")
        and decision.get("operational_mutations") == []
    )
    return [
        _result(
            "a303_v1_retirement_boundary",
            "governance",
            bounded,
            "A303.v1 remains retired from progression by explicit human choice; evidence is preserved and no operational authority is added.",
            "The A303.v1 human retirement decision, evidence preservation, reopening rule, or authority boundary drifted.",
            (
                decision_path,
                "docs/a303_v1_retirement_decision.schema.json",
                robustness_path,
                guardrail_path,
                "ops/validate_a303_v1_retirement.py",
                "tests/test_a303_v1_retirement.py",
                "CURRENT_DEVELOPMENT_STATUS.md",
            ),
        )
    ]


def check_capability_neutral_evaluation_boundary(root: Path) -> list[CheckResult]:
    """Execute the two capability ablations and enforce their claim boundaries."""

    definitions = (
        {
            "check_id": "external_evidence_ablation_boundary",
            "runner": "ops/evaluate_external_evidence_capability.py",
            "fixture": "tests/fixtures/evaluation/external_evidence_ablation_v1.json",
            "schema": "docs/evaluation_experiment_v2.schema.json",
            "capability": "EXTERNAL_EVIDENCE",
            "attribution": "ATTRIBUTED_TO_EXTERNAL_EVIDENCE",
            "required_exclusions": {
                "NEW_BUSINESS_RULE",
                "DECISION_QUALITY_IMPROVEMENT",
                "BUSINESS_OUTCOME_IMPROVEMENT",
                "DEPLOYED_RUNTIME_VERIFICATION",
                "PRODUCTION_READINESS",
            },
        },
        {
            "check_id": "decision_memory_ablation_boundary",
            "runner": "ops/evaluate_decision_memory_capability.py",
            "fixture": "tests/fixtures/evaluation/decision_memory_ablation_v1.json",
            "schema": "docs/evaluation_experiment_v3.schema.json",
            "capability": "DECISION_MEMORY",
            "attribution": "ATTRIBUTED_TO_DECISION_MEMORY",
            "required_exclusions": {
                "NEW_BUSINESS_RULE",
                "AUTONOMOUS_LEARNING",
                "DECISION_QUALITY_IMPROVEMENT",
                "BUSINESS_OUTCOME_IMPROVEMENT",
                "DEPLOYED_RUNTIME_VERIFICATION",
                "PRODUCTION_READINESS",
            },
        },
    )
    expected_boundary = {
        "mode": "LOCAL_READ_ONLY",
        "network_access_allowed": False,
        "operational_writes_allowed": False,
        "production_effect": False,
    }
    results: list[CheckResult] = []
    for definition in definitions:
        evidence = (
            definition["runner"],
            definition["fixture"],
            definition["schema"],
            "docs/evaluation_architecture.md",
            "docs/temporal_truthfulness.md",
        )
        try:
            if not all((root / path).is_file() for path in evidence):
                raise FileNotFoundError("capability-neutral evaluation evidence is incomplete")
            module = _load_repository_module(root, definition["runner"])
            manifest = json.loads((root / definition["fixture"]).read_text(encoding="utf-8"))
            report = module.run_experiment(manifest)
            layers = report["evaluation_layers"]
            bounded = (
                report["execution_boundary"] == expected_boundary
                and report["comparison"]["changed_capability"] == definition["capability"]
                and report["comparison"]["attribution"] == definition["attribution"]
                and layers["system_correctness"]["status"] == "PASS"
                and layers["capability_attribution"]["status"] == "PASS"
                and layers["decision_quality"]["status"] == "NOT_EVALUATED"
                and layers["business_outcome_effect"]["status"] == "NOT_EVALUATED"
                and layers["business_outcome_effect"]["outcome_evidence_class"] == "NOT_EVALUATED"
                and report["operational_mutations"] == []
                and definition["required_exclusions"]
                <= set(report["claim_boundary"]["not_supported"])
                and "A303" not in json.dumps(report, sort_keys=True)
            )
        except (FileNotFoundError, KeyError, TypeError, ValueError, RuntimeError) as error:
            bounded = False
            failure = f"The executable {definition['capability']} boundary drifted: {error}."
        else:
            failure = (
                f"The executable {definition['capability']} boundary permits an unsupported "
                "claim, mutation, temporal leak, or execution mode."
            )
        results.append(
            _result(
                definition["check_id"],
                "evaluation",
                bounded,
                f"{definition['capability']} remains a local read-only capability attribution with higher evaluation layers explicitly unevaluated.",
                failure,
                evidence,
            )
        )
    return results


def check_agent_runtime_boundary(root: Path) -> list[CheckResult]:
    """Execute Agent Runtime v1 and verify parity, bundle, and trace boundaries."""

    runner_path = "ops/run_governed_agent_runtime.py"
    fixture_path = "tests/fixtures/evaluation/agent_runtime_parity_v1.json"
    shared_evidence = (
        runner_path,
        fixture_path,
        "docs/agent_runtime_experiment_v1.schema.json",
        "docs/agent_runtime_host_registry_v1.json",
        "docs/agent_runtime_host_registry_v1.schema.json",
        "docs/agent_runtime_input_bundle_v1.schema.json",
        "docs/agent_runtime_host_trace_v1.schema.json",
        "ops/agent_runtime_adapters/reference_adapter_v1.py",
        "ops/agent_runtime_adapters/independent_adapter_v1.py",
        "docs/evaluation_architecture.md",
        "docs/architecture_current.md",
    )
    registry_ok = runtime_ok = bundle_ok = trace_ok = False
    failure = "The Agent Runtime executable contract or its declared evidence is invalid."
    try:
        if not all((root / path).is_file() for path in shared_evidence):
            raise FileNotFoundError("Agent Runtime evidence is incomplete")
        module = _load_repository_module(root, runner_path)
        manifest = json.loads((root / fixture_path).read_text(encoding="utf-8"))
        report = module.run_experiment(manifest)
        bundle = report["input_bundle"]
        traces = report["host_traces"]
        module.verify_input_bundle(bundle, expected_sha256=bundle["bundle_sha256"])
        for trace in traces:
            module.verify_host_trace(bundle, trace, expected_trace_sha256=trace["trace_sha256"])

        expected_boundary = {
            "mode": "LOCAL_READ_ONLY",
            "network_access_allowed": False,
            "operational_writes_allowed": False,
            "production_effect": False,
        }
        layers = report["evaluation_layers"]
        hosts = report["hosts"]
        architecture = (root / "docs/architecture_current.md").read_text(encoding="utf-8")
        evaluation = (root / "docs/evaluation_architecture.md").read_text(encoding="utf-8")
        normalized_architecture = " ".join(architecture.split())
        normalized_evaluation = " ".join(evaluation.split())
        precise_implementation_maturity = (
            "one deterministic reference adapter and one independently implemented "
            "registered local adapter"
            in normalized_architecture
            and "One reference adapter and one separately registered local "
            "implementation receive identical cutoff-eligible inputs"
            in normalized_evaluation
        )
        registrations = report["adapter_registry"]["registrations"]
        registry_ok = (
            report["adapter_registry"]["schema_version"]
            == "agent-runtime-host-registry.v1"
            and report["host_parity"]["registry_source_integrity"] is True
            and report["host_parity"]["distinct_implementation_paths"] is True
            and len({item["implementation_id"] for item in registrations}) == 2
            and len({item["implementation_group"] for item in registrations}) == 2
            and len({item["module_path"] for item in registrations}) == 2
            and len({item["source_sha256"] for item in registrations}) == 2
            and {
                "HOST_AUTHENTICATION",
                "MODEL_IDENTITY",
                "OPERATIONAL_APPROVAL",
                "ACTION_CREATION",
                "PRODUCTION_READINESS",
            }
            <= set(report["adapter_registry"]["claim_boundary"]["not_supported"])
        )
        runtime_ok = (
            report["execution_boundary"] == expected_boundary
            and len(hosts) == 2
            and len({item["host_id"] for item in hosts}) == 2
            and report["host_parity"]["status"] == "PASS"
            and layers["system_correctness"]["status"] == "PASS"
            and all(
                layers[name]["status"] == "NOT_EVALUATED"
                for name in ("capability_attribution", "decision_quality", "business_outcome_effect")
            )
            and report["operational_mutations"] == []
            and all(item["operational_mutations"] == [] for item in hosts)
            and all(
                item["approval_result"]
                == {
                    "status": "SIMULATED_PENDING_HUMAN_REVIEW",
                    "authority_granted": False,
                    "operational_action_created": False,
                }
                for item in hosts
            )
            and precise_implementation_maturity
            and registry_ok
        )
        cutoff_inputs = bundle["payload"]["cutoff_inputs"]
        included_ids = {
            item.get("evidence_id", item.get("memory_id"))
            for group in cutoff_inputs.values()
            for item in group
        }
        excluded_ids = set(report["input_window"]["post_cutoff_evidence_ids"]) | set(
            report["input_window"]["post_cutoff_memory_ids"]
        )
        bundle_ok = (
            report["host_parity"]["identical_inputs"] is True
            and len({item["input_bundle_sha256"] for item in hosts}) == 1
            and hosts[0]["input_bundle_sha256"] == bundle["bundle_sha256"]
            and not included_ids.intersection(excluded_ids)
            and bundle["payload"]["runtime_envelope"]["authority_profile"]
            == "EVALUATION_NO_MUTATION"
        )
        trace_ok = (
            len(traces) == 2
            and len({item["trace_sha256"] for item in traces}) == 2
            and all(
                item["payload"]["input_bundle_sha256"] == bundle["bundle_sha256"]
                and item["payload"]["host"]["source_sha256"]
                in {registration["source_sha256"] for registration in registrations}
                and item["payload"]["approval_result"]["authority_granted"] is False
                and item["payload"]["approval_result"]["operational_action_created"] is False
                and item["payload"]["operational_mutations"] == []
                for item in traces
            )
            and {
                "HOST_QUALITY_SUPERIORITY",
                "MODEL_COMPARISON",
                "OPERATIONAL_APPROVAL",
                "ACTION_CREATION",
                "PRODUCTION_READINESS",
            }
            <= set(report["claim_boundary"]["not_supported"])
        )
    except Exception as error:
        failure = f"The Agent Runtime executable boundary drifted: {error}."

    return [
        _result(
            "agent_runtime_host_registry_boundary",
            "agent_runtime",
            registry_ok,
            "The local registry binds two distinct import-free implementation paths and source digests without expanding authority or identity claims.",
            failure,
            shared_evidence,
        ),
        _result(
            "agent_runtime_parity_boundary",
            "agent_runtime",
            runtime_ok,
            "A reference adapter and a separately registered local implementation remain paired with no operational authority.",
            failure,
            shared_evidence,
        ),
        _result(
            "agent_runtime_input_bundle_boundary",
            "agent_runtime",
            bundle_ok,
            "The canonical content-addressed bundle is shared across hosts and excludes post-cutoff inputs and operational authority.",
            failure,
            shared_evidence,
        ),
        _result(
            "agent_runtime_host_trace_boundary",
            "agent_runtime",
            trace_ok,
            "Both host traces replay against the shared bundle and grant no identity, quality, approval, action, or production claim.",
            failure,
            shared_evidence,
        ),
    ]


def check_action_outcome_evidence_chain_boundary(root: Path) -> list[CheckResult]:
    api_path = "lambda/glap_operations_api.py"
    template_path = "infrastructure/operations-api-staging.yaml"
    client_path = "decision-brief-demo/app/operations-api.ts"
    page_path = "decision-brief-demo/app/page.tsx"
    workflow_path = ".github/workflows/deploy-operations-api-staging.yml"
    frontend_deploy_path = "ops/deploy_internal_operations_frontend.ps1"
    staging_verifier_path = "ops/verify_operations_staging.ps1"
    role_verifier_path = "ops/verify_operations_roles_staging.ps1"
    status_path = "CURRENT_DEVELOPMENT_STATUS.md"
    api = (root / api_path).read_text(encoding="utf-8")
    template = (root / template_path).read_text(encoding="utf-8")
    client = (root / client_path).read_text(encoding="utf-8")
    page = (root / page_path).read_text(encoding="utf-8")
    workflow = (root / workflow_path).read_text(encoding="utf-8")
    frontend_deploy = (root / frontend_deploy_path).read_text(encoding="utf-8")
    staging_verifier = (root / staging_verifier_path).read_text(encoding="utf-8")
    role_verifier = (root / role_verifier_path).read_text(encoding="utf-8")
    status = (root / status_path).read_text(encoding="utf-8")
    normalized_status = " ".join(status.split())
    api_bounded = all(
        marker in api
        for marker in (
            "def build_action_evidence_query",
            "fact_lifecycle_action_staging_v1",
            "fact_lifecycle_action_audit_staging_v1",
            "fact_lifecycle_outcome_staging_v1",
            "status = 'PENDING' AND observed_date IS NULL AND effect_pct IS NULL",
            '"proposal_immutable": True',
            '"audit_append_only": True',
            '"outcome_is_simulated": True',
            '"real_logistics_performance": False',
        )
    ) and api.count("time_basis = 'ACTUAL_CALENDAR'") >= 3
    route_bounded = all(
        marker in template
        for marker in (
            "RouteKey: GET /v1/actions/{action_id}/evidence",
            "AuthorizationType: JWT",
            "LIFECYCLE_ACTION_TABLE: fact_lifecycle_action_staging_v1",
            "LIFECYCLE_ACTION_AUDIT_TABLE: fact_lifecycle_action_audit_staging_v1",
        )
    )
    client_bounded = (
        "export async function loadActionEvidence" in client
        and "/evidence`" in client
        and "Action–Outcome evidence chain" in page
        and "never real logistics performance" in page
    )
    release_bounded = all(
        table in workflow
        for table in (
            "fact_lifecycle_action_staging_v1",
            "fact_lifecycle_action_audit_staging_v1",
            "fact_lifecycle_outcome_staging_v1",
        )
    ) and all(
        marker in source
        for source, marker in (
            (frontend_deploy, "Internal frontend build is missing the Action evidence contract"),
            (staging_verifier, "[switch]$RequireActionEvidence"),
            (role_verifier, "[switch]$RequireActionEvidence"),
        )
    )
    maturity_bounded = all(
        marker in normalized_status
        for marker in (
            "Action–Outcome evidence chain",
            "run `32621697316` deployed commit `9d50b7d` successfully",
            "`-RequireActionEvidence`",
            "All four temporary role-check users were removed",
            "No real Action was mutated",
            "No new write, role, table, or production path was added.",
        )
    )
    return [
        _result(
            "action_outcome_evidence_chain_boundary",
            "architecture",
            api_bounded and route_bounded and client_bounded and release_bounded
            and maturity_bounded,
            "The Action–Outcome evidence chain remains authenticated, cutoff-bounded, synthetic, read-only, and runtime-verified in private staging.",
            "The Action–Outcome evidence chain lost a temporal, governance, JWT, UI-disclosure, or deployment-maturity boundary.",
            (
                api_path, template_path, client_path, page_path, workflow_path,
                frontend_deploy_path, staging_verifier_path, role_verifier_path,
                status_path,
            ),
        )
    ]


def check_outcome_learning_evidence_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "template": "infrastructure/operations-api-staging.yaml",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "workflow": ".github/workflows/deploy-operations-api-staging.yml",
        "discovery": "ops/configure_operations_api_discovery.ps1",
        "data_access": "ops/configure_operations_api_data_access.ps1",
        "frontend_deploy": "ops/deploy_internal_operations_frontend.ps1",
        "staging_verifier": "ops/verify_operations_staging.ps1",
        "role_verifier": "ops/verify_operations_roles_staging.ps1",
        "status": "CURRENT_DEVELOPMENT_STATUS.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    api_bounded = all(
        marker in text["api"]
        for marker in (
            "def build_learning_evidence_query",
            "fact_policy_proposal_staging_v1",
            "observed_date <= DATE",
            'path == "/v1/learning"',
            '"review_required": True',
            '"eligibility_scope": "SYNTHETIC_POLICY_REVIEW_ONLY"',
            '"automatic_activation": False',
            '"deterministic_rules_replaced": False',
            '"outcomes_are_simulated": True',
            '"real_logistics_performance": False',
            '"model_readiness": False',
            '"production_readiness": False',
        )
    )
    route_bounded = all(
        marker in text["template"]
        for marker in (
            "RouteKey: GET /v1/learning",
            "AuthorizationType: JWT",
            "POLICY_PROPOSAL_TABLE: fact_policy_proposal_staging_v1",
            "MINIMUM_POLICY_OUTCOMES: '20'",
        )
    )
    client_bounded = all(
        marker in (text["client"] + text["page"])
        for marker in (
            "export async function loadLearningEvidence",
            "Learning Review",
            "Policy activation always requires a separate named-human approval",
            "synthetic policy-review evidence only",
            "deterministic safety rules remain in force",
        )
    )
    release_bounded = all(
        marker in text[source]
        for source, marker in (
            ("workflow", "fact_policy_proposal_staging_v1"),
            ("discovery", "fact_policy_proposal_staging_v1"),
            ("data_access", "fact_policy_proposal_staging_v1"),
            ("frontend_deploy", "Internal frontend build is missing the Learning evidence contract"),
            ("staging_verifier", "[switch]$RequireLearningEvidence"),
            ("role_verifier", "[switch]$RequireLearningEvidence"),
        )
    ) and all(
        forbidden not in text["template"]
        for forbidden in ("AWS::Scheduler::Schedule", "AWS::Lambda::Alias")
    )
    maturity_bounded = all(
        marker in " ".join(text["status"].split())
        for marker in (
            "Outcome–Learning evidence gate",
            "run `32621697316` deployed commit `9d50b7d` successfully",
            "`-RequireLearningEvidence`",
            "`INSUFFICIENT_ELIGIBLE_OUTCOMES` at `1/20` with no proposal present",
            "no proposal approval or activation endpoint",
        )
    )
    return [
        _result(
            "outcome_learning_evidence_boundary",
            "architecture",
            api_bounded and route_bounded and client_bounded and release_bounded
            and maturity_bounded,
            "The Outcome-to-Learning gate remains cutoff-bounded, synthetic, read-only, review-required, and runtime-verified in private staging.",
            "The Outcome-to-Learning gate lost an eligibility, JWT, no-activation, deterministic-rule, or maturity boundary.",
            tuple(paths.values()),
        )
    ]


def check_provider_label_readiness_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "contract": "docs/project_drift_contract.json",
        "api": "lambda/glap_operations_api.py",
        "template": "infrastructure/operations-api-staging.yaml",
        "workflow": ".github/workflows/deploy-operations-api-staging.yml",
        "discovery": "ops/configure_operations_api_discovery.ps1",
        "data_access": "ops/configure_operations_api_data_access.ps1",
        "frontend_deploy": "ops/deploy_internal_operations_frontend.ps1",
        "staging_verifier": "ops/verify_operations_staging.ps1",
        "role_verifier": "ops/verify_operations_roles_staging.ps1",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "feature_contract": "docs/multimodal_forecast_feature_contract.md",
        "temporal": "docs/temporal_truthfulness.md",
        "operations_doc": "docs/operations_api_v1.md",
        "status": "CURRENT_DEVELOPMENT_STATUS.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    contract = json.loads(text["contract"])
    capability = next(
        (
            item for item in contract.get("capabilities", [])
            if item.get("id") == "provider_label_readiness_dashboard"
        ),
        {},
    )
    boundary = str(capability.get("boundary", "")).lower()
    api_bounded = all(
        marker in text["api"]
        for marker in (
            "def build_label_readiness_query",
            "def build_label_readiness_contract",
            "vw_multimodal_outcome_label_v1",
            "GROUP BY transport_mode, provider_code",
            "label_observed_through_date <= DATE",
            'path == "/v1/label-readiness"',
            '"pending_labels_excluded": True',
            '"future_simulations_included": False',
            '"entity_identifiers_included": False',
            '"model_training_authorized": False',
            '"model_promotion_authorized": False',
            '"production_readiness": False',
        )
    ) and "shipment_id" not in text["api"].split(
        "def build_label_readiness_query", 1
    )[1].split("def _label_binary_target", 1)[0]
    route_bounded = all(
        marker in text["template"]
        for marker in (
            "RouteKey: GET /v1/label-readiness",
            "AuthorizationType: JWT",
            "LABEL_READINESS_SOURCE_VIEW: vw_multimodal_outcome_label_v1",
            "MINIMUM_LABEL_OBSERVED: '200'",
            "MINIMUM_LABEL_CLASS: '20'",
            "MINIMUM_LABEL_COST_DISTINCT: '10'",
        )
    ) and all(
        forbidden not in text["template"]
        for forbidden in ("AWS::Scheduler::Schedule", "AWS::Lambda::Alias")
    )
    release_bounded = all(
        marker in text[source]
        for source, marker in (
            ("workflow", "vw_multimodal_outcome_label_v1"),
            ("discovery", "${LabelReadinessSourceView}"),
            ("data_access", "Operational label-readiness source view: SELECT, DESCRIBE"),
            ("frontend_deploy", "Internal frontend build is missing the provider label-readiness contract"),
            ("staging_verifier", "[switch]$RequireLabelReadiness"),
            ("role_verifier", "[switch]$RequireLabelReadiness"),
            ("role_verifier", "label readiness governance boundary valid"),
            ("role_verifier", "label readiness entity and infrastructure identifiers redacted"),
        )
    )
    client_bounded = all(
        marker in (text["client"] + text["page"])
        for marker in (
            "export async function loadLabelReadiness",
            "Provider Label Readiness",
            "Pending labels and future simulations never count",
            "model training, model promotion, deployment, recurring prediction, and production readiness remain unauthorized",
        )
    )
    documentation_bounded = all(
        marker in " ".join(text[source].split())
        for source, marker in (
            ("feature_contract", "GET /v1/label-readiness"),
            ("temporal", "provider label-readiness surface"),
            ("operations_doc", "200 observed labels per provider"),
            ("status", "Provider label-readiness dashboard"),
            ("status", "implemented and locally verified"),
            ("status", "No current label count or readiness status is claimed from AWS"),
        )
    )
    capability_bounded = (
        capability.get("state") == "IMPLEMENTED_VERIFIED"
        and "not deployed" in boundary
        and "server-derived sydney cutoff" in boundary
        and "pending labels are coverage-only" in boundary
        and "future simulations" in boundary
        and "entity identifiers" in boundary
        and "training" in boundary
        and "promotion" in boundary
        and "production readiness" in boundary
        and "operational mutation authority remain false" in boundary
    )
    return [
        _result(
            "provider_label_readiness_boundary",
            "forecasting",
            api_bounded and route_bounded and release_bounded and client_bounded
            and documentation_bounded and capability_bounded,
            "Provider label readiness remains aggregate-only, actual-calendar bounded, locally verified, undeployed, and unable to grant training, promotion, or production authority.",
            "Provider label readiness lost its cutoff, aggregation, identifier-redaction, release-maturity, or no-authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_adapter_conformance_boundary(root: Path) -> list[CheckResult]:
    """Execute the offline package fixture and verify its fail-closed claims."""

    runner_path = "ops/verify_agent_runtime_adapter_package.py"
    fixture_root = "tests/fixtures/evaluation/adapter_conformance_v1"
    evidence = (
        runner_path,
        "ops/run_governed_agent_runtime.py",
        "tests/test_agent_runtime_adapter_conformance.py",
        f"{fixture_root}/package.json",
        f"{fixture_root}/adapter.py",
        f"{fixture_root}/input_bundle.json",
        f"{fixture_root}/host_trace.json",
        "docs/agent_runtime_adapter_package_v1.schema.json",
        "docs/agent_runtime_input_bundle_v1.schema.json",
        "docs/agent_runtime_host_trace_v1.schema.json",
        "docs/evaluation_architecture.md",
    )
    passed = False
    failure = "The offline adapter conformance package or its evidence is invalid."
    try:
        if not all((root / path).is_file() for path in evidence):
            raise FileNotFoundError("offline adapter conformance evidence is incomplete")
        module = _load_repository_module(root, runner_path)
        report = module.verify_package(root / fixture_root)
        expected_boundary = {
            "mode": "LOCAL_ISOLATED_REPLAY",
            "network_access_allowed": False,
            "operational_writes_allowed": False,
            "dynamic_dependency_install_allowed": False,
            "production_effect": False,
        }
        unsupported = set(report["claim_boundary"]["not_supported"])
        passed = (
            report["status"] == "PASS"
            and all(value == "PASS" for value in report["checks"].values())
            and report["submitted_trace_sha256"] == report["replay_trace_sha256"]
            and report["execution_boundary"] == expected_boundary
            and report["operational_mutations"] == []
            and report["evaluation_layers"]["system_correctness"]["status"]
            == "PASS"
            and all(
                report["evaluation_layers"][name]["status"] == "NOT_EVALUATED"
                for name in (
                    "capability_attribution",
                    "decision_quality",
                    "business_outcome_effect",
                )
            )
            and {
                "HOST_AUTHENTICATION",
                "MODEL_IDENTITY",
                "DECISION_QUALITY",
                "BUSINESS_OUTCOME_EFFECT",
                "OPERATIONAL_APPROVAL",
                "ACTION_CREATION",
                "PRODUCTION_READINESS",
            }
            <= unsupported
        )
    except Exception as error:
        failure = f"The offline adapter conformance boundary drifted: {error}."
    return [
        _result(
            "agent_runtime_adapter_conformance_boundary",
            "agent_runtime",
            passed,
            "A separately supplied four-file adapter package passes inspected, deterministic, bundle-bound offline replay without operational authority.",
            failure,
            evidence,
        )
    ]


def check_decision_quality_adjudication_boundary(root: Path) -> list[CheckResult]:
    evidence = (
        "docs/decision_quality_adjudication_v1.schema.json",
        "docs/decision_quality_adjudication_cyclone_gabrielle_t1_v1.json",
        "docs/decision_quality_five_review_reconciliation_v1.schema.json",
        "docs/decision_quality_five_review_reconciliation_v1.json",
        "docs/decision_quality_five_review_corpus_summary_v1.schema.json",
        "docs/decision_quality_five_review_corpus_summary_v1.json",
        "docs/decision_quality_human_disposition_v1.schema.json",
        "docs/decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json",
        "docs/decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json",
        "docs/decision_quality_rubric_v1.json",
        "ops/validate_decision_quality_adjudication.py",
        "tests/test_decision_quality_adjudication.py",
        "blinded-review-survey/data/review-bundle.json",
        "docs/decision_quality_evaluation.md",
    )
    passed = False
    failure = "The Decision Quality adjudication record is missing, resolved without authority, or has expanded its claim boundary."
    try:
        if not all((root / path).is_file() for path in evidence):
            raise FileNotFoundError("Decision Quality adjudication evidence is incomplete")
        validator = _load_repository_module(
            root, "ops/validate_decision_quality_adjudication.py"
        )
        record = validator.load_json(
            root / "docs/decision_quality_adjudication_cyclone_gabrielle_t1_v1.json"
        )
        bundle = validator.load_json(
            root / "blinded-review-survey/data/review-bundle.json"
        )
        reconciliation = validator.load_json(
            root / "docs/decision_quality_five_review_reconciliation_v1.json"
        )
        corpus_summary = validator.load_json(
            root / "docs/decision_quality_five_review_corpus_summary_v1.json"
        )
        t1_disposition = validator.load_json(
            root / "docs/decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json"
        )
        t2_disposition = validator.load_json(
            root / "docs/decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json"
        )
        rubric = validator.load_json(root / "docs/decision_quality_rubric_v1.json")
        passed = (
            validator.validate_record(record, bundle, today=sydney_business_date())
            == []
            and validator.validate_reconciliation(
                reconciliation,
                record,
                bundle,
                rubric,
                today=sydney_business_date(),
            )
            == []
            and validator.validate_corpus_summary(
                corpus_summary,
                bundle,
                rubric,
                today=sydney_business_date(),
            )
            == []
            and validator.validate_human_disposition(
                t1_disposition,
                corpus_summary,
                bundle,
                predecessor=record,
                today=sydney_business_date(),
            )
            == []
            and validator.validate_human_disposition(
                t2_disposition,
                corpus_summary,
                bundle,
                today=sydney_business_date(),
            )
            == []
            and record["adjudication"]["status"] == "PENDING_HUMAN_ADJUDICATION"
            and record["adjudication"]["resolution"] is None
            and record["source_evidence"]["review_count"] == 4
            and record["source_evidence"]["raw_review_result"]
            == "REVIEWERS_DO_NOT_AGREE"
            and record["governance"]["adjudication_is_not_a_fifth_review"] is True
            and record["authority"]["a303_reactivation_allowed"] is False
            and record["operational_mutations"] == []
            and reconciliation["aggregate_delta"]["review_count_after"] == 5
            and reconciliation["updated_result"]["preference_consensus_pct"]
            == 60.0
            and reconciliation["updated_result"]["result"]
            == "REVIEWERS_DO_NOT_AGREE"
            and reconciliation["updated_result"]["favored_variant_id"] is None
            and reconciliation["governance"]["full_corpus_reaggregation_pending"]
            is True
            and reconciliation["operational_mutations"] == []
            and corpus_summary["source_evidence"]["reviewer_count"] == 5
            and corpus_summary["source_evidence"]["review_record_count"] == 150
            and corpus_summary["corpus_result"][
                "review_evidence_favors_variant_count"
            ]
            == 14
            and corpus_summary["corpus_result"]["reviewers_do_not_agree_count"]
            == 16
            and corpus_summary["governance"]["full_corpus_reaggregation_complete"]
            is True
            and corpus_summary["authority"]["public_publication_allowed"] is False
            and corpus_summary["operational_mutations"] == []
            and t1_disposition["disposition"]["resolution"]
            == "RETAIN_INCONCLUSIVE"
            and t2_disposition["disposition"]["resolution"]
            == "RETAIN_INCONCLUSIVE"
            and t1_disposition["package_evidence"]["raw_review_result"]
            == "REVIEWERS_DO_NOT_AGREE"
            and t2_disposition["package_evidence"]["raw_review_result"]
            == "REVIEWERS_DO_NOT_AGREE"
            and t1_disposition["operational_mutations"] == []
            and t2_disposition["operational_mutations"] == []
        )
    except Exception as error:
        failure = f"The Decision Quality adjudication boundary drifted: {error}."
    return [
        _result(
            "decision_quality_adjudication_boundary",
            "evaluation",
            passed,
            "The identity-free five-review aggregate remains 14/16, and separate named-human records retain inconclusive dispositions for both Cyclone Gabrielle T1 and T2 without overriding the no-winner results.",
            failure,
            evidence,
        )
    ]


def check_public_evaluation_snapshot_boundary(root: Path) -> list[CheckResult]:
    evidence = (
        "docs/public_evaluation_snapshot_v1.schema.json",
        "docs/decision_quality_five_review_corpus_summary_v1.json",
        "docs/decision_quality_rubric_v1.json",
        "blinded-review-survey/data/review-bundle.json",
        "ops/validate_decision_quality_adjudication.py",
        "ops/export_public_evaluation_snapshot.py",
        "ops/canary_public_evaluation.py",
        "offline/data/evaluation-snapshot.json",
        "offline/glap-demo.html",
        ".github/workflows/pages.yml",
        "tests/test_public_evaluation_snapshot.py",
        "tests/test_public_evaluation_canary.py",
        "tests/test_offline_demo.py",
        "docs/evaluation_architecture.md",
        "docs/ops_snapshot.md",
        "docs/temporal_truthfulness.md",
    )
    passed = False
    failure = (
        "The versioned public Evaluation snapshot is missing, no longer an exact "
        "aggregate-only projection, or the page no longer fails closed."
    )
    try:
        if not all((root / path).is_file() for path in evidence):
            raise FileNotFoundError("public Evaluation snapshot evidence is incomplete")
        exporter = _load_repository_module(
            root, "ops/export_public_evaluation_snapshot.py"
        )
        source = exporter.load_json(
            root / "docs/decision_quality_five_review_corpus_summary_v1.json"
        )
        bundle = exporter.load_json(
            root / "blinded-review-survey/data/review-bundle.json"
        )
        rubric = exporter.load_json(root / "docs/decision_quality_rubric_v1.json")
        tracked = exporter.load_json(root / "offline/data/evaluation-snapshot.json")
        generated = exporter.build_public_snapshot(source, bundle, rubric)
        html = (root / "offline/glap-demo.html").read_text(encoding="utf-8")
        workflow = (root / ".github/workflows/pages.yml").read_text(
            encoding="utf-8"
        )
        required_html = (
            'const EVALUATION_SCHEMA_VERSION="public-evaluation-snapshot.v1"',
            'fetch("data/evaluation-snapshot.json",{cache:"no-store"})',
            "validateEvaluationSnapshot",
            "renderEvaluationUnavailable",
            "Evaluation privacy boundary fails closed",
            "Evaluation authority boundary fails closed",
            'id="evaluationState">UNAVAILABLE',
        )
        forbidden_html = (
            "Public aggregate only · 24 August 2026",
            "10</strong><small>cases · 30 frozen cutoffs",
            "14 favour A303-on · 16 no winner",
            "review_id",
            "package_digest",
            "bundle_digest",
            "source_collections",
            "submitted_at",
        )
        required_workflow = (
            '"offline/data/evaluation-snapshot.json"',
            '"ops/export_public_evaluation_snapshot.py"',
            '"ops/canary_public_evaluation.py"',
            '"ops/validate_decision_quality_adjudication.py"',
            '"docs/public_evaluation_snapshot_v1.schema.json"',
            '"docs/decision_quality_five_review_corpus_summary_v1.schema.json"',
            '"docs/decision_quality_five_review_corpus_summary_v1.json"',
            '"docs/decision_quality_rubric_v1.json"',
            '"blinded-review-survey/data/review-bundle.json"',
            "python ops/export_public_evaluation_snapshot.py",
            "python ops/canary_public_evaluation.py",
        )
        canary = (root / "ops/canary_public_evaluation.py").read_text(
            encoding="utf-8"
        )
        required_canary = (
            '"mode": "READ_ONLY"',
            "live_snapshot_matches_governed_projection",
            "aggregate_counts_reconcile",
            "authority_all_false",
            "page_loader_present",
            "fail_closed_state_present",
        )
        passed = (
            generated == tracked
            and exporter.validate_public_snapshot(
                tracked, today=sydney_business_date()
            )
            == []
            and exporter._protected_keys(tracked) == set()
            and all(marker in html for marker in required_html)
            and not any(marker in html for marker in forbidden_html)
            and all(marker in workflow for marker in required_workflow)
            and all(marker in canary for marker in required_canary)
            and workflow.index("python ops/export_public_evaluation_snapshot.py")
            < workflow.index("- name: Prepare static site")
            and workflow.index("uses: actions/deploy-pages@v4")
            < workflow.index("python ops/canary_public_evaluation.py")
        )
    except Exception as error:
        failure = f"The public Evaluation snapshot boundary drifted: {error}."
    return [
        _result(
            "public_evaluation_snapshot_boundary",
            "evaluation",
            passed,
            "The page reads a versioned, source-bound aggregate-only Evaluation snapshot, withholds invalid results, validates the exact projection before artifact preparation, and runs a read-only live canary after deployment.",
            failure,
            evidence,
        )
    ]


def run_audit(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    checks: list[CheckResult] = []
    checks.extend(check_contract(root, contract))
    checks.extend(check_manual_staging_boundary(root))
    checks.extend(check_stateful_recovery_evidence_boundary(root, contract))
    checks.extend(check_public_private_boundary(root))
    checks.extend(check_governed_action_outcome_boundary(root))
    checks.extend(check_action_outcome_evidence_chain_boundary(root))
    checks.extend(check_outcome_learning_evidence_boundary(root))
    checks.extend(check_provider_label_readiness_boundary(root))
    checks.extend(check_audit_automation(root))
    checks.extend(check_documentation_operating_model(root))
    checks.extend(check_action_contract(root, contract))
    checks.extend(check_action_assignment_rollout(root))
    checks.extend(check_action_complete_outcome_canary(root))
    checks.extend(check_action_mutation_release(root))
    checks.extend(check_readiness_contract(root))
    checks.extend(check_temporal_boundary(root))
    checks.extend(check_a303_outcome_robustness_boundary(root))
    checks.extend(check_a303_outcome_calibration_boundary(root))
    checks.extend(check_a303_v2_guardrail_boundary(root))
    checks.extend(check_a303_v1_retirement_boundary(root))
    checks.extend(check_capability_neutral_evaluation_boundary(root))
    checks.extend(check_decision_quality_adjudication_boundary(root))
    checks.extend(check_public_evaluation_snapshot_boundary(root))
    checks.extend(check_agent_runtime_boundary(root))
    checks.extend(check_adapter_conformance_boundary(root))
    overall = "DRIFT" if any(check.status == "DRIFT" for check in checks) else "PASS"
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sydney_date = sydney_business_date().isoformat()
    return {
        "schema_version": "project-drift-report.v1",
        "generated_at": generated_at,
        "sydney_as_of_date": sydney_date,
        "overall_status": overall,
        "summary": {
            "checks": len(checks),
            "passed": sum(check.status == "PASS" for check in checks),
            "drift": sum(check.status == "DRIFT" for check in checks),
        },
        "checks": [asdict(check) for check in checks],
        "capabilities": contract["capabilities"],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GLAP project drift audit",
        "",
        f"- Overall: **{report['overall_status']}**",
        f"- Sydney as-of date: `{report['sydney_as_of_date']}`",
        f"- Checks: {report['summary']['passed']} passed / {report['summary']['drift']} drift",
        "",
        "## Checks",
        "",
        "| Category | Check | Status | Result |",
        "| --- | --- | --- | --- |",
    ]
    for check in report["checks"]:
        summary = str(check["summary"]).replace("|", "\\|")
        lines.append(
            f"| {check['category']} | `{check['check_id']}` | {check['status']} | {summary} |"
        )
    lines.extend(
        [
            "",
            "## Capability baseline",
            "",
            "| Capability | State | Boundary |",
            "| --- | --- | --- |",
        ]
    )
    for capability in report["capabilities"]:
        lines.append(
            f"| `{capability['id']}` | {capability['state']} | {capability['boundary']} |"
        )
    lines.extend(
        [
            "",
            "This report is repository evidence only. It does not deploy, mutate AWS,",
            "activate a schedule, promote a model, or establish real logistics performance.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_audit(args.repo.resolve())
    rendered = (
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
    return 1 if report["overall_status"] == "DRIFT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
