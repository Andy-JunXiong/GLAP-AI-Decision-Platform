"""Run the frozen local-only Decision Memory capability ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "evaluation-experiment.v3"
REPORT_VERSION = "evaluation-report.v3"
TARGET_CAPABILITY = "DECISION_MEMORY"
DECISION_PROCEDURE_VERSION = "decision-memory-review.v1"
COMPARISON_FIELDS = ("recommendation", "priority", "human_review_required")
EXPERIMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
SYDNEY = ZoneInfo("Australia/Sydney")


class ContractError(ValueError):
    """Raised when an experiment would violate the v3 evaluation boundary."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    _require(set(value) == expected, f"{field} keys must be exactly {sorted(expected)}")


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        f"{field} must include a UTC offset",
    )
    return parsed


def _require_sydney_offset(value: datetime, field: str) -> None:
    _require(
        value.utcoffset() == value.astimezone(SYDNEY).utcoffset(),
        f"{field} must use the Australia/Sydney UTC offset",
    )


def _require_nonempty_string(value: object, field: str) -> None:
    _require(isinstance(value, str) and bool(value), f"{field} is required")


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
        "experiment_id must match the v3 identifier pattern",
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
            "decision_memory",
        },
        "scenario",
    )
    _require_nonempty_string(scenario.get("scenario_id"), "scenario_id")
    _require(
        scenario.get("scenario_mode") == "CONTROLLED_SYNTHETIC_REPLAY",
        "v3 supports controlled synthetic replay only",
    )
    _require(
        scenario.get("evidence_classification") == "SYNTHETIC_ENGINEERING_ONLY",
        "v3 evidence must remain synthetic engineering only",
    )
    cutoff = _timestamp(scenario.get("cutoff_at"), "scenario.cutoff_at")
    _require_sydney_offset(cutoff, "scenario.cutoff_at")
    _require(
        cutoff.astimezone(SYDNEY).date() <= datetime.now(SYDNEY).date(),
        "controlled replay cutoff cannot be later than the current Sydney date",
    )

    state = scenario.get("operational_state")
    _exact_keys(
        state,
        {"as_of_at", "shipment_scope", "context_key", "state_provenance"},
        "scenario.operational_state",
    )
    state_as_of = _timestamp(state.get("as_of_at"), "scenario.operational_state.as_of_at")
    _require_sydney_offset(state_as_of, "scenario.operational_state.as_of_at")
    _require(state_as_of <= cutoff, "operational state cannot be later than the cutoff")
    _require_nonempty_string(state.get("shipment_scope"), "shipment_scope")
    _require_nonempty_string(state.get("context_key"), "context_key")
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
                "available_at",
                "revision_version",
                "provenance",
                "facts",
            },
            field,
        )
        evidence_id = item.get("evidence_id")
        _require_nonempty_string(evidence_id, f"{field}.evidence_id")
        evidence_ids.append(evidence_id)
        _require(item.get("evidence_type") == "OPERATIONAL_SIGNAL", f"{evidence_id} has unsupported evidence_type")
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{evidence_id} has unsupported provenance")
        _require_nonempty_string(item.get("revision_version"), f"{evidence_id}.revision_version")
        _timestamp(item.get("event_time"), f"{evidence_id}.event_time")
        _timestamp(item.get("available_at"), f"{evidence_id}.available_at")
        facts = item.get("facts")
        _exact_keys(facts, {"signal_type", "severity"}, f"{evidence_id}.facts")
        _require_nonempty_string(facts.get("signal_type"), f"{evidence_id}.facts.signal_type")
        _require(facts.get("severity") in {"LOW", "MEDIUM", "HIGH"}, f"{evidence_id} has unsupported severity")
    _require(len(evidence_ids) == len(set(evidence_ids)), "evidence_id values must be unique")

    memories = scenario.get("decision_memory")
    _require(
        isinstance(memories, list) and bool(memories),
        "scenario decision_memory must be a non-empty list",
    )
    memory_ids: list[str] = []
    for index, item in enumerate(memories):
        field = f"scenario.decision_memory[{index}]"
        _exact_keys(
            item,
            {
                "memory_id",
                "decided_at",
                "available_at",
                "revision_version",
                "provenance",
                "context_key",
                "prior_recommendation",
                "review_status",
                "outcome_evidence_class",
            },
            field,
        )
        memory_id = item.get("memory_id")
        _require_nonempty_string(memory_id, f"{field}.memory_id")
        memory_ids.append(memory_id)
        decided_at = _timestamp(item.get("decided_at"), f"{memory_id}.decided_at")
        available_at = _timestamp(item.get("available_at"), f"{memory_id}.available_at")
        _require(decided_at <= available_at, f"{memory_id}.available_at cannot precede decided_at")
        _require_nonempty_string(item.get("revision_version"), f"{memory_id}.revision_version")
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{memory_id} has unsupported provenance")
        _require_nonempty_string(item.get("context_key"), f"{memory_id}.context_key")
        _require(
            item.get("prior_recommendation")
            in {"MONITOR_EVIDENCE", "REQUEST_BOUNDED_REVIEW"},
            f"{memory_id} has unsupported prior_recommendation",
        )
        _require(item.get("review_status") == "SYNTHETIC_REVIEWED", f"{memory_id} is not reviewed synthetic memory")
        _require(
            item.get("outcome_evidence_class") == "NOT_EVALUATED",
            f"{memory_id} cannot attach Outcome evidence in v3",
        )
    _require(len(memory_ids) == len(set(memory_ids)), "memory_id values must be unique")
    _require(
        any(
            item["context_key"] == state["context_key"]
            and item["prior_recommendation"] == "REQUEST_BOUNDED_REVIEW"
            and _timestamp(item["available_at"], f"{item['memory_id']}.available_at") <= cutoff
            for item in memories
        ),
        "a cutoff-eligible matching reviewed memory is required",
    )

    variants = manifest.get("variants")
    _require(isinstance(variants, list) and len(variants) == 2, "v3 requires exactly two variants")
    for index, variant in enumerate(variants):
        _exact_keys(variant, {"variant_id", "role", "capabilities"}, f"variants[{index}]")
        _exact_keys(variant.get("capabilities"), {TARGET_CAPABILITY}, f"variants[{index}].capabilities")
        _require_nonempty_string(variant.get("variant_id"), f"variants[{index}].variant_id")
        _require(
            type(variant["capabilities"].get(TARGET_CAPABILITY)) is bool,
            f"variants[{index}].capabilities.DECISION_MEMORY must be a boolean",
        )
    _require({item.get("role") for item in variants} == {"BASELINE", "CHALLENGER"}, "variants require one baseline and one challenger")
    _require(len({item["variant_id"] for item in variants}) == 2, "variant_id values must be unique")
    baseline = next(item for item in variants if item["role"] == "BASELINE")
    challenger = next(item for item in variants if item["role"] == "CHALLENGER")
    _require(baseline["capabilities"][TARGET_CAPABILITY] is False, "baseline must disable DECISION_MEMORY")
    _require(challenger["capabilities"][TARGET_CAPABILITY] is True, "challenger must enable DECISION_MEMORY")

    hypothesis = manifest.get("hypothesis")
    _exact_keys(
        hypothesis,
        {"changed_capability", "expected_decision_change", "primary_comparison_fields"},
        "hypothesis",
    )
    _require(hypothesis.get("changed_capability") == TARGET_CAPABILITY, "hypothesis capability must be DECISION_MEMORY")
    _require(hypothesis.get("expected_decision_change") is True, "v3 expects a Decision Memory delta")
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
    _require(layers.get("decision_quality") == "NOT_EVALUATED", "v3 cannot claim decision quality")
    _require(layers.get("business_outcome_effect") == "NOT_EVALUATED", "v3 cannot claim business outcome effect")


def _cutoff_eligible(items: list[dict[str, Any]], cutoff: datetime, id_field: str) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if _timestamp(item["available_at"], f"{item[id_field]}.available_at") <= cutoff
    ]


def _decision_id(experiment_id: str, variant_id: str, procedure_version: str) -> str:
    value = f"{experiment_id}|{variant_id}|{procedure_version}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def _evaluate_variant(
    manifest: dict[str, Any],
    variant: dict[str, Any],
    eligible_evidence: list[dict[str, Any]],
    eligible_memories: list[dict[str, Any]],
) -> dict[str, Any]:
    capability_on = variant["capabilities"][TARGET_CAPABILITY]
    visible_memories = eligible_memories if capability_on else []
    context_key = manifest["scenario"]["operational_state"]["context_key"]
    matching_memories = [
        item
        for item in visible_memories
        if item["context_key"] == context_key
        and item["prior_recommendation"] == "REQUEST_BOUNDED_REVIEW"
    ]
    if matching_memories:
        recommendation = "REQUEST_BOUNDED_REVIEW"
        priority = "HIGH"
        human_review_required = True
        rationale = (
            "The frozen evaluation procedure found cutoff-eligible reviewed synthetic memory "
            "for the same controlled context; request bounded human review without execution."
        )
    else:
        recommendation = "MONITOR_EVIDENCE"
        priority = "MEDIUM"
        human_review_required = False
        rationale = (
            "The frozen evaluation procedure received no decision-visible matching memory; "
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
            "fixed_evidence_ids": [item["evidence_id"] for item in eligible_evidence],
            "cutoff_eligible_memory_ids": [item["memory_id"] for item in eligible_memories],
            "decision_visible_memory_ids": [item["memory_id"] for item in visible_memories],
            "matching_memory_ids": [item["memory_id"] for item in matching_memories],
            "authority_profile": manifest["fixed_context"]["authority_profile"],
        },
        "operational_mutations": [],
    }


def run_experiment(manifest: dict[str, Any]) -> dict[str, Any]:
    """Evaluate Decision Memory access without an external read or write."""

    validate_manifest(manifest)
    scenario = manifest["scenario"]
    cutoff = _timestamp(scenario["cutoff_at"], "scenario.cutoff_at")
    eligible_evidence = _cutoff_eligible(scenario["evidence"], cutoff, "evidence_id")
    eligible_memories = _cutoff_eligible(scenario["decision_memory"], cutoff, "memory_id")
    variants = [
        _evaluate_variant(manifest, item, eligible_evidence, eligible_memories)
        for item in manifest["variants"]
    ]
    baseline = next(item for item in variants if item["role"] == "BASELINE")
    challenger = next(item for item in variants if item["role"] == "CHALLENGER")
    primary_fields = manifest["hypothesis"]["primary_comparison_fields"]
    changed_fields = [
        field
        for field in primary_fields
        if baseline["decision"][field] != challenger["decision"][field]
    ]
    decision_changed = bool(changed_fields)

    eligible_memory_ids = [item["memory_id"] for item in eligible_memories]
    all_memory_ids = [item["memory_id"] for item in scenario["decision_memory"]]
    post_cutoff_memory_ids = [item for item in all_memory_ids if item not in eligible_memory_ids]
    eligible_evidence_ids = [item["evidence_id"] for item in eligible_evidence]
    all_evidence_ids = [item["evidence_id"] for item in scenario["evidence"]]
    post_cutoff_evidence_ids = [item for item in all_evidence_ids if item not in eligible_evidence_ids]
    baseline_visible = baseline["trace"]["decision_visible_memory_ids"]
    challenger_visible = challenger["trace"]["decision_visible_memory_ids"]
    intended_visibility_delta = (
        baseline_visible == [] and challenger_visible == eligible_memory_ids
    )
    paired_source_snapshot = all(
        item["trace"]["fixed_evidence_ids"] == eligible_evidence_ids
        and item["trace"]["cutoff_eligible_memory_ids"] == eligible_memory_ids
        for item in variants
    )
    no_future_leakage = all(
        memory_id not in variant["trace"]["decision_visible_memory_ids"]
        for memory_id in post_cutoff_memory_ids
        for variant in variants
    ) and all(
        evidence_id not in variant["trace"]["fixed_evidence_ids"]
        for evidence_id in post_cutoff_evidence_ids
        for variant in variants
    )
    mutation_free = all(not item["operational_mutations"] for item in variants)
    system_passed = (
        mutation_free
        and paired_source_snapshot
        and intended_visibility_delta
        and no_future_leakage
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
        "scenario_id": scenario["scenario_id"],
        "scenario_mode": scenario["scenario_mode"],
        "cutoff_at": scenario["cutoff_at"],
        "evidence_classification": scenario["evidence_classification"],
        "execution_boundary": dict(manifest["execution_boundary"]),
        "fixed_context": dict(manifest["fixed_context"]),
        "input_window": {
            "cutoff_eligible_evidence_ids": eligible_evidence_ids,
            "post_cutoff_evidence_ids": post_cutoff_evidence_ids,
            "cutoff_eligible_memory_ids": eligible_memory_ids,
            "post_cutoff_memory_ids": post_cutoff_memory_ids,
        },
        "variants": variants,
        "comparison": {
            "changed_capability": TARGET_CAPABILITY,
            "decision_changed": decision_changed,
            "changed_fields": changed_fields,
            "intended_visibility_delta": intended_visibility_delta,
            "attribution": "ATTRIBUTED_TO_DECISION_MEMORY" if attribution_passed else "NOT_ATTRIBUTED",
        },
        "evaluation_layers": {
            "system_correctness": {
                "status": "PASS" if system_passed else "FAIL",
                "read_only_boundary": mutation_free,
                "paired_source_snapshot": paired_source_snapshot,
                "intended_visibility_delta": intended_visibility_delta,
                "post_cutoff_inputs_excluded": no_future_leakage,
            },
            "capability_attribution": {
                "status": "PASS" if attribution_passed else "FAIL",
                "decision_changed": decision_changed,
                "changed_capability": TARGET_CAPABILITY,
            },
            "decision_quality": {
                "status": "NOT_EVALUATED",
                "reason": "Using a prior reviewed decision does not establish that the new decision is better.",
            },
            "business_outcome_effect": {
                "status": "NOT_EVALUATED",
                "outcome_evidence_class": "NOT_EVALUATED",
                "reason": "Decision Memory v3 accepts no Outcome evidence or effect method.",
            },
        },
        "operational_mutations": [],
        "claim_boundary": {
            "supported": ["LOCAL_HARNESS_MECHANICS", "DECISION_MEMORY_CAPABILITY_ATTRIBUTION"],
            "not_supported": [
                "NEW_BUSINESS_RULE",
                "MEMORY_QUALITY_IMPROVEMENT",
                "AUTONOMOUS_LEARNING",
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
