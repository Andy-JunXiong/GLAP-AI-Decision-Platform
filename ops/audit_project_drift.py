"""Read-only architecture, capability, documentation, and evidence drift audit."""

from __future__ import annotations

import argparse
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


def check_action_contract(root: Path, contract: dict[str, Any]) -> list[CheckResult]:
    mutation_path = "lambda/glap_action_mutation.py"
    roadmap_path = "docs/implementation_roadmap.md"
    todo_path = "TODO.md"
    mutation = (root / mutation_path).read_text(encoding="utf-8")
    roadmap = (root / roadmap_path).read_text(encoding="utf-8")
    todo = (root / todo_path).read_text(encoding="utf-8")
    actual = _extract_action_operations(mutation)
    expected = set(contract.get("action_contract", {}).get("implemented_operations", []))
    not_implemented = set(contract.get("action_contract", {}).get("not_implemented", []))
    required_fields = set(contract.get("action_contract", {}).get("required_assignment_fields", []))
    fields_implemented = required_fields == {"owner", "due_date"} and all(
        token in mutation for token in ("action_owner", "action_due_date")
    )
    roadmap_current = "approve/edit/reject/complete" in roadmap
    todo_current = bool(
        re.search(r"(?m)^- \[x\] Add a governed Action edit event", todo)
        and re.search(r"(?m)^- \[x\] Extend authenticated Actions with an owner and due date", todo)
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
            roadmap_current and todo_current,
            "Roadmap and TODO match the repository Action edit/assignment implementation.",
            "Roadmap or TODO differs from the repository Action edit/assignment implementation.",
            (roadmap_path, todo_path),
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
        rollout.get("status") == "PLAN_ONLY_BLOCKED_AWS_WRITE_AUTHORIZATION"
        and rollout.get("business_timezone") == "Australia/Sydney"
        and rollout.get("evidence_boundary") == "SYNTHETIC_STAGING_ONLY"
        and all(authority.get(field) is False for field in protected_authority)
        and schema.get("additive_only") is True
        and schema.get("automatic_workflow_wiring") is False
        and rollout.get("release_paths", {}).get("action_mutation_lambda")
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
        is False
        and rollout.get("verified_release_evidence", {}).get(
            "operational_action_mutation_executed"
        )
        is False
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
    )
    return [
        _result(
            "action_assignment_rollout_boundary",
            "governance",
            bounded,
            "Action assignment rollout remains ordered and plan-only after the verified Lambda release; future writes still require approval.",
            "Action assignment rollout hides its blocker or expands deployment, mutation, or scheduling authority.",
            (
                contract_path,
                "docs/action_assignment_staging_rollout.md",
                "ops/validate_action_assignment_rollout.py",
                "sql/16_action_assignment_validation.sql",
            ),
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


def run_audit(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    checks: list[CheckResult] = []
    checks.extend(check_contract(root, contract))
    checks.extend(check_manual_staging_boundary(root))
    checks.extend(check_public_private_boundary(root))
    checks.extend(check_audit_automation(root))
    checks.extend(check_action_contract(root, contract))
    checks.extend(check_action_assignment_rollout(root))
    checks.extend(check_action_mutation_release(root))
    checks.extend(check_readiness_contract(root))
    checks.extend(check_temporal_boundary(root))
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
