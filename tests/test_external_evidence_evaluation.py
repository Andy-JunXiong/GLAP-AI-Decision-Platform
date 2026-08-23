import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "external_evidence_evaluation",
    ROOT / "ops" / "evaluate_external_evidence_capability.py",
)
evaluation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(evaluation)
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "evaluation"
    / "external_evidence_ablation_v1.json"
)


def manifest():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class ExternalEvidenceEvaluationTests(unittest.TestCase):
    def test_v2_schema_freezes_a_capability_neutral_boundary(self):
        schema = json.loads(
            (ROOT / "docs" / "evaluation_experiment_v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            schema["properties"]["fixed_context"]["properties"][
                "decision_procedure_version"
            ]["const"],
            "external-evidence-review.v1",
        )
        self.assertEqual(
            schema["properties"]["hypothesis"]["properties"][
                "changed_capability"
            ]["const"],
            "EXTERNAL_EVIDENCE",
        )
        self.assertNotIn("rule_contract_version", schema["properties"]["fixed_context"]["properties"])

    def test_external_evidence_is_the_only_difference_and_is_attributed(self):
        report = evaluation.run_experiment(manifest())
        decisions = {item["role"]: item["decision"] for item in report["variants"]}
        self.assertEqual(decisions["BASELINE"]["recommendation"], "MONITOR_EVIDENCE")
        self.assertEqual(decisions["CHALLENGER"]["recommendation"], "REQUEST_BOUNDED_REVIEW")
        self.assertTrue(report["comparison"]["intended_visibility_delta"])
        self.assertEqual(report["comparison"]["attribution"], "ATTRIBUTED_TO_EXTERNAL_EVIDENCE")
        self.assertEqual(report["evaluation_layers"]["capability_attribution"]["status"], "PASS")

    def test_variants_share_the_source_snapshot_but_only_challenger_uses_external_evidence(self):
        report = evaluation.run_experiment(manifest())
        variants = {item["role"]: item for item in report["variants"]}
        expected_source = [
            "operational-watch-signal-v1",
            "external-disruption-confirmation-v1",
        ]
        for variant in variants.values():
            self.assertEqual(variant["trace"]["cutoff_eligible_evidence_ids"], expected_source)
        self.assertEqual(
            variants["BASELINE"]["trace"]["decision_visible_evidence_ids"],
            ["operational-watch-signal-v1"],
        )
        self.assertEqual(
            variants["CHALLENGER"]["trace"]["decision_visible_evidence_ids"],
            expected_source,
        )

    def test_post_cutoff_evidence_is_never_decision_visible(self):
        report = evaluation.run_experiment(manifest())
        self.assertEqual(report["evidence_window"]["post_cutoff_evidence_ids"], ["post-cutoff-recovery-v1"])
        for variant in report["variants"]:
            self.assertNotIn(
                "post-cutoff-recovery-v1",
                variant["trace"]["decision_visible_evidence_ids"],
            )

    def test_run_is_deterministic_read_only_and_capability_neutral(self):
        first = evaluation.run_experiment(manifest())
        second = evaluation.run_experiment(manifest())
        self.assertEqual(first, second)
        self.assertEqual(first["operational_mutations"], [])
        self.assertEqual(first["evaluation_layers"]["system_correctness"]["status"], "PASS")
        self.assertIn("NEW_BUSINESS_RULE", first["claim_boundary"]["not_supported"])
        self.assertNotIn("A303", json.dumps(first))

    def test_quality_and_business_effect_are_not_inferred(self):
        report = evaluation.run_experiment(manifest())
        self.assertEqual(report["evaluation_layers"]["decision_quality"]["status"], "NOT_EVALUATED")
        self.assertEqual(report["evaluation_layers"]["business_outcome_effect"]["status"], "NOT_EVALUATED")

    def test_manifest_fails_closed_if_another_capability_is_added(self):
        changed = copy.deepcopy(manifest())
        changed["variants"][1]["capabilities"]["DECISION_MEMORY"] = True
        with self.assertRaisesRegex(evaluation.ContractError, "keys must be exactly"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_without_cutoff_eligible_high_external_evidence(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["evidence"][1]["available_at"] = "2025-03-07T09:30:00+11:00"
        changed["scenario"]["evidence"][1]["ingested_at"] = "2025-03-07T09:32:00+11:00"
        with self.assertRaisesRegex(evaluation.ContractError, "cutoff-eligible HIGH external event"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_if_baseline_enables_external_evidence(self):
        changed = copy.deepcopy(manifest())
        changed["variants"][0]["capabilities"]["EXTERNAL_EVIDENCE"] = True
        with self.assertRaisesRegex(evaluation.ContractError, "off in one variant"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_if_capability_uses_an_integer(self):
        changed = copy.deepcopy(manifest())
        changed["variants"][0]["capabilities"]["EXTERNAL_EVIDENCE"] = 0
        with self.assertRaisesRegex(evaluation.ContractError, "must be a boolean"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_for_a_future_controlled_replay(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["cutoff_at"] = "2099-03-07T09:00:00+11:00"
        changed["scenario"]["operational_state"]["as_of_at"] = "2099-03-07T09:00:00+11:00"
        with self.assertRaisesRegex(evaluation.ContractError, "current Sydney date"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_for_a_non_sydney_cutoff_offset(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["cutoff_at"] = "2025-03-07T09:00:00+10:00"
        with self.assertRaisesRegex(evaluation.ContractError, "Australia/Sydney UTC offset"):
            evaluation.run_experiment(changed)


if __name__ == "__main__":
    unittest.main()
