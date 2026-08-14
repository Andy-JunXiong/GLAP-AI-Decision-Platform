"""Run a deterministic, local-only GLAP capability-ablation experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "evaluation-experiment.v1"
REPORT_VERSION = "evaluation-report.v1"
TARGET_CAPABILITY = "A303_HIGH_RISK_ROUTE"
COMPARISON_FIELDS = ("recommendation", "priority", "human_review_required")


class ContractError(ValueError):
    """Raised when an experiment would violate the v1 evaluation boundary."""


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{field} must include a UTC offset")
    return parsed


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Fail closed on authority, pairing, temporal, or contract drift."""

    _require(manifest.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version")
    _require(manifest.get("purpose") == "CAPABILITY_ATTRIBUTION", "unsupported purpose")
    _require(manifest.get("business_timezone") == "Australia/Sydney", "business timezone must be Australia/Sydney")

    boundary = manifest.get("execution_boundary", {})
    _require(boundary.get("mode") == "LOCAL_READ_ONLY", "only LOCAL_READ_ONLY execution is allowed")
    for field in ("network_access_allowed", "operational_writes_allowed", "production_effect"):
        _require(boundary.get(field) is False, f"{field} must be false")

    context = manifest.get("fixed_context", {})
    _require(context.get("rule_contract_version") == "A303.v1", "unsupported rule contract")
    _require(context.get("authority_profile") == "EVALUATION_NO_MUTATION", "evaluation must use no-mutation authority")
    _require(isinstance(context.get("random_seed"), int), "random_seed must be an integer")

    scenario = manifest.get("scenario", {})
    _require(scenario.get("scenario_mode") == "CONTROLLED_SYNTHETIC_REPLAY", "v0.1 supports controlled synthetic replay only")
    _require(scenario.get("evidence_classification") == "SYNTHETIC_ENGINEERING_ONLY", "v0.1 evidence must remain synthetic engineering only")
    cutoff = _timestamp(scenario.get("cutoff_at"), "scenario.cutoff_at")
    state = scenario.get("operational_state", {})
    _require(_timestamp(state.get("as_of_at"), "scenario.operational_state.as_of_at") <= cutoff, "operational state cannot be later than the cutoff")
    _require(state.get("state_provenance") == "CONTROLLED_SYNTHETIC", "operational state provenance is unsupported")

    evidence = scenario.get("evidence")
    _require(isinstance(evidence, list) and bool(evidence), "scenario evidence must be a non-empty list")
    evidence_ids: list[str] = []
    for index, item in enumerate(evidence):
        _require(isinstance(item, dict), f"scenario.evidence[{index}] must be an object")
        evidence_id = item.get("evidence_id")
        _require(isinstance(evidence_id, str) and bool(evidence_id), f"scenario.evidence[{index}] needs an evidence_id")
        evidence_ids.append(evidence_id)
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{evidence_id} has unsupported provenance")
        for field in ("event_time", "published_at", "available_at", "ingested_at"):
            _timestamp(item.get(field), f"{evidence_id}.{field}")
    _require(len(evidence_ids) == len(set(evidence_ids)), "evidence_id values must be unique")

    variants = manifest.get("variants")
    _require(isinstance(variants, list) and len(variants) == 2, "v0.1 requires exactly two variants")
    _require({item.get("role") for item in variants} == {"BASELINE", "CHALLENGER"}, "variants require one baseline and one challenger")
    variant_ids = [item.get("variant_id") for item in variants]
    _require(all(isinstance(item, str) and item for item in variant_ids), "each variant needs a variant_id")
    _require(len(variant_ids) == len(set(variant_ids)), "variant_id values must be unique")
    capability_sets = [item.get("capabilities") for item in variants]
    _require(all(isinstance(item, dict) for item in capability_sets), "each variant needs capabilities")
    _require(all(set(item) == {TARGET_CAPABILITY} for item in capability_sets), "only A303 may vary in v0.1")
    _require({item[TARGET_CAPABILITY] for item in capability_sets} == {False, True}, "A303 must be off in one variant and on in the other")

    hypothesis = manifest.get("hypothesis", {})
    _require(hypothesis.get("changed_capability") == TARGET_CAPABILITY, "hypothesis capability must be A303")
    _require(hypothesis.get("expected_decision_change") is True, "v0.1 expects an A303 decision delta")
    primary_fields = hypothesis.get("primary_comparison_fields")
    _require(isinstance(primary_fields, list) and bool(primary_fields), "primary comparison fields are required")
    _require(set(primary_fields) <= set(COMPARISON_FIELDS), "unsupported primary comparison field")

    layers = manifest.get("evaluation_layers", {})
    _require(layers.get("system_correctness") == "EVALUATE", "system correctness must be evaluated")
    _require(layers.get("capability_attribution") == "EVALUATE", "capability attribution must be evaluated")
    _require(layers.get("decision_quality") == "NOT_EVALUATED", "v0.1 cannot claim decision quality")
    _require(layers.get("business_outcome_effect") == "NOT_EVALUATED", "v0.1 cannot claim business outcome effect")


def _visible_evidence(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    cutoff = _timestamp(scenario["cutoff_at"], "scenario.cutoff_at")
    return [
        item
        for item in scenario["evidence"]
        if _timestamp(item["available_at"], f"{item['evidence_id']}.available_at") <= cutoff
    ]


def _decision_id(experiment_id: str, variant_id: str, policy_version: str) -> str:
    value = f"{experiment_id}|{variant_id}|{policy_version}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def _evaluate_variant(
    manifest: dict[str, Any], variant: dict[str, Any], visible: list[dict[str, Any]]
) -> dict[str, Any]:
    capability_on = variant["capabilities"][TARGET_CAPABILITY]
    state = manifest["scenario"]["operational_state"]
    matching = [
        item
        for item in visible
        if item.get("facts", {}).get("signal_type") == TARGET_CAPABILITY
        and item.get("facts", {}).get("severity") == "HIGH"
    ]
    rule_fired = bool(capability_on and state.get("route_risk_level") == "HIGH" and matching)
    if rule_fired:
        recommendation = "RISK_MITIGATION"
        priority = "HIGH"
        human_review_required = True
        rationale = "A303.v1 observed a HIGH route-risk signal; propose bounded mitigation for human review."
        review_rationale = "A HIGH route-risk signal is present; propose bounded mitigation for human review."
    else:
        recommendation = "MONITOR"
        priority = "MEDIUM"
        human_review_required = False
        rationale = "A303.v1 did not fire in this variant; continue the versioned baseline monitoring SOP."
        review_rationale = "Continue monitoring and re-check at the next governed review point."
    return {
        "variant_id": variant["variant_id"],
        "role": variant["role"],
        "capabilities": dict(variant["capabilities"]),
        "decision": {
            "decision_id": _decision_id(
                manifest["experiment_id"],
                variant["variant_id"],
                manifest["fixed_context"]["policy_version"],
            ),
            "recommendation": recommendation,
            "priority": priority,
            "human_review_required": human_review_required,
            "rationale": rationale,
            "review_rationale": review_rationale,
            "status": "EVALUATION_PROPOSAL_ONLY",
        },
        "trace": {
            "rule_contract_version": manifest["fixed_context"]["rule_contract_version"],
            "rule_enabled": capability_on,
            "rule_fired": rule_fired,
            "visible_evidence_ids": [item["evidence_id"] for item in visible],
            "matched_evidence_ids": [item["evidence_id"] for item in matching],
            "authority_profile": manifest["fixed_context"]["authority_profile"],
        },
        "operational_mutations": [],
    }


def run_experiment(manifest: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the paired variants without performing an external read or write."""

    validate_manifest(manifest)
    visible = _visible_evidence(manifest["scenario"])
    variants = [_evaluate_variant(manifest, item, visible) for item in manifest["variants"]]
    baseline = next(item for item in variants if item["role"] == "BASELINE")
    challenger = next(item for item in variants if item["role"] == "CHALLENGER")
    primary_fields = manifest["hypothesis"]["primary_comparison_fields"]
    changed_fields = [
        field
        for field in primary_fields
        if baseline["decision"][field] != challenger["decision"][field]
    ]
    decision_changed = bool(changed_fields)
    visible_ids = [item["evidence_id"] for item in visible]
    all_ids = [item["evidence_id"] for item in manifest["scenario"]["evidence"]]
    excluded_ids = [item for item in all_ids if item not in visible_ids]
    mutation_free = all(not item["operational_mutations"] for item in variants)
    no_future_leakage = all(
        evidence_id not in variant["trace"]["visible_evidence_ids"]
        for evidence_id in excluded_ids
        for variant in variants
    )
    system_passed = (
        mutation_free
        and no_future_leakage
        and manifest["execution_boundary"]["operational_writes_allowed"] is False
        and all(item["trace"]["visible_evidence_ids"] == visible_ids for item in variants)
    )
    attribution_passed = decision_changed and changed_fields and TARGET_CAPABILITY == manifest["hypothesis"]["changed_capability"]

    return {
        "schema_version": REPORT_VERSION,
        "experiment_id": manifest["experiment_id"],
        "scenario_id": manifest["scenario"]["scenario_id"],
        "scenario_mode": manifest["scenario"]["scenario_mode"],
        "cutoff_at": manifest["scenario"]["cutoff_at"],
        "evidence_classification": manifest["scenario"]["evidence_classification"],
        "execution_boundary": dict(manifest["execution_boundary"]),
        "fixed_context": dict(manifest["fixed_context"]),
        "evidence_window": {
            "visible_evidence_ids": visible_ids,
            "post_cutoff_evidence_ids": excluded_ids,
        },
        "variants": variants,
        "comparison": {
            "changed_capability": TARGET_CAPABILITY,
            "decision_changed": decision_changed,
            "changed_fields": changed_fields,
            "attribution": "ATTRIBUTED_TO_A303_HIGH_RISK_ROUTE" if attribution_passed else "NOT_ATTRIBUTED",
        },
        "evaluation_layers": {
            "system_correctness": {
                "status": "PASS" if system_passed else "FAIL",
                "read_only_boundary": mutation_free,
                "paired_visible_evidence": True,
                "post_cutoff_evidence_excluded": no_future_leakage,
            },
            "capability_attribution": {
                "status": "PASS" if attribution_passed else "FAIL",
                "decision_changed": decision_changed,
                "changed_capability": TARGET_CAPABILITY,
            },
            "decision_quality": {
                "status": "NOT_EVALUATED",
                "rubric_version": "decision-quality-rubric.v1",
                "reason": "No independent blinded expert reviews are attached.",
            },
            "business_outcome_effect": {
                "status": "NOT_EVALUATED",
                "outcome_evidence_class": "NOT_EVALUATED",
                "reason": "No factual or counterfactual outcome method is attached.",
            },
        },
        "operational_mutations": [],
        "claim_boundary": {
            "supported": ["LOCAL_HARNESS_MECHANICS", "A303_V1_CAPABILITY_ATTRIBUTION"],
            "not_supported": [
                "DEPLOYED_A303_RUNTIME_VERIFICATION",
                "DECISION_QUALITY_IMPROVEMENT",
                "BUSINESS_OUTCOME_IMPROVEMENT",
                "PRODUCTION_READINESS",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = run_experiment(manifest)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if all(
        report["evaluation_layers"][layer]["status"] == "PASS"
        for layer in ("system_correctness", "capability_attribution")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
