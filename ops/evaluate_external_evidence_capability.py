"""Run the frozen local-only External Evidence capability ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "evaluation-experiment.v2"
REPORT_VERSION = "evaluation-report.v2"
TARGET_CAPABILITY = "EXTERNAL_EVIDENCE"
DECISION_PROCEDURE_VERSION = "external-evidence-review.v1"
COMPARISON_FIELDS = ("recommendation", "priority", "human_review_required")
EXPERIMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
SYDNEY = ZoneInfo("Australia/Sydney")


class ContractError(ValueError):
    """Raised when an experiment would violate the v2 evaluation boundary."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    actual = set(value)
    _require(actual == expected, f"{field} keys must be exactly {sorted(expected)}")


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{field} must include a UTC offset")
    return parsed


def _require_sydney_offset(value: datetime, field: str) -> None:
    expected = value.astimezone(SYDNEY).utcoffset()
    _require(value.utcoffset() == expected, f"{field} must use the Australia/Sydney UTC offset")


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Fail closed on schema, authority, pairing, temporal, or claim drift."""

    _exact_keys(
        manifest,
        {
            "schema_version",
            "experiment_id",
            "purpose",
            "business_timezone",
            "execution_boundary",
            "scenario",
            "fixed_context",
            "variants",
            "hypothesis",
            "evaluation_layers",
        },
        "manifest",
    )
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version")
    _require(
        isinstance(manifest.get("experiment_id"), str)
        and bool(EXPERIMENT_ID_PATTERN.fullmatch(manifest["experiment_id"])),
        "experiment_id must match the v2 identifier pattern",
    )
    _require(manifest.get("purpose") == "CAPABILITY_ATTRIBUTION", "unsupported purpose")
    _require(
        manifest.get("business_timezone") == "Australia/Sydney",
        "business timezone must be Australia/Sydney",
    )

    boundary = manifest.get("execution_boundary")
    _exact_keys(
        boundary,
        {"mode", "network_access_allowed", "operational_writes_allowed", "production_effect"},
        "execution_boundary",
    )
    _require(boundary.get("mode") == "LOCAL_READ_ONLY", "only LOCAL_READ_ONLY execution is allowed")
    for field in ("network_access_allowed", "operational_writes_allowed", "production_effect"):
        _require(boundary.get(field) is False, f"{field} must be false")

    context = manifest.get("fixed_context")
    _exact_keys(
        context,
        {"decision_procedure_version", "authority_profile", "random_seed"},
        "fixed_context",
    )
    _require(
        context.get("decision_procedure_version") == DECISION_PROCEDURE_VERSION,
        "unsupported decision procedure",
    )
    _require(
        context.get("authority_profile") == "EVALUATION_NO_MUTATION",
        "evaluation must use no-mutation authority",
    )
    _require(type(context.get("random_seed")) is int, "random_seed must be an integer")
    _require(context["random_seed"] >= 0, "random_seed must be non-negative")

    scenario = manifest.get("scenario")
    _exact_keys(
        scenario,
        {
            "scenario_id",
            "scenario_mode",
            "cutoff_at",
            "evidence_classification",
            "operational_state",
            "evidence",
        },
        "scenario",
    )
    _require(
        scenario.get("scenario_mode") == "CONTROLLED_SYNTHETIC_REPLAY",
        "v2 supports controlled synthetic replay only",
    )
    _require(
        scenario.get("evidence_classification") == "SYNTHETIC_ENGINEERING_ONLY",
        "v2 evidence must remain synthetic engineering only",
    )
    cutoff = _timestamp(scenario.get("cutoff_at"), "scenario.cutoff_at")
    _require_sydney_offset(cutoff, "scenario.cutoff_at")
    _require(
        cutoff.astimezone(SYDNEY).date() <= datetime.now(SYDNEY).date(),
        "controlled replay cutoff cannot be later than the current Sydney date",
    )
    state = scenario.get("operational_state")
    _exact_keys(state, {"as_of_at", "shipment_scope", "state_provenance"}, "scenario.operational_state")
    state_as_of = _timestamp(state.get("as_of_at"), "scenario.operational_state.as_of_at")
    _require_sydney_offset(state_as_of, "scenario.operational_state.as_of_at")
    _require(
        state_as_of <= cutoff,
        "operational state cannot be later than the cutoff",
    )
    _require(
        isinstance(scenario.get("scenario_id"), str) and bool(scenario["scenario_id"]),
        "scenario_id is required",
    )
    _require(
        isinstance(state.get("shipment_scope"), str) and bool(state["shipment_scope"]),
        "shipment_scope is required",
    )
    _require(
        state.get("state_provenance") == "CONTROLLED_SYNTHETIC",
        "operational state provenance is unsupported",
    )

    evidence = scenario.get("evidence")
    _require(isinstance(evidence, list) and bool(evidence), "scenario evidence must be a non-empty list")
    evidence_ids: list[str] = []
    for index, item in enumerate(evidence):
        field = f"scenario.evidence[{index}]"
        _exact_keys(
            item,
            {
                "evidence_id",
                "evidence_type",
                "event_time",
                "published_at",
                "available_at",
                "ingested_at",
                "revision_version",
                "provenance",
                "facts",
            },
            field,
        )
        evidence_id = item.get("evidence_id")
        _require(isinstance(evidence_id, str) and bool(evidence_id), f"{field} needs an evidence_id")
        evidence_ids.append(evidence_id)
        _require(
            item.get("evidence_type") in {"OPERATIONAL_SIGNAL", "EXTERNAL_EVENT"},
            f"{evidence_id} has unsupported evidence_type",
        )
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{evidence_id} has unsupported provenance")
        _require(
            isinstance(item.get("revision_version"), str) and bool(item["revision_version"]),
            f"{evidence_id}.revision_version is required",
        )
        parsed_timestamps: dict[str, datetime] = {}
        for timestamp_field in ("event_time", "published_at", "available_at", "ingested_at"):
            parsed_timestamps[timestamp_field] = _timestamp(
                item.get(timestamp_field), f"{evidence_id}.{timestamp_field}"
            )
        _require(
            parsed_timestamps["published_at"] <= parsed_timestamps["available_at"],
            f"{evidence_id}.available_at cannot precede published_at",
        )
        _require(
            parsed_timestamps["available_at"] <= parsed_timestamps["ingested_at"],
            f"{evidence_id}.ingested_at cannot precede available_at",
        )
        facts = item.get("facts")
        _exact_keys(facts, {"signal_type", "severity"}, f"{evidence_id}.facts")
        _require(
            isinstance(facts.get("signal_type"), str) and bool(facts["signal_type"]),
            f"{evidence_id}.facts.signal_type is required",
        )
        _require(facts.get("severity") in {"LOW", "MEDIUM", "HIGH"}, f"{evidence_id} has unsupported severity")
    _require(len(evidence_ids) == len(set(evidence_ids)), "evidence_id values must be unique")
    _require(
        any(
            item["evidence_type"] == "EXTERNAL_EVENT"
            and item["facts"]["severity"] == "HIGH"
            and _timestamp(item["available_at"], f"{item['evidence_id']}.available_at") <= cutoff
            for item in evidence
        ),
        "a cutoff-eligible HIGH external event is required",
    )

    variants = manifest.get("variants")
    _require(isinstance(variants, list) and len(variants) == 2, "v2 requires exactly two variants")
    for index, variant in enumerate(variants):
        _exact_keys(variant, {"variant_id", "role", "capabilities"}, f"variants[{index}]")
        _exact_keys(variant.get("capabilities"), {TARGET_CAPABILITY}, f"variants[{index}].capabilities")
        _require(
            isinstance(variant.get("variant_id"), str) and bool(variant["variant_id"]),
            f"variants[{index}] needs a variant_id",
        )
        _require(
            type(variant["capabilities"].get(TARGET_CAPABILITY)) is bool,
            f"variants[{index}].capabilities.EXTERNAL_EVIDENCE must be a boolean",
        )
    _require({item.get("role") for item in variants} == {"BASELINE", "CHALLENGER"}, "variants require one baseline and one challenger")
    _require(len({item["variant_id"] for item in variants}) == 2, "variant_id values must be unique")
    _require(
        {item["capabilities"][TARGET_CAPABILITY] for item in variants} == {False, True},
        "EXTERNAL_EVIDENCE must be off in one variant and on in the other",
    )
    baseline = next(item for item in variants if item["role"] == "BASELINE")
    challenger = next(item for item in variants if item["role"] == "CHALLENGER")
    _require(baseline["capabilities"][TARGET_CAPABILITY] is False, "baseline must disable EXTERNAL_EVIDENCE")
    _require(challenger["capabilities"][TARGET_CAPABILITY] is True, "challenger must enable EXTERNAL_EVIDENCE")

    hypothesis = manifest.get("hypothesis")
    _exact_keys(
        hypothesis,
        {"changed_capability", "expected_decision_change", "primary_comparison_fields"},
        "hypothesis",
    )
    _require(hypothesis.get("changed_capability") == TARGET_CAPABILITY, "hypothesis capability must be EXTERNAL_EVIDENCE")
    _require(hypothesis.get("expected_decision_change") is True, "v2 expects an External Evidence decision delta")
    primary_fields = hypothesis.get("primary_comparison_fields")
    _require(isinstance(primary_fields, list) and bool(primary_fields), "primary comparison fields are required")
    _require(len(primary_fields) == len(set(primary_fields)), "primary comparison fields must be unique")
    _require(set(primary_fields) <= set(COMPARISON_FIELDS), "unsupported primary comparison field")

    layers = manifest.get("evaluation_layers")
    _exact_keys(
        layers,
        {"system_correctness", "capability_attribution", "decision_quality", "business_outcome_effect"},
        "evaluation_layers",
    )
    _require(layers.get("system_correctness") == "EVALUATE", "system correctness must be evaluated")
    _require(layers.get("capability_attribution") == "EVALUATE", "capability attribution must be evaluated")
    _require(layers.get("decision_quality") == "NOT_EVALUATED", "v2 cannot claim decision quality")
    _require(layers.get("business_outcome_effect") == "NOT_EVALUATED", "v2 cannot claim business outcome effect")


def _cutoff_eligible_evidence(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    cutoff = _timestamp(scenario["cutoff_at"], "scenario.cutoff_at")
    return [
        item
        for item in scenario["evidence"]
        if _timestamp(item["available_at"], f"{item['evidence_id']}.available_at") <= cutoff
    ]


def _decision_id(experiment_id: str, variant_id: str, procedure_version: str) -> str:
    value = f"{experiment_id}|{variant_id}|{procedure_version}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def _evaluate_variant(
    manifest: dict[str, Any], variant: dict[str, Any], cutoff_eligible: list[dict[str, Any]]
) -> dict[str, Any]:
    capability_on = variant["capabilities"][TARGET_CAPABILITY]
    decision_visible = [
        item
        for item in cutoff_eligible
        if item["evidence_type"] != "EXTERNAL_EVENT" or capability_on
    ]
    qualifying_external = [
        item
        for item in decision_visible
        if item["evidence_type"] == "EXTERNAL_EVENT" and item["facts"]["severity"] == "HIGH"
    ]
    if qualifying_external:
        recommendation = "REQUEST_BOUNDED_REVIEW"
        priority = "HIGH"
        human_review_required = True
        rationale = (
            "The frozen evaluation procedure received cutoff-eligible HIGH external evidence; "
            "request a bounded human review without executing an operational change."
        )
    else:
        recommendation = "MONITOR_EVIDENCE"
        priority = "MEDIUM"
        human_review_required = False
        rationale = (
            "The frozen evaluation procedure received no decision-visible HIGH external evidence; "
            "continue the evaluation-only evidence watch."
        )
    return {
        "variant_id": variant["variant_id"],
        "role": variant["role"],
        "capabilities": dict(variant["capabilities"]),
        "decision": {
            "decision_id": _decision_id(
                manifest["experiment_id"],
                variant["variant_id"],
                manifest["fixed_context"]["decision_procedure_version"],
            ),
            "recommendation": recommendation,
            "priority": priority,
            "human_review_required": human_review_required,
            "rationale": rationale,
            "status": "EVALUATION_PROPOSAL_ONLY",
        },
        "trace": {
            "decision_procedure_version": manifest["fixed_context"]["decision_procedure_version"],
            "capability_enabled": capability_on,
            "cutoff_eligible_evidence_ids": [item["evidence_id"] for item in cutoff_eligible],
            "decision_visible_evidence_ids": [item["evidence_id"] for item in decision_visible],
            "qualifying_external_evidence_ids": [item["evidence_id"] for item in qualifying_external],
            "authority_profile": manifest["fixed_context"]["authority_profile"],
        },
        "operational_mutations": [],
    }


def run_experiment(manifest: dict[str, Any]) -> dict[str, Any]:
    """Evaluate External Evidence access without an external read or write."""

    validate_manifest(manifest)
    cutoff_eligible = _cutoff_eligible_evidence(manifest["scenario"])
    variants = [_evaluate_variant(manifest, item, cutoff_eligible) for item in manifest["variants"]]
    baseline = next(item for item in variants if item["role"] == "BASELINE")
    challenger = next(item for item in variants if item["role"] == "CHALLENGER")
    primary_fields = manifest["hypothesis"]["primary_comparison_fields"]
    changed_fields = [
        field
        for field in primary_fields
        if baseline["decision"][field] != challenger["decision"][field]
    ]
    decision_changed = bool(changed_fields)

    cutoff_ids = [item["evidence_id"] for item in cutoff_eligible]
    all_ids = [item["evidence_id"] for item in manifest["scenario"]["evidence"]]
    post_cutoff_ids = [item for item in all_ids if item not in cutoff_ids]
    eligible_external_ids = [
        item["evidence_id"] for item in cutoff_eligible if item["evidence_type"] == "EXTERNAL_EVENT"
    ]
    baseline_visible = baseline["trace"]["decision_visible_evidence_ids"]
    challenger_visible = challenger["trace"]["decision_visible_evidence_ids"]
    intended_visibility_delta = (
        all(item not in baseline_visible for item in eligible_external_ids)
        and all(item in challenger_visible for item in eligible_external_ids)
        and set(challenger_visible) - set(baseline_visible) == set(eligible_external_ids)
        and set(baseline_visible) - set(challenger_visible) == set()
    )
    no_future_leakage = all(
        evidence_id not in variant["trace"]["decision_visible_evidence_ids"]
        for evidence_id in post_cutoff_ids
        for variant in variants
    )
    mutation_free = all(not item["operational_mutations"] for item in variants)
    paired_source_snapshot = all(
        item["trace"]["cutoff_eligible_evidence_ids"] == cutoff_ids for item in variants
    )
    system_passed = (
        mutation_free
        and no_future_leakage
        and paired_source_snapshot
        and intended_visibility_delta
        and manifest["execution_boundary"]["operational_writes_allowed"] is False
    )
    attribution_passed = (
        decision_changed
        and intended_visibility_delta
        and manifest["hypothesis"]["changed_capability"] == TARGET_CAPABILITY
    )

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
            "cutoff_eligible_evidence_ids": cutoff_ids,
            "cutoff_eligible_external_evidence_ids": eligible_external_ids,
            "post_cutoff_evidence_ids": post_cutoff_ids,
        },
        "variants": variants,
        "comparison": {
            "changed_capability": TARGET_CAPABILITY,
            "decision_changed": decision_changed,
            "changed_fields": changed_fields,
            "intended_visibility_delta": intended_visibility_delta,
            "attribution": "ATTRIBUTED_TO_EXTERNAL_EVIDENCE" if attribution_passed else "NOT_ATTRIBUTED",
        },
        "evaluation_layers": {
            "system_correctness": {
                "status": "PASS" if system_passed else "FAIL",
                "read_only_boundary": mutation_free,
                "paired_source_snapshot": paired_source_snapshot,
                "intended_visibility_delta": intended_visibility_delta,
                "post_cutoff_evidence_excluded": no_future_leakage,
            },
            "capability_attribution": {
                "status": "PASS" if attribution_passed else "FAIL",
                "decision_changed": decision_changed,
                "changed_capability": TARGET_CAPABILITY,
            },
            "decision_quality": {
                "status": "NOT_EVALUATED",
                "reason": "Capability attribution does not establish that either decision is better.",
            },
            "business_outcome_effect": {
                "status": "NOT_EVALUATED",
                "outcome_evidence_class": "NOT_EVALUATED",
                "reason": "No factual or counterfactual outcome method is attached.",
            },
        },
        "operational_mutations": [],
        "claim_boundary": {
            "supported": [
                "LOCAL_HARNESS_MECHANICS",
                "EXTERNAL_EVIDENCE_CAPABILITY_ATTRIBUTION",
            ],
            "not_supported": [
                "NEW_BUSINESS_RULE",
                "DECISION_QUALITY_IMPROVEMENT",
                "BUSINESS_OUTCOME_IMPROVEMENT",
                "DEPLOYED_RUNTIME_VERIFICATION",
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
