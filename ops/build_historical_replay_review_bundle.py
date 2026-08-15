"""Build frozen, blinded review packages for the Historical Replay corpus."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ROOT = Path(__file__).resolve().parents[1]
_CORPUS = _load_module(
    "glap_historical_replay_corpus_for_review",
    Path(__file__).with_name("run_historical_replay_corpus.py"),
)
_QUALITY = _load_module(
    "glap_decision_quality_for_historical_review",
    Path(__file__).with_name("evaluate_decision_quality.py"),
)

FREEZE_VERSION = "historical-replay-review-freeze.v3"
BUNDLE_VERSION = "historical-replay-review-bundle.v3"
KEY_BUNDLE_VERSION = "historical-replay-review-key-bundle.v3"
PACKAGE_VERSION = "decision-review-package.v3"
KEY_VERSION = "decision-review-blind-key.v3"
OPTION_CONTRACT_VERSION = "decision-option-contract.v3"
REVIEW_SCOPE = "ALL_FROZEN_CUTOFFS"
FREEZE_SUPPORTS = [
    "FROZEN_CORPUS_RUBRIC_AND_OPTION_CONTRACT_INPUTS",
    "DETERMINISTIC_BLINDED_REVIEW_HANDOFF",
]
FREEZE_DOES_NOT_SUPPORT = [
    "INDEPENDENT_REVIEW_COMPLETION",
    "DECISION_QUALITY_RESULT",
    "BUSINESS_OUTCOME_EFFECT",
    "PRODUCTION_READINESS",
]


class HistoricalReviewContractError(ValueError):
    """Raised when frozen review inputs or blinding boundaries drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HistoricalReviewContractError(message)


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    _require(set(value) == expected, f"{field} contains missing or unsupported fields")


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoricalReviewContractError(f"{field} must be an ISO-8601 timestamp") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{field} needs a UTC offset")
    return parsed


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_freeze(
    freeze: dict[str, Any],
    corpus_manifest: dict[str, Any],
    scenario_directory: Path,
    rubric: dict[str, Any],
    decision_option_contract: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate that the freeze binds the exact corpus, scenarios, and rubric."""

    _exact_keys(
        freeze,
        {
            "schema_version", "freeze_id", "frozen_at", "corpus_id",
            "corpus_manifest_digest", "rubric_version", "rubric_digest",
            "decision_option_contract_version", "decision_option_contract_digest",
            "review_scope", "scenario_count", "cutoff_count", "scenarios",
            "authority", "claim_boundary",
        },
        "review freeze",
    )
    _require(freeze.get("schema_version") == FREEZE_VERSION, "unsupported review freeze version")
    _require(isinstance(freeze.get("freeze_id"), str) and freeze["freeze_id"], "freeze_id is required")
    _timestamp(freeze.get("frozen_at"), "frozen_at")
    _require(freeze.get("review_scope") == REVIEW_SCOPE, "review scope must cover all frozen cutoffs")
    _require(freeze.get("corpus_id") == corpus_manifest.get("corpus_id"), "freeze corpus_id mismatch")
    _require(
        freeze.get("corpus_manifest_digest") == canonical_digest(corpus_manifest),
        "frozen corpus manifest digest mismatch",
    )
    _QUALITY.validate_rubric(rubric)
    _require(freeze.get("rubric_version") == rubric.get("schema_version"), "freeze rubric version mismatch")
    _require(freeze.get("rubric_digest") == canonical_digest(rubric), "frozen rubric digest mismatch")
    _require(
        decision_option_contract.get("schema_version") == OPTION_CONTRACT_VERSION,
        "unsupported decision option contract",
    )
    _require(
        freeze.get("decision_option_contract_version") == OPTION_CONTRACT_VERSION,
        "freeze decision option contract version mismatch",
    )
    _require(
        freeze.get("decision_option_contract_digest") == canonical_digest(decision_option_contract),
        "frozen decision option contract digest mismatch",
    )

    frozen_entries = freeze.get("scenarios")
    _require(isinstance(frozen_entries, list) and bool(frozen_entries), "frozen scenarios are required")
    manifest_entries = corpus_manifest.get("scenarios", [])
    _require(len(frozen_entries) == len(manifest_entries), "frozen scenario membership count mismatch")
    scenarios: list[dict[str, Any]] = []
    for index, (frozen, manifest_entry) in enumerate(zip(frozen_entries, manifest_entries)):
        _exact_keys(frozen, {"scenario_id", "file", "scenario_digest"}, f"frozen scenario {index}")
        _require(
            frozen.get("scenario_id") == manifest_entry.get("scenario_id")
            and frozen.get("file") == manifest_entry.get("file"),
            "frozen scenario membership or order mismatch",
        )
        path = scenario_directory / manifest_entry["file"]
        _require(path.is_file(), f"frozen scenario file is missing: {manifest_entry['file']}")
        scenario = _load(path)
        _require(
            frozen.get("scenario_digest") == canonical_digest(scenario),
            f"frozen scenario digest mismatch: {manifest_entry['file']}",
        )
        scenarios.append(scenario)

    report = _CORPUS.run_corpus(corpus_manifest, scenario_directory)
    summary = report["summary"]
    _require(freeze.get("scenario_count") == summary["scenario_count"], "frozen scenario count mismatch")
    _require(freeze.get("cutoff_count") == summary["cutoff_count"], "frozen cutoff count mismatch")
    authority = freeze.get("authority", {})
    _exact_keys(
        authority,
        {"profile", "network_access_allowed", "operational_writes_allowed", "production_effect"},
        "freeze authority",
    )
    _require(authority.get("profile") == "EVALUATION_NO_MUTATION", "freeze requires no-mutation authority")
    for field in ("network_access_allowed", "operational_writes_allowed", "production_effect"):
        _require(authority.get(field) is False, f"freeze {field} must be false")
    claim_boundary = freeze.get("claim_boundary", {})
    _exact_keys(claim_boundary, {"supports", "does_not_support"}, "freeze claim boundary")
    _require(
        claim_boundary.get("supports") == FREEZE_SUPPORTS,
        "freeze supported claims differ from the v1 boundary",
    )
    _require(
        claim_boundary.get("does_not_support") == FREEZE_DOES_NOT_SUPPORT,
        "freeze excluded claims differ from the v1 boundary",
    )
    return report, scenarios


def _review_rationale(decision: dict[str, Any]) -> str:
    if decision["recommendation"] == "RISK_MITIGATION":
        return "Propose bounded risk mitigation for human review using only the supplied cutoff evidence."
    return "Continue monitoring and re-check at the next governed review point."


def _blinded_decision_content(
    decision: dict[str, Any],
    evidence_mapping: dict[str, Any],
) -> dict[str, Any]:
    content = decision.get("decision_content")
    _require(isinstance(content, dict), "decision content is required")
    _exact_keys(
        content,
        {
            "contract_version", "decision_basis", "risk_assessment", "action_plan",
            "problem_response", "solution_horizons", "intended_benefits",
            "tradeoffs_and_uncertainty", "authority_boundary",
        },
        "decision content",
    )
    _require(content.get("contract_version") == OPTION_CONTRACT_VERSION, "decision content contract mismatch")
    source_to_blind = {
        mapped["source_id"]: (blind_source_id, mapped["fact_mapping"])
        for blind_source_id, mapped in evidence_mapping.items()
    }
    basis = content["decision_basis"]
    citations: list[dict[str, Any]] = []
    for citation in basis["evidence_citations"]:
        source_id = citation["source_id"]
        _require(source_id in source_to_blind, "decision cites evidence outside the cutoff")
        blind_source_id, fact_mapping = source_to_blind[source_id]
        _require(set(citation["fact_ids"]) <= set(fact_mapping.values()), "decision cites an unknown fact")
        reverse_facts = {source_fact: blind_fact for blind_fact, source_fact in fact_mapping.items()}
        citations.append({
            "evidence_id": blind_source_id,
            "fact_ids": [reverse_facts[fact_id] for fact_id in citation["fact_ids"]],
            "why_relevant": citation["why_relevant"],
        })
    return {
        "contract_version": content["contract_version"],
        "decision_basis": {**basis, "evidence_citations": citations},
        "problem_response": content["problem_response"],
        "risk_assessment": content["risk_assessment"],
        "action_plan": content["action_plan"],
        "solution_horizons": content["solution_horizons"],
        "intended_benefits": content["intended_benefits"],
        "tradeoffs_and_uncertainty": content["tradeoffs_and_uncertainty"],
        "authority_boundary": content["authority_boundary"],
    }


def _scenario_brief(
    scenario: dict[str, Any],
    cutoff: dict[str, Any],
    snapshot: dict[str, Any],
    visible_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    facts = [fact for evidence in visible_evidence for fact in evidence["facts"]]
    mode = scenario["scenario_profile"]["transport_mode"].replace("_", " ").lower()
    disruption = scenario["scenario_profile"]["disruption_type"].replace("_", " ").lower()
    if facts:
        fact_summary = "; ".join(fact["summary"] for fact in facts[:2])
        story_summary = (
            f"At this point in the historical story, {len(visible_evidence)} cutoff-eligible authoritative "
            f"source(s) report: {fact_summary}"
        )
    else:
        story_summary = (
            "This is a pre-confirmation control point. The heading identifies the complete historical case, "
            "but no authoritative event fact is eligible by this cutoff; the decision begins from controlled "
            "synthetic business exposure only."
        )
    decision_pressure = (
        f"The anonymous synthetic {mode} cohort is "
        f"{'exposed' if snapshot['exposed_to_disruption_node'] else 'not exposed'} to the relevant node, "
        f"has {snapshot['inventory_cover_days']} days of inventory cover, "
        f"{snapshot['sla_criticality']} SLA criticality, and alternate capacity "
        f"{'recorded but not yet validated' if snapshot['alternate_capacity_available'] else 'not recorded'}."
    )
    difficulty_points = [
        "Separate cutoff-visible facts from the later-known complete historical story.",
        (
            f"Balance a {snapshot['inventory_cover_days']}-day synthetic inventory buffer and "
            f"{snapshot['sla_criticality']} SLA criticality against incomplete cost, lead-time, and feasibility data."
        ),
        "Compare speed and resilience against the risk of premature action, while preserving named-human authority.",
    ]
    downstream_risks = [
        (
            f"If the {disruption} reaches the synthetic cohort, delay may consume the inventory buffer and put service commitments at risk."
        ),
        "If the dependency remains unresolved, backlog, premium-cost, customer-service, and network-resilience pressure may compound over time.",
    ]
    return {
        "story_summary": story_summary,
        "decision_pressure": decision_pressure,
        "difficulty_points": difficulty_points,
        "downstream_risks": downstream_risks,
        "decision_question": (
            "Which option responds most credibly to the point-in-time problem across immediate, short-term, and long-term horizons while keeping benefits hypothetical and execution human-governed?"
        ),
        "fact_boundary": (
            f"Use only the {len(visible_evidence)} source(s) and {len(facts)} fact(s) visible at {cutoff['cutoff_at']}; "
            "later recovery and outcome facts are excluded."
        ),
    }


def _build_package(
    freeze: dict[str, Any],
    scenario: dict[str, Any],
    scenario_report: dict[str, Any],
    cutoff: dict[str, Any],
    cutoff_report: dict[str, Any],
    rubric: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    sources_by_id = {item["source_id"]: item for item in scenario["sources"]}
    snapshots_by_id = {
        item["snapshot_id"]: item
        for item in scenario["controlled_internal_state"]["snapshots"]
    }
    visible_evidence: list[dict[str, Any]] = []
    evidence_mapping: dict[str, Any] = {}
    for source_index, source_id in enumerate(cutoff_report["visible_source_ids"], start=1):
        source = sources_by_id[source_id]
        blind_source_id = f"EVIDENCE_{source_index}"
        facts: list[dict[str, Any]] = []
        fact_mapping: dict[str, str] = {}
        for fact_index, fact in enumerate(source["extracted_facts"], start=1):
            blind_fact_id = f"{blind_source_id}_FACT_{fact_index}"
            facts.append({
                "fact_id": blind_fact_id,
                "fact_type": fact["fact_type"],
                "summary": fact["summary"],
                "signal_type": fact["decision_signal"]["signal_type"].replace("A303_", ""),
                "severity": fact["decision_signal"]["severity"],
            })
            fact_mapping[blind_fact_id] = fact["fact_id"]
        visible_evidence.append({
            "evidence_id": blind_source_id,
            "evidence_type": source["source_type"],
            "published_at": source["published_at"],
            "available_at": source["available_at"],
            "revision_label": source["revision_label"],
            "facts": facts,
        })
        evidence_mapping[blind_source_id] = {
            "source_id": source_id,
            "fact_mapping": fact_mapping,
        }

    review_id = hashlib.sha256(
        (
            f"{freeze['freeze_id']}|{scenario['scenario_id']}|"
            f"{cutoff['cutoff_id']}|{rubric['schema_version']}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    variants = cutoff_report["variants"]
    _require(len(variants) == 2, "historical review requires exactly two variants")
    ordered = sorted(
        variants,
        key=lambda item: hashlib.sha256(
            f"{freeze['corpus_manifest_digest']}|{review_id}|{item['variant_id']}".encode("utf-8")
        ).hexdigest(),
    )
    options: list[dict[str, Any]] = []
    mapping: dict[str, Any] = {}
    for index, decision in enumerate(ordered):
        option_id = f"OPTION_{chr(ord('A') + index)}"
        options.append({
            "option_id": option_id,
            "recommendation": decision["recommendation"],
            "priority": decision["priority"],
            "human_review_required": decision["human_review_required"],
            "rationale": _review_rationale(decision),
            "content": _blinded_decision_content(decision, evidence_mapping),
            "status": "EVALUATION_PROPOSAL_ONLY",
        })
        mapping[option_id] = {
            "variant_id": decision["variant_id"],
            "role": "CHALLENGER" if decision["a303_enabled"] else "BASELINE",
            "capabilities": {"A303_HIGH_RISK_ROUTE": decision["a303_enabled"]},
        }

    snapshot = snapshots_by_id[cutoff["state_snapshot_id"]]
    package_payload = {
        "schema_version": PACKAGE_VERSION,
        "review_id": review_id,
        "rubric_version": rubric["schema_version"],
        "scenario": {
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_mode": "HYBRID_HISTORICAL_REPLAY",
            "cutoff_id": cutoff["cutoff_id"],
            "cutoff_at": cutoff["cutoff_at"],
            "evidence_classification": scenario_report["evidence_classification"],
            "scenario_profile": scenario_report["scenario_profile"],
            "operational_state": {
                "as_of_at": snapshot["as_of_at"],
                "state_provenance": snapshot["provenance"],
                "shipment_scope": snapshot["shipment_scope"],
                "exposed_to_disruption_node": snapshot["exposed_to_disruption_node"],
                "inventory_cover_days": snapshot["inventory_cover_days"],
                "sla_criticality": snapshot["sla_criticality"],
                "alternate_capacity_available": snapshot["alternate_capacity_available"],
            },
            "brief": _scenario_brief(scenario, cutoff, snapshot, visible_evidence),
            "visible_evidence": visible_evidence,
        },
        "decision_policy": {
            "allowed_recommendations": ["MONITOR", "RISK_MITIGATION"],
            "high_impact_action_requires_human_review": True,
            "execution_authority": "NONE_EVALUATION_PROPOSAL_ONLY",
            "outcome_claim_allowed": False,
        },
        "options": options,
        "review_instructions": {
            "score_each_option_independently": True,
            "use_only_supplied_cutoff_evidence": True,
            "do_not_seek_option_identity": True,
            "do_not_infer_business_outcome": True,
        },
        "claim_boundary": {
            "evaluable": "POINT_IN_TIME_DECISION_QUALITY",
            "not_evaluable": ["BUSINESS_OUTCOME_EFFECT", "PRODUCTION_READINESS"],
        },
    }
    package_digest = canonical_digest(package_payload)
    package = {**package_payload, "package_digest": package_digest}
    blind_key = {
        "schema_version": KEY_VERSION,
        "review_id": review_id,
        "package_digest": package_digest,
        "mapping": mapping,
        "evidence_mapping": evidence_mapping,
        "distribution": "STUDY_OWNER_ONLY_DO_NOT_SHARE_WITH_REVIEWERS",
    }
    return package, blind_key


def build_review_bundle(
    freeze: dict[str, Any],
    corpus_manifest: dict[str, Any],
    scenario_directory: Path,
    rubric: dict[str, Any],
    decision_option_contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a reviewer-safe package bundle and a separately held key bundle."""

    corpus_report, scenarios = validate_freeze(
        freeze, corpus_manifest, scenario_directory, rubric, decision_option_contract
    )
    packages: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    for scenario, scenario_report in zip(scenarios, corpus_report["scenario_reports"]):
        _require(
            scenario_report["evaluation_layers"]["system_correctness"]["status"] == "PASS",
            "system correctness must pass before review packaging",
        )
        _require(
            scenario_report["evaluation_layers"]["capability_attribution"]["status"] == "PASS",
            "capability attribution must pass before review packaging",
        )
        for cutoff, cutoff_report in zip(scenario["cutoffs"], scenario_report["cutoff_results"]):
            package, key = _build_package(
                freeze, scenario, scenario_report, cutoff, cutoff_report, rubric
            )
            packages.append(package)
            keys.append(key)

    _require(len(packages) == freeze["cutoff_count"], "review package count differs from freeze")
    bundle_id = hashlib.sha256(
        (
            f"{freeze['freeze_id']}|{freeze['corpus_manifest_digest']}|"
            f"{freeze['rubric_digest']}|{freeze['decision_option_contract_digest']}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    bundle_payload = {
        "schema_version": BUNDLE_VERSION,
        "bundle_id": bundle_id,
        "freeze_id": freeze["freeze_id"],
        "corpus_id": freeze["corpus_id"],
        "corpus_manifest_digest": freeze["corpus_manifest_digest"],
        "rubric_version": freeze["rubric_version"],
        "rubric_digest": freeze["rubric_digest"],
        "decision_option_contract_version": freeze["decision_option_contract_version"],
        "decision_option_contract_digest": freeze["decision_option_contract_digest"],
        "review_scope": REVIEW_SCOPE,
        "package_count": len(packages),
        "packages": packages,
        "distribution": "REVIEWER_SAFE_DO_NOT_DISTRIBUTE_THE_KEY_BUNDLE",
        "claim_boundary": {
            "supports": [
                "FROZEN_CORPUS_REVIEW_HANDOFF",
                "DETERMINISTIC_BLINDED_PACKAGE_GENERATION",
                "STORY_COMPLETE_RUBRIC_ASSESSABLE_OPTION_CONTENT_V3",
            ],
            "does_not_support": [
                "INDEPENDENT_REVIEW_COMPLETION",
                "DECISION_QUALITY_RESULT",
                "BUSINESS_OUTCOME_EFFECT",
                "PRODUCTION_READINESS",
            ],
        },
        "operational_mutations": [],
    }
    bundle_digest = canonical_digest(bundle_payload)
    bundle = {**bundle_payload, "bundle_digest": bundle_digest}
    key_bundle = {
        "schema_version": KEY_BUNDLE_VERSION,
        "bundle_id": bundle_id,
        "bundle_digest": bundle_digest,
        "freeze_id": freeze["freeze_id"],
        "package_count": len(keys),
        "keys": keys,
        "distribution": "STUDY_OWNER_ONLY_DO_NOT_SHARE_WITH_REVIEWERS",
        "operational_mutations": [],
    }
    return bundle, key_bundle


def _write(value: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, default=_ROOT / "docs" / "decision_quality_rubric_v1.json")
    parser.add_argument(
        "--decision-option-contract",
        type=Path,
        default=_ROOT / "docs" / "decision_option_contract_v3.json",
    )
    parser.add_argument("--bundle-output", type=Path, required=True)
    parser.add_argument("--key-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle, key_bundle = build_review_bundle(
        _load(args.freeze),
        _load(args.corpus_manifest),
        args.corpus_manifest.parent,
        _load(args.rubric),
        _load(args.decision_option_contract),
    )
    _write(bundle, args.bundle_output)
    _write(key_bundle, args.key_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
