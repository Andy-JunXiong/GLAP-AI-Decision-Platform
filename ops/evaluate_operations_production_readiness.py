"""Validate and render the offline Operations production-readiness evidence."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs" / "operations_production_readiness_evidence_v1.json"
EXPECTED_GATE_IDS = (
    "authenticated_access_and_rbac",
    "mutation_idempotency_and_concurrency",
    "controlled_dependency_failure_and_recovery",
    "throttling_alarm_and_recovery",
    "sustained_read_load",
    "security_negative_suite",
    "athena_query_cost_baseline",
    "backup_restore_exercise",
    "iceberg_maintenance_exercise",
    "slo_incident_ownership_exercise",
)
ELIGIBLE_STATE = "RUNTIME_VERIFIED_STAGING"
ALLOWED_STATES = {
    ELIGIBLE_STATE,
    "PARTIAL_EVIDENCE",
    "DESIGNED_NOT_EXERCISED",
    "NOT_EXECUTED",
}
ALLOWED_EVIDENCE_CLASSES = {
    "STAGING_ENGINEERING",
    "REPOSITORY_ENGINEERING",
    "NONE",
}
AUTHORITY_FIELDS = {
    "production_deployment_authorized",
    "production_alias_change_authorized",
    "recurring_schedule_authorized",
    "production_table_write_authorized",
    "operational_mutation_authorized",
    "policy_activation_authorized",
    "model_promotion_authorized",
}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "as_of_date",
    "business_timezone",
    "scope",
    "evidence_boundary",
    "execution",
    "authority",
    "required_gates",
    "summary",
    "claim_boundary",
}
GATE_FIELDS = {"id", "state", "evidence_class", "evidence_refs", "finding"}
PROTECTED_FINDING_PATTERNS = (
    re.compile(r"arn:aws", re.IGNORECASE),
    re.compile(r"s3://", re.IGNORECASE),
    re.compile(r"\b\d{12}\b"),
    re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b"),
)


def load_evidence(path: Path = EVIDENCE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sydney_business_date() -> date:
    return datetime.now(ZoneInfo("Australia/Sydney")).date()


def _computed_summary(gates: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = sum(
        isinstance(gate, dict) and gate.get("state") == ELIGIBLE_STATE
        for gate in gates
    )
    required = len(EXPECTED_GATE_IDS)
    return {
        "required_gate_count": required,
        "eligible_gate_count": eligible,
        "blocked_gate_count": required - eligible,
        "production_readiness": eligible == required,
    }


def validate_evidence(
    evidence: dict[str, Any], *, today: date | None = None, root: Path = ROOT
) -> list[str]:
    if not isinstance(evidence, dict):
        return ["evidence must be an object"]
    errors: list[str] = []
    if set(evidence) != TOP_LEVEL_FIELDS:
        errors.append("top-level field inventory is incomplete or unexpected")
    if evidence.get("schema_version") != "operations-production-readiness-evidence.v1":
        errors.append("unsupported schema_version")
    if evidence.get("business_timezone") != "Australia/Sydney":
        errors.append("business timezone must remain Australia/Sydney")
    if evidence.get("scope") != "PRIVATE_OPERATIONS_STAGING":
        errors.append("scope must remain private Operations staging")
    if evidence.get("evidence_boundary") != "SYNTHETIC_ENGINEERING_ONLY":
        errors.append("evidence boundary must remain synthetic engineering only")

    try:
        as_of_date = date.fromisoformat(evidence.get("as_of_date", ""))
    except (TypeError, ValueError):
        errors.append("as_of_date must be an ISO calendar date")
    else:
        if as_of_date > (today or sydney_business_date()):
            errors.append("as_of_date cannot be later than the current Sydney date")

    execution = evidence.get("execution", {})
    if not isinstance(execution, dict):
        errors.append("execution must be an object")
        execution = {}
    if set(execution) != {"mode", "network_access", "external_writes_executed"}:
        errors.append("execution field inventory is incomplete or unexpected")
    if execution.get("mode") != "OFFLINE_REPOSITORY_EVIDENCE_RECONCILIATION":
        errors.append("execution mode must remain offline repository reconciliation")
    for field in ("network_access", "external_writes_executed"):
        if execution.get(field) is not False:
            errors.append(f"execution.{field} must remain false")

    authority = evidence.get("authority", {})
    if not isinstance(authority, dict):
        errors.append("authority must be an object")
        authority = {}
    if set(authority) != AUTHORITY_FIELDS:
        errors.append("authority field inventory is incomplete or unexpected")
    for field in AUTHORITY_FIELDS:
        if authority.get(field) is not False:
            errors.append(f"authority.{field} must remain false")

    gates = evidence.get("required_gates", [])
    if not isinstance(gates, list):
        errors.append("required_gates must be a list")
        gates = []
    gate_ids = [gate.get("id") for gate in gates if isinstance(gate, dict)]
    if tuple(gate_ids) != EXPECTED_GATE_IDS:
        errors.append("required gate inventory or order drifted")
    for gate in gates:
        if not isinstance(gate, dict):
            errors.append("every gate must be an object")
            continue
        gate_id = gate.get("id", "unknown")
        if set(gate) != GATE_FIELDS:
            errors.append(f"{gate_id} field inventory is incomplete or unexpected")
        state = gate.get("state")
        evidence_class = gate.get("evidence_class")
        refs = gate.get("evidence_refs")
        if state not in ALLOWED_STATES:
            errors.append(f"{gate_id} has an unsupported state")
        if evidence_class not in ALLOWED_EVIDENCE_CLASSES:
            errors.append(f"{gate_id} has an unsupported evidence class")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            errors.append(f"{gate_id} evidence_refs must be a string list")
            refs = []
        elif len(refs) != len(set(refs)):
            errors.append(f"{gate_id} evidence_refs must be unique")
        for ref in refs:
            candidate = (root / ref).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{gate_id} evidence reference escapes the repository")
                continue
            if not candidate.is_file():
                errors.append(f"{gate_id} evidence reference is missing: {ref}")
        if state == ELIGIBLE_STATE and evidence_class != "STAGING_ENGINEERING":
            errors.append(f"{gate_id} runtime verification requires staging engineering evidence")
        if state == "NOT_EXECUTED" and evidence_class != "NONE":
            errors.append(f"{gate_id} not-executed state must use NONE evidence class")
        if not isinstance(gate.get("finding"), str) or not gate["finding"].strip():
            errors.append(f"{gate_id} requires a finding")
        elif any(pattern.search(gate["finding"]) for pattern in PROTECTED_FINDING_PATTERNS):
            errors.append(f"{gate_id} finding contains a protected identifier pattern")

    computed = _computed_summary(gates)
    if evidence.get("summary") != computed:
        errors.append("summary does not match the required gate states")
    claim = evidence.get("claim_boundary", {})
    if not isinstance(claim, dict):
        errors.append("claim boundary must be an object")
        claim = {}
    if set(claim) != {
        "status",
        "real_logistics_performance",
        "production_sla",
        "production_readiness",
    }:
        errors.append("claim boundary field inventory is incomplete or unexpected")
    if claim.get("status") != "NOT_READY_INCOMPLETE_EVIDENCE":
        errors.append("claim status must remain NOT_READY_INCOMPLETE_EVIDENCE")
    for field in ("real_logistics_performance", "production_sla", "production_readiness"):
        if claim.get(field) is not False:
            errors.append(f"claim_boundary.{field} must remain false")
    if computed["production_readiness"] is True:
        errors.append("v1 evidence must not claim complete production readiness")
    return errors


def build_report(evidence: dict[str, Any]) -> dict[str, Any]:
    gates = evidence["required_gates"]
    return {
        "schema_version": "operations-production-readiness-report.v1",
        "as_of_date": evidence["as_of_date"],
        "scope": evidence["scope"],
        "status": evidence["claim_boundary"]["status"],
        "evidence_boundary": evidence["evidence_boundary"],
        "summary": _computed_summary(gates),
        "gates": [
            {
                "id": gate["id"],
                "state": gate["state"],
                "finding": gate["finding"],
            }
            for gate in gates
        ],
        "execution": evidence["execution"],
        "authority": evidence["authority"],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Operations production-readiness evidence",
        "",
        f"- Status: **{report['status']}**",
        f"- Sydney as-of date: `{report['as_of_date']}`",
        f"- Scope: `{report['scope']}`",
        f"- Eligible gates: {summary['eligible_gate_count']}/{summary['required_gate_count']}",
        f"- Blocked gates: {summary['blocked_gate_count']}",
        "- Production readiness: `false`",
        "",
        "| Required gate | Evidence state | Finding |",
        "| --- | --- | --- |",
    ]
    for gate in report["gates"]:
        finding = gate["finding"].replace("|", "\\|")
        lines.append(f"| `{gate['id']}` | `{gate['state']}` | {finding} |")
    lines.extend(
        [
            "",
            "This report is an offline reconciliation of synthetic engineering evidence. ",
            "It executed no network request or external write and grants no production authority.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    evidence = load_evidence(args.evidence)
    errors = validate_evidence(evidence)
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    report = build_report(evidence)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
