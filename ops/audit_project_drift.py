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
            "Staging source now counts one latest cutoff version per `outcome_id`",
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
        == "OBSERVED_OUTCOME_SOURCE_FIX_DEPLOYED_RUNTIME_RECHECK_PENDING"
    )
    return [
        _result(
            "action_assignment_rollout_boundary",
            "governance",
            bounded,
            "Action assignment and named-human COMPLETE remain reconciled; the downstream Learning source fix is staging-deployed with runtime recheck pending and no standing authority.",
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
        ".github/workflows/refactor-stateful-lifecycle-generator-staging.yml",
        "ops/deploy_stateful_lifecycle_generator_stack.ps1",
        "lambda/glap_governed_closed_loop.py",
        "lambda/glap_lifecycle_athena_adapter.py",
        "tests/test_action_complete_outcome_canary.py",
        "tests/test_governed_closed_loop.py",
        "tests/test_lifecycle_athena_adapter.py",
        "docs/deployment_workflow.md",
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
            "The runtime canary remains failed closed below threshold; the latest-logical-Outcome source fix is staging-deployed with digest and runtime rechecks pending and grants no standing authority.",
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
    evidence_path = "docs/operations_production_readiness_evidence_v1.json"
    schema_path = "docs/operations_production_readiness_evidence_v1.schema.json"
    evaluator_path = "ops/evaluate_operations_production_readiness.py"
    read_load_plan_path = "docs/operations_authenticated_read_load_plan_v1.json"
    read_load_plan_schema_path = "docs/operations_authenticated_read_load_plan_v1.schema.json"
    read_load_baseline_schema_path = "docs/operations_authenticated_read_load_baseline_v1.schema.json"
    read_load_validator_path = "ops/validate_operations_authenticated_read_load_plan.py"
    read_load_simulator_path = "ops/simulate_operations_authenticated_read_load.py"
    read_load_runner_path = "ops/run_operations_authenticated_read_load_staging.ps1"
    contract = json.loads((root / contract_path).read_text(encoding="utf-8"))
    evidence = json.loads((root / evidence_path).read_text(encoding="utf-8"))
    evaluator = _load_repository_module(root, evaluator_path)
    read_load_validator = _load_repository_module(root, read_load_validator_path)
    read_load_simulator = _load_repository_module(root, read_load_simulator_path)
    read_load_plan = json.loads((root / read_load_plan_path).read_text(encoding="utf-8"))
    authority = contract.get("authority", {})
    forbidden_authority = (
        "recurring_schedule_enabled",
        "production_alias_change_authorized",
        "production_table_write_authorized",
        "policy_activation_authorized",
        "model_promotion_authorized",
    )
    contract_bounded = (
        contract.get("status") == "DESIGNED_NOT_DEPLOYED"
        and authority.get("named_human_owner_required") is True
        and all(authority.get(field) is False for field in forbidden_authority)
        and contract.get("business_timezone") == "Australia/Sydney"
        and contract.get("evidence_boundary") == "SYNTHETIC_ENGINEERING_ONLY"
    )
    evidence_errors = evaluator.validate_evidence(
        evidence,
        today=sydney_business_date(),
        root=root,
    )
    summary = evidence.get("summary", {})
    evidence_bounded = (
        evidence_errors == []
        and summary.get("required_gate_count") == 10
        and summary.get("eligible_gate_count") == 4
        and summary.get("blocked_gate_count") == 6
        and summary.get("production_readiness") is False
        and evidence.get("claim_boundary", {}).get("status")
        == "NOT_READY_INCOMPLETE_EVIDENCE"
    )
    read_load_errors = read_load_validator.validate_plan(
        read_load_plan,
        today=sydney_business_date(),
        root=root,
    )
    sustained_gate = next(
        (
            gate
            for gate in evidence.get("required_gates", [])
            if gate.get("id") == "sustained_read_load"
        ),
        {},
    )
    simulator_source = (root / read_load_simulator_path).read_text(encoding="utf-8")
    runner_source = (root / read_load_runner_path).read_text(encoding="utf-8")
    simulator_bounded = False
    if read_load_errors == []:
        try:
            healthy_simulation = read_load_simulator.simulate_scenario(
                read_load_plan, "healthy"
            )
            reconciliation_simulation = read_load_simulator.simulate_scenario(
                read_load_plan, "reconciliation_failure"
            )
        except (AssertionError, ValueError):
            pass
        else:
            simulator_bounded = (
                read_load_simulator.validate_simulation_report(
                    healthy_simulation, read_load_plan
                )
                == []
                and read_load_simulator.validate_simulation_report(
                    reconciliation_simulation, read_load_plan
                )
                == []
                and healthy_simulation.get("schedule", {}).get("scheduled_requests")
                == 1740
                and healthy_simulation.get("result", {}).get("run_status")
                == "COMPLETED"
                and healthy_simulation.get("execution", {}).get("network_access")
                is False
                and healthy_simulation.get("execution", {}).get(
                    "staging_requests_executed"
                )
                is False
                and healthy_simulation.get("claim_boundary", {}).get(
                    "staging_runtime_evidence"
                )
                is False
                and reconciliation_simulation.get("result", {}).get("run_status")
                == "FAILED_CLOSED"
                and reconciliation_simulation.get("result", {}).get(
                    "candidate_baseline_valid"
                )
                is False
                and all(
                    marker not in simulator_source
                    for marker in (
                        "import boto3",
                        "import requests",
                        "import subprocess",
                        "import socket",
                        "import urllib",
                        "import time",
                        "sleep(",
                    )
                )
            )
    runner_write_hosts = "\n".join(
        line for line in runner_source.splitlines() if "Write-Host" in line
    )
    runner_bounded = (
        "[switch]$Apply" in runner_source
        and "[switch]$AuthorizedSustainedReadLoad" in runner_source
        and "if (-not $Apply)" in runner_source
        and "Apply requires -AuthorizedSustainedReadLoad from a named human"
        in runner_source
        and runner_source.index("if (-not $Apply)")
        < runner_source.index("$awsScope =")
        and "--message-action SUPPRESS" in runner_source
        and "--group-name viewer" in runner_source
        and "-Method GET" in runner_source
        and "-Method POST" not in runner_source
        and "admin-delete-user" in runner_source
        and "cognito-idp list-users" in runner_source
        and "Test-UserAbsent" in runner_source
        and "admin-get-user" not in runner_source
        and "$accessToken = $null" in runner_source
        and "--baseline $baselinePath" in runner_source
        and "[System.IO.File]::WriteAllText" in runner_source
        and "[System.Text.UTF8Encoding]::new($false)" in runner_source
        and "-Encoding utf8NoBOM" not in runner_source
        and "Remove-Item -LiteralPath $baselinePath" in runner_source
        and "Persisted result artifact: False" in runner_source
        and "Redacted per-route latency diagnostic" in runner_source
        and "foreach ($safeRouteResult in $routeResults)" in runner_source
        and "$safeRouteResult.route_id" in runner_source
        and "$safeRouteResult.requests_completed" in runner_source
        and "$safeRouteResult.latency_p50_ms" in runner_source
        and "$safeRouteResult.latency_p95_ms" in runner_source
        and "$safeRouteResult.latency_p99_ms" in runner_source
        and "$plan.abort_gates.max_p95_latency_ms" in runner_source
        and "exceeds_p95_gate={5}" in runner_source
        and all(
            marker not in runner_write_hosts
            for marker in (
                "$endpoint",
                "$route.path",
                "$username",
                "$accessToken",
                "$login",
                "$password",
            )
        )
        and "production_accessed = $false" in runner_source
        and "recurring_schedule_created = $false" in runner_source
    )
    sustained_finding = str(sustained_gate.get("finding", ""))
    read_load_bounded = (
        read_load_errors == []
        and simulator_bounded
        and runner_bounded
        and sustained_gate.get("state") == "PARTIAL_EVIDENCE"
        and sustained_gate.get("evidence_class") == "STAGING_ENGINEERING"
        and read_load_plan_path in sustained_gate.get("evidence_refs", [])
        and read_load_simulator_path in sustained_gate.get("evidence_refs", [])
        and read_load_runner_path in sustained_gate.get("evidence_refs", [])
        and "20 of 20 responses were successful" in sustained_finding
        and "overall p95 latency was 6023 ms" in sustained_finding
        and "outcomes_pending at 7054 ms" in sustained_finding
        and "risks_open at 6023 ms" in sustained_finding
        and "label_readiness at 4167 ms" in sustained_finding
        and "other four routes remained below the gate" in sustained_finding
        and "temporary viewer was confirmed removed" in sustained_finding
        and "no result artifact was persisted" in sustained_finding
        and "two unchanged mandatory outcomes_pending queries together with exactly two workers"
        in sustained_finding
        and "manual workflow run 33220634162" in sustained_finding
        and "updated the private staging stack" in sustained_finding
        and "performed no live API or latency recheck" in sustained_finding
        and "functional runtime preservation and performance effect remain unverified"
        in sustained_finding
        and read_load_plan.get("execution", {}).get("load_executed") is False
        and read_load_plan.get("authorization", {}).get("staging_load_run_authorized") is False
    )
    return [
        _result(
            "production_readiness_boundary",
            "governance",
            contract_bounded and evidence_bounded and read_load_bounded,
            "Production-readiness controls remain bounded while the offline evidence harness truthfully reports 4/10 eligible gates, the 2026-08-29 diagnostic p95 breaches, and a two-worker outcomes_pending correction delivered to private staging without claiming a live functional recheck, runtime improvement, a completed baseline, or production authority.",
            "The production-readiness contract or evidence harness claims unsupported maturity, loses required gates, or expands protected authority.",
            (
                contract_path,
                evidence_path,
                schema_path,
                evaluator_path,
                read_load_plan_path,
                read_load_plan_schema_path,
                read_load_baseline_schema_path,
                read_load_validator_path,
                read_load_simulator_path,
                read_load_runner_path,
                "tests/test_operations_authenticated_read_load_plan.py",
                "tests/test_operations_authenticated_read_load_simulator.py",
                "tests/test_operations_authenticated_read_load_runner.py",
                "tests/test_operations_production_readiness.py",
                "docs/athena_cost_governance.md",
                "docs/incremental_refresh_contract.md",
            ),
        )
    ]


def check_public_claim_truth(root: Path) -> list[CheckResult]:
    validator_path = "ops/validate_public_claims.py"
    manifest_path = "docs/public_claim_manifest_v1.json"
    validator = _load_repository_module(root, validator_path)
    errors = validator.validate_manifest(validator.load_manifest(root), root)
    status = (root / "CURRENT_DEVELOPMENT_STATUS.md").read_text(encoding="utf-8")
    architecture = (root / "docs/architecture_current.md").read_text(encoding="utf-8")
    plan = (root / "DEVELOPMENT_PLAN.md").read_text(encoding="utf-8")
    bounded = (
        errors == []
        and "IMPLEMENTED_LOCALLY_VERIFIED_NOT_PUBLISHED" in status
        and "HIGH_RISK_DECISION_EXECUTION_OUTCOME_VALUE_CLAIMS_V1" in architecture
        and "No new intelligence layer is added" in plan
        and "benefit_estimate.status = NOT_ESTIMATED" in plan
    )
    return [
        _result(
            "public_claim_truth_boundary",
            "governance",
            bounded,
            "High-risk public claims remain semantically mapped, evidence-classified, disclosed, source-backed where required, and locally verified without publication.",
            "The public Claim Truth manifest, source mapping, disclosure, backing evidence, or maturity boundary drifted.",
            (
                manifest_path,
                validator_path,
                "tests/test_public_claims.py",
                "decision-brief-demo/app/page.tsx",
                "offline/glap-demo.html",
                "README.md",
                "docs/architecture_current.md",
                "docs/ops_snapshot.md",
                "DEVELOPMENT_PLAN.md",
                "CURRENT_DEVELOPMENT_STATUS.md",
            ),
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
    infrastructure_path = "INFRASTRUCTURE.md"
    api = (root / api_path).read_text(encoding="utf-8")
    template = (root / template_path).read_text(encoding="utf-8")
    client = (root / client_path).read_text(encoding="utf-8")
    page = (root / page_path).read_text(encoding="utf-8")
    workflow = (root / workflow_path).read_text(encoding="utf-8")
    frontend_deploy = (root / frontend_deploy_path).read_text(encoding="utf-8")
    staging_verifier = (root / staging_verifier_path).read_text(encoding="utf-8")
    role_verifier = (root / role_verifier_path).read_text(encoding="utf-8")
    status = (root / status_path).read_text(encoding="utf-8")
    infrastructure = (root / infrastructure_path).read_text(encoding="utf-8")
    normalized_status = " ".join(status.split())
    normalized_infrastructure = " ".join(infrastructure.split())
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
    infrastructure_maturity_bounded = all(
        marker in normalized_infrastructure
        for marker in (
            "Action–Outcome evidence chain",
            "deployed and runtime-verified in private staging",
            "run `32621697316` deployed the API",
            "all four temporary role-check users were removed",
            "adds no Action mutation, approval, schedule, alias, or production authority",
        )
    ) and (
        "route and environment binding are merged to `main` but not deployed"
        not in normalized_infrastructure
    )
    return [
        _result(
            "action_outcome_evidence_chain_boundary",
            "architecture",
            api_bounded and route_bounded and client_bounded and release_bounded
            and maturity_bounded and infrastructure_maturity_bounded,
            "The Action–Outcome evidence chain remains authenticated, cutoff-bounded, synthetic, read-only, and runtime-verified in private staging.",
            "The Action–Outcome evidence chain lost a temporal, governance, JWT, UI-disclosure, or deployment-maturity boundary.",
            (
                api_path, template_path, client_path, page_path, workflow_path,
                frontend_deploy_path, staging_verifier_path, role_verifier_path,
                status_path, infrastructure_path,
            ),
        )
    ]


def check_cost_anomaly_decision_brief_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "engine": "lambda/glap_governed_closed_loop.py",
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/cost_anomaly_decision_brief_v1.md",
        "engine_tests": "tests/test_governed_closed_loop.py",
        "adapter_tests": "tests/test_lifecycle_athena_adapter.py",
        "api_tests": "tests/test_operations_api.py",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    engine_bounded = all(
        marker in text["engine"]
        for marker in (
            'COST_SOURCE_CONTRACT_VERSION = "stateful-cost-variance.v1"',
            'COST_METRIC_NAME = "cost_variance_pct"',
            'action_type = "REVIEW_COST"',
            '"selected_alternative": action_type',
            "COST_ANOMALY must exceed a non-negative threshold",
        )
    )
    api_bounded = all(
        marker in text["api"]
        for marker in (
            "def build_cost_anomaly_decision_brief",
            '"decision_type": "COST_ANOMALY"',
            '"source_contract_version": COST_SOURCE_CONTRACT_VERSION',
            '"rate_card_version": None',
            '"rate_card_version_status": "UNAVAILABLE_IN_ALERT_CONTRACT"',
            '"action_type": "REVIEW_COST"',
            '"status": "NOT_ESTIMATED"',
            '"execution_authorized": False',
            "def build_decision_brief_v1",
        )
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'decision_type: "COST_ANOMALY"',
            'source_contract_version: "stateful-cost-variance.v1"',
            'rate_card_version: null',
            'rate_card_version_status: "UNAVAILABLE_IN_ALERT_CONTRACT"',
            'action_type: "REVIEW_COST" | "MONITOR_COST" | "NO_ACTION"',
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "Review the governed response to a cost anomaly.",
            "Rate-card version unavailable in Alert contract",
            "No rate-card identifier is inferred.",
            "This brief itself performs no mutation.",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "Existing Cost Actions remain legacy-null and are never backfilled",
            "rate_card_version_status",
            "UNAVAILABLE_IN_ALERT_CONTRACT",
            "monetary_value` stays `null`",
            "33020601008",
            "33020683956",
            "the Generator ran",
            "zero natural Cost proposals",
            "established no runtime binding evidence",
            "32982946620",
        )
    )
    tests_bounded = (
        "test_cost_action_preserves_decision_brief_binding_and_source_contract"
        in text["engine_tests"]
        and "test_cost_action_binding_flows_through_adapter"
        in text["adapter_tests"]
        and "test_cost_anomaly_decision_brief_is_deterministic_and_not_estimated"
        in text["api_tests"]
        and "test_viewer_risk_response_includes_governed_cost_decision_brief"
        in text["api_tests"]
    )
    return [
        _result(
            "cost_anomaly_decision_brief_boundary",
            "governance",
            engine_bounded
            and api_bounded
            and client_bounded
            and page_bounded
            and contract_bounded
            and tests_bounded,
            "COST_ANOMALY Decision Brief remains deterministic, staging-deployed, source-versioned, rate-card-honest, NOT_ESTIMATED, human-reviewed, and runtime-evidence bounded.",
            "COST_ANOMALY Decision Brief lost its exact input, source-version, unavailable-rate-card, no-value, fail-closed, test, or authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_cost_anomaly_runtime_evidence_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "reconciler": "ops/reconcile_cost_anomaly_runtime_staging.ps1",
        "tests": "tests/test_cost_anomaly_runtime_evidence.py",
        "contract": "docs/cost_anomaly_runtime_evidence_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    reconciler_lower = text["reconciler"].lower()
    normalized_contract = " ".join(text["contract"].split())
    reconciler_bounded = all(
        marker in text["reconciler"]
        for marker in (
            "Get-SydneyBusinessDate",
            "Minimum created date is in the future; no AWS call was made",
            "alert_grain = 'SHIPMENT_COST'",
            "alert_dimension = 'TOTAL_COST'",
            "metric_name = 'cost_variance_pct'",
            "decision_brief_version = 'decision-brief.v1'",
            "action_type = 'REVIEW_COST'",
            "selected_alternative = 'REVIEW_COST'",
            "stateful-cost-variance.v1",
            "At least one naturally generated Cost proposal exists",
            "Pre-release Cost Actions remain legacy-null",
            "Protected identifiers were not printed",
        )
    ) and not any(
        marker in reconciler_lower
        for marker in (
            "insert into",
            "merge into",
            "update ",
            "delete from",
            "invoke-restmethod",
            "invoke-webrequest",
            "write-host $query",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "executed against staging on `2026-08-27`; failed closed",
            "bounded actual-calendar cohort contained zero Cost proposals",
            "established no runtime Decision-binding evidence",
            "does not invoke the Generator",
            "does not create, backfill, edit, approve, reject, or complete an Action",
            "Future simulation cannot satisfy the gate",
            "Athena writes its query-result object",
            "any future rerun requires separate human authorization",
            "does not establish human approval, execution, realised value, causal effect",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "test_reconciler_is_aggregate_only_and_read_only",
            "test_reconciler_enforces_cost_source_and_exact_binding",
            "test_reconciler_is_actual_calendar_and_future_fail_closed",
            "test_reconciler_requires_natural_proposal_and_preserves_human_gate",
            "test_contract_preserves_authority_and_maturity",
        )
    )
    return [
        _result(
            "cost_anomaly_runtime_evidence_boundary",
            "governance",
            reconciler_bounded and contract_bounded and tests_bounded,
            "The Cost runtime reconciler remains aggregate-only, actual-calendar bounded, fail-closed, and unable to manufacture a proposal or human judgment.",
            "The Cost runtime reconciler lost its read-only, temporal, exact-binding, legacy-null, test, or authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_sla_breach_runtime_evidence_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "reconciler": "ops/reconcile_sla_breach_runtime_staging.ps1",
        "tests": "tests/test_sla_breach_runtime_evidence.py",
        "contract": "docs/sla_breach_runtime_evidence_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    reconciler_lower = text["reconciler"].lower()
    normalized_contract = " ".join(text["contract"].split())
    reconciler_bounded = all(
        marker in text["reconciler"]
        for marker in (
            "Get-SydneyBusinessDate",
            "Minimum created date is in the future; no AWS call was made",
            "alert.alert_type = 'SLA_BREACH'",
            "alert.alert_grain = 'SHIPMENT_MILESTONE'",
            "source_match_count = 1 AND eligible_source_match_count = 1",
            "decision_brief_version = 'decision-brief.v1'",
            "action_type = 'EXPEDITE_MILESTONE'",
            "selected_alternative = 'EXPEDITE_MILESTONE'",
            "round(metric_value - threshold_value, 2)",
            "[switch]$BindingDiagnostic",
            "brief_version_valid",
            "action_type_valid",
            "selected_alternative_valid",
            "rationale_shape_valid",
            "rationale_value_valid",
            "Every SLA rationale has the calculated breach value",
            "[switch]$RationaleDiagnostic",
            "rationale_present_valid",
            "rationale_prefix_valid",
            "rationale_suffix_valid",
            "rationale_numeric_token_valid",
            "rationale_numeric_equality_valid",
            "FROM binding_diagnostics",
            "Every SLA rationale numeric token equals the calculated breach",
            "substr(",
            "At least one naturally generated SLA proposal exists",
            "Pre-release SLA Actions remain legacy-null",
            "Protected identifiers were not printed",
        )
    ) and not any(
        marker in reconciler_lower
        for marker in (
            "ends_with(",
            "regexp_like",
            "regexp_extract",
        )
    ) and not any(
        marker in reconciler_lower
        for marker in (
            "insert into",
            "merge into",
            "update ",
            "delete from",
            "invoke-restmethod",
            "invoke-webrequest",
            "write-host $query",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "corrected full reconciliation passed against `2026-08-27` staging",
            "exactly one same-date open `SLA_BREACH` Alert",
            "seven governed milestone/delay-metric pairs",
            "calculated hours above threshold",
            "does not invoke the Generator",
            "does not create, backfill, edit, approve, reject, or complete an Action",
            "Future simulation cannot satisfy the gate",
            "every run is an external AWS operation requiring separate human authorization",
            "no root cause is established",
            "Binding diagnostic result — 2026-08-27",
            "Exact milestone-bound rationale shape and calculated breach value failed",
            "cannot distinguish a persisted rationale-text difference from a verifier-expression difference",
            "optional `-RationaleDiagnostic` mode",
            "`ENDS_WITH_EXPRESSION`",
            "`length` plus `substr` comparison",
            "returned all five rationale-only booleans true",
            "`[A-Z_]+`",
            "digit-bearing `P2P_DEPARTURE` and `P2P_ARRIVAL`",
            "contains no rationale regex",
            "Corrected full reconciliation result",
            "returned all seven aggregate booleans true",
            "synthetic staging runtime evidence",
            "would not establish human approval, execution, realised value, causal effect",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "test_reconciler_is_aggregate_only_and_read_only",
            "test_reconciler_enforces_all_seven_sla_source_pairs",
            "test_reconciler_enforces_exact_binding_and_rationale_inputs",
            "test_optional_binding_diagnostic_splits_five_components",
            "test_optional_rationale_diagnostic_avoids_regex_for_five_subchecks",
            "test_reconciler_is_actual_calendar_and_future_fail_closed",
            "test_reconciler_requires_natural_proposal_and_preserves_human_gate",
            "test_contract_preserves_authority_and_maturity",
        )
    )
    return [
        _result(
            "sla_breach_runtime_evidence_boundary",
            "governance",
            reconciler_bounded and contract_bounded and tests_bounded,
            "The SLA runtime reconciler remains aggregate-only, exact-one-source, actual-calendar bounded, fail-closed, and unable to manufacture a proposal or human judgment.",
            "The SLA runtime reconciler lost its read-only, temporal, exact-source, exact-binding, legacy-null, test, or authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_sla_outcome_provenance_readiness_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "audit": "ops/audit_sla_outcome_provenance_readiness_staging.ps1",
        "tests": "tests/test_sla_outcome_provenance_readiness.py",
        "contract": "docs/sla_outcome_provenance_readiness_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    audit_lower = text["audit"].lower()
    normalized_contract = " ".join(text["contract"].split())
    audit_bounded = all(
        marker in text["audit"]
        for marker in (
            "Get-SydneyBusinessDate",
            "Minimum created date is in the future; no AWS call was made",
            "action.alert_type = 'SLA_BREACH'",
            "action.execution_scenario_id IS NULL",
            "action.decision_brief_version = 'decision-brief.v1'",
            "action.selected_alternative = 'EXPEDITE_MILESTONE'",
            "events.approve_event_count = 1",
            "events.reject_event_count = 0",
            "events.complete_event_count = 1",
            "events.invalid_human_audit_event_count = 0",
            "outcome.row_rank = 1",
            "outcome_without_valid_completion_count",
            "invalid_pending_outcome_count",
            "invalid_closed_outcome_count",
            "invalid_outcome_status_count",
            "valid_provenance_outcome_count",
            "WAITING_HUMAN_REVIEW",
            "WAITING_OBSERVATION_DUE_DATE",
            "READY_FOR_OUTCOME_OBSERVATION",
            "READY_FOR_PROVENANCE_VERIFICATION",
            "BLOCKED_CONTRACT_DRIFT",
            "Protected counts, identifiers, actor values, and Outcome values were not printed",
            "mutations executed: False",
        )
    ) and not any(
        marker in audit_lower
        for marker in (
            "insert into",
            "merge into",
            "update ",
            "delete from",
            "invoke-restmethod",
            "invoke-webrequest",
            "write-host $query",
            "workflow run",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "executed against `2026-08-27` staging; `WAITING_HUMAN_REVIEW`",
            "A natural SLA Decision-bound proposal exists",
            "no named-human completed SLA Action",
            "expected human governance wait state",
            "Expected absence is a readiness state, not invented evidence",
            "Only contract drift causes a non-zero audit exit",
            "Outcome without a valid completion",
            "exactly one named-human `APPROVE`",
            "exactly one named-human `COMPLETE`",
            "latest cutoff-eligible Outcome version",
            "never prints counts",
            "Every runtime audit therefore requires separate explicit human authorization",
            "does not establish human approval, execution, realised value, causality",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "test_audit_is_read_only_aggregate_only_and_identifier_free",
            "test_audit_is_actual_calendar_cutoff_bounded_before_aws",
            "test_audit_requires_exact_decision_pair_and_named_human_chain",
            "test_audit_requires_latest_valid_outcome_provenance",
            "test_audit_exposes_only_bounded_readiness_states",
            "test_audit_cannot_manufacture_human_or_outcome_evidence",
            "test_contract_preserves_readiness_and_authority_boundaries",
        )
    )
    return [
        _result(
            "sla_outcome_provenance_readiness_boundary",
            "governance",
            audit_bounded and contract_bounded and tests_bounded,
            "The SLA Outcome provenance readiness audit remains aggregate-only, cutoff-bounded, named-human-gated, identifier-free, and unable to manufacture workflow evidence.",
            "The SLA Outcome provenance readiness audit lost its temporal, human-governance, provenance, privacy, read-only, test, or authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_sla_decision_review_handoff_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "resolver": "decision-brief-demo/app/decision-review-handoff.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "tests": "decision-brief-demo/tests/rendered-html.test.mjs",
        "contract": "docs/sla_decision_review_handoff_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    resolver_bounded = all(
        marker in text["resolver"]
        for marker in (
            "matchingRisks.length === 0",
            "matchingRisks.length !== 1",
            'risk.status !== "OPEN"',
            "risk.shipment_id !== action.shipment_id",
            "risk.alert_type !== action.alert_type",
            "risk.decision_brief.schema_version !== action.decision_brief_version",
            "risk.decision_brief.recommendation.action_type !== action.selected_alternative",
            "risk.decision_brief.recommendation.rationale !== action.selection_rationale",
            "Human review remains blocked and no Action was changed.",
        )
    ) and not any(
        marker in text["resolver"]
        for marker in (
            "fetch(",
            "loadActionEvidence",
            "submitOperation",
            "sessionStorage",
            "localStorage",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "resolveDecisionReviewHandoff(action, operationsRisks)",
            "reviewAction(item)",
            "Only the Action whose bound Brief you just reviewed is shown.",
            "no mutation or evidence query ran automatically",
            "visibleActions.map",
            "Back to bound Decision Brief",
            "Open selected Action",
            "This returns only to the Action whose immutable binding matches this Brief.",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "opens an Action review only when its immutable Decision Brief binding reconciles",
            'reason_code: "MISSING_RISK"',
            'reason_code: "AMBIGUOUS_RISK"',
            'reason_code: "ACTION_BINDING_INCOMPLETE"',
            'reason_code: "SOURCE_MISMATCH"',
            'reason_code: "DECISION_BINDING_MISMATCH"',
            'reason_code: "RATIONALE_MISMATCH"',
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "deployed to private staging and exact-source canary verified on `2026-08-28`",
            "exactly one current open Risk",
            "does not fall back to a different Risk, Brief, or Action",
            "performs no automatic evidence-chain request",
            "no API route, data write, deployment mechanism, or human decision authority",
            "remains `WAITING_HUMAN_REVIEW`",
            "made no authenticated entity request",
        )
    )
    return [
        _result(
            "sla_decision_review_handoff_boundary",
            "governance",
            resolver_bounded and page_bounded and tests_bounded and contract_bounded,
            "The SLA Decision review handoff remains exact-one, binding-complete, selected-Action focused, query-passive, mutation-free, and exact-source verified in private staging without business-decision authority.",
            "The SLA Decision review handoff lost its exact binding, fail-closed, selected-Action, no-query, no-mutation, test, maturity, or authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_decision_queue_discovery_controls_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "filter": "decision-brief-demo/app/decision-queue-filter.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "tests": "decision-brief-demo/tests/rendered-html.test.mjs",
        "contract": "docs/decision_queue_discovery_controls_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    filter_bounded = all(
        marker in text["filter"]
        for marker in (
            '"ALL"',
            '"CRITICAL"',
            '"HIGH"',
            '"MEDIUM"',
            '"LOW"',
            'action.status === "PROPOSED" || action.status === "EDITED"',
            "action.alert_severity.trim().toUpperCase() === severity",
            "return filterDecisionQueue(actions, severity).length",
        )
    ) and not any(
        marker in text["filter"]
        for marker in (
            "fetch(",
            "sessionStorage",
            "localStorage",
            "submitOperation",
            "loadActionEvidence",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            'item.id === "signals"',
            '"Risk Hotspots"',
            'aria-label="Decision severity filter"',
            "decisionSeverityFilters.map",
            "filterDecisionQueue(actions, severityFilter)",
            "No waiting Actions match this severity",
            "reviewAction(item)",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "filters the authenticated Decision Queue by severity without changing Action state",
            'filterDecisionQueue(actions, "MEDIUM")',
            'decisionSeverityCount(actions, "MEDIUM")',
            'decisionSeverityCount(actions, "LOW")',
            'actions[3].status, "COMPLETED"',
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "deployed to private staging and exact-source canary verified on `2026-08-28`",
            "same `Risk Hotspots` name as the destination page",
            "`All` contains only `PROPOSED` and `EDITED` Actions",
            "Closed or completed Actions cannot re-enter Decision Queue through filtering",
            "Filtering does not weaken its exact-one Risk resolution",
            "adds no API route, request, storage, query, mutation, telemetry, deployment mechanism, or public Pages surface",
            "made no authenticated entity request",
        )
    )
    return [
        _result(
            "decision_queue_discovery_controls_boundary",
            "governance",
            filter_bounded and page_bounded and tests_bounded and contract_bounded,
            "Decision Queue discovery remains waiting-only, severity-bounded, Risk-Hotspots aligned, selected-handoff preserving, browser-local, mutation-free, and exact-source verified in private staging.",
            "Decision Queue discovery lost its waiting-only, severity, naming, selected-handoff, no-request, no-mutation, test, maturity, or authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_decision_truth_staging_rollout_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "migration": "sql/16_decision_action_binding_v1.sql",
        "validation": "sql/17_decision_action_binding_validation.sql",
        "plan": "ops/plan_decision_truth_staging_rollout.ps1",
        "workflow": ".github/workflows/deploy-stateful-lifecycle-staging.yml",
        "stack_deployer": "ops/deploy_stateful_lifecycle_stack.ps1",
        "generator_workflow": ".github/workflows/refactor-stateful-lifecycle-generator-staging.yml",
        "generator_template": "infrastructure/stateful-lifecycle-generator-staging.yaml",
        "generator_deployer": "ops/deploy_stateful_lifecycle_generator_stack.ps1",
        "generator_refactor": "ops/refactor_stateful_lifecycle_generator_stack.ps1",
        "tests": "tests/test_decision_truth_staging_rollout.py",
        "deployment_tests": "tests/test_stateful_lifecycle_deployment.py",
        "runbook": "docs/decision_truth_staging_rollout.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_runbook = " ".join(text["runbook"].split())
    migration_body = re.sub(r"(?m)^\s*--.*$", "", text["migration"])
    validation_body = re.sub(r"(?m)^\s*--.*$", "", text["validation"])
    migration_statements = [
        item for item in migration_body.split(";") if item.strip()
    ]
    validation_statements = [
        item for item in validation_body.split(";") if item.strip()
    ]
    migration_bounded = (
        len(migration_statements) == 2
        and all(
            marker in text["migration"]
            for marker in (
                "PLAN ONLY",
                "fact_lifecycle_action_staging_v1",
                "vw_lifecycle_action_current_staging_v1",
                "decision_brief_version",
                "selected_alternative",
                "selection_rationale",
            )
        )
        and not re.search(
            r"(?i)\b(DROP|DELETE|INSERT|UPDATE|MERGE|TRUNCATE)\b",
            migration_body,
        )
    )
    validation_bounded = (
        len(validation_statements) == 1
        and all(
            marker in text["validation"]
            for marker in (
                "missing_action_binding_columns",
                "missing_action_current_binding_columns",
                "partial_action_binding",
                "invalid_decision_brief_v1_binding",
                "invalid_cost_decision_brief_v1_binding",
                "current_view_binding_mismatch",
                "SELECT check_name, failure_count",
            )
        )
        and not re.search(
            r"(?i)\b(ALTER|CREATE|DROP|DELETE|INSERT|UPDATE|MERGE|TRUNCATE)\b",
            validation_body,
        )
    )
    plan_bounded = all(
        marker in text["plan"]
        for marker in (
            "Mode: local render only",
            "Aggregate validation checks: 6",
            "Release order: schema, validation, lifecycle producer, Operations API, private frontend, read-only verification",
            "Existing Actions backfilled: False",
            "COST_ANOMALY binding source present: True",
            "COST_ANOMALY staging producer released: True",
            "COST_ANOMALY staging readers released: True",
            "COST_ANOMALY runtime binding observed: False",
            "AWS session inspected: False",
            "Athena query started: False",
            "Schema migration applied: False",
            "Staging package deployed: False",
            "Operational continuation authorized: False",
            "Public Pages deployment: False",
            "Production effect: False",
        )
    ) and not any(
        marker in text["plan"].lower()
        for marker in (
            "[switch]$apply",
            "& aws",
            "start-query-execution",
            "workflow run",
            "invoke-webrequest",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "test_migration_is_two_statement_additive_staging_only",
            "test_post_migration_validation_is_one_read_only_aggregate",
            "test_plan_renderer_has_no_aws_or_apply_path",
            "test_runbook_preserves_human_owned_release_order",
            "test_runtime_proof_cannot_be_manufactured_or_overclaimed",
        )
    )
    generator_release_bounded = (
        all(
            marker not in text["workflow"]
            for marker in (
                "plan-stack-only",
                "deploy-stack-only",
                "GeneratorOnly",
            )
        )
        and all(
            marker in text["stack_deployer"]
            for marker in (
                "Generator function managed here: False",
                "blocked until the reviewed generator stack refactor is complete",
                "Generator ownership must be exclusive",
                "ParameterKey=GeneratorArtifactKey,UsePreviousValue=true",
            )
        )
        and all(
            marker in text["generator_workflow"]
            for marker in (
                "- plan-refactor",
                "default: inspect-refactor",
                "- execute-refactor",
                "- plan-release",
                "- deploy-release",
                'normalized_refactor_id="$STACK_REFACTOR_ID"',
                "Invalid refactor input",
                "Unexpected refactor input",
                "LifecycleGeneratorFunction only",
                "Production effect:",
            )
        )
        and text["generator_template"].count("Type: AWS::Lambda::Function") == 1
        and "AWS::IAM::Role" not in text["generator_template"]
        and "Parameters:" not in text["generator_template"]
        and all(
            marker in text["generator_template"]
            for marker in (
                "{{ARTIFACT_BUCKET}}",
                "{{GENERATOR_ARTIFACT_KEY}}",
                "{{FUNCTION_NAME}}",
                "{{EXECUTION_ROLE_ARN}}",
                "{{ATHENA_OUTPUT_URI}}",
                "{{ATHENA_WORKGROUP}}",
                "{{SOURCE_DATABASE}}",
            )
        )
        and all(
            marker in text["generator_deployer"]
            for marker in (
                "must own exactly one expected Lambda function",
                "lambda get-function-configuration",
                '--template-body "file://$renderedTemplatePath"',
                'forbiddenSection in @("Parameters", "Mappings", "Conditions", "Rules", "Transform")',
                "$changes.Count -ne 1",
                'Replacement -ne "False"',
                "without upload or execution",
            )
        )
        and "--use-previous-template" not in text["generator_deployer"]
        and "--parameters @parameterArguments" not in text["generator_deployer"]
        and all(
            marker in text["generator_refactor"]
            for marker in (
                "Assert-ExactMove",
                'forbiddenSection in @("Parameters", "Mappings", "Conditions", "Rules", "Transform")',
                "destination template must inline deployed configuration",
                "[switch]$Inspect",
                '$allActions.Count -ne 2',
                '$stackCreates.Count -ne 1',
                '$moves.Count -ne 1',
                "Existing generator stack refactor plan is available",
                "A separate human dispatch must supply this exact ID",
                "Post-refactor generator ownership verification failed",
            )
        )
        and all(
            marker in text["deployment_tests"]
            for marker in (
                "test_generator_has_an_independent_manual_refactor_and_release_workflow",
                "test_independent_generator_template_and_release_are_exactly_one_resource",
                "test_generator_stack_refactor_is_one_move_and_separate_execution",
                "test_shared_stack_release_fails_closed_without_exclusive_generator_ownership",
            )
        )
    )
    runbook_bounded = all(
        marker in normalized_runbook
        for marker in (
            "Each numbered write is a separate human authority decision",
            "deploying only readers cannot create truthful bindings",
            "Do not create, backfill, or mutate an Action merely to satisfy the test",
            "Existing `COST_ANOMALY` Actions remain unbound",
            "every newly bound `COST_ANOMALY` Action",
            "all six checks returned zero",
            "`deploy-release`",
            "independent one-resource stack",
            "The additive columns are retained",
            "Rollback never changes production",
        )
    )
    return [
        _result(
            "decision_truth_staging_rollout_boundary",
            "governance",
            migration_bounded
            and validation_bounded
            and plan_bounded
            and tests_bounded
            and generator_release_bounded
            and runbook_bounded,
            "Decision Truth staging rollout preserves its validated additive schema plus an independent one-resource generator stack, exact change-set release, producer-before-reader order, and separate human authority for every external write.",
            "Decision Truth rollout lost additive/read-only validation, independent one-resource generator ownership, exact release scope, producer ordering, legacy-null compatibility, or the human-owned execution boundary.",
            tuple(paths.values()),
        )
    ]


def check_outcome_decision_provenance_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/outcome_review_decision_provenance_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    api_bounded = all(
        marker in text["api"]
        for marker in (
            "def build_outcome_review_query",
            "a.decision_brief_version, a.selected_alternative",
            "a.temporal_scope_id = 'OPERATIONAL'",
            "a.execution_mode = 'OPERATIONAL'",
            "a.time_basis = 'ACTUAL_CALENDAR'",
            "a.as_of_date <= DATE",
            "a.created_date <= DATE",
            "from concurrent.futures import ThreadPoolExecutor",
            "def _query_outcome_rows_parallel",
            'ThreadPoolExecutor(max_workers=2, thread_name_prefix="outcome-read")',
            "pool.submit(_query_rows, item_client, item_query)",
            "pool.submit(_query_rows, cohort_client, cohort_query)",
            "item_future.cancel()",
            "cohort_future.cancel()",
            "rows, cohort_rows = _query_outcome_rows_parallel(",
        )
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'decision_brief_version: "decision-brief.v1" | null',
            "selected_alternative: string | null",
            "export async function loadOutcomeReview",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "Decision source:",
            "legacy or unbound Action",
            "not causal estimates or real logistics performance",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "does not copy Decision provenance into the Outcome table",
            "establish traceability, not causality",
            "does not add an Outcome, Action, approval, completion, or activation write",
            "applied it and all six aggregate checks returned zero",
            "deployed private readers passed read-only and four-role verification",
            "Cost producer/API/cockpit revisions are deployed and reader/RBAC verified",
            "exactly two bounded workers",
            "either read fails, the complete response still fails closed",
            "does not cache or omit either query",
            "bounded parallel-read correction delivered to staging, live recheck pending",
            "authorized workflow run `33220634162` passed contract tests and updated the",
            "performed no post-deployment live read or latency",
        )
    )
    return [
        _result(
            "outcome_decision_provenance_boundary",
            "governance",
            api_bounded and client_bounded and page_bounded and contract_bounded,
            "Outcome Review preserves cutoff-bounded, read-only Decision provenance while a staging-delivered two-worker read correction retains both queries, complete-response fail-closed behavior, legacy-null handling, and non-causal claims without asserting a live recheck.",
            "Outcome Review lost a temporal, read-only, legacy-null, or non-causal Decision provenance boundary.",
            tuple(paths.values()),
        )
    ]


def check_decision_contract_outcome_cohort_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/decision_contract_outcome_cohort_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    query_source = text["api"].split(
        "def build_outcome_cohort_query", 1
    )[-1].split("def _finite_float_value", 1)[0]
    api_bounded = all(
        marker in query_source
        for marker in (
            "observed_date <= DATE",
            "try_cast(effect_pct AS double) IS NOT NULL",
            "nullif(trim(decision_brief_version), '') IS NOT NULL",
            "nullif(trim(selected_alternative), '') IS NOT NULL",
            "GROUP BY a.decision_brief_version, a.selected_alternative",
        )
    ) and "LIMIT" not in query_source and all(
        marker in text["api"]
        for marker in (
            '"schema_version": "outcome-cohort-summary.v1"',
            '"descriptive_summary_only": True',
            '"causal_effect_estimate": False',
            '"financial_value_estimated": False',
            '"real_logistics_performance": False',
            '"model_readiness": False',
            '"policy_activation_authorized": False',
        )
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'schema_version: "outcome-cohort-summary.v1"',
            "pending_excluded: true",
            "unbound_actions_excluded: true",
            "future_simulations_excluded: true",
            "causal_effect_estimate: false",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "Decision-contract Outcome cohorts",
            "No eligible Decision cohorts",
            "These cohorts are descriptive only",
            "not causal estimates, realised value, model readiness, or policy authority",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "Pending Outcomes, future simulations, legacy Actions",
            "cohort counts are not derived from the separately bounded Outcome card list",
            "does not establish treatment assignment",
            "adds no route, table, mutation, Learning threshold",
            "all six aggregate checks returned zero",
            "producer/API/frontend deployment and cohort runtime verification remain separate",
        )
    )
    return [
        _result(
            "decision_contract_outcome_cohort_boundary",
            "governance",
            api_bounded and client_bounded and page_bounded and contract_bounded,
            "Decision-contract Outcome cohorts remain observed-only, bound, descriptive, synthetic, reconciled, read-only, and authority bounded.",
            "Decision-contract Outcome cohorts lost an eligibility, reconciliation, descriptive-only, or no-authority boundary.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_evidence_sufficiency_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/outcome_cohort_evidence_sufficiency_v1.md",
        "approval_contract": "docs/outcome_cohort_threshold_contract_v1.json",
        "approval_schema": "docs/outcome_cohort_threshold_contract_v1.schema.json",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    try:
        approval_contract = json.loads(text["approval_contract"])
        approval_schema = json.loads(text["approval_schema"])
    except (TypeError, ValueError):
        approval_contract = {}
        approval_schema = {}
    api_bounded = all(
        marker in text["api"]
        for marker in (
            'APPROVED_OUTCOME_COHORT_CONTRACT_VERSION = "outcome-cohort-threshold-contract.v1"',
            "APPROVED_OUTCOME_COHORT_OBSERVATION_FLOOR = 20",
            "APPROVED_OUTCOME_COHORT_RESULT_STATE_FLOOR = 2",
            "approved_minimum_observed: int | None = None",
            "approved_minimum_result_states: int | None = None",
            "approved_threshold_contract_version: str | None = None",
            "approved_minimum_observed=APPROVED_OUTCOME_COHORT_OBSERVATION_FLOOR",
            "approved_minimum_result_states=APPROVED_OUTCOME_COHORT_RESULT_STATE_FLOOR",
            "APPROVED_OUTCOME_COHORT_CONTRACT_VERSION",
            '"schema_version": "outcome-cohort-evidence-sufficiency.v1"',
            '"configuration_status": (',
            'else "PENDING_HUMAN_APPROVAL"',
            '"comparison_scope": "DESCRIPTIVE_SYNTHETIC_ONLY"',
            '"human_threshold_approval_required": True',
            '"automatic_threshold_selection": False',
        )
    ) and not any(
        marker in text["api"]
        for marker in (
            "OUTCOME_COHORT_MINIMUM_SAMPLE",
            "OUTCOME_COHORT_MINIMUM_RESULT_STATES",
            'os.getenv("OUTCOME_COHORT',
        )
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'schema_version: "outcome-cohort-evidence-sufficiency.v1"',
            'configuration_status: "PENDING_HUMAN_APPROVAL" | "HUMAN_APPROVED_CONTRACT"',
            "minimum_observed_outcomes: number | null",
            "minimum_distinct_result_states: number | null",
            "automatic_threshold_selection: false",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "Comparison thresholds await human approval",
            "No minimum sample or result-coverage threshold has been approved",
            "comparison eligibility is blocked",
            "Human-approved descriptive gate",
            "represented result states per cohort",
            "Result-state coverage",
            "Comparison eligible",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "`HUMAN_APPROVED_CONTRACT`",
            "`minimum_observed_outcomes = 20`",
            "`minimum_distinct_result_states = 2`",
            "Changing either value requires a new versioned contract and a new explicit human approval",
            "cannot select its own thresholds",
            "adds no route, table, CloudFormation change, environment configuration",
        )
    )
    approved_contract_bounded = (
        set(approval_contract) == {
            "schema_version",
            "contract_version",
            "approval",
            "thresholds",
            "scope",
            "authority",
        }
        and approval_contract.get("schema_version")
        == "outcome-cohort-threshold-contract.v1"
        and approval_contract.get("contract_version")
        == "outcome-cohort-threshold-contract.v1"
        and approval_contract.get("approval") == {
            "status": "HUMAN_APPROVED",
            "approved_by_role": "PROJECT_OWNER",
            "approved_on": "2026-08-25",
            "evidence": "EXPLICIT_SESSION_INSTRUCTION",
        }
        and approval_contract.get("thresholds") == {
            "minimum_observed_outcomes": 20,
            "minimum_distinct_result_states": 2,
        }
        and approval_contract.get("scope") == {
            "comparison_scope": "DESCRIPTIVE_SYNTHETIC_ONLY",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT",
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
        }
        and approval_contract.get("authority") == {
            "causal_effect_estimate": False,
            "financial_value_estimated": False,
            "real_logistics_performance": False,
            "model_readiness": False,
            "policy_activation_authorized": False,
            "deployment_authorized": False,
            "production_authorized": False,
        }
        and approval_schema.get("properties", {})
        .get("contract_version", {})
        .get("const") == "outcome-cohort-threshold-contract.v1"
        and approval_schema.get("additionalProperties") is False
    )
    return [
        _result(
            "outcome_cohort_evidence_sufficiency_boundary",
            "governance",
            api_bounded
            and client_bounded
            and page_bounded
            and contract_bounded
            and approved_contract_bounded,
            "The human-approved 20/2 v1 contract is code-bound, machine-readable, descriptive-only, and fail-closed against drift.",
            "Outcome cohort thresholds drifted from the approved 20/2 contract or gained unsupported comparison authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_evidence_gap_boundary(root: Path) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/outcome_cohort_evidence_gap_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    api_bounded = all(
        marker in text["api"]
        for marker in (
            '"schema_version": "outcome-cohort-evidence-gap.v1"',
            "max(approved_minimum_observed - observed, 0)",
            "max(approved_minimum_result_states - distinct_result_states, 0)",
            '"calculation_only": True',
            '"outcome_collection_recommended": False',
            '"outcome_creation_authorized": False',
            '"lifecycle_continuation_authorized": False',
        )
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'schema_version: "outcome-cohort-evidence-gap.v1"',
            "additional_observed_outcomes: number | null",
            "additional_distinct_result_states: number | null",
            "outcome_collection_recommended: false",
            "outcome_creation_authorized: false",
            "lifecycle_continuation_authorized: false",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "Outcome evidence gap",
            "Result-state gap",
            "Evidence gaps are arithmetic differences from the approved 20/2 contract",
            "not instructions to create Outcomes or advance the lifecycle",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "`max(20 - observed_outcome_count, 0)`",
            "`max(2 - distinct_result_states, 0)`",
            "The explainer is a calculation, not a data-collection plan",
            "`outcome_creation_authorized`",
            "`lifecycle_continuation_authorized` false",
            "adds no query, route, table, environment value, CloudFormation change",
        )
    )
    return [
        _result(
            "outcome_cohort_evidence_gap_boundary",
            "governance",
            api_bounded and client_bounded and page_bounded and contract_bounded,
            "Outcome cohort evidence gaps remain exact, non-negative, calculation-only, and unable to authorize evidence creation or lifecycle advancement.",
            "Outcome cohort evidence gaps drifted from the approved targets or gained collection, mutation, or lifecycle authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_descriptive_comparison_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/outcome_cohort_descriptive_comparison_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    api_bounded = all(
        marker in text["api"]
        for marker in (
            '"schema_version": "outcome-cohort-descriptive-comparison.v1"',
            "comparison_available = len(eligible_comparison_cohorts) >= 2",
            'else "INSUFFICIENT_ELIGIBLE_COHORTS"',
            '"required_eligible_cohort_count": 2',
            "eligible_comparison_cohorts if comparison_available else []",
            '"ranking_produced": False',
            '"preferred_alternative_selected": False',
            '"causal_superiority_estimated": False',
            '"statistical_significance_estimated": False',
            '"action_recommended": False',
        )
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            "descriptive_comparison_view?:",
            'schema_version: "outcome-cohort-descriptive-comparison.v1"',
            'status: "AVAILABLE" | "INSUFFICIENT_ELIGIBLE_COHORTS"',
            "required_eligible_cohort_count: 2",
            "preferred_alternative_selected: false",
            "statistical_significance_estimated: false",
            "action_recommended: false",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "Cohort comparison contract unavailable",
            "Cohort comparison unavailable",
            "no data collection is recommended",
            "Eligible Outcome cohort comparison",
            "Side-by-side descriptive status mix and effect ranges",
            "This view produces no ranking, preferred alternative, causal superiority, statistical significance, or Action recommendation",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "`AVAILABLE` only when `eligible_cohort_count >= 2`",
            "an empty `cohorts` array while unavailable",
            "does not sort cohorts by effect or status",
            "`ranking_produced`",
            "`preferred_alternative_selected`",
            "`statistical_significance_estimated`",
            "adds no query, route, table, environment value, CloudFormation change",
        )
    )
    return [
        _result(
            "outcome_cohort_descriptive_comparison_boundary",
            "governance",
            api_bounded and client_bounded and page_bounded and contract_bounded,
            "Eligible cohort comparison remains two-cohort-gated, descriptive-only, order-neutral, and unable to rank, select, infer superiority, or recommend Action.",
            "Eligible cohort comparison lost its two-cohort gate or gained ranking, selection, inference, or Action authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_comparison_provenance_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/outcome_cohort_comparison_provenance_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    api_bounded = all(
        marker in text["api"]
        for marker in (
            '"schema_version": "outcome-cohort-comparison-provenance.v1"',
            '"binding_source": "IMMUTABLE_ACTION_PROPOSAL"',
            '"cohort_summary_schema_version": "outcome-cohort-summary.v1"',
            '"threshold_contract_version": (',
            '"execution_mode": "OPERATIONAL"',
            '"time_basis": "ACTUAL_CALENDAR"',
            '"observed_only": True',
            '"pending_excluded": True',
            '"unbound_actions_excluded": True',
            '"future_simulations_excluded": True',
            '"action_identifiers_exposed": False',
            '"outcome_identifiers_exposed": False',
            '"shipment_identifiers_exposed": False',
            '"read_only": True',
        )
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'schema_version: "outcome-cohort-comparison-provenance.v1"',
            'binding_source: "IMMUTABLE_ACTION_PROPOSAL"',
            'cohort_summary_schema_version: "outcome-cohort-summary.v1"',
            'evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT"',
            "action_identifiers_exposed: false",
            "outcome_identifiers_exposed: false",
            "shipment_identifiers_exposed: false",
            "read_only: true",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "View comparison provenance",
            "Binding source",
            "Sydney cutoff",
            "Threshold contract",
            "Aggregation contract",
            "Aggregate only—none exposed",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "`outcome-cohort-comparison-provenance.v1`",
            "binding source `IMMUTABLE_ACTION_PROPOSAL`",
            "Action, Outcome, and shipment identifiers are not included",
            "Provenance establishes traceability, not validity of a preferred alternative",
            "adds no query, route, table, environment value, CloudFormation change",
        )
    )
    return [
        _result(
            "outcome_cohort_comparison_provenance_boundary",
            "governance",
            api_bounded and client_bounded and page_bounded and contract_bounded,
            "Comparison provenance remains immutable-binding-traceable, cutoff-bounded, aggregate-only, identifier-free, and read-only.",
            "Comparison provenance lost its immutable/cutoff binding or exposed entity identifiers or mutation authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_comparison_fingerprint_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "api": "lambda/glap_operations_api.py",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "contract": "docs/outcome_cohort_comparison_fingerprint_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    api_bounded = all(
        marker in text["api"]
        for marker in (
            "fingerprint_payload = {",
            'f"{value:.2f}"',
            "canonical_comparison = json.dumps(",
            "ensure_ascii=True",
            'separators=(",", ":")',
            "sort_keys=True",
            '"schema_version": "outcome-cohort-comparison-fingerprint.v1"',
            '"algorithm": "SHA-256"',
            '"JSON_SORT_KEYS_COMPACT_UTF8_ASCII_DECIMAL_2_STRINGS"',
            '"digest": hashlib.sha256(canonical_comparison).hexdigest()',
            '"verification_scope": "RESPONSE_CONTENT_INTEGRITY_ONLY"',
            '"digital_signature": False',
            '"source_authenticity_attested": False',
            '"business_validity_attested": False',
        )
    ) and (
        text["api"].index("fingerprint_payload = {")
        < text["api"].index("canonical_comparison = json.dumps(")
        < text["api"].index('comparison_cohort["integrity"] = {')
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'schema_version: "outcome-cohort-comparison-fingerprint.v1"',
            'algorithm: "SHA-256"',
            'canonicalization: "JSON_SORT_KEYS_COMPACT_UTF8_ASCII_DECIMAL_2_STRINGS"',
            'verification_scope: "RESPONSE_CONTENT_INTEGRITY_ONLY"',
            "digital_signature: false",
            "source_authenticity_attested: false",
            "business_validity_attested: false",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "Integrity algorithm",
            "Verification scope",
            "comparison-fingerprint",
            "Deterministic content fingerprint only—not a digital signature, source-authenticity attestation, or business-validity proof",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "`outcome-cohort-comparison-fingerprint.v1` covers exactly:",
            "percentage values are normalized to fixed two-decimal ASCII strings",
            "signed zero is normalized to `0.00`",
            "The integrity object itself is excluded from its own digest",
            "supports `RESPONSE_CONTENT_INTEGRITY_ONLY`",
            "It is not a digital signature, MAC, timestamp authority, source-authenticity attestation",
            "`business_validity_attested` false",
            "adds no query, route, key, secret, certificate",
        )
    )
    return [
        _result(
            "outcome_cohort_comparison_fingerprint_boundary",
            "governance",
            api_bounded and client_bounded and page_bounded and contract_bounded,
            "Comparison fingerprints remain deterministic across server/browser number formatting, cover only the displayed aggregate and provenance, and grant no signature, authenticity, validity, mutation, or production authority.",
            "Comparison fingerprints lost deterministic canonicalization or gained signature, authenticity, validity, mutation, or production authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_comparison_verifier_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "verifier": "decision-brief-demo/app/outcome-comparison-fingerprint.ts",
        "client": "decision-brief-demo/app/operations-api.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "tests": "decision-brief-demo/tests/rendered-html.test.mjs",
        "package": "decision-brief-demo/package.json",
        "contract": "docs/outcome_cohort_comparison_verifier_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    verifier_bounded = all(
        marker in text["verifier"]
        for marker in (
            "EXPECTED_COVERED_FIELDS",
            "Number.isFinite(value)",
            "value === 0 ? 0 : value",
            "normalized.toFixed(2)",
            "Number(text) !== normalized",
            "Canonical strings must be ASCII",
            "Number.isSafeInteger(value)",
            "Object.keys(value).sort()",
            'integrity.schema_version === "outcome-cohort-comparison-fingerprint.v1"',
            "if (!integrity) return false",
            'integrity.algorithm === "SHA-256"',
            'integrity.verification_scope === "RESPONSE_CONTENT_INTEGRITY_ONLY"',
            "integrity.digital_signature === false",
            "integrity.source_authenticity_attested === false",
            "integrity.business_validity_attested === false",
            "globalThis.crypto.subtle.digest(",
            "new TextEncoder().encode(canonicalPayload)",
            'status: "VERIFIED", reason_code: "MATCH"',
            'status: "MISMATCH", reason_code: "DIGEST_MISMATCH"',
            'status: "MISMATCH", reason_code: "VERIFICATION_ERROR"',
        )
    )
    client_bounded = "export type OutcomeComparisonCohort" in text["client"]
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "verifyOutcomeComparisonFingerprint",
            "fingerprintVerification.view === comparisonView",
            'verification?.status !== "VERIFIED"',
            "Comparison metrics and provenance remain hidden until browser verification completes",
            "Comparison metrics and provenance are withheld",
            "Fingerprint verified",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "verifies the server comparison fingerprint and fails closed on drift",
            "await verifyOutcomeComparisonFingerprint(cohort)",
            'status: "VERIFIED", reason_code: "MATCH"',
            "changedMetric.effect_pct.average = 2.01",
            "expandedTrust.integrity.digital_signature = true",
            "delete missingIntegrity.integrity",
            'status: "MISMATCH"',
        )
    ) and "--experimental-strip-types --test" in text["package"]
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "before the private cockpit reveals any covered comparison metric or provenance field",
            "Digital-signature, source-authenticity, and business-validity fields must all remain false",
            "A missing integrity object or Web Crypto, malformed values, metadata drift, authority-flag drift, canonicalization failure, and digest mismatch all resolve to `MISMATCH`",
            "proves neither server or source authenticity nor business validity",
            "adds no API request, route, entity identifier, key, secret, certificate, telemetry, persistence, mutation",
        )
    )
    return [
        _result(
            "outcome_cohort_comparison_verifier_boundary",
            "governance",
            verifier_bounded
            and client_bounded
            and page_bounded
            and tests_bounded
            and contract_bounded,
            "The private cockpit verifier recomputes the exact bounded fingerprint, reveals covered comparison evidence only after a match, and fails closed without gaining authenticity, validity, mutation, or production authority.",
            "The private cockpit verifier stopped failing closed, weakened canonical or trust checks, or gained authenticity, validity, mutation, or production authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_comparison_diagnostics_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "verifier": "decision-brief-demo/app/outcome-comparison-fingerprint.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "css": "decision-brief-demo/app/operations.css",
        "tests": "decision-brief-demo/tests/rendered-html.test.mjs",
        "contract": "docs/outcome_cohort_comparison_diagnostics_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    reason_codes = (
        '"MATCH"',
        '"MISSING_INTEGRITY"',
        '"CONTRACT_METADATA_MISMATCH"',
        '"CRYPTO_UNAVAILABLE"',
        '"NON_CANONICAL_CONTENT"',
        '"DIGEST_MISMATCH"',
        '"VERIFICATION_ERROR"',
    )
    verifier_bounded = all(
        marker in text["verifier"] for marker in reason_codes
    ) and all(
        marker in text["verifier"]
        for marker in (
            'status: "VERIFIED"; reason_code: "MATCH"',
            'status: "MISMATCH";',
            'Exclude<OutcomeComparisonFingerprintReason, "MATCH">',
            'return { status: "MISMATCH", reason_code: "MISSING_INTEGRITY" }',
            'return { status: "MISMATCH", reason_code: "CONTRACT_METADATA_MISMATCH" }',
            'return { status: "MISMATCH", reason_code: "CRYPTO_UNAVAILABLE" }',
            'return { status: "MISMATCH", reason_code: "NON_CANONICAL_CONTENT" }',
            'return { status: "MISMATCH", reason_code: "VERIFICATION_ERROR" }',
            '? { status: "VERIFIED", reason_code: "MATCH" }',
            ': { status: "MISMATCH", reason_code: "DIGEST_MISMATCH" }',
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "comparisonFingerprintDiagnostic",
            'Exclude<OutcomeComparisonFingerprintReason, "MATCH">',
            "The response does not include the required v1 integrity contract",
            "Browser cryptography is unavailable for this verification attempt",
            "The covered response values do not satisfy the canonical comparison format",
            "The recomputed digest does not match the response fingerprint",
            "Browser verification could not complete safely",
            "comparison-diagnostic-code",
            "Comparison metrics and provenance are withheld",
        )
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            'reason_code: "MATCH"',
            'reason_code: "DIGEST_MISMATCH"',
            'reason_code: "CONTRACT_METADATA_MISMATCH"',
            'reason_code: "MISSING_INTEGRITY"',
            "nonCanonical.effect_pct.average = 2.001",
            'reason_code: "NON_CANONICAL_CONTENT"',
            'reason_code: "CRYPTO_UNAVAILABLE"',
            'reason_code: "VERIFICATION_ERROR"',
        )
    )
    css_bounded = "comparison-diagnostic-code" in text["css"]
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "exactly one bounded reason code",
            "No raw exception, stack trace, canonical payload, covered metric, provenance value, or computed digest is included",
            "Every non-`MATCH` reason retains `status=MISMATCH`",
            "The cockpit displays only the reason code and a fixed operator-safe explanation",
            "add no API request, route, telemetry, persistence, identifier exposure, key, secret, certificate, mutation",
        )
    )
    return [
        _result(
            "outcome_cohort_comparison_diagnostics_boundary",
            "governance",
            verifier_bounded
            and page_bounded
            and tests_bounded
            and css_bounded
            and contract_bounded,
            "Comparison verification diagnostics remain bounded to fixed local reason codes, disclose no covered evidence or raw errors, and preserve fail-closed mismatch behavior without telemetry or authority expansion.",
            "Comparison verification diagnostics leaked covered evidence or raw errors, weakened mismatch behavior, or gained telemetry, persistence, mutation, or production authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_comparison_retry_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "verifier": "decision-brief-demo/app/outcome-comparison-fingerprint.ts",
        "page": "decision-brief-demo/app/page.tsx",
        "css": "decision-brief-demo/app/operations.css",
        "tests": "decision-brief-demo/tests/rendered-html.test.mjs",
        "contract": "docs/outcome_cohort_comparison_retry_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    try:
        retry_reason_block = text["verifier"].split(
            "const RETRYABLE_REASON_CODES", 1
        )[1].split("]);", 1)[0]
        retry_function = text["page"].split(
            "const retryFingerprintVerification", 1
        )[1].split('if (operationsState === "demo")', 1)[0]
    except IndexError:
        retry_reason_block = ""
        retry_function = ""
    retry_reasons_exact = all(
        reason in retry_reason_block
        for reason in ('"CRYPTO_UNAVAILABLE"', '"VERIFICATION_ERROR"')
    ) and not any(
        reason in retry_reason_block
        for reason in (
            '"MATCH"',
            '"MISSING_INTEGRITY"',
            '"CONTRACT_METADATA_MISMATCH"',
            '"NON_CANONICAL_CONTENT"',
            '"DIGEST_MISMATCH"',
        )
    )
    verifier_bounded = retry_reasons_exact and all(
        marker in text["verifier"]
        for marker in (
            "isOutcomeComparisonFingerprintRetryable",
            'verification.status === "MISMATCH"',
            "RETRYABLE_REASON_CODES.has(verification.reason_code)",
        )
    )
    page_bounded = all(
        marker in text["page"]
        for marker in (
            "retryFingerprintVerification",
            "isOutcomeComparisonFingerprintRetryable(existing)",
            "attempts >= 1",
            "delete results[verificationKey]",
            "retry_attempts: { ...current.retry_attempts, [verificationKey]: 1 }",
            "await verifyOutcomeComparisonFingerprint(cohort)",
            "current.view === comparisonView",
            "retryable && <button",
            "Retry local verification",
            "browser-only check without requesting new data",
        )
    ) and not any(
        marker in retry_function
        for marker in ("fetch(", "refresh(", "loadOutcomeReview(", "sessionStorage", "localStorage")
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            'status: "MISMATCH", reason_code: "CRYPTO_UNAVAILABLE"',
            'status: "MISMATCH", reason_code: "VERIFICATION_ERROR"',
            'status: "MISMATCH", reason_code: "DIGEST_MISMATCH"',
            'status: "VERIFIED", reason_code: "MATCH"',
            "attempts >= 1",
            "delete results\\[verificationKey\\]",
        )
    )
    css_bounded = all(
        marker in text["css"]
        for marker in ("comparison-local-retry", "cursor: pointer")
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "Exactly two reason codes are retryable",
            "structural failures and never expose the retry control",
            "Each cohort receives at most one local retry for the currently loaded comparison response",
            "runs the same verifier against the same cohort object",
            "only if the original comparison-view object is still current",
            "never calls refresh, `fetch`, the Operations API, or any other network surface",
            "adds no API request, route, telemetry, persistence, browser storage, identifier exposure",
        )
    )
    return [
        _result(
            "outcome_cohort_comparison_retry_boundary",
            "governance",
            verifier_bounded
            and page_bounded
            and tests_bounded
            and css_bounded
            and contract_bounded,
            "Comparison re-verification remains one-attempt, same-response, browser-local, transient-reason-only, fail-closed, and free of network, storage, telemetry, mutation, or production authority.",
            "Comparison re-verification expanded to structural failures or repeated attempts, changed response scope, weakened content withholding, or gained network, storage, telemetry, mutation, or production authority.",
            tuple(paths.values()),
        )
    ]


def check_outcome_cohort_comparison_envelope_boundary(
    root: Path,
) -> list[CheckResult]:
    paths = {
        "validator": "decision-brief-demo/app/outcome-comparison-envelope.ts",
        "client": "decision-brief-demo/app/operations-api.ts",
        "tests": "decision-brief-demo/tests/rendered-html.test.mjs",
        "contract": "docs/outcome_cohort_comparison_envelope_validator_v1.md",
    }
    text = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in paths.items()
    }
    normalized_contract = " ".join(text["contract"].split())
    validator_bounded = all(
        marker in text["validator"]
        for marker in (
            'const ENVELOPE_ERROR = "Outcome comparison envelope failed closed"',
            "export function validateOutcomeComparisonResponse",
            "if (summary === undefined) return",
            "if (envelope === undefined) return",
            'envelope.schema_version !== "outcome-cohort-descriptive-comparison.v1"',
            'status !== "AVAILABLE" && status !== "INSUFFICIENT_ELIGIBLE_COHORTS"',
            "envelope.required_eligible_cohort_count !== 2",
            'envelope.comparison_scope !== "DESCRIPTIVE_SYNTHETIC_ONLY"',
            "eligibleCount + excludedCount !== summary.cohorts.length",
            "!Array.isArray(cohorts)",
            "!cohorts.every(hasCohortIdentity)",
            "governance.ranking_produced !== false",
            "governance.preferred_alternative_selected !== false",
            "governance.causal_superiority_estimated !== false",
            "governance.statistical_significance_estimated !== false",
            "governance.action_recommended !== false",
            'if (status === "AVAILABLE")',
            "eligibleCount < 2 || cohorts.length !== eligibleCount",
            "eligibleCount >= 2 || cohorts.length !== 0",
        )
    ) and not any(
        marker in text["validator"]
        for marker in ("fetch(", "sessionStorage", "localStorage", "sendBeacon")
    )
    client_bounded = all(
        marker in text["client"]
        for marker in (
            'import { validateOutcomeComparisonResponse } from "./outcome-comparison-envelope"',
            "const response = await request<unknown>",
            "validateOutcomeComparisonResponse(response)",
            "return response as OutcomeResponse",
        )
    ) and (
        text["client"].index("const response = await request<unknown>")
        < text["client"].index("validateOutcomeComparisonResponse(response)")
        < text["client"].index("return response as OutcomeResponse")
    )
    tests_bounded = all(
        marker in text["tests"]
        for marker in (
            "validates the comparison envelope before the cockpit can iterate it",
            "nonIterable.cohort_summary.descriptive_comparison_view.cohorts = {}",
            "inconsistentCounts.cohort_summary.descriptive_comparison_view.excluded_cohort_count = 0",
            'unavailableStatus.cohort_summary.descriptive_comparison_view.status = "INSUFFICIENT_ELIGIBLE_COHORTS"',
            "expandedAuthority.cohort_summary.descriptive_comparison_view.governance.action_recommended = true",
            "validateOutcomeComparisonResponse(response)",
        )
    )
    contract_bounded = all(
        marker in normalized_contract
        for marker in (
            "before React or the per-cohort fingerprint verifier can iterate it",
            "eligible and excluded counts are non-negative safe integers whose sum equals the parent summary cohort count",
            "all five governance flags remain exactly false",
            "A present but malformed summary or comparison envelope throws one fixed safe error",
            "does not validate the covered metrics or provenance inside a cohort",
            "adds no endpoint, request, retry, telemetry, persistence, browser storage",
        )
    )
    return [
        _result(
            "outcome_cohort_comparison_envelope_boundary",
            "governance",
            validator_bounded
            and client_bounded
            and tests_bounded
            and contract_bounded,
            "The Outcome client validates an iterable, count-reconciled, descriptive-only, all-false comparison envelope before rendering and fails malformed present responses closed without adding network, storage, mutation, or production authority.",
            "The comparison envelope can reach rendering without structural reconciliation, fail-open governance, or has gained network, storage, mutation, or production authority.",
            tuple(paths.values()),
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
            ("status", "deployed by the named human"),
            ("status", "32807768764"),
            ("status", "32809501684"),
            ("status", "all four temporary users were removed"),
            ("status", "No current label count or readiness status is claimed from AWS"),
        )
    )
    capability_bounded = (
        capability.get("state") == "IMPLEMENTED_STAGING"
        and "deployed and runtime-verified in staging" in boundary
        and "server-derived sydney cutoff" in boundary
        and "pending labels are coverage-only" in boundary
        and "future simulations" in boundary
        and "entity identifiers" in boundary
        and "training" in boundary
        and "promotion" in boundary
        and "pages publication" in boundary
        and "production readiness" in boundary
        and "operational mutation authority remain false" in boundary
    )
    return [
        _result(
            "provider_label_readiness_boundary",
            "forecasting",
            api_bounded and route_bounded and release_bounded and client_bounded
            and documentation_bounded and capability_bounded,
            "Provider label readiness remains aggregate-only, actual-calendar bounded, staging-deployed and runtime-verified, and unable to grant training, promotion, Pages, production, or mutation authority.",
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
        "docs/architecture_current.md",
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
        architecture = (root / "docs/architecture_current.md").read_text(
            encoding="utf-8"
        )
        normalized_architecture = " ".join(architecture.split())
        architecture_current = all(
            marker in normalized_architecture
            for marker in (
                "Five compatible reviews per cutoff meet the minimum-review count",
                "Fourteen package results favour `glap-a303-on`",
                "fourteen controls remain unanimous ties",
                "Cyclone Gabrielle T1 and T2 are the two non-control no-winner packages",
                "Five complete eligible human reviews now exist across the governed collection surfaces",
            )
        ) and all(
            stale not in normalized_architecture
            for stale in (
                "Four compatible reviews per cutoff",
                "fifteen package results remain no-winner",
                "Four complete eligible human reviews now exist outside the repository",
            )
        )
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
            and architecture_current
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
    checks.extend(check_cost_anomaly_decision_brief_boundary(root))
    checks.extend(check_sla_breach_runtime_evidence_boundary(root))
    checks.extend(check_sla_outcome_provenance_readiness_boundary(root))
    checks.extend(check_sla_decision_review_handoff_boundary(root))
    checks.extend(check_decision_queue_discovery_controls_boundary(root))
    checks.extend(check_cost_anomaly_runtime_evidence_boundary(root))
    checks.extend(check_decision_truth_staging_rollout_boundary(root))
    checks.extend(check_outcome_decision_provenance_boundary(root))
    checks.extend(check_decision_contract_outcome_cohort_boundary(root))
    checks.extend(check_outcome_cohort_evidence_sufficiency_boundary(root))
    checks.extend(check_outcome_cohort_evidence_gap_boundary(root))
    checks.extend(check_outcome_cohort_descriptive_comparison_boundary(root))
    checks.extend(check_outcome_cohort_comparison_provenance_boundary(root))
    checks.extend(check_outcome_cohort_comparison_fingerprint_boundary(root))
    checks.extend(check_outcome_cohort_comparison_verifier_boundary(root))
    checks.extend(check_outcome_cohort_comparison_diagnostics_boundary(root))
    checks.extend(check_outcome_cohort_comparison_retry_boundary(root))
    checks.extend(check_outcome_cohort_comparison_envelope_boundary(root))
    checks.extend(check_outcome_learning_evidence_boundary(root))
    checks.extend(check_provider_label_readiness_boundary(root))
    checks.extend(check_audit_automation(root))
    checks.extend(check_documentation_operating_model(root))
    checks.extend(check_action_contract(root, contract))
    checks.extend(check_action_assignment_rollout(root))
    checks.extend(check_action_complete_outcome_canary(root))
    checks.extend(check_action_mutation_release(root))
    checks.extend(check_readiness_contract(root))
    checks.extend(check_public_claim_truth(root))
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
