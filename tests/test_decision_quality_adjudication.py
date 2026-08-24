import copy
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_decision_quality_adjudication",
    ROOT / "ops" / "validate_decision_quality_adjudication.py",
)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


class DecisionQualityAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.record = validator.load_json(validator.RECORD_PATH)
        self.reconciliation = validator.load_json(validator.RECONCILIATION_PATH)
        self.bundle = validator.load_json(validator.BUNDLE_PATH)
        self.rubric = validator.load_json(validator.RUBRIC_PATH)
        self.corpus_summary = validator.load_json(validator.CORPUS_SUMMARY_PATH)
        self.t1_disposition = validator.load_json(validator.T1_DISPOSITION_PATH)
        self.t2_disposition = validator.load_json(validator.T2_DISPOSITION_PATH)

    def errors(self, record=None):
        return validator.validate_record(
            record or self.record, self.bundle, today=date(2026, 8, 24)
        )

    def reconciliation_errors(self, record=None, predecessor=None):
        return validator.validate_reconciliation(
            record or self.reconciliation,
            predecessor or self.record,
            self.bundle,
            self.rubric,
            today=date(2026, 8, 24),
        )

    def corpus_errors(self, record=None):
        return validator.validate_corpus_summary(
            record or self.corpus_summary,
            self.bundle,
            self.rubric,
            today=date(2026, 8, 24),
        )

    def disposition_errors(self, record, predecessor=None):
        return validator.validate_human_disposition(
            record,
            self.corpus_summary,
            self.bundle,
            predecessor=predecessor,
            today=date(2026, 8, 24),
        )

    def test_pending_record_is_valid_and_content_addressed(self):
        self.assertEqual(self.errors(), [])

    def test_resolution_cannot_be_inferred_without_named_owner_record(self):
        record = copy.deepcopy(self.record)
        record["adjudication"]["status"] = "RESOLVED_HUMAN_ADJUDICATION"
        record["adjudication"]["resolution"] = "FAVORS_GLAP_A303_ON"
        self.assertIn(
            "no adjudication resolution is authorized in the pending record",
            self.errors(record),
        )

    def test_original_reviews_cannot_be_changed_or_extended(self):
        record = copy.deepcopy(self.record)
        record["source_evidence"]["review_count"] = 5
        record["governance"]["original_review_count"] = 5
        errors = self.errors(record)
        self.assertIn("the frozen 2:2 aggregate declaration has changed", errors)
        self.assertIn(
            "adjudication cannot rewrite or extend the four original reviews", errors
        )

    def test_package_and_digest_drift_fail_closed(self):
        record = copy.deepcopy(self.record)
        record["source_evidence"]["package_digest"] = "0" * 64
        errors = self.errors(record)
        self.assertIn("the adjudication package identity has drifted", errors)
        self.assertIn("adjudication record digest mismatch", errors)

    def test_adjudication_cannot_reactivate_a303_or_gain_authority(self):
        record = copy.deepcopy(self.record)
        record["authority"]["a303_reactivation_allowed"] = True
        record["authority"]["aws_write_allowed"] = True
        self.assertIn(
            "the adjudication record has gained operational authority",
            self.errors(record),
        )

    def test_schema_preserves_pending_and_append_only_resolution_shapes(self):
        schema = json.loads(
            (ROOT / "docs" / "decision_quality_adjudication_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        rendered = json.dumps(schema, sort_keys=True)
        self.assertIn("PENDING_HUMAN_ADJUDICATION", rendered)
        self.assertIn("RESOLVED_HUMAN_ADJUDICATION", rendered)
        self.assertIn("append_new_record_for_resolution", rendered)
        self.assertIn("A303_REACTIVATION", rendered)

    def test_fifth_review_reconciliation_is_valid_and_content_addressed(self):
        self.assertEqual(self.reconciliation_errors(), [])

    def test_fifth_review_still_fails_the_frozen_consensus_gate(self):
        result = self.reconciliation["updated_result"]
        self.assertEqual(result["preference_consensus_pct"], 60.0)
        self.assertEqual(result["minimum_preference_consensus_pct"], 66.67)
        self.assertFalse(result["gate_checks"]["preference_consensus_met"])
        self.assertEqual(result["result"], "REVIEWERS_DO_NOT_AGREE")
        self.assertIsNone(result["favored_variant_id"])

    def test_fifth_review_record_does_not_retain_identity_or_answers(self):
        source = self.reconciliation["source_evidence"]
        self.assertFalse(source["reviewer_identifiers_retained"])
        self.assertFalse(source["account_credentials_retained"])
        self.assertFalse(source["answer_content_retained"])
        rendered = json.dumps(self.reconciliation, sort_keys=True).lower()
        self.assertNotIn("glap-review-99-private", rendered)
        self.assertNotIn("reviewer-private", rendered)

    def test_fifth_review_cannot_be_promoted_to_a_winner(self):
        record = copy.deepcopy(self.reconciliation)
        record["updated_result"]["result"] = "REVIEW_EVIDENCE_FAVORS_VARIANT"
        record["updated_result"]["favored_variant_id"] = "glap-a303-on"
        self.assertIn(
            "the frozen five-review gate result has changed",
            self.reconciliation_errors(record),
        )

    def test_fifth_review_must_reference_the_immutable_predecessor(self):
        record = copy.deepcopy(self.reconciliation)
        record["predecessor"]["record_digest"] = "0" * 64
        errors = self.reconciliation_errors(record)
        self.assertIn("the five-review reconciliation predecessor has drifted", errors)
        self.assertIn("five-review reconciliation digest mismatch", errors)

    def test_five_review_schema_preserves_privacy_and_authority_boundaries(self):
        schema = json.loads(
            (
                ROOT
                / "docs"
                / "decision_quality_five_review_reconciliation_v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        rendered = json.dumps(schema, sort_keys=True)
        self.assertIn("INDIVIDUAL_REVIEW_DISCLOSURE", rendered)
        self.assertIn("FULL_FIVE_REVIEW_CORPUS_RESULT", rendered)
        self.assertIn("PENDING_HUMAN_ADJUDICATION", rendered)

    def test_full_five_review_corpus_summary_is_valid_and_content_addressed(self):
        self.assertEqual(self.corpus_errors(), [])
        self.assertEqual(self.corpus_summary["source_evidence"]["review_record_count"], 150)
        self.assertEqual(
            self.corpus_summary["corpus_result"],
            {
                "review_evidence_favors_variant_count": 14,
                "reviewers_do_not_agree_count": 16,
                "favored_variant_counts": {"glap-a303-on": 14},
                "unanimous_control_tie_count": 14,
            },
        )

    def test_full_corpus_summary_retains_no_identity_or_answer_content(self):
        record = self.corpus_summary
        self.assertEqual(
            record["privacy"],
            {
                "reviewer_identifiers_retained": False,
                "credentials_retained": False,
                "answer_content_retained": False,
                "notes_retained": False,
                "raw_exports_retained": False,
            },
        )
        rendered = json.dumps(record, sort_keys=True).lower()
        self.assertNotIn("private-reviewer-name", rendered)
        self.assertNotIn("glap-review-99-private", rendered)
        self.assertNotIn("answers", rendered)

    def test_full_corpus_summary_cannot_promote_a_no_winner_package(self):
        record = copy.deepcopy(self.corpus_summary)
        record["non_control_no_winner_packages"][1]["result"] = (
            "REVIEW_EVIDENCE_FAVORS_VARIANT"
        )
        self.assertIn(
            "the five-review non-control no-winner set has changed",
            self.corpus_errors(record),
        )

    def test_both_named_human_dispositions_retain_inconclusive(self):
        self.assertEqual(
            self.disposition_errors(self.t1_disposition, predecessor=self.record), []
        )
        self.assertEqual(self.disposition_errors(self.t2_disposition), [])
        self.assertEqual(
            {
                self.t1_disposition["disposition"]["resolution"],
                self.t2_disposition["disposition"]["resolution"],
            },
            {"RETAIN_INCONCLUSIVE"},
        )

    def test_t1_resolution_appends_to_pending_record_and_t2_starts_own_lineage(self):
        self.assertEqual(self.t1_disposition["record_version"], 2)
        self.assertEqual(
            self.t1_disposition["supersedes_record_digest"],
            self.record["record_digest"],
        )
        self.assertEqual(self.t2_disposition["record_version"], 1)
        self.assertIsNone(self.t2_disposition["supersedes_record_digest"])

    def test_disposition_cannot_turn_no_winner_into_a_winner(self):
        record = copy.deepcopy(self.t2_disposition)
        record["disposition"]["resolution"] = "FAVORS_GLAP_A303_ON"
        self.assertIn(
            "the named-human retain-inconclusive disposition has changed",
            self.disposition_errors(record),
        )

    def test_disposition_cannot_override_raw_review_or_gain_authority(self):
        record = copy.deepcopy(self.t1_disposition)
        record["package_evidence"]["raw_review_result"] = (
            "REVIEW_EVIDENCE_FAVORS_VARIANT"
        )
        record["authority"]["a303_reactivation_allowed"] = True
        errors = self.disposition_errors(record, predecessor=self.record)
        self.assertIn("the human disposition package evidence has drifted", errors)
        self.assertIn("the no-winner consensus gate has been overridden", errors)
        self.assertIn("the human disposition has gained operational authority", errors)

    def test_disposition_records_retain_no_human_identity_or_answers(self):
        for record in (self.t1_disposition, self.t2_disposition):
            self.assertFalse(record["privacy"]["study_owner_identity_retained"])
            self.assertFalse(record["privacy"]["reviewer_identifiers_retained"])
            self.assertFalse(record["privacy"]["answer_content_retained"])
            rendered = json.dumps(record, sort_keys=True).lower()
            self.assertNotIn("glap-review-99-private", rendered)
            self.assertNotIn("reviewer-private", rendered)


if __name__ == "__main__":
    unittest.main()
