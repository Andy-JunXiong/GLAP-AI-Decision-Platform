import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "historical_replay"
FREEZE_PATH = FIXTURE_DIR / "review_freeze_v1.json"
CORPUS_PATH = FIXTURE_DIR / "corpus_v1.json"
RUBRIC_PATH = ROOT / "docs" / "decision_quality_rubric_v1.json"


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


review_bundle = load_module(
    "historical_replay_review_bundle", "ops/build_historical_replay_review_bundle.py"
)
quality = load_module("historical_replay_review_quality", "ops/evaluate_decision_quality.py")


def inputs():
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    return freeze, corpus, rubric


class HistoricalReplayReviewBundleTests(unittest.TestCase):
    def test_freeze_binds_ten_scenarios_and_thirty_cutoffs(self):
        freeze, corpus, rubric = inputs()
        report, scenarios = review_bundle.validate_freeze(
            freeze, corpus, FIXTURE_DIR, rubric
        )
        self.assertEqual(report["summary"]["scenario_count"], 10)
        self.assertEqual(report["summary"]["cutoff_count"], 30)
        self.assertEqual(len(scenarios), 10)
        self.assertEqual(
            [item["scenario_id"] for item in scenarios],
            [item["scenario_id"] for item in corpus["scenarios"]],
        )

    def test_bundle_is_deterministic_complete_and_immutable(self):
        freeze, corpus, rubric = inputs()
        bundle, keys = review_bundle.build_review_bundle(
            freeze, corpus, FIXTURE_DIR, rubric
        )
        second_bundle, second_keys = review_bundle.build_review_bundle(
            freeze, corpus, FIXTURE_DIR, rubric
        )
        self.assertEqual(bundle, second_bundle)
        self.assertEqual(keys, second_keys)
        self.assertEqual(bundle["package_count"], 30)
        self.assertEqual(keys["package_count"], 30)
        self.assertEqual(bundle["operational_mutations"], [])
        self.assertEqual(keys["operational_mutations"], [])
        payload = {key: value for key, value in bundle.items() if key != "bundle_digest"}
        self.assertEqual(bundle["bundle_digest"], review_bundle.canonical_digest(payload))
        for package, key in zip(bundle["packages"], keys["keys"]):
            package_payload = {
                field: value for field, value in package.items() if field != "package_digest"
            }
            self.assertEqual(
                package["package_digest"], review_bundle.canonical_digest(package_payload)
            )
            self.assertEqual(key["package_digest"], package["package_digest"])

    def test_public_bundle_does_not_expose_variant_or_key_identity(self):
        freeze, corpus, rubric = inputs()
        bundle, keys = review_bundle.build_review_bundle(
            freeze, corpus, FIXTURE_DIR, rubric
        )
        public_text = json.dumps(bundle, sort_keys=True)
        for prohibited in (
            "A303",
            "baseline-a303-off",
            "glap-a303-on",
            '"role"',
            '"capabilities"',
            "rule_fired",
            "decision_changed",
            "attribution",
        ):
            self.assertNotIn(prohibited, public_text)
        private_text = json.dumps(keys, sort_keys=True)
        self.assertIn("glap-a303-on", private_text)
        self.assertIn('"mapping"', private_text)

    def test_post_decision_reveal_sources_never_enter_review_evidence(self):
        freeze, corpus, rubric = inputs()
        _, keys = review_bundle.build_review_bundle(
            freeze, corpus, FIXTURE_DIR, rubric
        )
        reveal_source_ids = set()
        for entry in corpus["scenarios"]:
            scenario = json.loads((FIXTURE_DIR / entry["file"]).read_text(encoding="utf-8"))
            reveal_source_ids.update(item["source_id"] for item in scenario["reveal_timeline"])
        mapped_source_ids = {
            evidence["source_id"]
            for key in keys["keys"]
            for evidence in key["evidence_mapping"].values()
        }
        self.assertTrue(reveal_source_ids)
        self.assertTrue(mapped_source_ids)
        self.assertTrue(reveal_source_ids.isdisjoint(mapped_source_ids))

    def test_changed_rubric_or_scenario_fails_closed(self):
        freeze, corpus, rubric = inputs()
        changed_rubric = copy.deepcopy(rubric)
        changed_rubric["dimensions"][0]["question"] += " changed"
        with self.assertRaisesRegex(
            review_bundle.HistoricalReviewContractError, "rubric digest mismatch"
        ):
            review_bundle.validate_freeze(freeze, corpus, FIXTURE_DIR, changed_rubric)
        changed_freeze = copy.deepcopy(freeze)
        changed_freeze["scenarios"][0]["scenario_digest"] = "0" * 64
        with self.assertRaisesRegex(
            review_bundle.HistoricalReviewContractError, "scenario digest mismatch"
        ):
            review_bundle.validate_freeze(changed_freeze, corpus, FIXTURE_DIR, rubric)

        changed_claim = copy.deepcopy(freeze)
        changed_claim["claim_boundary"]["does_not_support"].remove(
            "PRODUCTION_READINESS"
        )
        with self.assertRaisesRegex(
            review_bundle.HistoricalReviewContractError,
            "excluded claims differ",
        ):
            review_bundle.validate_freeze(changed_claim, corpus, FIXTURE_DIR, rubric)

    def test_each_package_is_compatible_with_pending_quality_scoring(self):
        freeze, corpus, rubric = inputs()
        bundle, keys = review_bundle.build_review_bundle(
            freeze, corpus, FIXTURE_DIR, rubric
        )
        pairs = set()
        for package, key in zip(bundle["packages"], keys["keys"]):
            summary = quality.score_reviews(package, key, rubric, [])
            self.assertEqual(summary["status"], "PENDING_EXPERT_REVIEWS")
            self.assertEqual(summary["claim_boundary"]["supports"], [])
            self.assertEqual(summary["operational_mutations"], [])
            scenario = package["scenario"]
            pairs.add((scenario["scenario_id"], scenario["cutoff_id"]))
        self.assertEqual(len(pairs), 30)


if __name__ == "__main__":
    unittest.main()
