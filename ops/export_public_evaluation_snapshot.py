"""Build and validate the aggregate-only public Evaluation snapshot."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "docs" / "decision_quality_five_review_corpus_summary_v1.json"
BUNDLE_PATH = ROOT / "blinded-review-survey" / "data" / "review-bundle.json"
RUBRIC_PATH = ROOT / "docs" / "decision_quality_rubric_v1.json"
SNAPSHOT_PATH = ROOT / "offline" / "data" / "evaluation-snapshot.json"
SOURCE_VALIDATOR_PATH = ROOT / "ops" / "validate_decision_quality_adjudication.py"

SCHEMA_VERSION = "public-evaluation-snapshot.v1"
SOURCE_CONTRACT = "decision-quality-five-review-corpus-summary.v1"
EVIDENCE_CLASS = "HYBRID_HISTORICAL_REPLAY"
EXPECTED_SUPPORTS = ["FIVE_REVIEW_CONTROLLED_POINT_IN_TIME_DECISION_QUALITY"]
EXPECTED_EXCLUSIONS = [
    "INDIVIDUAL_REVIEW_DISCLOSURE",
    "BUSINESS_OUTCOME_EFFECT",
    "REAL_LOGISTICS_PERFORMANCE",
    "A303_REACTIVATION",
    "MODEL_PROMOTION",
    "PRODUCTION_READINESS",
    "OPERATIONAL_AUTHORITY",
]
PROTECTED_KEYS = {
    "review_id",
    "package_digest",
    "bundle_id",
    "bundle_digest",
    "aggregate_artifact_digest",
    "source_collections",
    "record_digest",
    "scenario_id",
    "cutoff_id",
    "cutoff_at",
    "score_delta",
    "favored_variant_id",
    "submitted_at",
}
SAFE_COMPARISON_LABELS = {
    "T1_COROMANDEL_HIGHWAY_CLOSURES_CONFIRMED": "T1",
    "T2_NORTHLAND_NETWORK_ISOLATION_CONFIRMED": "T2",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_source_validator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "public_evaluation_source_validator", SOURCE_VALIDATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the Decision Quality source validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _protected_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in PROTECTED_KEYS:
                found.add(key)
            found.update(_protected_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_protected_keys(child))
    return found


def build_public_snapshot(
    source: dict[str, Any], bundle: dict[str, Any], rubric: dict[str, Any]
) -> dict[str, Any]:
    source_errors = _load_source_validator().validate_corpus_summary(
        source, bundle, rubric
    )
    if source_errors:
        raise ValueError("source corpus is invalid: " + "; ".join(source_errors))

    packages = bundle.get("packages", [])
    scenario_ids = {
        package.get("scenario", {}).get("scenario_id") for package in packages
    }
    if None in scenario_ids:
        raise ValueError("a frozen review package has no scenario identity")
    if {
        package.get("scenario", {}).get("evidence_classification")
        for package in packages
    } != {EVIDENCE_CLASS}:
        raise ValueError("the frozen corpus contains an unsupported evidence class")

    source_evidence = source["source_evidence"]
    result = source["corpus_result"]
    comparisons = []
    for item in source["non_control_no_winner_packages"]:
        cutoff_label = SAFE_COMPARISON_LABELS.get(item.get("cutoff_id"))
        if cutoff_label is None:
            raise ValueError("a non-control no-winner comparison has no safe label")
        comparisons.append(
            {
                "case_label": "Cyclone Gabrielle",
                "cutoff_label": cutoff_label,
                "baseline_preference_count": item["baseline_preference_count"],
                "challenger_preference_count": item["challenger_preference_count"],
                "preference_consensus_pct": item["preference_consensus_pct"],
                "result": item["result"],
            }
        )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "status": "available",
        "evaluation_as_of_date": source["created_on_sydney_date"],
        "source_contract": SOURCE_CONTRACT,
        "evidence_class": EVIDENCE_CLASS,
        "corpus": {
            "case_count": len(scenario_ids),
            "cutoff_count": source_evidence["package_count"],
            "complete_review_count": source_evidence["reviewer_count"],
            "minimum_review_count": 3,
            "locked_review_record_count": source_evidence["review_record_count"],
        },
        "decision_quality": {
            "status": "MIXED",
            "favors_a303_on_count": result[
                "review_evidence_favors_variant_count"
            ],
            "no_winner_count": result["reviewers_do_not_agree_count"],
            "unanimous_control_tie_count": result["unanimous_control_tie_count"],
            "minimum_preference_consensus_pct": rubric["interpretation_gate"][
                "minimum_preference_consensus_pct"
            ],
            "non_control_no_winner_comparisons": comparisons,
        },
        "privacy": {
            "reviewer_identifiers_retained": False,
            "credentials_retained": False,
            "answer_content_retained": False,
            "notes_retained": False,
            "private_source_artifacts_retained": False,
        },
        "claim_boundary": {
            "supports": EXPECTED_SUPPORTS,
            "does_not_support": EXPECTED_EXCLUSIONS,
        },
        "authority": {
            "publication_authority_from_snapshot": False,
            "aws_write_allowed": False,
            "review_mutation_allowed": False,
            "action_mutation_allowed": False,
            "policy_activation_allowed": False,
            "model_promotion_allowed": False,
            "production_effect": False,
        },
    }
    errors = validate_public_snapshot(snapshot)
    if errors:
        raise ValueError("generated public snapshot is invalid: " + "; ".join(errors))
    return snapshot


def validate_public_snapshot(
    snapshot: dict[str, Any], today: date | None = None
) -> list[str]:
    errors: list[str] = []
    current_date = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    expected_root = {
        "schema_version",
        "status",
        "evaluation_as_of_date",
        "source_contract",
        "evidence_class",
        "corpus",
        "decision_quality",
        "privacy",
        "claim_boundary",
        "authority",
    }
    if set(snapshot) != expected_root:
        errors.append("public Evaluation snapshot shape has drifted")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported public Evaluation snapshot schema")
    if snapshot.get("status") != "available":
        errors.append("public Evaluation snapshot status must be available")
    try:
        as_of_date = date.fromisoformat(str(snapshot.get("evaluation_as_of_date")))
        if as_of_date > current_date:
            errors.append("public Evaluation snapshot cannot be future-dated")
    except ValueError:
        errors.append("evaluation_as_of_date must use YYYY-MM-DD")
    if snapshot.get("source_contract") != SOURCE_CONTRACT:
        errors.append("public Evaluation source contract has drifted")
    if snapshot.get("evidence_class") != EVIDENCE_CLASS:
        errors.append("public Evaluation evidence class has drifted")

    corpus = snapshot.get("corpus", {})
    required_corpus = {
        "case_count",
        "cutoff_count",
        "complete_review_count",
        "minimum_review_count",
        "locked_review_record_count",
    }
    if set(corpus) != required_corpus or not all(
        type(corpus.get(key)) is int and corpus[key] > 0 for key in required_corpus
    ):
        errors.append("public Evaluation corpus counts are incomplete")
    elif (
        corpus["complete_review_count"] < corpus["minimum_review_count"]
        or corpus["locked_review_record_count"]
        != corpus["cutoff_count"] * corpus["complete_review_count"]
    ):
        errors.append("public Evaluation corpus counts do not reconcile")

    quality = snapshot.get("decision_quality", {})
    required_quality = {
        "status",
        "favors_a303_on_count",
        "no_winner_count",
        "unanimous_control_tie_count",
        "minimum_preference_consensus_pct",
        "non_control_no_winner_comparisons",
    }
    if set(quality) != required_quality or quality.get("status") != "MIXED":
        errors.append("public Decision Quality result is incomplete")
    else:
        numeric_counts = (
            quality.get("favors_a303_on_count"),
            quality.get("no_winner_count"),
            quality.get("unanimous_control_tie_count"),
        )
        if not all(type(value) is int and value >= 0 for value in numeric_counts):
            errors.append("public Decision Quality counts must be non-negative integers")
        elif (
            quality["favors_a303_on_count"] + quality["no_winner_count"]
            != corpus.get("cutoff_count")
            or quality["unanimous_control_tie_count"] > quality["no_winner_count"]
        ):
            errors.append("public Decision Quality counts do not reconcile")

        gate = quality.get("minimum_preference_consensus_pct")
        if type(gate) not in (int, float) or not 0 < gate <= 100:
            errors.append("public preference consensus gate is invalid")

        comparisons = quality.get("non_control_no_winner_comparisons")
        if not isinstance(comparisons, list) or len(comparisons) != 2:
            errors.append("public no-winner comparisons must contain T1 and T2")
        else:
            labels = {item.get("cutoff_label") for item in comparisons}
            expected_keys = {
                "case_label",
                "cutoff_label",
                "baseline_preference_count",
                "challenger_preference_count",
                "preference_consensus_pct",
                "result",
            }
            if labels != {"T1", "T2"}:
                errors.append("public no-winner labels have drifted")
            if (
                quality.get("unanimous_control_tie_count") + len(comparisons)
                != quality.get("no_winner_count")
            ):
                errors.append("public no-winner comparisons do not reconcile")
            for item in comparisons:
                if (
                    not isinstance(item, dict)
                    or set(item) != expected_keys
                    or item.get("case_label") != "Cyclone Gabrielle"
                ):
                    errors.append("public no-winner comparison shape has drifted")
                    continue
                baseline = item.get("baseline_preference_count")
                challenger = item.get("challenger_preference_count")
                consensus = item.get("preference_consensus_pct")
                if (
                    item.get("result") != "REVIEWERS_DO_NOT_AGREE"
                    or type(baseline) is not int
                    or type(challenger) is not int
                    or baseline < 0
                    or challenger < 0
                    or baseline + challenger
                    != corpus.get("complete_review_count")
                    or type(consensus) not in (int, float)
                    or not 0 <= consensus < gate
                ):
                    errors.append("public no-winner comparison no longer fails the gate")

    expected_privacy = {
        "reviewer_identifiers_retained": False,
        "credentials_retained": False,
        "answer_content_retained": False,
        "notes_retained": False,
        "private_source_artifacts_retained": False,
    }
    if snapshot.get("privacy") != expected_privacy:
        errors.append("public Evaluation privacy boundary has expanded")
    if snapshot.get("claim_boundary") != {
        "supports": EXPECTED_SUPPORTS,
        "does_not_support": EXPECTED_EXCLUSIONS,
    }:
        errors.append("public Evaluation claim boundary has expanded")
    expected_authority = {
        "publication_authority_from_snapshot": False,
        "aws_write_allowed": False,
        "review_mutation_allowed": False,
        "action_mutation_allowed": False,
        "policy_activation_allowed": False,
        "model_promotion_allowed": False,
        "production_effect": False,
    }
    if snapshot.get("authority") != expected_authority:
        errors.append("public Evaluation snapshot has gained authority")
    protected = _protected_keys(snapshot)
    if protected:
        errors.append("protected source fields reached the public snapshot: " + ", ".join(sorted(protected)))
    return errors


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="replace the tracked public snapshot after all source checks pass",
    )
    args = parser.parse_args()
    snapshot = build_public_snapshot(
        load_json(SOURCE_PATH), load_json(BUNDLE_PATH), load_json(RUBRIC_PATH)
    )
    rendered = canonical_json(snapshot)
    if args.write:
        SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")
        print(f"WROTE: {SNAPSHOT_PATH.relative_to(ROOT)}")
        return 0
    if not SNAPSHOT_PATH.is_file():
        print("INVALID: tracked public Evaluation snapshot is missing")
        return 1
    tracked = SNAPSHOT_PATH.read_text(encoding="utf-8")
    if tracked != rendered:
        print("INVALID: tracked public Evaluation snapshot differs from validated source projection")
        return 1
    print("PASS: public Evaluation snapshot is aggregate-only, source-bound, and current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
