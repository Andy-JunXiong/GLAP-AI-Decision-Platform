import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "historical_replay_corpus", ROOT / "ops" / "run_historical_replay_corpus.py"
)
corpus_runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(corpus_runner)
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "historical_replay"
MANIFEST = FIXTURE_DIR / "corpus_v1.json"
FAA_SCENARIO = FIXTURE_DIR / "faa_notam_outage_2023_v1.json"
RAIL_SCENARIO = FIXTURE_DIR / "us_rail_labor_risk_2022_v1.json"


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


class HistoricalReplayCorpusTests(unittest.TestCase):
    def test_manifest_schema_and_five_scenario_corpus_are_valid(self):
        schema = json.loads(
            (ROOT / "docs" / "historical_replay_corpus_v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], "historical-replay-corpus.v1")
        corpus_runner.validate_manifest(manifest())
        report = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        self.assertEqual(report["summary"]["scenario_count"], 5)

    def test_corpus_summary_preserves_scenario_level_attribution(self):
        report = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        self.assertEqual(
            report["summary"],
            {
                "scenario_count": 5,
                "cutoff_count": 15,
                "attributed_cutoff_count": 6,
                "no_delta_cutoff_count": 9,
            },
        )
        self.assertEqual(
            [item["scenario_id"] for item in report["scenario_reports"]],
            [
                "baltimore-key-bridge-2024-v1",
                "panama-canal-drought-2023-v1",
                "red-sea-security-2023-v1",
                "faa-notam-outage-2023-v1",
                "us-rail-labor-risk-2022-v1",
            ],
        )

    def test_panama_medium_signal_does_not_trigger_before_high_signal(self):
        report = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        panama = next(
            item for item in report["scenario_reports"]
            if item["scenario_id"] == "panama-canal-drought-2023-v1"
        )
        changes = {
            item["cutoff_id"]: item["comparison"]["decision_changed"]
            for item in panama["cutoff_results"]
        }
        self.assertFalse(changes["T1_MEDIUM_CAPACITY_SIGNAL"])
        self.assertTrue(changes["T2_HIGH_DROUGHT_CAPACITY_RISK"])

    def test_red_sea_reveal_is_not_visible_at_decision_cutoffs(self):
        report = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        red_sea = next(
            item for item in report["scenario_reports"]
            if item["scenario_id"] == "red-sea-security-2023-v1"
        )
        self.assertTrue(
            all(
                "IMO_MSC_RESOLUTION_2024_05_24" in item["hidden_source_ids"]
                for item in red_sea["cutoff_results"]
            )
        )

    def test_benchmark_gate_reports_real_coverage_gaps(self):
        report = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        self.assertEqual(len(report["coverage"]["disruption_types"]), 5)
        self.assertEqual(len(report["coverage"]["regions"]), 3)
        self.assertEqual(report["coverage"]["transport_modes"], ["AIR", "OCEAN", "RAIL"])
        self.assertEqual(report["coverage"]["severity_bands"], ["HIGH", "MEDIUM"])
        self.assertFalse(report["benchmark_gate"]["eligible"])
        self.assertEqual(report["benchmark_gate"]["status"], "NOT_MET")
        self.assertTrue(report["benchmark_gate"]["checks"]["disruption_type_count"])
        self.assertTrue(report["benchmark_gate"]["checks"]["transport_mode_count"])
        self.assertTrue(report["benchmark_gate"]["checks"]["severity_band_count"])
        self.assertFalse(report["benchmark_gate"]["checks"]["independent_reviews"])
        self.assertEqual(report["decision_quality"]["status"], "NOT_EVALUATED")

    def test_faa_exact_timestamps_hold_back_the_ground_stop(self):
        scenario = json.loads(FAA_SCENARIO.read_text(encoding="utf-8"))
        report = corpus_runner._REPLAY.run_replay(scenario)
        results = {item["cutoff_id"]: item for item in report["cutoff_results"]}
        self.assertFalse(results["T1_OUTAGE_WITHOUT_GROUND_STOP"]["comparison"]["decision_changed"])
        self.assertNotIn(
            "FAA_NATIONWIDE_GROUND_STOP_2023_01_11_1221Z",
            results["T1_OUTAGE_WITHOUT_GROUND_STOP"]["visible_source_ids"],
        )
        self.assertTrue(results["T2_NATIONWIDE_GROUND_STOP"]["comparison"]["decision_changed"])

    def test_exact_source_timestamp_cannot_be_shifted(self):
        scenario = json.loads(FAA_SCENARIO.read_text(encoding="utf-8"))
        scenario["sources"][0]["available_at"] = "2023-01-11T00:48:00+00:00"
        with self.assertRaisesRegex(corpus_runner.ReplayContractError, "must be its availability"):
            corpus_runner._REPLAY.validate_corpus(scenario)

    def test_medium_rail_scenario_remains_no_delta_at_every_cutoff(self):
        scenario = json.loads(RAIL_SCENARIO.read_text(encoding="utf-8"))
        report = corpus_runner._REPLAY.run_replay(scenario)
        self.assertEqual(report["scenario_profile"]["severity_band"], "MEDIUM")
        self.assertTrue(
            all(not item["comparison"]["decision_changed"] for item in report["cutoff_results"])
        )
        self.assertEqual(
            report["evaluation_layers"]["capability_attribution"]["attributed_cutoff_ids"],
            [],
        )

    def test_scenario_severity_must_match_final_cutoff_evidence(self):
        scenario = json.loads(RAIL_SCENARIO.read_text(encoding="utf-8"))
        scenario["scenario_profile"]["severity_band"] = "HIGH"
        with self.assertRaisesRegex(corpus_runner.ReplayContractError, "severity band differs"):
            corpus_runner._REPLAY.validate_corpus(scenario)

    def test_manifest_rejects_path_traversal_and_duplicate_membership(self):
        changed = copy.deepcopy(manifest())
        changed["scenarios"][0]["file"] = "../outside.json"
        with self.assertRaisesRegex(corpus_runner.ReplayContractError, "local JSON basename"):
            corpus_runner.validate_manifest(changed)
        changed = copy.deepcopy(manifest())
        changed["scenarios"][1]["scenario_id"] = changed["scenarios"][0]["scenario_id"]
        with self.assertRaisesRegex(corpus_runner.ReplayContractError, "scenario IDs must be unique"):
            corpus_runner.validate_manifest(changed)

    def test_manifest_scenario_identity_cannot_drift(self):
        changed = copy.deepcopy(manifest())
        changed["scenarios"][0]["scenario_id"] = "different-scenario-id"
        with self.assertRaisesRegex(corpus_runner.ReplayContractError, "scenario ID differs"):
            corpus_runner.run_corpus(changed, FIXTURE_DIR)

    def test_corpus_run_is_deterministic_and_read_only(self):
        first = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        second = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        self.assertEqual(first, second)
        self.assertEqual(first["operational_mutations"], [])
        self.assertTrue(
            all(item["operational_mutations"] == [] for item in first["scenario_reports"])
        )


if __name__ == "__main__":
    unittest.main()
