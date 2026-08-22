import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "historical_replay"


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


reconcile = load_module(
    "review_collection_reconciliation", "ops/reconcile_review_collections.py"
)
review_builder = load_module(
    "review_collection_reconciliation_bundle", "ops/build_historical_replay_review_bundle.py"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def review_inputs():
    review_bundle = load_json(ROOT / "blinded-review-survey" / "data" / "review-bundle.json")
    display_bundle = load_json(ROOT / "lambda" / "ten_story_review_bundle.json")
    return review_bundle, display_bundle


def stage_map(display_bundle):
    return {
        stage["review_id"]: {"case_id": case["id"], "moment": stage["moment"]}
        for case in display_bundle["cases"]
        for stage in case["stages"]
    }


def judgments(choice):
    return {dimension: choice for dimension in reconcile.EXPECTED_DIMENSIONS}


def formal_export(review_bundle, reviewer_refs):
    submissions = []
    for index, reviewer_ref in enumerate(reviewer_refs):
        submitted_at = f"2026-08-20T0{index}:30:00+10:00"
        submissions.append({
            "reviewer_id": reviewer_ref,
            "submitted_at": submitted_at,
            "collection_id": reconcile.FORMAL_COLLECTION,
            "bundle_id": review_bundle["bundle_id"],
            "bundle_digest": review_bundle["bundle_digest"],
            "attestations": {
                "independent": True,
                "no_conflict": True,
                "no_blind_key": True,
            },
            "answers": [
                {
                    "review_id": package["review_id"],
                    "package_digest": package["package_digest"],
                    "judgments": judgments("OPTION_A"),
                    "preferred": "OPTION_A",
                    "confidence": 4,
                    "notes": "",
                    "committed_at": submitted_at,
                    "status": "ANSWER_LOCKED",
                }
                for package in review_bundle["packages"]
            ],
        })
    return {
        "schema_version": reconcile.FORMAL_EXPORT_VERSION,
        "collection_id": reconcile.FORMAL_COLLECTION,
        "submissions": submissions,
    }


def mainland_export(review_bundle, display_bundle, reviewer_refs):
    stages = stage_map(display_bundle)
    submissions = []
    for index, reviewer_ref in enumerate(reviewer_refs):
        submitted_at = f"2026-08-21T0{index}:30:00+10:00"
        answers = []
        for package in review_bundle["packages"]:
            review_id = package["review_id"]
            stage = stages[review_id]
            answers.append({
                "schema_version": reconcile.MAINLAND_ANSWER_VERSION,
                "review_id": review_id,
                "package_digest": package["package_digest"],
                "case_id": stage["case_id"],
                "moment": stage["moment"],
                "collection_id": reconcile.MAINLAND_COLLECTION,
                "bundle_digest": display_bundle["bundle_digest"],
                "source_bundle_id": review_bundle["bundle_id"],
                "source_bundle_digest": review_bundle["bundle_digest"],
                "reviewer_id": reviewer_ref,
                "committed_at": submitted_at,
                "judgments": judgments("OPTION_A"),
                "preferred": "OPTION_A",
                "confidence": 4,
                "notes": "",
                "status": "ANSWER_LOCKED",
            })
        submissions.append({
            "schema_version": reconcile.MAINLAND_SUBMISSION_VERSION,
            "collection_id": reconcile.MAINLAND_COLLECTION,
            "bundle_digest": display_bundle["bundle_digest"],
            "source_bundle_id": review_bundle["bundle_id"],
            "source_bundle_digest": review_bundle["bundle_digest"],
            "reviewer_id": reviewer_ref,
            "submitted_at": submitted_at,
            "attestations": {
                "independent": True,
                "no_conflict": True,
                "no_blind_key": True,
            },
            "answers": answers,
            "status": "SUBMITTED_LOCKED",
            "claim_boundary": "Separate mainland-access collection.",
        })
    return {
        "schema_version": reconcile.MAINLAND_EXPORT_VERSION,
        "collection_id": reconcile.MAINLAND_COLLECTION,
        "bundle_digest": display_bundle["bundle_digest"],
        "source_bundle_id": review_bundle["bundle_id"],
        "source_bundle_digest": review_bundle["bundle_digest"],
        "submissions": submissions,
    }


class ReviewCollectionReconciliationTests(unittest.TestCase):
    def test_four_cross_entry_reviewers_reconcile_and_aggregate(self):
        review_bundle, display_bundle = review_inputs()
        formal = reconcile.normalize_formal_export(
            formal_export(review_bundle, ["reviewer-formal-one", "reviewer-formal-two"]),
            review_bundle,
        )
        mainland = reconcile.normalize_mainland_export(
            mainland_export(review_bundle, display_bundle, ["reviewer-mainland-one", "reviewer-mainland-two"]),
            review_bundle,
            display_bundle,
        )
        combined = reconcile.reconcile_collections(review_bundle, formal + mainland)
        self.assertEqual(combined["reviewer_count"], 4)
        self.assertEqual(combined["package_count"], 30)
        self.assertEqual(combined["review_record_count"], 120)
        self.assertEqual(
            combined["source_collections"],
            {reconcile.FORMAL_COLLECTION: 2, reconcile.MAINLAND_COLLECTION: 2},
        )
        self.assertTrue(all(combined["compatibility_checks"].values()))
        self.assertEqual(combined["operational_mutations"], [])
        self.assertTrue(all(len(rows) == 4 for rows in combined["reviews_by_package"].values()))

        freeze = load_json(FIXTURE_DIR / "review_freeze_v3.json")
        corpus = load_json(FIXTURE_DIR / "corpus_v1.json")
        rubric = load_json(ROOT / "docs" / "decision_quality_rubric_v1.json")
        option_contract = load_json(ROOT / "docs" / "decision_option_contract_v3.json")
        built_bundle, key_bundle = review_builder.build_review_bundle(
            freeze, corpus, FIXTURE_DIR, rubric, option_contract
        )
        self.assertEqual(built_bundle, review_bundle)
        summary = reconcile.aggregate_corpus(
            combined, review_bundle, key_bundle, rubric
        )
        self.assertEqual(summary["reviewer_count"], 4)
        self.assertEqual(len(summary["package_summaries"]), 30)
        self.assertEqual(sum(summary["result_counts"].values()), 30)
        self.assertEqual(summary["operational_mutations"], [])

    def test_changed_mainland_package_digest_fails_closed(self):
        review_bundle, display_bundle = review_inputs()
        source = mainland_export(
            review_bundle, display_bundle, ["reviewer-mainland-one"]
        )
        source["submissions"][0]["answers"][0]["package_digest"] = "0" * 64
        with self.assertRaisesRegex(
            reconcile.ReviewReconciliationError, "package digest mismatch"
        ):
            reconcile.normalize_mainland_export(source, review_bundle, display_bundle)

    def test_incomplete_attestation_fails_closed(self):
        review_bundle, display_bundle = review_inputs()
        source = mainland_export(
            review_bundle, display_bundle, ["reviewer-mainland-one"]
        )
        source["submissions"][0]["attestations"]["no_conflict"] = False
        with self.assertRaisesRegex(
            reconcile.ReviewReconciliationError, "must have no conflict"
        ):
            reconcile.normalize_mainland_export(source, review_bundle, display_bundle)

    def test_duplicate_reviewer_across_surfaces_fails_closed(self):
        review_bundle, display_bundle = review_inputs()
        formal = reconcile.normalize_formal_export(
            formal_export(review_bundle, ["reviewer-shared-one"]), review_bundle
        )
        mainland = reconcile.normalize_mainland_export(
            mainland_export(review_bundle, display_bundle, ["reviewer-shared-one"]),
            review_bundle,
            display_bundle,
        )
        with self.assertRaisesRegex(
            reconcile.ReviewReconciliationError, "unique across entry surfaces"
        ):
            reconcile.reconcile_collections(review_bundle, formal + mainland)

    def test_changed_display_bundle_fails_closed(self):
        review_bundle, display_bundle = review_inputs()
        changed = copy.deepcopy(display_bundle)
        changed["cases"][0]["stages"][0]["package_digest"] = "0" * 64
        with self.assertRaisesRegex(
            reconcile.ReviewReconciliationError, "display bundle digest mismatch"
        ):
            reconcile.validate_mainland_display_bundle(changed, review_bundle)


if __name__ == "__main__":
    unittest.main()
