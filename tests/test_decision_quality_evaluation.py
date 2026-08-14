import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


capability = load_module("decision_evaluation_for_quality", "ops/evaluate_decision_capabilities.py")
quality = load_module("decision_quality_evaluation", "ops/evaluate_decision_quality.py")
FIXTURE = ROOT / "tests" / "fixtures" / "evaluation" / "a303_high_risk_route_v1.json"


def inputs():
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = capability.run_experiment(manifest)
    rubric = quality.load_default_rubric(ROOT)
    package, key = quality.build_review_package(manifest, report, rubric)
    return manifest, report, rubric, package, key


def review(package, reviewer_ref, preferred_option, high_option, reviewed_at):
    rows = []
    for option in package["options"]:
        score = 4 if option["option_id"] == high_option else 2
        rows.append({
            "option_id": option["option_id"],
            "dimension_scores": {
                "evidence_grounding": score,
                "risk_detection_and_proportionality": score,
                "policy_compliance": score,
                "actionability": score,
                "authority_compliance": score,
            },
        })
    return {
        "schema_version": "decision-quality-review.v1",
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
        "option_scores": rows,
        "preferred_option": preferred_option,
        "confidence": 4,
    }


class DecisionQualityEvaluationTests(unittest.TestCase):
    def test_rubric_is_complete_and_weights_sum_to_one(self):
        _, _, rubric, _, _ = inputs()
        quality.validate_rubric(rubric)
        self.assertAlmostEqual(sum(item["weight"] for item in rubric["dimensions"]), 1.0)
        self.assertEqual(rubric["interpretation_gate"]["minimum_independent_reviewers"], 3)

    def test_review_package_hides_variant_rule_and_capability_identity(self):
        _, _, _, package, key = inputs()
        rendered = json.dumps(package, sort_keys=True)
        self.assertNotIn("A303", rendered)
        self.assertNotIn("baseline-a303-off", rendered)
        self.assertNotIn("glap-a303-on", rendered)
        self.assertNotIn('"role"', rendered)
        self.assertNotIn('"capabilities"', rendered)
        self.assertIn("glap-a303-on", json.dumps(key, sort_keys=True))
        self.assertEqual(package["scenario"]["visible_evidence"][0]["evidence_id"], "EVIDENCE_1")

    def test_package_and_blind_key_are_deterministic_and_separate(self):
        manifest, report, rubric, package, key = inputs()
        second_package, second_key = quality.build_review_package(manifest, report, rubric)
        self.assertEqual(package, second_package)
        self.assertEqual(key, second_key)
        self.assertNotIn("mapping", package)
        self.assertEqual(key["package_digest"], package["package_digest"])

    def test_three_independent_reviews_can_pass_the_interpretation_gate(self):
        _, _, rubric, package, key = inputs()
        challenger_option = next(
            option_id
            for option_id, mapping in key["mapping"].items()
            if mapping["role"] == "CHALLENGER"
        )
        reviews = [
            review(package, f"reviewer-expert-{index}", challenger_option, challenger_option, f"2026-08-14T1{index}:00:00+10:00")
            for index in range(3)
        ]
        summary = quality.score_reviews(package, key, rubric, reviews)
        self.assertEqual(summary["status"], "EVALUATED_CONTROLLED_SYNTHETIC")
        self.assertEqual(summary["result"], "REVIEW_EVIDENCE_FAVORS_VARIANT")
        self.assertEqual(summary["favored_variant_id"], "glap-a303-on")
        self.assertFalse(summary["reviewer_identifiers_retained"])
        self.assertEqual(summary["operational_mutations"], [])

    def test_fewer_than_three_reviews_remain_pending(self):
        _, _, rubric, package, key = inputs()
        option_id = package["options"][0]["option_id"]
        one_review = review(package, "reviewer-expert-one", option_id, option_id, "2026-08-14T10:00:00+10:00")
        summary = quality.score_reviews(package, key, rubric, [one_review])
        self.assertEqual(summary["status"], "PENDING_EXPERT_REVIEWS")
        self.assertEqual(summary["claim_boundary"]["supports"], [])
        self.assertIsNone(summary["favored_variant_id"])

    def test_ties_cannot_turn_one_preference_into_false_consensus(self):
        _, _, rubric, package, key = inputs()
        option_id = package["options"][0]["option_id"]
        reviews = [
            review(package, "reviewer-expert-one", option_id, option_id, "2026-08-14T10:00:00+10:00"),
            review(package, "reviewer-expert-two", "TIE", option_id, "2026-08-14T11:00:00+10:00"),
            review(package, "reviewer-expert-three", "TIE", option_id, "2026-08-14T12:00:00+10:00"),
        ]
        summary = quality.score_reviews(package, key, rubric, reviews)
        self.assertEqual(summary["status"], "REQUIRES_ADJUDICATION")
        self.assertFalse(summary["gate_checks"]["minimum_non_tie_preferences_met"])

    def test_duplicate_or_unblinded_reviewer_fails_closed(self):
        _, _, rubric, package, key = inputs()
        option_id = package["options"][0]["option_id"]
        item = review(package, "reviewer-expert-one", option_id, option_id, "2026-08-14T10:00:00+10:00")
        with self.assertRaisesRegex(quality.ReviewContractError, "duplicate reviewer_ref"):
            quality.score_reviews(package, key, rubric, [item, copy.deepcopy(item)])
        unblinded = copy.deepcopy(item)
        unblinded["attestations"]["blind_key_access"] = True
        with self.assertRaisesRegex(quality.ReviewContractError, "blind-key access"):
            quality.score_reviews(package, key, rubric, [unblinded])

    def test_modified_package_or_invalid_score_fails_closed(self):
        _, _, rubric, package, key = inputs()
        changed_package = copy.deepcopy(package)
        changed_package["options"][0]["priority"] = "CRITICAL"
        with self.assertRaisesRegex(quality.ReviewContractError, "package was modified"):
            quality.score_reviews(changed_package, key, rubric, [])
        option_id = package["options"][0]["option_id"]
        item = review(package, "reviewer-expert-one", option_id, option_id, "2026-08-14T10:00:00+10:00")
        item["option_scores"][0]["dimension_scores"]["actionability"] = 5
        with self.assertRaisesRegex(quality.ReviewContractError, "score must be"):
            quality.score_reviews(package, key, rubric, [item])


if __name__ == "__main__":
    unittest.main()
