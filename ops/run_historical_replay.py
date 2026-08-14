"""Validate and run a local, no-mutation historical capability replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "historical-replay-scenario.v1"
REPORT_VERSION = "historical-replay-report.v1"
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class ReplayContractError(ValueError):
    """Raised when a corpus violates evidence, time, or authority boundaries."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayContractError(message)


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    _require(set(value) == expected, f"{field} contains missing or unsupported fields")


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayContractError(f"{field} must include a UTC offset")
    return parsed


def _date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ReplayContractError(f"{field} must be an ISO date") from exc


def _digest_facts(facts: list[dict[str, Any]]) -> str:
    payload = json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_event_timezone(value: datetime, timezone_name: str, field: str) -> None:
    zone = ZoneInfo(timezone_name)
    local = value.astimezone(zone)
    _require(local.utcoffset() == value.utcoffset(), f"{field} offset does not match {timezone_name}")


def validate_corpus(corpus: dict[str, Any]) -> None:
    """Fail closed on source revision, cutoff, reveal, or authority drift."""

    _exact_keys(corpus, {
        "schema_version", "scenario_id", "title", "scenario_profile", "event_timezone",
        "glap_business_timezone", "evidence_classification", "source_policy",
        "sources", "controlled_internal_state", "cutoffs", "reveal_timeline",
        "evaluation", "authority", "claim_boundary",
    }, "corpus")
    _require(corpus.get("schema_version") == SCHEMA_VERSION, "unsupported historical replay schema")
    _require(corpus.get("glap_business_timezone") == "Australia/Sydney", "GLAP timezone must be Australia/Sydney")
    _require(corpus.get("evidence_classification") == "HYBRID_HISTORICAL_REPLAY", "historical replay must use hybrid evidence classification")
    scenario_profile = corpus.get("scenario_profile", {})
    _exact_keys(
        scenario_profile,
        {"disruption_type", "region", "transport_mode", "severity_band"},
        "scenario_profile",
    )
    _require(
        scenario_profile.get("transport_mode") in {"OCEAN", "AIR", "RAIL", "ROAD", "MULTIMODAL"},
        "scenario transport mode is invalid",
    )
    _require(scenario_profile.get("severity_band") in SEVERITY_ORDER, "scenario severity band is invalid")
    for field in ("disruption_type", "region"):
        _require(
            isinstance(scenario_profile.get(field), str) and bool(scenario_profile[field]),
            f"scenario {field} is required",
        )
    timezone_name = corpus.get("event_timezone")
    try:
        ZoneInfo(str(timezone_name))
    except Exception as exc:
        raise ReplayContractError("event_timezone is invalid") from exc

    source_policy = corpus.get("source_policy", {})
    _exact_keys(source_policy, {"availability_rule", "full_source_content_stored", "allowed_domains"}, "source_policy")
    availability_rule = source_policy.get("availability_rule")
    _require(
        availability_rule in {"DATE_ONLY_CONSERVATIVE_NEXT_DAY", "EXACT_SOURCE_TIMESTAMP"},
        "unsupported source availability rule",
    )
    _require(source_policy.get("full_source_content_stored") is False, "full source content cannot be stored")
    allowed_domains = source_policy.get("allowed_domains")
    _require(isinstance(allowed_domains, list) and bool(allowed_domains), "allowed source domains are required")

    sources = corpus.get("sources")
    _require(isinstance(sources, list) and len(sources) >= 3, "at least three authoritative sources are required")
    _require(all(isinstance(item, dict) for item in sources), "every source must be an object")
    source_ids = [item.get("source_id") for item in sources]
    _require(all(isinstance(item, str) and item for item in source_ids), "every source needs an ID")
    _require(len(source_ids) == len(set(source_ids)), "source IDs must be unique")
    fact_ids: list[str] = []
    sources_by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_id = source["source_id"]
        _exact_keys(source, {
            "source_id", "publisher", "source_type", "url", "publication_precision",
            "published_at", "latest_content_date", "available_at", "retrieved_at",
            "revision_label", "extracted_facts", "content_digest",
        }, source_id)
        sources_by_id[source_id] = source
        _require(source.get("source_type") == "AUTHORITATIVE_PUBLIC_SOURCE", f"{source_id} is not authoritative")
        parsed_url = urlparse(str(source.get("url", "")))
        _require(parsed_url.scheme == "https" and parsed_url.hostname in allowed_domains, f"{source_id} uses an unapproved source domain")
        publication_precision = source.get("publication_precision")
        expected_precision = (
            "DATE_ONLY_CONSERVATIVE_NEXT_DAY"
            if availability_rule == "DATE_ONLY_CONSERVATIVE_NEXT_DAY"
            else "EXACT_TIMESTAMP"
        )
        _require(publication_precision == expected_precision, f"{source_id} has unsupported time precision")
        published = _timestamp(source.get("published_at"), f"{source_id}.published_at")
        available = _timestamp(source.get("available_at"), f"{source_id}.available_at")
        retrieved = _timestamp(source.get("retrieved_at"), f"{source_id}.retrieved_at")
        _assert_event_timezone(published, str(timezone_name), f"{source_id}.published_at")
        _assert_event_timezone(available, str(timezone_name), f"{source_id}.available_at")
        latest_content_date = _date(source.get("latest_content_date"), f"{source_id}.latest_content_date")
        _require(latest_content_date >= published.date(), f"{source_id} latest content date precedes publication")
        if publication_precision == "DATE_ONLY_CONSERVATIVE_NEXT_DAY":
            _require(published.time().replace(tzinfo=None) == time(23, 59, 59), f"{source_id} date-only publication must use 23:59:59")
            expected_available = datetime.combine(
                latest_content_date + timedelta(days=1), time.min, tzinfo=published.tzinfo
            )
            _require(available == expected_available, f"{source_id} violates conservative next-day availability")
        else:
            _require(latest_content_date == published.date(), f"{source_id} exact timestamp content date must match publication")
            _require(available == published, f"{source_id} exact source timestamp must be its availability")
        _require(retrieved >= available, f"{source_id} retrieval precedes availability")
        facts = source.get("extracted_facts")
        _require(isinstance(facts, list) and bool(facts), f"{source_id} needs extracted facts")
        _require(all(isinstance(item, dict) for item in facts), f"{source_id} facts must be objects")
        _require(source.get("content_digest") == _digest_facts(facts), f"{source_id} extracted-fact digest mismatch")
        for fact in facts:
            fact_id = fact.get("fact_id")
            _exact_keys(
                fact,
                {"fact_id", "fact_type", "summary", "fact_provenance", "decision_signal"},
                f"{source_id}.fact",
            )
            _require(isinstance(fact_id, str) and fact_id, f"{source_id} contains a fact without an ID")
            fact_ids.append(fact_id)
            _require(fact.get("fact_provenance") == "HISTORICAL_PUBLIC", f"{fact_id} provenance is invalid")
            summary = fact.get("summary")
            _require(isinstance(summary, str) and 0 < len(summary) <= 500, f"{fact_id} summary length is invalid")
            signal = fact.get("decision_signal", {})
            _exact_keys(signal, {"signal_type", "severity"}, f"{fact_id}.decision_signal")
            _require(signal.get("severity") in SEVERITY_ORDER, f"{fact_id} severity is invalid")
    _require(len(fact_ids) == len(set(fact_ids)), "fact IDs must be unique")

    internal = corpus.get("controlled_internal_state", {})
    _exact_keys(
        internal,
        {"state_contract_version", "provenance", "contains_real_enterprise_data", "snapshots"},
        "controlled_internal_state",
    )
    _require(internal.get("provenance") == "CONTROLLED_SYNTHETIC", "internal state must be controlled synthetic")
    _require(internal.get("contains_real_enterprise_data") is False, "real enterprise data is not allowed in v0.1")
    snapshots = internal.get("snapshots")
    _require(isinstance(snapshots, list) and len(snapshots) >= 3, "at least three internal snapshots are required")
    _require(all(isinstance(item, dict) for item in snapshots), "every internal snapshot must be an object")
    snapshot_ids = [item.get("snapshot_id") for item in snapshots]
    _require(all(isinstance(item, str) and item for item in snapshot_ids), "every snapshot needs an ID")
    _require(len(snapshot_ids) == len(set(snapshot_ids)), "snapshot IDs must be unique")
    snapshots_by_id = {item["snapshot_id"]: item for item in snapshots}
    for snapshot in snapshots:
        _exact_keys(snapshot, {
            "snapshot_id", "as_of_at", "provenance", "shipment_scope",
            "exposed_to_disruption_node", "inventory_cover_days", "sla_criticality",
            "alternate_capacity_available",
        }, str(snapshot.get("snapshot_id")))
        _require(snapshot.get("provenance") == "CONTROLLED_SYNTHETIC", f"{snapshot['snapshot_id']} provenance is invalid")
        _require(
            str(snapshot.get("shipment_scope", "")).startswith("AGGREGATE_COHORT_"),
            f"{snapshot['snapshot_id']} shipment scope must remain aggregate",
        )
        _assert_event_timezone(
            _timestamp(snapshot.get("as_of_at"), f"{snapshot['snapshot_id']}.as_of_at"),
            str(timezone_name),
            f"{snapshot['snapshot_id']}.as_of_at",
        )

    cutoffs = corpus.get("cutoffs")
    _require(isinstance(cutoffs, list) and len(cutoffs) >= 3, "at least three cutoffs are required")
    _require(all(isinstance(item, dict) for item in cutoffs), "every cutoff must be an object")
    cutoff_ids = [item.get("cutoff_id") for item in cutoffs]
    _require(all(isinstance(item, str) and item for item in cutoff_ids), "every cutoff needs an ID")
    _require(len(cutoff_ids) == len(set(cutoff_ids)), "cutoff IDs must be unique")
    prior_cutoff: datetime | None = None
    current_sydney_date = datetime.now(ZoneInfo("Australia/Sydney")).date()
    for cutoff in cutoffs:
        cutoff_id = cutoff["cutoff_id"]
        _exact_keys(cutoff, {
            "cutoff_id", "cutoff_at", "state_snapshot_id",
            "expected_visible_source_ids", "expected_hidden_source_ids",
            "expected_a303_decision_change",
        }, cutoff_id)
        cutoff_at = _timestamp(cutoff.get("cutoff_at"), f"{cutoff_id}.cutoff_at")
        _assert_event_timezone(cutoff_at, str(timezone_name), f"{cutoff_id}.cutoff_at")
        _require(
            cutoff_at.astimezone(ZoneInfo("Australia/Sydney")).date() <= current_sydney_date,
            f"{cutoff_id} is future-dated relative to Sydney",
        )
        _require(prior_cutoff is None or cutoff_at > prior_cutoff, "cutoffs must be strictly increasing")
        prior_cutoff = cutoff_at
        snapshot_id = cutoff.get("state_snapshot_id")
        _require(snapshot_id in snapshots_by_id, f"{cutoff_id} references an unknown state snapshot")
        snapshot_at = _timestamp(snapshots_by_id[snapshot_id]["as_of_at"], f"{snapshot_id}.as_of_at")
        _require(snapshot_at == cutoff_at, f"{cutoff_id} state snapshot must be frozen at the cutoff")
        visible = {
            source_id
            for source_id, source in sources_by_id.items()
            if _timestamp(source["available_at"], f"{source_id}.available_at") <= cutoff_at
        }
        hidden = set(source_ids) - visible
        _require(set(cutoff.get("expected_visible_source_ids", [])) == visible, f"{cutoff_id} visible-source contract drift")
        _require(set(cutoff.get("expected_hidden_source_ids", [])) == hidden, f"{cutoff_id} hidden-source contract drift")

    final_cutoff = _timestamp(cutoffs[-1]["cutoff_at"], "final cutoff")
    decision_severities = [
        fact["decision_signal"]["severity"]
        for source in sources
        if _timestamp(source["available_at"], f"{source['source_id']}.available_at") <= final_cutoff
        for fact in source["extracted_facts"]
    ]
    _require(bool(decision_severities), "final cutoff must contain eligible decision evidence")
    observed_severity_band = max(decision_severities, key=lambda item: SEVERITY_ORDER[item])
    _require(
        scenario_profile["severity_band"] == observed_severity_band,
        "scenario severity band differs from final-cutoff evidence",
    )
    reveals = corpus.get("reveal_timeline")
    _require(isinstance(reveals, list) and bool(reveals), "reveal timeline is required")
    _require(all(isinstance(item, dict) for item in reveals), "every reveal must be an object")
    reveal_ids = [item.get("reveal_id") for item in reveals]
    _require(all(isinstance(item, str) and item for item in reveal_ids), "every reveal needs an ID")
    _require(len(reveal_ids) == len(set(reveal_ids)), "reveal IDs must be unique")
    for reveal in reveals:
        reveal_id = reveal["reveal_id"]
        _exact_keys(
            reveal,
            {"reveal_id", "source_id", "available_at", "outcome_evidence_class", "decision_input_allowed"},
            reveal_id,
        )
        source_id = reveal.get("source_id")
        _require(source_id in sources_by_id, f"{reveal_id} references an unknown source")
        reveal_at = _timestamp(reveal.get("available_at"), f"{reveal_id}.available_at")
        _require(reveal_at == _timestamp(sources_by_id[source_id]["available_at"], f"{source_id}.available_at"), f"{reveal_id} time differs from source")
        _require(reveal_at > final_cutoff, f"{reveal_id} is not isolated after the final decision cutoff")
        _require(reveal.get("decision_input_allowed") is False, f"{reveal_id} cannot be a decision input")
        _require(reveal.get("outcome_evidence_class") == "OBSERVED_FACTUAL", f"{reveal_id} outcome evidence class is invalid")

    evaluation = corpus.get("evaluation", {})
    _exact_keys(
        evaluation,
        {"rule_contract_version", "baseline_variant", "challenger_variant"},
        "evaluation",
    )
    _require(evaluation.get("rule_contract_version") == "A303.v1", "unsupported replay rule contract")
    authority = corpus.get("authority", {})
    _exact_keys(
        authority,
        {"profile", "network_access_allowed", "operational_writes_allowed", "production_effect"},
        "authority",
    )
    _require(authority.get("profile") == "EVALUATION_NO_MUTATION", "historical replay requires no-mutation authority")
    for field in ("network_access_allowed", "operational_writes_allowed", "production_effect"):
        _require(authority.get(field) is False, f"{field} must be false")


def _visible_sources(corpus: dict[str, Any], cutoff_at: datetime) -> list[dict[str, Any]]:
    return [
        source
        for source in corpus["sources"]
        if _timestamp(source["available_at"], f"{source['source_id']}.available_at") <= cutoff_at
    ]


def _risk_from_snapshot(snapshot: dict[str, Any], visible_sources: list[dict[str, Any]]) -> dict[str, Any]:
    signals = [
        {"source_id": source["source_id"], **fact["decision_signal"]}
        for source in visible_sources
        for fact in source["extracted_facts"]
    ]
    strongest = max(signals, key=lambda item: SEVERITY_ORDER[item["severity"]]) if signals else None
    high_route_risk = bool(
        snapshot.get("exposed_to_disruption_node")
        and strongest
        and strongest["severity"] == "HIGH"
    )
    return {
        "signal_type": "A303_HIGH_RISK_ROUTE" if high_route_risk else "NO_HIGH_ROUTE_RISK",
        "severity": "HIGH" if high_route_risk else "LOW",
        "derived_from_source_ids": sorted({item["source_id"] for item in signals}),
        "derivation": "DETERMINISTIC_PUBLIC_EVIDENCE_PLUS_CONTROLLED_SYNTHETIC_EXPOSURE",
    }


def _decision(variant_id: str, enabled: bool, risk: dict[str, Any]) -> dict[str, Any]:
    fired = enabled and risk["signal_type"] == "A303_HIGH_RISK_ROUTE"
    return {
        "variant_id": variant_id,
        "a303_enabled": enabled,
        "recommendation": "RISK_MITIGATION" if fired else "MONITOR",
        "priority": "HIGH" if fired else "MEDIUM",
        "human_review_required": fired,
        "rule_fired": fired,
        "status": "EVALUATION_PROPOSAL_ONLY",
        "operational_mutations": [],
    }


def run_replay(corpus: dict[str, Any]) -> dict[str, Any]:
    """Run paired A303 decisions at every frozen cutoff after validation."""

    validate_corpus(corpus)
    snapshots_by_id = {
        item["snapshot_id"]: item for item in corpus["controlled_internal_state"]["snapshots"]
    }
    results: list[dict[str, Any]] = []
    for cutoff in corpus["cutoffs"]:
        cutoff_at = _timestamp(cutoff["cutoff_at"], f"{cutoff['cutoff_id']}.cutoff_at")
        visible_sources = _visible_sources(corpus, cutoff_at)
        snapshot = snapshots_by_id[cutoff["state_snapshot_id"]]
        risk = _risk_from_snapshot(snapshot, visible_sources)
        baseline = _decision("baseline-a303-off", False, risk)
        challenger = _decision("glap-a303-on", True, risk)
        changed = any(
            baseline[field] != challenger[field]
            for field in ("recommendation", "priority", "human_review_required")
        )
        _require(changed is cutoff["expected_a303_decision_change"], f"{cutoff['cutoff_id']} decision-change expectation failed")
        results.append({
            "cutoff_id": cutoff["cutoff_id"],
            "cutoff_at": cutoff["cutoff_at"],
            "state_snapshot_id": cutoff["state_snapshot_id"],
            "internal_state_provenance": snapshot["provenance"],
            "visible_source_ids": [item["source_id"] for item in visible_sources],
            "visible_fact_ids": [
                fact["fact_id"] for source in visible_sources for fact in source["extracted_facts"]
            ],
            "hidden_source_ids": cutoff["expected_hidden_source_ids"],
            "derived_risk": risk,
            "variants": [baseline, challenger],
            "comparison": {
                "decision_changed": changed,
                "attribution": "ATTRIBUTED_TO_A303_HIGH_RISK_ROUTE" if changed else "NO_DECISION_DELTA_RULE_CONDITION_ABSENT",
            },
        })

    return {
        "schema_version": REPORT_VERSION,
        "scenario_id": corpus["scenario_id"],
        "scenario_profile": corpus["scenario_profile"],
        "evidence_classification": corpus["evidence_classification"],
        "source_availability_policy": corpus["source_policy"]["availability_rule"],
        "cutoff_results": results,
        "reveal_timeline": [
            {
                "reveal_id": item["reveal_id"],
                "source_id": item["source_id"],
                "available_at": item["available_at"],
                "decision_input_allowed": False,
            }
            for item in corpus["reveal_timeline"]
        ],
        "evaluation_layers": {
            "system_correctness": {
                "status": "PASS",
                "source_digests_verified": True,
                "cutoff_visibility_verified": True,
                "reveal_isolation_verified": True,
                "controlled_internal_state_verified": True,
                "no_mutation_authority_verified": True,
            },
            "capability_attribution": {
                "status": "PASS",
                "attributed_cutoff_ids": [
                    item["cutoff_id"] for item in results if item["comparison"]["decision_changed"]
                ],
                "no_delta_cutoff_ids": [
                    item["cutoff_id"] for item in results if not item["comparison"]["decision_changed"]
                ],
            },
            "decision_quality": {
                "status": "NOT_EVALUATED",
                "rubric_version": "decision-quality-rubric.v1",
                "reason": "No independent blinded expert reviews are attached.",
            },
            "business_outcome_effect": {
                "status": "NOT_EVALUATED",
                "reason": "Factual reveals do not identify the counterfactual result of an unchosen action.",
            },
        },
        "claim_boundary": corpus["claim_boundary"],
        "operational_mutations": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    report = run_replay(corpus)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
