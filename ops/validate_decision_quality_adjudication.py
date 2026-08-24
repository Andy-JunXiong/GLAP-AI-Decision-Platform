"""Validate the append-only Cyclone Gabrielle T1 adjudication evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ROOT / "docs" / "decision_quality_adjudication_cyclone_gabrielle_t1_v1.json"
RECONCILIATION_PATH = ROOT / "docs" / "decision_quality_five_review_reconciliation_v1.json"
CORPUS_SUMMARY_PATH = ROOT / "docs" / "decision_quality_five_review_corpus_summary_v1.json"
T1_DISPOSITION_PATH = ROOT / "docs" / "decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json"
T2_DISPOSITION_PATH = ROOT / "docs" / "decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json"
BUNDLE_PATH = ROOT / "blinded-review-survey" / "data" / "review-bundle.json"
RUBRIC_PATH = ROOT / "docs" / "decision_quality_rubric_v1.json"
EXPECTED_SUPPORTS = ["GOVERNED_DECISION_QUALITY_ADJUDICATION_RECORD"]
EXPECTED_EXCLUSIONS = [
    "BUSINESS_OUTCOME_EFFECT",
    "REAL_LOGISTICS_PERFORMANCE",
    "A303_REACTIVATION",
    "MODEL_PROMOTION",
    "PRODUCTION_READINESS",
    "OPERATIONAL_AUTHORITY",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_digest(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "record_digest"}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_record(
    record: dict[str, Any], bundle: dict[str, Any], today: date | None = None
) -> list[str]:
    errors: list[str] = []
    current_date = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    if record.get("schema_version") != "decision-quality-adjudication.v1":
        errors.append("unsupported adjudication schema")
    if record.get("record_version") != 1 or record.get("supersedes_record_digest") is not None:
        errors.append("the pending record must be the first immutable version")
    try:
        created = date.fromisoformat(str(record.get("created_on_sydney_date")))
        if created > current_date:
            errors.append("the adjudication record cannot be future-dated")
    except ValueError:
        errors.append("created_on_sydney_date must use YYYY-MM-DD")

    bundle_payload = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    encoded_bundle = json.dumps(
        bundle_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    actual_bundle_digest = hashlib.sha256(encoded_bundle).hexdigest()
    source = record.get("source_evidence", {})
    if (
        bundle.get("schema_version") != "historical-replay-review-bundle.v3"
        or bundle.get("bundle_digest") != actual_bundle_digest
        or source.get("bundle_id") != bundle.get("bundle_id")
        or source.get("bundle_digest") != bundle.get("bundle_digest")
    ):
        errors.append("the adjudication source is not the frozen v3 bundle")
    matches = [
        package
        for package in bundle.get("packages", [])
        if package.get("review_id") == source.get("review_id")
    ]
    if len(matches) != 1:
        errors.append("the adjudication must bind exactly one frozen package")
    else:
        package = matches[0]
        scenario = package.get("scenario", {})
        if (
            source.get("package_digest") != package.get("package_digest")
            or source.get("scenario_id") != scenario.get("scenario_id")
            or source.get("cutoff_id") != scenario.get("cutoff_id")
            or source.get("cutoff_at") != scenario.get("cutoff_at")
        ):
            errors.append("the adjudication package identity has drifted")
    if source != {
        "bundle_id": "35397ba1fb3d15d87ad7c071",
        "bundle_digest": "60ebd29e920a489c3c171d1daf27b6fe85efbc884e77d2763b64b7b6a14d3cdb",
        "review_id": "91753061d940f8fa9be70d81",
        "package_digest": "b7e925e02d3118c888246b78cec248d1237c63d303284e35b461f7aa5b5a03a5",
        "scenario_id": "new-zealand-cyclone-gabrielle-roads-2023-v1",
        "cutoff_id": "T1_COROMANDEL_HIGHWAY_CLOSURES_CONFIRMED",
        "cutoff_at": "2023-02-13T10:40:00+13:00",
        "evidence_classification": "HYBRID_HISTORICAL_REPLAY",
        "review_count": 4,
        "raw_review_result": "REVIEWERS_DO_NOT_AGREE",
        "raw_review_status": "REQUIRES_ADJUDICATION",
        "non_tie_preference_count": 4,
        "maximum_preference_count": 2,
        "preference_consensus_pct": 50.0,
        "score_delta": 0.0,
    }:
        errors.append("the frozen 2:2 aggregate declaration has changed")

    if record.get("adjudication") != {
        "status": "PENDING_HUMAN_ADJUDICATION",
        "resolution": None,
        "rationale": None,
        "decided_by_named_study_owner": False,
        "decided_on_sydney_date": None,
    }:
        errors.append("no adjudication resolution is authorized in the pending record")
    if record.get("governance") != {
        "original_reviews_immutable": True,
        "original_review_count": 4,
        "adjudication_is_not_a_fifth_review": True,
        "raw_review_result_remains_authoritative": True,
        "resolution_is_separate_disposition": True,
        "append_new_record_for_resolution": True,
    }:
        errors.append("adjudication cannot rewrite or extend the four original reviews")
    boundary = record.get("claim_boundary", {})
    if boundary.get("supports") != EXPECTED_SUPPORTS or boundary.get("does_not_support") != EXPECTED_EXCLUSIONS:
        errors.append("the adjudication claim boundary has expanded")
    if record.get("authority") != {
        "profile": "LOCAL_EVALUATION_GOVERNANCE_ONLY",
        "network_access_allowed": False,
        "aws_write_allowed": False,
        "review_mutation_allowed": False,
        "action_authority": "NONE",
        "policy_activation_allowed": False,
        "model_promotion_allowed": False,
        "production_effect": False,
        "a303_reactivation_allowed": False,
    }:
        errors.append("the adjudication record has gained operational authority")
    if record.get("operational_mutations") != []:
        errors.append("adjudication must not contain an operational mutation")
    if record.get("record_digest") != canonical_digest(record):
        errors.append("adjudication record digest mismatch")
    return errors


def validate_reconciliation(
    record: dict[str, Any],
    predecessor: dict[str, Any],
    bundle: dict[str, Any],
    rubric: dict[str, Any],
    today: date | None = None,
) -> list[str]:
    errors: list[str] = []
    current_date = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    if record.get("schema_version") != "decision-quality-five-review-reconciliation.v1":
        errors.append("unsupported five-review reconciliation schema")
    try:
        created = date.fromisoformat(str(record.get("created_on_sydney_date")))
        if created > current_date:
            errors.append("the five-review reconciliation cannot be future-dated")
    except ValueError:
        errors.append("five-review created_on_sydney_date must use YYYY-MM-DD")

    predecessor_ref = record.get("predecessor", {})
    if (
        predecessor.get("record_digest") != canonical_digest(predecessor)
        or predecessor_ref.get("record_digest") != predecessor.get("record_digest")
        or predecessor_ref.get("review_count") != 4
        or predecessor_ref.get("result") != "REVIEWERS_DO_NOT_AGREE"
        or predecessor_ref.get("status") != "REQUIRES_ADJUDICATION"
    ):
        errors.append("the five-review reconciliation predecessor has drifted")

    source = record.get("source_evidence", {})
    matches = [
        package
        for package in bundle.get("packages", [])
        if package.get("review_id") == source.get("review_id")
    ]
    if len(matches) != 1 or (
        source.get("bundle_id") != bundle.get("bundle_id")
        or source.get("bundle_digest") != bundle.get("bundle_digest")
        or source.get("package_digest") != (
            matches[0].get("package_digest") if matches else None
        )
    ):
        errors.append("the fifth review is not bound to the frozen package")
    if source != {
        "bundle_id": "35397ba1fb3d15d87ad7c071",
        "bundle_digest": "60ebd29e920a489c3c171d1daf27b6fe85efbc884e77d2763b64b7b6a14d3cdb",
        "review_id": "91753061d940f8fa9be70d81",
        "package_digest": "b7e925e02d3118c888246b78cec248d1237c63d303284e35b461f7aa5b5a03a5",
        "source_collection": "human-evaluation-story.v2",
        "submission_count": 1,
        "locked_answer_count": 30,
        "required_attestations_complete": True,
        "reviewer_identifiers_retained": False,
        "account_credentials_retained": False,
        "answer_content_retained": False,
    }:
        errors.append("the aggregate-only fifth-review declaration has changed")

    delta = record.get("aggregate_delta", {})
    expected_delta = {
        "review_count_before": 4,
        "review_count_after": 5,
        "review_record_count_after": 150,
        "non_tie_preference_count_after": 5,
        "baseline_a303_off_preference_count": 2,
        "glap_a303_on_preference_count": 3,
        "maximum_preference_count_after": 3,
    }
    if delta != expected_delta:
        errors.append("the five-review aggregate delta has changed")

    gate = rubric.get("interpretation_gate", {})
    expected_result = {
        "preference_consensus_pct": 60.0,
        "minimum_preference_consensus_pct": 66.67,
        "baseline_a303_off_mean_comparative_preference_share": 41.5,
        "glap_a303_on_mean_comparative_preference_share": 58.5,
        "score_delta": 17.0,
        "minimum_mean_score_delta": 5.0,
        "gate_checks": {
            "minimum_reviewers_met": True,
            "minimum_non_tie_preferences_met": True,
            "preference_consensus_met": False,
            "score_and_preference_winners_align": True,
            "minimum_score_delta_met": True,
        },
        "status": "REQUIRES_ADJUDICATION",
        "result": "REVIEWERS_DO_NOT_AGREE",
        "favored_variant_id": None,
        "adjudication_status": "PENDING_HUMAN_ADJUDICATION",
    }
    if (
        gate.get("minimum_preference_consensus_pct") != 66.67
        or gate.get("minimum_mean_score_delta") != 5.0
        or record.get("updated_result") != expected_result
    ):
        errors.append("the frozen five-review gate result has changed")
    if round(100 * delta.get("maximum_preference_count_after", 0) / 5, 2) != 60.0:
        errors.append("the five-review preference consensus is inconsistent")
    if round(
        record.get("updated_result", {}).get(
            "glap_a303_on_mean_comparative_preference_share", 0
        )
        - record.get("updated_result", {}).get(
            "baseline_a303_off_mean_comparative_preference_share", 0
        ),
        2,
    ) != 17.0:
        errors.append("the five-review score delta is inconsistent")

    if record.get("governance") != {
        "predecessor_immutable": True,
        "fifth_review_is_human_evidence": True,
        "fifth_review_is_not_an_adjudication_vote": True,
        "full_corpus_reaggregation_pending": True,
        "new_human_disposition_required": True,
    }:
        errors.append("the five-review governance boundary has changed")
    boundary = record.get("claim_boundary", {})
    if boundary.get("supports") != ["AGGREGATE_ONLY_FIFTH_REVIEW_RECONCILIATION"] or boundary.get(
        "does_not_support"
    ) != [
        "INDIVIDUAL_REVIEW_DISCLOSURE",
        "FULL_FIVE_REVIEW_CORPUS_RESULT",
        "BUSINESS_OUTCOME_EFFECT",
        "REAL_LOGISTICS_PERFORMANCE",
        "A303_REACTIVATION",
        "MODEL_PROMOTION",
        "PRODUCTION_READINESS",
        "OPERATIONAL_AUTHORITY",
    ]:
        errors.append("the five-review claim boundary has expanded")
    if record.get("authority") != {
        "profile": "LOCAL_EVALUATION_RECONCILIATION_ONLY",
        "network_access_allowed": False,
        "aws_write_allowed": False,
        "review_mutation_allowed": False,
        "action_authority": "NONE",
        "policy_activation_allowed": False,
        "model_promotion_allowed": False,
        "production_effect": False,
        "a303_reactivation_allowed": False,
    }:
        errors.append("the five-review reconciliation has gained operational authority")
    if record.get("operational_mutations") != []:
        errors.append("the five-review reconciliation must not contain an operational mutation")
    if record.get("record_digest") != canonical_digest(record):
        errors.append("five-review reconciliation digest mismatch")
    return errors


def validate_corpus_summary(
    record: dict[str, Any],
    bundle: dict[str, Any],
    rubric: dict[str, Any],
    today: date | None = None,
) -> list[str]:
    errors: list[str] = []
    current_date = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    if record.get("schema_version") != "decision-quality-five-review-corpus-summary.v1":
        errors.append("unsupported five-review corpus summary schema")
    try:
        created = date.fromisoformat(str(record.get("created_on_sydney_date")))
        if created > current_date:
            errors.append("the five-review corpus summary cannot be future-dated")
    except ValueError:
        errors.append("five-review corpus created_on_sydney_date must use YYYY-MM-DD")

    source = record.get("source_evidence", {})
    expected_source = {
        "bundle_id": "35397ba1fb3d15d87ad7c071",
        "bundle_digest": "60ebd29e920a489c3c171d1daf27b6fe85efbc884e77d2763b64b7b6a14d3cdb",
        "reviewer_count": 5,
        "package_count": 30,
        "review_record_count": 150,
        "source_collections": {
            "human-evaluation-story.v2": 3,
            "glap-ten-story-review.v1": 2,
        },
        "aggregate_artifact_digest": "81ae052f34c6ddd957ecc7f9500e65784d90b6db6e807a9582c1bd4e86248bec",
    }
    if source != expected_source or (
        source.get("bundle_id") != bundle.get("bundle_id")
        or source.get("bundle_digest") != bundle.get("bundle_digest")
        or source.get("package_count") != len(bundle.get("packages", []))
    ):
        errors.append("the five-review corpus source declaration has changed")

    expected_result = {
        "review_evidence_favors_variant_count": 14,
        "reviewers_do_not_agree_count": 16,
        "favored_variant_counts": {"glap-a303-on": 14},
        "unanimous_control_tie_count": 14,
    }
    if record.get("corpus_result") != expected_result:
        errors.append("the five-review corpus result has changed")
    elif sum(
        (
            record["corpus_result"]["review_evidence_favors_variant_count"],
            record["corpus_result"]["reviewers_do_not_agree_count"],
        )
    ) != source.get("package_count"):
        errors.append("the five-review package counts do not reconcile")

    expected_packages = [
        {
            "review_id": "91753061d940f8fa9be70d81",
            "package_digest": "b7e925e02d3118c888246b78cec248d1237c63d303284e35b461f7aa5b5a03a5",
            "scenario_id": "new-zealand-cyclone-gabrielle-roads-2023-v1",
            "cutoff_id": "T1_COROMANDEL_HIGHWAY_CLOSURES_CONFIRMED",
            "baseline_preference_count": 2,
            "challenger_preference_count": 3,
            "preference_consensus_pct": 60.0,
            "score_delta": 17.0,
            "result": "REVIEWERS_DO_NOT_AGREE",
            "favored_variant_id": None,
        },
        {
            "review_id": "f065f154bf704bbd7b07c49f",
            "package_digest": "2df9064228894796cf937142be0491b274b3a0aad8e731bc61bc123ae3536b30",
            "scenario_id": "new-zealand-cyclone-gabrielle-roads-2023-v1",
            "cutoff_id": "T2_NORTHLAND_NETWORK_ISOLATION_CONFIRMED",
            "baseline_preference_count": 2,
            "challenger_preference_count": 3,
            "preference_consensus_pct": 60.0,
            "score_delta": 31.0,
            "result": "REVIEWERS_DO_NOT_AGREE",
            "favored_variant_id": None,
        },
    ]
    packages = record.get("non_control_no_winner_packages")
    if packages != expected_packages:
        errors.append("the five-review non-control no-winner set has changed")
    else:
        frozen = {
            package.get("review_id"): package
            for package in bundle.get("packages", [])
        }
        for package in packages:
            source_package = frozen.get(package["review_id"], {})
            scenario = source_package.get("scenario", {})
            if (
                source_package.get("package_digest") != package["package_digest"]
                or scenario.get("scenario_id") != package["scenario_id"]
                or scenario.get("cutoff_id") != package["cutoff_id"]
            ):
                errors.append("a five-review no-winner package is not bundle-bound")

    if rubric.get("interpretation_gate", {}).get("minimum_preference_consensus_pct") != 66.67:
        errors.append("the frozen preference consensus gate has changed")
    if record.get("privacy") != {
        "reviewer_identifiers_retained": False,
        "credentials_retained": False,
        "answer_content_retained": False,
        "notes_retained": False,
        "raw_exports_retained": False,
    }:
        errors.append("the five-review privacy boundary has changed")
    rendered = json.dumps(record, sort_keys=True).lower()
    if re.search(r"\bglap-review-\d", rendered) or "reviewer-" in rendered:
        errors.append("private reviewer data reached the aggregate summary")
    if record.get("governance") != {
        "full_corpus_reaggregation_complete": True,
        "live_sources_read_only": True,
        "human_disposition_inferred": False,
        "public_refresh_pending_separate_authorization": True,
        "predecessor_records_immutable": True,
    }:
        errors.append("the five-review corpus governance boundary has changed")
    if record.get("authority") != {
        "profile": "LOCAL_AGGREGATE_EVIDENCE_ONLY",
        "aws_write_allowed": False,
        "review_mutation_allowed": False,
        "public_publication_allowed": False,
        "action_authority": "NONE",
        "policy_activation_allowed": False,
        "model_promotion_allowed": False,
        "production_effect": False,
        "a303_reactivation_allowed": False,
    }:
        errors.append("the five-review corpus summary has gained authority")
    boundary = record.get("claim_boundary", {})
    if boundary.get("supports") != ["FIVE_REVIEW_CONTROLLED_POINT_IN_TIME_DECISION_QUALITY"] or boundary.get("does_not_support") != [
        "INDIVIDUAL_REVIEW_DISCLOSURE",
        "BUSINESS_OUTCOME_EFFECT",
        "REAL_LOGISTICS_PERFORMANCE",
        "A303_REACTIVATION",
        "MODEL_PROMOTION",
        "PRODUCTION_READINESS",
        "OPERATIONAL_AUTHORITY",
    ]:
        errors.append("the five-review corpus claim boundary has expanded")
    if record.get("operational_mutations") != []:
        errors.append("the five-review corpus summary must not contain a mutation")
    if record.get("record_digest") != canonical_digest(record):
        errors.append("five-review corpus summary digest mismatch")
    return errors


def validate_human_disposition(
    record: dict[str, Any],
    corpus: dict[str, Any],
    bundle: dict[str, Any],
    predecessor: dict[str, Any] | None = None,
    today: date | None = None,
) -> list[str]:
    errors: list[str] = []
    current_date = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    if record.get("schema_version") != "decision-quality-human-disposition.v1":
        errors.append("unsupported Decision Quality human disposition schema")
    try:
        created = date.fromisoformat(str(record.get("created_on_sydney_date")))
        decided = date.fromisoformat(
            str(record.get("disposition", {}).get("decided_on_sydney_date"))
        )
        if created > current_date or decided > current_date or created != decided:
            errors.append("the human disposition date is invalid or future-dated")
    except ValueError:
        errors.append("human disposition dates must use YYYY-MM-DD")

    source_corpus = record.get("source_corpus", {})
    if source_corpus != {
        "schema_version": "decision-quality-five-review-corpus-summary.v1",
        "record_digest": corpus.get("record_digest"),
        "reviewer_count": 5,
        "review_record_count": 150,
    } or corpus.get("record_digest") != canonical_digest(corpus):
        errors.append("the human disposition is not bound to the frozen five-review corpus")

    package = record.get("package_evidence", {})
    summaries = {
        item.get("review_id"): item
        for item in corpus.get("non_control_no_winner_packages", [])
    }
    summary = summaries.get(package.get("review_id"), {})
    frozen = {
        item.get("review_id"): item for item in bundle.get("packages", [])
    }.get(package.get("review_id"), {})
    scenario = frozen.get("scenario", {})
    expected_package = {
        "review_id": summary.get("review_id"),
        "package_digest": summary.get("package_digest"),
        "scenario_id": summary.get("scenario_id"),
        "cutoff_id": summary.get("cutoff_id"),
        "cutoff_at": scenario.get("cutoff_at"),
        "baseline_preference_count": summary.get("baseline_preference_count"),
        "challenger_preference_count": summary.get("challenger_preference_count"),
        "preference_consensus_pct": summary.get("preference_consensus_pct"),
        "minimum_preference_consensus_pct": 66.67,
        "score_delta": summary.get("score_delta"),
        "raw_review_result": summary.get("result"),
        "favored_variant_id": summary.get("favored_variant_id"),
    }
    if package != expected_package or frozen.get("package_digest") != package.get(
        "package_digest"
    ):
        errors.append("the human disposition package evidence has drifted")
    if not (
        package.get("preference_consensus_pct") == 60.0
        and package.get("minimum_preference_consensus_pct") == 66.67
        and package.get("preference_consensus_pct")
        < package.get("minimum_preference_consensus_pct")
        and package.get("raw_review_result") == "REVIEWERS_DO_NOT_AGREE"
        and package.get("favored_variant_id") is None
    ):
        errors.append("the no-winner consensus gate has been overridden")

    expected_lineage = {
        "91753061d940f8fa9be70d81": (
            "cyclone-gabrielle-t1-decision-quality-disposition-v2",
            2,
            predecessor.get("record_digest") if predecessor else None,
        ),
        "f065f154bf704bbd7b07c49f": (
            "cyclone-gabrielle-t2-decision-quality-disposition-v1",
            1,
            None,
        ),
    }.get(package.get("review_id"))
    actual_lineage = (
        record.get("disposition_id"),
        record.get("record_version"),
        record.get("supersedes_record_digest"),
    )
    if expected_lineage is None or actual_lineage != expected_lineage:
        errors.append("the human disposition lineage has drifted")
    if predecessor and predecessor.get("record_digest") != canonical_digest(predecessor):
        errors.append("the superseded pending record digest is invalid")

    expected_rationale = {
        17.0: "Five reviewers split 3:2, so 60% consensus is below the frozen 66.67% gate; the 17-point score delta cannot replace the consensus requirement.",
        31.0: "Five reviewers split 3:2, so 60% consensus is below the frozen 66.67% gate; the 31-point score delta cannot replace the consensus requirement.",
    }.get(package.get("score_delta"))
    if record.get("disposition") != {
        "status": "RESOLVED_HUMAN_ADJUDICATION",
        "resolution": "RETAIN_INCONCLUSIVE",
        "rationale": expected_rationale,
        "decided_by_named_study_owner": True,
        "decided_on_sydney_date": "2026-08-24",
    }:
        errors.append("the named-human retain-inconclusive disposition has changed")
    if record.get("privacy") != {
        "study_owner_identity_retained": False,
        "reviewer_identifiers_retained": False,
        "credentials_retained": False,
        "answer_content_retained": False,
        "notes_retained": False,
    }:
        errors.append("the human disposition privacy boundary has changed")
    if record.get("governance") != {
        "original_reviews_immutable": True,
        "disposition_is_not_an_additional_review": True,
        "raw_review_result_remains_authoritative": True,
        "no_winner_converted_to_winner": True,
        "separate_disposition_per_package": True,
    }:
        errors.append("the human disposition governance boundary has changed")
    if record.get("claim_boundary") != {
        "supports": ["HUMAN_RETAIN_INCONCLUSIVE_DISPOSITION"],
        "does_not_support": [
            "REVIEW_RESULT_OVERRIDE",
            "BUSINESS_OUTCOME_EFFECT",
            "REAL_LOGISTICS_PERFORMANCE",
            "A303_REACTIVATION",
            "MODEL_PROMOTION",
            "PRODUCTION_READINESS",
            "OPERATIONAL_AUTHORITY",
        ],
    }:
        errors.append("the human disposition claim boundary has expanded")
    if record.get("authority") != {
        "profile": "LOCAL_EVALUATION_GOVERNANCE_ONLY",
        "aws_write_allowed": False,
        "review_mutation_allowed": False,
        "public_publication_allowed": False,
        "action_authority": "NONE",
        "policy_activation_allowed": False,
        "model_promotion_allowed": False,
        "production_effect": False,
        "a303_reactivation_allowed": False,
    }:
        errors.append("the human disposition has gained operational authority")
    if record.get("operational_mutations") != []:
        errors.append("the human disposition must not contain an operational mutation")
    rendered = json.dumps(record, sort_keys=True).lower()
    if re.search(r"\bglap-review-\d", rendered) or "reviewer-" in rendered:
        errors.append("private identity reached the human disposition")
    if record.get("record_digest") != canonical_digest(record):
        errors.append("human disposition record digest mismatch")
    return errors


def main() -> int:
    predecessor = load_json(RECORD_PATH)
    bundle = load_json(BUNDLE_PATH)
    errors = validate_record(predecessor, bundle)
    errors.extend(
        validate_reconciliation(
            load_json(RECONCILIATION_PATH),
            predecessor,
            bundle,
            load_json(RUBRIC_PATH),
        )
    )
    errors.extend(
        validate_corpus_summary(
            load_json(CORPUS_SUMMARY_PATH),
            bundle,
            load_json(RUBRIC_PATH),
        )
    )
    corpus = load_json(CORPUS_SUMMARY_PATH)
    errors.extend(
        validate_human_disposition(
            load_json(T1_DISPOSITION_PATH),
            corpus,
            bundle,
            predecessor=predecessor,
        )
    )
    errors.extend(
        validate_human_disposition(
            load_json(T2_DISPOSITION_PATH),
            corpus,
            bundle,
        )
    )
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(
        "PASS: the five-review 14/16 aggregate is preserved and the named human "
        "retains inconclusive dispositions for Cyclone Gabrielle T1 and T2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
