import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "decision_memory_evaluation",
    ROOT / "ops" / "evaluate_decision_memory_capability.py",
)
evaluation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(evaluation)
FIXTURE = (
    ROOT / "tests" / "fixtures" / "evaluation" / "decision_memory_ablation_v1.json"
)


def manifest():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class DecisionMemoryEvaluationTests(unittest.TestCase):
    def test_v3_schema_freezes_decision_memory_without_a_rule_contract(self):
        schema = json.loads(
            (ROOT / "docs" / "evaluation_experiment_v3.schema.json").read_text(
                encoding="utf-8"
            )
        )
        context = schema["properties"]["fixed_context"]["properties"]
        self.assertEqual(
            context["decision_procedure_version"]["const"],
            "decision-memory-review.v1",
        )
        self.assertNotIn("rule_contract_version", context)
        memory = schema["$defs"]["memory"]["properties"]
        self.assertEqual(memory["outcome_evidence_class"]["const"], "NOT_EVALUATED")

    def test_decision_memory_is_the_only_difference_and_is_attributed(self):
        report = evaluation.run_experiment(manifest())
        decisions = {item["role"]: item["decision"] for item in report["variants"]}
        self.assertEqual(decisions["BASELINE"]["recommendation"], "MONITOR_EVIDENCE")
        self.assertEqual(decisions["CHALLENGER"]["recommendation"], "REQUEST_BOUNDED_REVIEW")
        self.assertTrue(report["comparison"]["intended_visibility_delta"])
        self.assertEqual(report["comparison"]["attribution"], "ATTRIBUTED_TO_DECISION_MEMORY")
        self.assertEqual(report["evaluation_layers"]["capability_attribution"]["status"], "PASS")

    def test_variants_share_evidence_and_memory_source_snapshot(self):
        report = evaluation.run_experiment(manifest())
        variants = {item["role"]: item for item in report["variants"]}
        expected_memories = [
            "matching-reviewed-memory-v1",
            "nonmatching-reviewed-memory-v1",
        ]
        for variant in variants.values():
            self.assertEqual(variant["trace"]["fixed_evidence_ids"], ["current-operational-watch-v1"])
            self.assertEqual(variant["trace"]["cutoff_eligible_memory_ids"], expected_memories)
        self.assertEqual(variants["BASELINE"]["trace"]["decision_visible_memory_ids"], [])
        self.assertEqual(
            variants["CHALLENGER"]["trace"]["decision_visible_memory_ids"],
            expected_memories,
        )
        self.assertEqual(
            variants["CHALLENGER"]["trace"]["matching_memory_ids"],
            ["matching-reviewed-memory-v1"],
        )

    def test_post_cutoff_evidence_and_memory_are_never_visible(self):
        report = evaluation.run_experiment(manifest())
        self.assertEqual(
            report["input_window"]["post_cutoff_evidence_ids"],
            ["post-cutoff-operational-update-v1"],
        )
        self.assertEqual(
            report["input_window"]["post_cutoff_memory_ids"],
            ["post-cutoff-matching-memory-v1"],
        )
        for variant in report["variants"]:
            self.assertNotIn(
                "post-cutoff-matching-memory-v1",
                variant["trace"]["decision_visible_memory_ids"],
            )

    def test_run_is_deterministic_read_only_and_capability_neutral(self):
        first = evaluation.run_experiment(manifest())
        second = evaluation.run_experiment(manifest())
        self.assertEqual(first, second)
        self.assertEqual(first["operational_mutations"], [])
        self.assertEqual(first["evaluation_layers"]["system_correctness"]["status"], "PASS")
        self.assertIn("AUTONOMOUS_LEARNING", first["claim_boundary"]["not_supported"])
        self.assertNotIn("A303", json.dumps(first))

    def test_quality_outcome_and_learning_are_not_inferred(self):
        report = evaluation.run_experiment(manifest())
        self.assertEqual(report["evaluation_layers"]["decision_quality"]["status"], "NOT_EVALUATED")
        self.assertEqual(report["evaluation_layers"]["business_outcome_effect"]["status"], "NOT_EVALUATED")

    def test_manifest_fails_closed_if_external_evidence_is_added(self):
        changed = copy.deepcopy(manifest())
        changed["variants"][1]["capabilities"]["EXTERNAL_EVIDENCE"] = True
        with self.assertRaisesRegex(evaluation.ContractError, "keys must be exactly"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_if_memory_attaches_outcome_evidence(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["decision_memory"][0]["outcome_evidence_class"] = "OBSERVED_FACTUAL"
        with self.assertRaisesRegex(evaluation.ContractError, "cannot attach Outcome evidence"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_without_matching_cutoff_eligible_memory(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["decision_memory"][0]["context_key"] = "CONTROLLED_CONTEXT_OTHER_03"
        with self.assertRaisesRegex(evaluation.ContractError, "cutoff-eligible matching reviewed memory"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_for_future_controlled_replay(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["cutoff_at"] = "2099-03-07T09:00:00+11:00"
        changed["scenario"]["operational_state"]["as_of_at"] = "2099-03-07T09:00:00+11:00"
        with self.assertRaisesRegex(evaluation.ContractError, "current Sydney date"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_when_memory_availability_precedes_decision(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["decision_memory"][0]["available_at"] = "2025-02-07T07:55:00+11:00"
        with self.assertRaisesRegex(evaluation.ContractError, "cannot precede decided_at"):
            evaluation.run_experiment(changed)


if __name__ == "__main__":
    unittest.main()
