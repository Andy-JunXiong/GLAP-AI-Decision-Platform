"""Build blinded decision-review packages and aggregate independent reviews."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


RUBRIC_VERSION = "decision-quality-rubric.v1"
PACKAGE_VERSION = "decision-review-package.v1"
KEY_VERSION = "decision-review-blind-key.v1"
PACKAGE_KEY_VERSIONS = {
    PACKAGE_VERSION: KEY_VERSION,
    "decision-review-package.v2": "decision-review-blind-key.v2",
    "decision-review-package.v3": "decision-review-blind-key.v3",
}
REVIEW_VERSION = "decision-quality-review.v1"
SUMMARY_VERSION = "decision-quality-summary.v1"


class ReviewContractError(ValueError):
    """Raised when blinding, review independence, or scoring contracts drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewContractError(message)


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReviewContractError(f"{field} must include a UTC offset")
    return parsed


def _canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _package_payload(package: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in package.items() if key != "package_digest"}


def load_default_rubric(root: Path | None = None) -> dict[str, Any]:
    repository_root = root or Path(__file__).resolve().parents[1]
    path = repository_root / "docs" / "decision_quality_rubric_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_rubric(rubric: dict[str, Any]) -> None:
    _require(rubric.get("schema_version") == RUBRIC_VERSION, "unsupported rubric version")
    _require(rubric.get("score_min") == 0 and rubric.get("score_max") == 4, "v1 scores must range from 0 to 4")
    dimensions = rubric.get("dimensions")
    _require(isinstance(dimensions, list) and bool(dimensions), "rubric dimensions are required")
    ids = [item.get("id") for item in dimensions]
    _require(all(isinstance(item, str) and item for item in ids), "every dimension needs an id")
    _require(len(ids) == len(set(ids)), "rubric dimension IDs must be unique")
    weights = [item.get("weight") for item in dimensions]
    _require(all(isinstance(item, (int, float)) and item > 0 for item in weights), "rubric weights must be positive")
    _require(abs(sum(weights) - 1.0) < 1e-9, "rubric weights must sum to 1.0")
    for item in dimensions:
        anchors = item.get("anchors", {})
        _require(set(anchors) == {"0", "1", "2", "3", "4"}, f"{item['id']} must define all score anchors")
    gate = rubric.get("interpretation_gate", {})
    _require(gate.get("minimum_independent_reviewers", 0) >= 3, "at least three reviewers are required")
    _require(gate.get("minimum_non_tie_preferences", 0) >= 2, "at least two non-tie preferences are required")
    _require(50 < gate.get("minimum_preference_consensus_pct", 0) <= 100, "preference consensus threshold is invalid")
    _require(gate.get("minimum_mean_score_delta", -1) >= 0, "score delta threshold is invalid")


def build_review_package(
    manifest: dict[str, Any], report: dict[str, Any], rubric: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a reviewer-safe package and a separately held deblinding key."""

    validate_rubric(rubric)
    _require(manifest.get("schema_version") == "evaluation-experiment.v1", "unsupported experiment manifest")
    _require(report.get("schema_version") == "evaluation-report.v1", "unsupported evaluation report")
    _require(report.get("experiment_id") == manifest.get("experiment_id"), "manifest/report experiment mismatch")
    _require(report.get("scenario_id") == manifest.get("scenario", {}).get("scenario_id"), "manifest/report scenario mismatch")
    _require(report.get("cutoff_at") == manifest.get("scenario", {}).get("cutoff_at"), "manifest/report cutoff mismatch")
    _require(report.get("evidence_classification") == manifest.get("scenario", {}).get("evidence_classification"), "manifest/report evidence classification mismatch")
    _require(report.get("fixed_context") == manifest.get("fixed_context"), "manifest/report fixed context mismatch")
    boundary = report.get("execution_boundary", {})
    _require(
        boundary.get("mode") == "LOCAL_READ_ONLY"
        and boundary.get("network_access_allowed") is False
        and boundary.get("operational_writes_allowed") is False
        and boundary.get("production_effect") is False,
        "report execution boundary is not local read-only",
    )
    _require(report.get("operational_mutations") == [], "report contains an operational mutation")
    _require(all(item.get("operational_mutations") == [] for item in report.get("variants", [])), "variant contains an operational mutation")
    _require(report.get("evaluation_layers", {}).get("system_correctness", {}).get("status") == "PASS", "system correctness must pass before review")
    _require(report.get("evaluation_layers", {}).get("capability_attribution", {}).get("status") == "PASS", "capability attribution must pass before review")

    visible_ids = report.get("evidence_window", {}).get("visible_evidence_ids", [])
    evidence_by_id = {
        item["evidence_id"]: item for item in manifest.get("scenario", {}).get("evidence", [])
    }
    _require(set(visible_ids) <= set(evidence_by_id), "report references unknown evidence")
    cutoff = _timestamp(report["cutoff_at"], "report.cutoff_at")
    _require(
        all(
            _timestamp(evidence_by_id[evidence_id]["available_at"], f"{evidence_id}.available_at") <= cutoff
            for evidence_id in visible_ids
        ),
        "review package cannot include post-cutoff evidence",
    )
    manifest_variants = {
        item["variant_id"]: item["capabilities"] for item in manifest.get("variants", [])
    }
    report_variants = {
        item.get("variant_id"): item.get("capabilities") for item in report.get("variants", [])
    }
    _require(report_variants == manifest_variants, "manifest/report variant mismatch")
    visible_evidence: list[dict[str, Any]] = []
    evidence_mapping: dict[str, str] = {}
    for index, evidence_id in enumerate(visible_ids):
        blind_evidence_id = f"EVIDENCE_{index + 1}"
        source = evidence_by_id[evidence_id]
        facts = dict(source["facts"])
        if facts.get("signal_type") == "A303_HIGH_RISK_ROUTE":
            facts["signal_type"] = "HIGH_RISK_ROUTE"
        visible_evidence.append({
            "evidence_id": blind_evidence_id,
            "evidence_type": source["evidence_type"],
            "event_time": source["event_time"],
            "published_at": source["published_at"],
            "available_at": source["available_at"],
            "revision_version": source["revision_version"],
            "facts": facts,
        })
        evidence_mapping[blind_evidence_id] = evidence_id
    variants = report.get("variants", [])
    _require(len(variants) == 2, "v1 review requires exactly two variants")
    review_id = hashlib.sha256(
        f"{report['experiment_id']}|{report['scenario_id']}|{RUBRIC_VERSION}".encode("utf-8")
    ).hexdigest()[:24]
    seed = manifest.get("fixed_context", {}).get("random_seed")
    _require(isinstance(seed, int), "manifest random seed is required")
    ordered = sorted(
        variants,
        key=lambda item: hashlib.sha256(
            f"{seed}|{review_id}|{item['variant_id']}".encode("utf-8")
        ).hexdigest(),
    )

    options: list[dict[str, Any]] = []
    mapping: dict[str, Any] = {}
    for index, variant in enumerate(ordered):
        option_id = f"OPTION_{chr(ord('A') + index)}"
        decision = variant["decision"]
        options.append({
            "option_id": option_id,
            "recommendation": decision["recommendation"],
            "priority": decision["priority"],
            "human_review_required": decision["human_review_required"],
            "rationale": decision["review_rationale"],
            "status": "EVALUATION_PROPOSAL_ONLY",
        })
        mapping[option_id] = {
            "variant_id": variant["variant_id"],
            "role": variant["role"],
            "capabilities": variant["capabilities"],
        }

    package_payload = {
        "schema_version": PACKAGE_VERSION,
        "review_id": review_id,
        "rubric_version": RUBRIC_VERSION,
        "scenario": {
            "scenario_id": report["scenario_id"],
            "scenario_mode": report["scenario_mode"],
            "cutoff_at": report["cutoff_at"],
            "evidence_classification": report["evidence_classification"],
            "operational_state": manifest["scenario"]["operational_state"],
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
            "do_not_seek_variant_identity": True,
            "do_not_infer_business_outcome": True,
        },
        "claim_boundary": {
            "evaluable": "POINT_IN_TIME_DECISION_QUALITY",
            "not_evaluable": ["BUSINESS_OUTCOME_EFFECT", "PRODUCTION_READINESS"],
        },
    }
    package_digest = _canonical_digest(package_payload)
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


def validate_review(
    review: dict[str, Any], package: dict[str, Any], rubric: dict[str, Any]
) -> None:
    _require(review.get("schema_version") == REVIEW_VERSION, "unsupported review version")
    _require(review.get("review_id") == package.get("review_id"), "review_id does not match package")
    _require(review.get("package_digest") == package.get("package_digest"), "review package digest mismatch")
    _require(review.get("rubric_version") == rubric.get("schema_version"), "review rubric version mismatch")
    reviewer_ref = review.get("reviewer_ref")
    _require(isinstance(reviewer_ref, str) and re.fullmatch(r"reviewer-[a-z0-9][a-z0-9-]{2,63}", reviewer_ref) is not None, "reviewer_ref must be pseudonymous")
    _timestamp(review.get("reviewed_at"), "reviewed_at")
    attestations = review.get("attestations", {})
    _require(attestations.get("independent_review") is True, "review must be independent")
    _require(attestations.get("conflict_of_interest") is False, "conflicted review is not eligible")
    _require(attestations.get("blind_key_access") is False, "reviewer with blind-key access is not eligible")

    expected_options = {item["option_id"] for item in package.get("options", [])}
    expected_dimensions = {item["id"] for item in rubric.get("dimensions", [])}
    rows = review.get("option_scores")
    _require(isinstance(rows, list) and len(rows) == len(expected_options), "review must score every option once")
    option_ids = [item.get("option_id") for item in rows]
    _require(set(option_ids) == expected_options and len(option_ids) == len(set(option_ids)), "review option IDs are incomplete or duplicated")
    for row in rows:
        scores = row.get("dimension_scores")
        _require(isinstance(scores, dict) and set(scores) == expected_dimensions, "review dimensions are incomplete or changed")
        for dimension, score in scores.items():
            _require(isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 4, f"{dimension} score must be an integer from 0 to 4")
    _require(review.get("preferred_option") in expected_options | {"TIE"}, "preferred option is invalid")
    confidence = review.get("confidence")
    _require(isinstance(confidence, int) and not isinstance(confidence, bool) and 1 <= confidence <= 5, "confidence must be an integer from 1 to 5")
    notes = review.get("review_notes", "")
    _require(isinstance(notes, str) and len(notes) <= 1000, "review_notes must be at most 1000 characters")


def score_reviews(
    package: dict[str, Any], blind_key: dict[str, Any], rubric: dict[str, Any], reviews: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aggregate blinded reviews, then expose only de-identified results."""

    validate_rubric(rubric)
    package_version = package.get("schema_version")
    _require(package_version in PACKAGE_KEY_VERSIONS, "unsupported review package")
    _require(package.get("rubric_version") == rubric.get("schema_version"), "package rubric mismatch")
    _require(package.get("package_digest") == _canonical_digest(_package_payload(package)), "review package was modified")
    _require(
        blind_key.get("schema_version") == PACKAGE_KEY_VERSIONS[package_version],
        "unsupported blind key",
    )
    _require(blind_key.get("review_id") == package.get("review_id"), "blind key review mismatch")
    _require(blind_key.get("package_digest") == package.get("package_digest"), "blind key package mismatch")
    option_ids = {item["option_id"] for item in package.get("options", [])}
    _require(set(blind_key.get("mapping", {})) == option_ids, "blind key option mapping mismatch")

    reviewer_refs: list[str] = []
    for review in reviews:
        validate_review(review, package, rubric)
        reviewer_refs.append(review["reviewer_ref"])
    _require(len(reviewer_refs) == len(set(reviewer_refs)), "duplicate reviewer_ref is not allowed")

    weights = {item["id"]: item["weight"] for item in rubric["dimensions"]}
    option_review_scores: dict[str, list[float]] = {option_id: [] for option_id in option_ids}
    preference_counts = {option_id: 0 for option_id in option_ids}
    tie_count = 0
    for review in reviews:
        for row in review["option_scores"]:
            normalized = sum(
                row["dimension_scores"][dimension] / 4.0 * weight * 100.0
                for dimension, weight in weights.items()
            )
            option_review_scores[row["option_id"]].append(normalized)
        if review["preferred_option"] == "TIE":
            tie_count += 1
        else:
            preference_counts[review["preferred_option"]] += 1

    option_means = {
        option_id: round(sum(scores) / len(scores), 2) if scores else None
        for option_id, scores in option_review_scores.items()
    }
    non_tie_preferences = sum(preference_counts.values())
    preference_winner = (
        max(sorted(preference_counts), key=preference_counts.get)
        if non_tie_preferences
        else None
    )
    consensus_pct = round(
        100.0 * max(preference_counts.values()) / non_tie_preferences, 2
    ) if non_tie_preferences else 0.0
    scored_options = [item for item, score in option_means.items() if score is not None]
    score_winner = max(sorted(scored_options), key=option_means.get) if scored_options else None
    score_values = sorted((score for score in option_means.values() if score is not None), reverse=True)
    score_delta = round(score_values[0] - score_values[1], 2) if len(score_values) == 2 else None

    gate = rubric["interpretation_gate"]
    enough_reviewers = len(reviews) >= gate["minimum_independent_reviewers"]
    enough_non_tie_preferences = non_tie_preferences >= gate["minimum_non_tie_preferences"]
    enough_consensus = consensus_pct >= gate["minimum_preference_consensus_pct"]
    winners_align = preference_winner is not None and preference_winner == score_winner
    material_delta = score_delta is not None and score_delta >= gate["minimum_mean_score_delta"]
    if not enough_reviewers:
        status = "PENDING_EXPERT_REVIEWS"
        result = "INSUFFICIENT_REVIEW_EVIDENCE"
    elif not enough_non_tie_preferences or not enough_consensus or not winners_align:
        status = "REQUIRES_ADJUDICATION"
        result = "REVIEWERS_DO_NOT_AGREE"
    elif not material_delta:
        status = "EVALUATED_CONTROLLED_SYNTHETIC"
        result = "NO_MATERIAL_DECISION_QUALITY_DIFFERENCE"
    else:
        status = "EVALUATED_CONTROLLED_SYNTHETIC"
        result = "REVIEW_EVIDENCE_FAVORS_VARIANT"

    deblinded = {
        option_id: {
            **blind_key["mapping"][option_id],
            "mean_quality_score": option_means[option_id],
            "preference_count": preference_counts[option_id],
        }
        for option_id in sorted(option_ids)
    }
    favored_variant = (
        blind_key["mapping"][score_winner]["variant_id"]
        if result == "REVIEW_EVIDENCE_FAVORS_VARIANT" and score_winner
        else None
    )
    return {
        "schema_version": SUMMARY_VERSION,
        "review_id": package["review_id"],
        "package_digest": package["package_digest"],
        "evidence_classification": package["scenario"]["evidence_classification"],
        "review_count": len(reviews),
        "reviewer_identifiers_retained": False,
        "status": status,
        "result": result,
        "favored_variant_id": favored_variant,
        "score_delta": score_delta,
        "preference_consensus_pct": consensus_pct,
        "tie_count": tie_count,
        "gate_checks": {
            "minimum_reviewers_met": enough_reviewers,
            "minimum_non_tie_preferences_met": enough_non_tie_preferences,
            "preference_consensus_met": enough_consensus,
            "score_and_preference_winners_align": winners_align,
            "minimum_score_delta_met": material_delta,
        },
        "deblinded_options": deblinded,
        "claim_boundary": {
            "supports": ["CONTROLLED_POINT_IN_TIME_DECISION_QUALITY_REVIEW"] if status == "EVALUATED_CONTROLLED_SYNTHETIC" else [],
            "does_not_support": [
                "BUSINESS_OUTCOME_EFFECT",
                "REAL_LOGISTICS_PERFORMANCE",
                "MODEL_PROMOTION",
                "PRODUCTION_READINESS",
            ],
        },
        "operational_mutations": [],
    }


def _write_or_print(value: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-package")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--report", type=Path, required=True)
    build.add_argument("--rubric", type=Path)
    build.add_argument("--package-output", type=Path, required=True)
    build.add_argument("--key-output", type=Path, required=True)
    score = subparsers.add_parser("score-reviews")
    score.add_argument("--package", type=Path, required=True)
    score.add_argument("--key", type=Path, required=True)
    score.add_argument("--review", type=Path, action="append", default=[])
    score.add_argument("--rubric", type=Path)
    score.add_argument("--output", type=Path)
    return parser.parse_args()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    rubric = _load(args.rubric) if args.rubric else load_default_rubric()
    if args.command == "build-package":
        package, blind_key = build_review_package(_load(args.manifest), _load(args.report), rubric)
        _write_or_print(package, args.package_output)
        _write_or_print(blind_key, args.key_output)
        return 0
    package = _load(args.package)
    blind_key = _load(args.key)
    summary = score_reviews(package, blind_key, rubric, [_load(path) for path in args.review])
    _write_or_print(summary, args.output)
    return 0 if summary["status"] != "REQUIRES_ADJUDICATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
