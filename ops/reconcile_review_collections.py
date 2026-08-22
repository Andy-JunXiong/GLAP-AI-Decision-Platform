"""Validate and combine formal Sites and mainland Decision Quality reviews.

The output is a private, study-owner-only evidence artifact.  The reconciler
never writes either source database and never changes the frozen review bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORMAL_EXPORT_VERSION = "glap-formal-story-review-export.v1"
MAINLAND_EXPORT_VERSION = "glap-ten-story-review-export.v1"
MAINLAND_SUBMISSION_VERSION = "glap-ten-story-review-submission.v1"
MAINLAND_ANSWER_VERSION = "glap-ten-story-answer.v1"
COMBINED_VERSION = "decision-quality-combined-review-evidence.v1"
CORPUS_SUMMARY_VERSION = "decision-quality-corpus-summary.v1"
REVIEW_VERSION = "decision-quality-comparative-review.v1"
FORMAL_COLLECTION = "human-evaluation-story.v2"
MAINLAND_COLLECTION = "glap-ten-story-review.v1"
EXPECTED_DIMENSIONS = {
    "evidence_grounding",
    "risk_detection_and_proportionality",
    "policy_compliance",
    "actionability",
    "authority_compliance",
}
CHOICES = {"OPTION_A", "OPTION_B", "TIE"}


class ReviewReconciliationError(ValueError):
    """Raised when cross-entry review evidence is not safely compatible."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_QUALITY = _load_module(
    "glap_decision_quality_for_review_reconciliation",
    Path(__file__).with_name("evaluate_decision_quality.py"),
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewReconciliationError(message)


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewReconciliationError(f"{field} must be an ISO-8601 timestamp") from exc
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        f"{field} must include a UTC offset",
    )
    return parsed


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _javascript_canonical_digest(value: Any) -> str:
    """Match the display bundle generator's JSON.stringify canonical form."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _package_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _require(
        bundle.get("schema_version") == "historical-replay-review-bundle.v3",
        "only the frozen v3 review bundle is eligible",
    )
    payload = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    _require(
        bundle.get("bundle_digest") == _canonical_digest(payload),
        "frozen review bundle digest mismatch",
    )
    packages = bundle.get("packages")
    _require(
        isinstance(packages, list)
        and len(packages) == bundle.get("package_count") == 30,
        "frozen review bundle must contain exactly 30 packages",
    )
    result: dict[str, dict[str, Any]] = {}
    for package in packages:
        review_id = package.get("review_id")
        _require(isinstance(review_id, str) and review_id, "every package needs a review_id")
        _require(review_id not in result, "frozen review IDs must be unique")
        _require(
            package.get("schema_version") == "decision-review-package.v3",
            "every frozen package must use decision-review-package.v3",
        )
        _require(
            {item.get("option_id") for item in package.get("options", [])}
            == {"OPTION_A", "OPTION_B"},
            f"{review_id} does not contain the two blinded options",
        )
        result[review_id] = package
    return result


def validate_mainland_display_bundle(
    display_bundle: dict[str, Any], review_bundle: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Prove the mainland display is a lossless identity projection of v3."""

    packages = _package_map(review_bundle)
    _require(
        display_bundle.get("schema_version") == "glap-ten-story-display-bundle.v1",
        "unsupported mainland display bundle",
    )
    _require(
        display_bundle.get("source_bundle_id") == review_bundle.get("bundle_id"),
        "mainland display source bundle ID mismatch",
    )
    _require(
        display_bundle.get("source_bundle_digest") == review_bundle.get("bundle_digest"),
        "mainland display source bundle digest mismatch",
    )
    _require(
        display_bundle.get("source_package_count") == len(packages),
        "mainland display source package count mismatch",
    )
    payload = {key: value for key, value in display_bundle.items() if key != "bundle_digest"}
    _require(
        display_bundle.get("bundle_digest") == _javascript_canonical_digest(payload),
        "mainland display bundle digest mismatch",
    )
    stages: dict[str, dict[str, Any]] = {}
    for case in display_bundle.get("cases", []):
        case_id = case.get("id")
        for stage in case.get("stages", []):
            review_id = stage.get("review_id")
            _require(review_id not in stages, "mainland display review IDs must be unique")
            stages[review_id] = {
                "case_id": case_id,
                "moment": stage.get("moment"),
                "package_digest": stage.get("package_digest"),
            }
    _require(set(stages) == set(packages), "mainland display review membership differs from v3")
    for review_id, stage in stages.items():
        _require(
            stage["package_digest"] == packages[review_id].get("package_digest"),
            f"mainland display package digest mismatch for {review_id}",
        )
    return stages


def _reviewer_ref(value: object, field: str) -> str:
    reviewer_ref = str(value or "")
    _require(
        re.fullmatch(r"reviewer-[a-z0-9][a-z0-9-]{2,63}", reviewer_ref) is not None,
        f"{field} must be pseudonymous",
    )
    return reviewer_ref


def _validate_attestations(attestations: object, field: str) -> None:
    _require(isinstance(attestations, dict), f"{field} attestations are required")
    _require(attestations.get("independent") is True, f"{field} must be independent")
    _require(attestations.get("no_conflict") is True, f"{field} must have no conflict")
    _require(attestations.get("no_blind_key") is True, f"{field} must have no blind-key access")


def _normalized_review(
    answer: dict[str, Any], reviewer_ref: str, reviewed_at: str, package: dict[str, Any]
) -> dict[str, Any]:
    judgments = answer.get("judgments")
    _require(
        isinstance(judgments, dict) and set(judgments) == EXPECTED_DIMENSIONS,
        f"{reviewer_ref}/{answer.get('review_id')} has changed review dimensions",
    )
    _require(
        all(choice in CHOICES for choice in judgments.values()),
        f"{reviewer_ref}/{answer.get('review_id')} has an invalid judgment",
    )
    preferred = answer.get("preferred")
    _require(preferred in CHOICES, f"{reviewer_ref}/{answer.get('review_id')} has an invalid preference")
    confidence = answer.get("confidence")
    _require(
        isinstance(confidence, int) and not isinstance(confidence, bool) and 1 <= confidence <= 5,
        f"{reviewer_ref}/{answer.get('review_id')} has invalid confidence",
    )
    notes = answer.get("notes", "")
    _require(isinstance(notes, str) and len(notes) <= 1000, "review notes exceed the formal limit")
    result = {
        "schema_version": REVIEW_VERSION,
        "review_id": package["review_id"],
        "package_digest": package["package_digest"],
        "rubric_version": package["rubric_version"],
        "reviewer_ref": reviewer_ref,
        "reviewed_at": reviewed_at,
        "attestations": {
            "independent_review": True,
            "conflict_of_interest": False,
            "blind_key_access": False,
        },
        "comparative_judgments": judgments,
        "preferred_option": preferred,
        "confidence": confidence,
    }
    if notes:
        result["review_notes"] = notes
    _QUALITY.validate_review(result, package, _QUALITY.load_default_rubric(ROOT))
    return result


def _normalize_mainland_submission(
    submission: dict[str, Any],
    review_bundle: dict[str, Any],
    display_bundle: dict[str, Any],
    packages: dict[str, dict[str, Any]],
    stages: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    reviewer_ref = _reviewer_ref(submission.get("reviewer_id"), "mainland reviewer_id")
    _require(
        submission.get("schema_version") == MAINLAND_SUBMISSION_VERSION,
        f"{reviewer_ref} uses an unsupported mainland submission version",
    )
    _require(submission.get("status") == "SUBMITTED_LOCKED", f"{reviewer_ref} is not locked")
    _require(submission.get("collection_id") == MAINLAND_COLLECTION, f"{reviewer_ref} collection mismatch")
    _require(
        submission.get("bundle_digest") == display_bundle.get("bundle_digest"),
        f"{reviewer_ref} mainland display digest mismatch",
    )
    _require(
        submission.get("source_bundle_id") == review_bundle.get("bundle_id")
        and submission.get("source_bundle_digest") == review_bundle.get("bundle_digest"),
        f"{reviewer_ref} frozen source bundle mismatch",
    )
    _validate_attestations(submission.get("attestations"), reviewer_ref)
    reviewed_at = str(submission.get("submitted_at", ""))
    _timestamp(reviewed_at, f"{reviewer_ref}.submitted_at")
    answers = submission.get("answers")
    _require(isinstance(answers, list) and len(answers) == len(packages), f"{reviewer_ref} must contain 30 answers")
    review_ids = [answer.get("review_id") for answer in answers]
    _require(len(review_ids) == len(set(review_ids)), f"{reviewer_ref} contains duplicate answers")
    _require(set(review_ids) == set(packages), f"{reviewer_ref} answer membership differs from v3")
    normalized: list[dict[str, Any]] = []
    for answer in answers:
        review_id = answer.get("review_id")
        stage = stages[review_id]
        _require(answer.get("schema_version") == MAINLAND_ANSWER_VERSION, f"{reviewer_ref}/{review_id} answer version mismatch")
        _require(answer.get("reviewer_id") == reviewer_ref, f"{reviewer_ref}/{review_id} reviewer mismatch")
        _require(answer.get("status") == "ANSWER_LOCKED", f"{reviewer_ref}/{review_id} is not locked")
        _require(answer.get("collection_id") == MAINLAND_COLLECTION, f"{reviewer_ref}/{review_id} collection mismatch")
        _require(answer.get("bundle_digest") == display_bundle.get("bundle_digest"), f"{reviewer_ref}/{review_id} display digest mismatch")
        _require(
            answer.get("source_bundle_id") == review_bundle.get("bundle_id")
            and answer.get("source_bundle_digest") == review_bundle.get("bundle_digest"),
            f"{reviewer_ref}/{review_id} source bundle mismatch",
        )
        _require(answer.get("case_id") == stage["case_id"] and answer.get("moment") == stage["moment"], f"{reviewer_ref}/{review_id} story position mismatch")
        _require(answer.get("package_digest") == packages[review_id].get("package_digest"), f"{reviewer_ref}/{review_id} package digest mismatch")
        _timestamp(answer.get("committed_at"), f"{reviewer_ref}/{review_id}.committed_at")
        normalized.append(_normalized_review(answer, reviewer_ref, reviewed_at, packages[review_id]))
    return {
        "reviewer_ref": reviewer_ref,
        "source_collection": MAINLAND_COLLECTION,
        "source_schema_version": MAINLAND_SUBMISSION_VERSION,
        "submitted_at": reviewed_at,
        "reviews": normalized,
    }


def normalize_mainland_export(
    source_export: dict[str, Any],
    review_bundle: dict[str, Any],
    display_bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    packages = _package_map(review_bundle)
    stages = validate_mainland_display_bundle(display_bundle, review_bundle)
    _require(source_export.get("schema_version") == MAINLAND_EXPORT_VERSION, "unsupported mainland export")
    _require(source_export.get("collection_id") == MAINLAND_COLLECTION, "mainland export collection mismatch")
    _require(source_export.get("bundle_digest") == display_bundle.get("bundle_digest"), "mainland export display digest mismatch")
    _require(
        source_export.get("source_bundle_id") == review_bundle.get("bundle_id")
        and source_export.get("source_bundle_digest") == review_bundle.get("bundle_digest"),
        "mainland export frozen source mismatch",
    )
    submissions = source_export.get("submissions")
    _require(isinstance(submissions, list) and bool(submissions), "mainland export has no submissions")
    return [
        _normalize_mainland_submission(item, review_bundle, display_bundle, packages, stages)
        for item in submissions
    ]


def normalize_formal_export(
    source_export: dict[str, Any], review_bundle: dict[str, Any]
) -> list[dict[str, Any]]:
    packages = _package_map(review_bundle)
    _require(source_export.get("schema_version") == FORMAL_EXPORT_VERSION, "unsupported formal Sites export")
    _require(source_export.get("collection_id") == FORMAL_COLLECTION, "formal Sites collection mismatch")
    submissions = source_export.get("submissions")
    _require(isinstance(submissions, list) and bool(submissions), "formal Sites export has no submissions")
    normalized_submissions: list[dict[str, Any]] = []
    for submission in submissions:
        reviewer_ref = _reviewer_ref(submission.get("reviewer_id"), "formal reviewer_id")
        _require(submission.get("collection_id") == FORMAL_COLLECTION, f"{reviewer_ref} formal collection mismatch")
        _require(
            submission.get("bundle_id") == review_bundle.get("bundle_id")
            and submission.get("bundle_digest") == review_bundle.get("bundle_digest"),
            f"{reviewer_ref} formal frozen bundle mismatch",
        )
        _validate_attestations(submission.get("attestations"), reviewer_ref)
        reviewed_at = str(submission.get("submitted_at", ""))
        _timestamp(reviewed_at, f"{reviewer_ref}.submitted_at")
        answers = submission.get("answers")
        _require(isinstance(answers, list) and len(answers) == len(packages), f"{reviewer_ref} must contain 30 final answers")
        review_ids = [answer.get("review_id") for answer in answers]
        _require(len(review_ids) == len(set(review_ids)), f"{reviewer_ref} contains duplicate answers")
        _require(set(review_ids) == set(packages), f"{reviewer_ref} answer membership differs from v3")
        normalized: list[dict[str, Any]] = []
        for answer in answers:
            review_id = answer.get("review_id")
            _require(answer.get("status") == "ANSWER_LOCKED", f"{reviewer_ref}/{review_id} is not final")
            _require(answer.get("package_digest") == packages[review_id].get("package_digest"), f"{reviewer_ref}/{review_id} package digest mismatch")
            _timestamp(answer.get("committed_at"), f"{reviewer_ref}/{review_id}.committed_at")
            normalized.append(_normalized_review(answer, reviewer_ref, reviewed_at, packages[review_id]))
        normalized_submissions.append({
            "reviewer_ref": reviewer_ref,
            "source_collection": FORMAL_COLLECTION,
            "source_schema_version": FORMAL_EXPORT_VERSION,
            "submitted_at": reviewed_at,
            "reviews": normalized,
        })
    return normalized_submissions


def reconcile_collections(
    review_bundle: dict[str, Any], submissions: list[dict[str, Any]]
) -> dict[str, Any]:
    packages = _package_map(review_bundle)
    _require(bool(submissions), "at least one eligible submission is required")
    reviewer_refs = [item["reviewer_ref"] for item in submissions]
    _require(len(reviewer_refs) == len(set(reviewer_refs)), "reviewer IDs must be unique across entry surfaces")
    reviews_by_package: dict[str, list[dict[str, Any]]] = {review_id: [] for review_id in packages}
    for submission in submissions:
        _require(len(submission["reviews"]) == len(packages), f"{submission['reviewer_ref']} is incomplete")
        for review in submission["reviews"]:
            reviews_by_package[review["review_id"]].append(review)
    _require(
        all(len(reviews) == len(submissions) for reviews in reviews_by_package.values()),
        "every frozen package must have one review from every reviewer",
    )
    sources: dict[str, int] = {}
    for submission in submissions:
        source = submission["source_collection"]
        sources[source] = sources.get(source, 0) + 1
    return {
        "schema_version": COMBINED_VERSION,
        "bundle_id": review_bundle["bundle_id"],
        "bundle_digest": review_bundle["bundle_digest"],
        "rubric_version": review_bundle["rubric_version"],
        "package_count": len(packages),
        "reviewer_count": len(submissions),
        "review_record_count": len(submissions) * len(packages),
        "source_collections": sources,
        "compatibility_checks": {
            "same_frozen_bundle": True,
            "same_review_ids": True,
            "same_package_digests": True,
            "same_rubric_dimensions": True,
            "all_answers_locked": True,
            "all_submissions_attested": True,
            "distinct_reviewer_refs": True,
        },
        "submissions": submissions,
        "reviews_by_package": reviews_by_package,
        "distribution": "STUDY_OWNER_ONLY_CONTAINS_PSEUDONYMOUS_HUMAN_REVIEWS",
        "claim_boundary": {
            "supports": ["COMPATIBLE_CROSS_ENTRY_REVIEW_AGGREGATION"],
            "does_not_support": [
                "BUSINESS_OUTCOME_EFFECT",
                "REAL_LOGISTICS_PERFORMANCE",
                "MODEL_PROMOTION",
                "PRODUCTION_READINESS",
            ],
        },
        "operational_mutations": [],
    }


def aggregate_corpus(
    combined: dict[str, Any],
    review_bundle: dict[str, Any],
    key_bundle: dict[str, Any],
    rubric: dict[str, Any],
) -> dict[str, Any]:
    _require(key_bundle.get("schema_version") == "historical-replay-review-key-bundle.v3", "unsupported v3 key bundle")
    _require(
        key_bundle.get("bundle_id") == combined.get("bundle_id")
        and key_bundle.get("bundle_digest") == combined.get("bundle_digest"),
        "blind key bundle does not match combined evidence",
    )
    packages = _package_map(review_bundle)
    keys = {item.get("review_id"): item for item in key_bundle.get("keys", [])}
    _require(set(keys) == set(packages), "blind key package membership mismatch")
    summaries = []
    for package in review_bundle["packages"]:
        review_id = package["review_id"]
        summaries.append(
            _QUALITY.score_reviews(
                package,
                keys[review_id],
                rubric,
                combined["reviews_by_package"][review_id],
            )
        )
    result_counts: dict[str, int] = {}
    favored_counts: dict[str, int] = {}
    for summary in summaries:
        result_counts[summary["result"]] = result_counts.get(summary["result"], 0) + 1
        favored = summary.get("favored_variant_id")
        if favored:
            favored_counts[favored] = favored_counts.get(favored, 0) + 1
    return {
        "schema_version": CORPUS_SUMMARY_VERSION,
        "bundle_id": combined["bundle_id"],
        "bundle_digest": combined["bundle_digest"],
        "evidence_classification": "HYBRID_HISTORICAL_REPLAY",
        "reviewer_count": combined["reviewer_count"],
        "package_count": combined["package_count"],
        "result_counts": result_counts,
        "favored_variant_counts": favored_counts,
        "package_summaries": summaries,
        "claim_boundary": {
            "supports": ["CONTROLLED_POINT_IN_TIME_DECISION_QUALITY_REVIEW"],
            "does_not_support": [
                "BUSINESS_OUTCOME_EFFECT",
                "REAL_LOGISTICS_PERFORMANCE",
                "MODEL_PROMOTION",
                "PRODUCTION_READINESS",
            ],
        },
        "operational_mutations": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-bundle",
        type=Path,
        default=ROOT / "blinded-review-survey" / "data" / "review-bundle.json",
    )
    parser.add_argument(
        "--mainland-display-bundle",
        type=Path,
        default=ROOT / "lambda" / "ten_story_review_bundle.json",
    )
    parser.add_argument("--formal-export", type=Path)
    parser.add_argument("--mainland-export", type=Path)
    parser.add_argument("--key-bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _require(args.formal_export or args.mainland_export, "provide at least one review export")
    review_bundle = _load(args.review_bundle)
    submissions: list[dict[str, Any]] = []
    if args.formal_export:
        submissions.extend(normalize_formal_export(_load(args.formal_export), review_bundle))
    if args.mainland_export:
        submissions.extend(
            normalize_mainland_export(
                _load(args.mainland_export),
                review_bundle,
                _load(args.mainland_display_bundle),
            )
        )
    combined = reconcile_collections(review_bundle, submissions)
    output: dict[str, Any] = {"combined_evidence": combined}
    if args.key_bundle:
        output["corpus_summary"] = aggregate_corpus(
            combined,
            review_bundle,
            _load(args.key_bundle),
            _QUALITY.load_default_rubric(ROOT),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cli_summary = {
        "reviewer_count": combined["reviewer_count"],
        "package_count": combined["package_count"],
        "review_record_count": combined["review_record_count"],
        "source_collections": combined["source_collections"],
        "aggregated": "corpus_summary" in output,
    }
    if "corpus_summary" in output:
        cli_summary["result_counts"] = output["corpus_summary"]["result_counts"]
        cli_summary["favored_variant_counts"] = output["corpus_summary"][
            "favored_variant_counts"
        ]
    print(json.dumps(cli_summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
