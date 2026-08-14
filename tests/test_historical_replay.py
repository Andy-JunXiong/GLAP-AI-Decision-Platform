import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "historical_replay", ROOT / "ops" / "run_historical_replay.py"
)
replay = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(replay)
FIXTURE = ROOT / "tests" / "fixtures" / "historical_replay" / "baltimore_key_bridge_2024_v1.json"


def corpus():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class HistoricalReplayTests(unittest.TestCase):
    def test_schema_and_initial_corpus_are_valid(self):
        schema = json.loads(
            (ROOT / "docs" / "historical_replay_scenario_v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], "historical-replay-scenario.v1")
        replay.validate_corpus(corpus())

    def test_cutoffs_expose_only_conservatively_available_sources(self):
        report = replay.run_replay(corpus())
        visible = {
            item["cutoff_id"]: item["visible_source_ids"] for item in report["cutoff_results"]
        }
        self.assertEqual(visible["T0_PRE_EVENT"], [])
        self.assertEqual(visible["T1_CONFIRMED_DISRUPTION"], ["USACE_INITIAL_RESPONSE_CURRENT_REVISION"])
        self.assertEqual(
            visible["T2_RECOVERY_TIMELINE"],
            ["USACE_INITIAL_RESPONSE_CURRENT_REVISION", "USACE_REOPENING_TIMELINE_2024_04_04"],
        )

    def test_current_march_26_page_cannot_be_backdated_before_march_31(self):
        changed = copy.deepcopy(corpus())
        changed["sources"][0]["available_at"] = "2024-03-27T00:00:00-04:00"
        with self.assertRaisesRegex(replay.ReplayContractError, "conservative next-day availability"):
            replay.validate_corpus(changed)

    def test_source_fact_tampering_is_detected(self):
        changed = copy.deepcopy(corpus())
        changed["sources"][0]["extracted_facts"][0]["summary"] += " Changed."
        with self.assertRaisesRegex(replay.ReplayContractError, "digest mismatch"):
            replay.validate_corpus(changed)

    def test_raw_source_content_or_entity_state_field_is_rejected(self):
        changed = copy.deepcopy(corpus())
        changed["sources"][0]["raw_source_content"] = "Full page content must not be stored."
        with self.assertRaisesRegex(replay.ReplayContractError, "unsupported fields"):
            replay.validate_corpus(changed)
        changed = copy.deepcopy(corpus())
        changed["controlled_internal_state"]["snapshots"][0]["shipment_id"] = "not-allowed"
        with self.assertRaisesRegex(replay.ReplayContractError, "unsupported fields"):
            replay.validate_corpus(changed)

    def test_unapproved_source_domain_is_rejected(self):
        changed = copy.deepcopy(corpus())
        changed["sources"][0]["url"] = "https://example.com/unverified"
        with self.assertRaisesRegex(replay.ReplayContractError, "unapproved source domain"):
            replay.validate_corpus(changed)

    def test_declared_visibility_must_equal_timestamp_visibility(self):
        changed = copy.deepcopy(corpus())
        changed["cutoffs"][1]["expected_visible_source_ids"] = []
        with self.assertRaisesRegex(replay.ReplayContractError, "visible-source contract drift"):
            replay.validate_corpus(changed)

    def test_future_historical_cutoff_is_rejected_against_sydney_date(self):
        changed = copy.deepcopy(corpus())
        changed["cutoffs"][0]["cutoff_at"] = "2099-01-01T00:00:00-05:00"
        changed["controlled_internal_state"]["snapshots"][0]["as_of_at"] = "2099-01-01T00:00:00-05:00"
        with self.assertRaisesRegex(replay.ReplayContractError, "future-dated relative to Sydney"):
            replay.validate_corpus(changed)

    def test_reveals_cannot_enter_a_decision_cutoff(self):
        changed = copy.deepcopy(corpus())
        changed["reveal_timeline"][0]["decision_input_allowed"] = True
        with self.assertRaisesRegex(replay.ReplayContractError, "cannot be a decision input"):
            replay.validate_corpus(changed)

    def test_real_enterprise_state_is_rejected(self):
        changed = copy.deepcopy(corpus())
        changed["controlled_internal_state"]["contains_real_enterprise_data"] = True
        with self.assertRaisesRegex(replay.ReplayContractError, "real enterprise data"):
            replay.validate_corpus(changed)

    def test_a303_delta_appears_only_after_eligible_disruption_evidence(self):
        report = replay.run_replay(corpus())
        comparisons = {
            item["cutoff_id"]: item["comparison"] for item in report["cutoff_results"]
        }
        self.assertFalse(comparisons["T0_PRE_EVENT"]["decision_changed"])
        self.assertTrue(comparisons["T1_CONFIRMED_DISRUPTION"]["decision_changed"])
        self.assertTrue(comparisons["T2_RECOVERY_TIMELINE"]["decision_changed"])
        self.assertEqual(
            report["evaluation_layers"]["capability_attribution"]["attributed_cutoff_ids"],
            ["T1_CONFIRMED_DISRUPTION", "T2_RECOVERY_TIMELINE"],
        )

    def test_replay_is_deterministic_read_only_and_does_not_claim_quality(self):
        first = replay.run_replay(corpus())
        second = replay.run_replay(corpus())
        self.assertEqual(first, second)
        self.assertEqual(first["operational_mutations"], [])
        self.assertTrue(
            all(
                variant["operational_mutations"] == []
                for cutoff in first["cutoff_results"]
                for variant in cutoff["variants"]
            )
        )
        self.assertEqual(first["evaluation_layers"]["decision_quality"]["status"], "NOT_EVALUATED")
        self.assertEqual(first["evaluation_layers"]["business_outcome_effect"]["status"], "NOT_EVALUATED")


if __name__ == "__main__":
    unittest.main()
