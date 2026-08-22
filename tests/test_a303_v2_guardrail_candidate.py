import copy
import importlib.util
import json
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


candidate = load_module(
    "a303_v2_guardrail_candidate_for_tests",
    "ops/evaluate_a303_v2_guardrail_candidate.py",
)


class A303V2GuardrailCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposal = json.loads(
            (ROOT / "docs" / "a303_v2_eligibility_guardrail_proposal.json").read_text(
                encoding="utf-8"
            )
        )
        cls.source_result = json.loads(
            (
                ROOT / "docs" / "a303_synthetic_outcome_robustness_result_v1.json"
            ).read_text(encoding="utf-8")
        )
        cls.simulator = json.loads(
            (ROOT / "docs" / "a303_outcome_simulator_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.protocol = json.loads(
            (
                ROOT / "docs" / "a303_outcome_sensitivity_protocol_v1.json"
            ).read_text(encoding="utf-8")
        )
        cls.gate = json.loads(
            (ROOT / "docs" / "a303_synthetic_capability_gate_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.bundle = json.loads(
            (ROOT / "blinded-review-survey" / "data" / "review-bundle.json").read_text(
                encoding="utf-8"
            )
        )
        cls.corpus_path = (
            ROOT / "tests" / "fixtures" / "historical_replay" / "corpus_v1.json"
        )
        cls.corpus = json.loads(cls.corpus_path.read_text(encoding="utf-8"))
        corpus_report = candidate._ROBUSTNESS._CORPUS.run_corpus(
            cls.corpus, cls.corpus_path.parent
        )
        changed = {
            (scenario["scenario_id"], cutoff["cutoff_id"]): cutoff["comparison"][
                "decision_changed"
            ]
            for scenario in corpus_report["scenario_reports"]
            for cutoff in scenario["cutoff_results"]
        }
        split_case = (
            "new-zealand-cyclone-gabrielle-roads-2023-v1",
            "T1_COROMANDEL_HIGHWAY_CLOSURES_CONFIRMED",
        )
        package_summaries = []
        for package in cls.bundle["packages"]:
            scenario = package["scenario"]
            key = (scenario["scenario_id"], scenario["cutoff_id"])
            favors_a303 = changed[key] and key != split_case
            package_summaries.append(
                {
                    "review_id": package["review_id"],
                    "package_digest": package["package_digest"],
                    "review_count": 4,
                    "result": (
                        "REVIEW_EVIDENCE_FAVORS_VARIANT"
                        if favors_a303
                        else "REVIEWERS_DO_NOT_AGREE"
                    ),
                    "favored_variant_id": "glap-a303-on" if favors_a303 else None,
                }
            )
        cls.quality = {
            "schema_version": "decision-quality-corpus-summary.v1",
            "bundle_id": cls.bundle["bundle_id"],
            "bundle_digest": cls.bundle["bundle_digest"],
            "reviewer_count": 4,
            "package_count": 30,
            "package_summaries": package_summaries,
        }
        cls.report = cls.evaluate()

    @classmethod
    def evaluate(cls, *, proposal=None):
        return candidate.run_candidate_screen(
            cls.proposal if proposal is None else proposal,
            cls.source_result,
            cls.simulator,
            cls.protocol,
            cls.gate,
            cls.quality,
            cls.bundle,
            cls.corpus,
            cls.corpus_path.parent,
        )

    def test_neither_guardrail_candidate_passes_the_development_gate(self):
        self.assertEqual(
            self.report["slice_conclusion"]["status"],
            "NO_A303_V2_GUARDRAIL_CANDIDATE_PASSES_DEVELOPMENT_GATE",
        )
        self.assertTrue(self.report["slice_conclusion"]["human_decision_required"])
        self.assertTrue(
            all(
                item["development_disposition"]
                == "REJECT_OR_FUNDAMENTALLY_REDESIGN"
                for item in self.report["candidate_results"]
            )
        )

    def test_central_safe_candidate_exposes_action_subset_risk(self):
        result = self.report["candidate_results"][0]
        self.assertEqual(result["candidate_id"], "a303-v2-central-safe")
        self.assertEqual(
            result["coverage"],
            {
                "action_opportunity_count": 2,
                "distinct_action_scenario_count": 2,
                "abstention_opportunity_count": 14,
                "negative_control_count": 14,
            },
        )
        self.assertEqual(
            result["action_subset"]["interpretation_counts"],
            {
                "MODEL_FAVORS_A303_ON": 372,
                "MODEL_FAVORS_A303_OFF": 66,
                "NO_MATERIAL_MODELED_DIFFERENCE": 48,
            },
        )
        self.assertEqual(result["action_subset"]["non_negative_pct"], 86.42)

    def test_full_set_neutrality_cannot_hide_abstention(self):
        central_safe, stable_only = self.report["candidate_results"]
        self.assertEqual(
            central_safe["full_opportunity_set"]["non_negative_pct"], 98.3
        )
        self.assertIn(
            "minimum_action_subset_non_negative_pct", central_safe["failed_checks"]
        )
        self.assertEqual(stable_only["coverage"]["action_opportunity_count"], 0)
        self.assertEqual(
            stable_only["full_opportunity_set"]["non_negative_pct"], 100.0
        )
        self.assertIn("minimum_action_opportunity_count", stable_only["failed_checks"])

    def test_same_corpus_candidates_are_never_confirmatory(self):
        for result in self.report["candidate_results"]:
            self.assertEqual(
                result["confirmatory_eligibility"],
                "NOT_ELIGIBLE_POST_HOC_SAME_CORPUS",
            )
        self.assertFalse(
            self.report["validation_boundary"][
                "same_corpus_can_satisfy_confirmatory_gate"
            ]
        )

    def test_anti_abstention_gate_cannot_be_weakened(self):
        proposal = copy.deepcopy(self.proposal)
        proposal["anti_abstention_gate"]["minimum_action_opportunity_count"] = 0
        with self.assertRaisesRegex(candidate.GuardrailCandidateError, "weakened"):
            self.evaluate(proposal=proposal)

    def test_proposal_cannot_gain_activation_authority(self):
        proposal = copy.deepcopy(self.proposal)
        proposal["authority"]["rule_activation_allowed"] = True
        with self.assertRaisesRegex(candidate.GuardrailCandidateError, "gained"):
            self.evaluate(proposal=proposal)

    def test_tracked_result_matches_reproducible_candidate_report(self):
        tracked = json.loads(
            (
                ROOT / "docs" / "a303_v2_guardrail_development_result_v1.json"
            ).read_text(encoding="utf-8")
        )
        schema = json.loads(
            (
                ROOT
                / "docs"
                / "a303_v2_guardrail_development_result_v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(tracked), set(schema["required"]))
        self.assertEqual(set(tracked), set(schema["properties"]))
        candidate_schema = schema["properties"]["candidate_results"]["items"]
        for item in tracked["candidate_results"]:
            self.assertEqual(set(item), set(candidate_schema["required"]))
            self.assertEqual(set(item), set(candidate_schema["properties"]))
        self.assertEqual(tracked["proposal_sha256"], self.report["proposal_digest"])
        self.assertEqual(
            tracked["source_result_sha256"], self.report["source_result_digest"]
        )
        self.assertEqual(tracked["slice_conclusion"], self.report["slice_conclusion"])
        for expected, actual in zip(
            tracked["candidate_results"], self.report["candidate_results"]
        ):
            self.assertEqual(expected["candidate_id"], actual["candidate_id"])
            self.assertEqual(
                expected["action_opportunity_count"],
                actual["coverage"]["action_opportunity_count"],
            )
            self.assertEqual(
                expected["action_subset_non_negative_pct"],
                actual["action_subset"]["non_negative_pct"],
            )
            self.assertEqual(expected["failed_checks"], actual["failed_checks"])


if __name__ == "__main__":
    unittest.main()
