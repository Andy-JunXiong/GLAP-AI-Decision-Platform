import copy
import importlib.util
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reconcile_live_five_reviews_readonly",
    ROOT / "ops" / "reconcile_live_five_reviews_readonly.py",
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class LiveFiveReviewReconciliationTests(unittest.TestCase):
    def test_mainland_export_filters_wrong_collection_and_bundle(self):
        display = {
            "bundle_digest": "display",
            "source_bundle_id": "source-id",
            "source_bundle_digest": "source-digest",
        }
        eligible = {
            "collection_id": "glap-ten-story-review.v1",
            "bundle_digest": "display",
            "source_bundle_id": "source-id",
            "source_bundle_digest": "source-digest",
            "submitted_at": "2026-08-22T00:00:00Z",
            "reviewer_id": "reviewer-eligible",
        }
        wrong = copy.deepcopy(eligible)
        wrong["collection_id"] = "superseded"
        result = module.build_mainland_export([wrong, eligible], display)
        self.assertEqual(result["submissions"], [eligible])

    def test_aggregate_safety_rejects_private_fields(self):
        with self.assertRaisesRegex(ValueError, "private review field"):
            module.assert_aggregate_safe({"submissions": []})
        with self.assertRaisesRegex(ValueError, "pseudonymous reviewer"):
            module.assert_aggregate_safe({"value": "reviewer-private"})

    def test_aggregate_safety_accepts_identity_free_summary(self):
        module.assert_aggregate_safe(
            {
                "reviewer_count": 5,
                "reviewer_identifiers_retained": False,
                "result_counts": {"REVIEWERS_DO_NOT_AGREE": 1},
            }
        )


if __name__ == "__main__":
    unittest.main()
