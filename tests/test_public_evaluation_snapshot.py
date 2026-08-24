import copy
import importlib.util
import json
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_public_evaluation_snapshot",
    ROOT / "ops" / "export_public_evaluation_snapshot.py",
)
EXPORTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = EXPORTER
SPEC.loader.exec_module(EXPORTER)


class PublicEvaluationSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EXPORTER.load_json(EXPORTER.SOURCE_PATH)
        cls.bundle = EXPORTER.load_json(EXPORTER.BUNDLE_PATH)
        cls.rubric = EXPORTER.load_json(EXPORTER.RUBRIC_PATH)
        cls.snapshot = EXPORTER.load_json(EXPORTER.SNAPSHOT_PATH)

    def test_tracked_snapshot_is_exact_validated_projection(self):
        generated = EXPORTER.build_public_snapshot(
            self.source, self.bundle, self.rubric
        )
        self.assertEqual(generated, self.snapshot)
        self.assertEqual(
            EXPORTER.validate_public_snapshot(
                self.snapshot, today=date(2026, 8, 25)
            ),
            [],
        )

    def test_snapshot_contains_only_aggregate_safe_fields(self):
        self.assertEqual(EXPORTER._protected_keys(self.snapshot), set())
        rendered = json.dumps(self.snapshot, sort_keys=True).lower()
        for private_marker in (
            "glap-review-",
            "@",
            "human-evaluation-story.v2",
            "glap-ten-story-review.v1",
        ):
            with self.subTest(private_marker=private_marker):
                self.assertNotIn(private_marker, rendered)

        self.assertEqual(self.snapshot["corpus"]["case_count"], 10)
        self.assertEqual(self.snapshot["corpus"]["cutoff_count"], 30)
        self.assertEqual(self.snapshot["corpus"]["complete_review_count"], 5)
        self.assertEqual(self.snapshot["corpus"]["locked_review_record_count"], 150)

    def test_snapshot_fails_closed_on_future_date_or_count_drift(self):
        future = copy.deepcopy(self.snapshot)
        future["evaluation_as_of_date"] = "2026-08-26"
        self.assertTrue(
            any(
                "future-dated" in error
                for error in EXPORTER.validate_public_snapshot(
                    future, today=date(2026, 8, 25)
                )
            )
        )

        drifted = copy.deepcopy(self.snapshot)
        drifted["corpus"]["locked_review_record_count"] = 149
        self.assertTrue(
            any(
                "do not reconcile" in error
                for error in EXPORTER.validate_public_snapshot(drifted)
            )
        )

    def test_snapshot_fails_closed_on_private_field_or_authority(self):
        private = copy.deepcopy(self.snapshot)
        private["decision_quality"]["review_id"] = "private"
        errors = EXPORTER.validate_public_snapshot(private)
        self.assertTrue(any("protected source fields" in error for error in errors))

        authority = copy.deepcopy(self.snapshot)
        authority["authority"]["action_mutation_allowed"] = True
        errors = EXPORTER.validate_public_snapshot(authority)
        self.assertTrue(any("gained authority" in error for error in errors))

    def test_invalid_source_cannot_generate_a_public_snapshot(self):
        source = copy.deepcopy(self.source)
        source["privacy"]["answer_content_retained"] = True
        with self.assertRaisesRegex(ValueError, "source corpus is invalid"):
            EXPORTER.build_public_snapshot(source, self.bundle, self.rubric)

    def test_schema_closes_privacy_authority_and_unknown_fields(self):
        schema = EXPORTER.load_json(
            ROOT / "docs" / "public_evaluation_snapshot_v1.schema.json"
        )
        self.assertFalse(schema["additionalProperties"])
        for section in ("corpus", "decision_quality", "privacy", "authority"):
            self.assertFalse(schema["properties"][section]["additionalProperties"])
        for definition in schema["properties"]["privacy"]["properties"].values():
            self.assertIs(definition["const"], False)
        for definition in schema["properties"]["authority"]["properties"].values():
            self.assertIs(definition["const"], False)


if __name__ == "__main__":
    unittest.main()
