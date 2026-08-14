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
ROAD_SCENARIO = FIXTURE_DIR / "gotthard_road_tunnel_closure_2023_v1.json"
SUEZ_SCENARIO = FIXTURE_DIR / "suez_ever_given_grounding_2021_v1.json"
NZ_CYCLONE_SCENARIO = FIXTURE_DIR / "new_zealand_cyclone_gabrielle_roads_2023_v1.json"
SINGAPORE_PORT_SCENARIO = FIXTURE_DIR / "singapore_port_congestion_2024_v1.json"
BRAZIL_FLOOD_SCENARIO = FIXTURE_DIR / "rio_grande_do_sul_flood_highways_2024_v1.json"


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


class HistoricalReplayCorpusTests(unittest.TestCase):
    def test_manifest_schema_and_ten_scenario_corpus_are_valid(self):
        schema = json.loads(
            (ROOT / "docs" / "historical_replay_corpus_v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], "historical-replay-corpus.v1")
        corpus_runner.validate_manifest(manifest())
        report = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        self.assertEqual(report["summary"]["scenario_count"], 10)

    def test_corpus_summary_preserves_scenario_level_attribution(self):
        report = corpus_runner.run_corpus(manifest(), FIXTURE_DIR)
        self.assertEqual(
            report["summary"],
            {
                "scenario_count": 10,
                "cutoff_count": 30,
                "attributed_cutoff_count": 16,
                "no_delta_cutoff_count": 14,
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
                "gotthard-road-tunnel-closure-2023-v1",
                "suez-ever-given-grounding-2021-v1",
                "new-zealand-cyclone-gabrielle-roads-2023-v1",
                "singapore-port-congestion-2024-v1",
                "rio-grande-do-sul-flood-highways-2024-v1",
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
        self.assertEqual(len(report["coverage"]["disruption_types"]), 10)
        self.assertEqual(len(report["coverage"]["regions"]), 8)
        self.assertEqual(report["coverage"]["transport_modes"], ["AIR", "OCEAN", "RAIL", "ROAD"])
        self.assertEqual(report["coverage"]["severity_bands"], ["HIGH", "MEDIUM"])
        self.assertFalse(report["benchmark_gate"]["eligible"])
        self.assertEqual(report["benchmark_gate"]["status"], "NOT_MET")
        self.assertTrue(report["benchmark_gate"]["checks"]["scenario_count"])
        self.assertTrue(report["benchmark_gate"]["checks"]["disruption_type_count"])
        self.assertTrue(report["benchmark_gate"]["checks"]["transport_mode_count"])
        self.assertTrue(report["benchmark_gate"]["checks"]["severity_band_count"])
        self.assertFalse(report["benchmark_gate"]["checks"]["independent_reviews"])
        self.assertEqual(report["decision_quality"]["status"], "NOT_EVALUATED")

    def test_gotthard_adds_road_and_europe_without_reveal_leakage(self):
        scenario = json.loads(ROAD_SCENARIO.read_text(encoding="utf-8"))
        report = corpus_runner._REPLAY.run_replay(scenario)
        self.assertEqual(
            report["scenario_profile"],
            {
                "disruption_type": "ROAD_TUNNEL_INFRASTRUCTURE_FAILURE",
                "region": "EUROPE",
                "transport_mode": "ROAD",
                "severity_band": "HIGH",
            },
        )
        results = {item["cutoff_id"]: item for item in report["cutoff_results"]}
        self.assertFalse(
            results["T0_BEFORE_OFFICIAL_CLOSURE_SOURCE_AVAILABLE"]["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T1_CLOSURE_CONFIRMED_UNTIL_FURTHER_NOTICE"]["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T2_REPAIR_CONTINUES_REOPENING_TIME_PENDING"]["comparison"]["decision_changed"]
        )
        self.assertTrue(
            all(
                "FEDRO_GOTTHARD_REOPENING_2023_09_15" in item["hidden_source_ids"]
                for item in report["cutoff_results"]
            )
        )

    def test_suez_adds_north_africa_grounding_without_recovery_leakage(self):
        scenario = json.loads(SUEZ_SCENARIO.read_text(encoding="utf-8"))
        report = corpus_runner._REPLAY.run_replay(scenario)
        self.assertEqual(
            report["scenario_profile"],
            {
                "disruption_type": "CANAL_VESSEL_GROUNDING",
                "region": "NORTH_AFRICA",
                "transport_mode": "OCEAN",
                "severity_band": "HIGH",
            },
        )
        results = {item["cutoff_id"]: item for item in report["cutoff_results"]}
        self.assertFalse(
            results["T0_BEFORE_OFFICIAL_GROUNDING_SOURCE_AVAILABLE"]["comparison"]["decision_changed"]
        )
        self.assertTrue(results["T1_GROUNDING_RESPONSE_ACTIVE"]["comparison"]["decision_changed"])
        final = results["T2_REFLOATING_ANNOUNCEMENT_NOT_YET_CONSERVATIVELY_AVAILABLE"]
        self.assertTrue(final["comparison"]["decision_changed"])
        self.assertNotIn("SCA_EVER_GIVEN_REFLOATED_2021_03_29", final["visible_source_ids"])
        self.assertTrue(
            all(
                "SCA_SUEZ_BOTH_DIRECTIONS_FULL_CAPACITY_2021_03_31"
                in item["hidden_source_ids"]
                for item in report["cutoff_results"]
            )
        )

    def test_nz_cyclone_adds_oceania_weather_roads_without_recovery_leakage(self):
        scenario = json.loads(NZ_CYCLONE_SCENARIO.read_text(encoding="utf-8"))
        report = corpus_runner._REPLAY.run_replay(scenario)
        self.assertEqual(
            report["scenario_profile"],
            {
                "disruption_type": "EXTREME_WEATHER_ROAD_NETWORK",
                "region": "OCEANIA",
                "transport_mode": "ROAD",
                "severity_band": "HIGH",
            },
        )
        results = {item["cutoff_id"]: item for item in report["cutoff_results"]}
        self.assertFalse(
            results["T0_BEFORE_FIRST_NZTA_CYCLONE_SOURCE_AVAILABLE"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T1_COROMANDEL_HIGHWAY_CLOSURES_CONFIRMED"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T2_NORTHLAND_NETWORK_ISOLATION_CONFIRMED"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            all(
                "NZTA_NORTHLAND_NETWORK_REOPENING_2023_02_15_1236"
                in item["hidden_source_ids"]
                for item in report["cutoff_results"]
            )
        )

    def test_singapore_adds_southeast_asia_port_congestion_without_recovery_leakage(self):
        scenario = json.loads(SINGAPORE_PORT_SCENARIO.read_text(encoding="utf-8"))
        report = corpus_runner._REPLAY.run_replay(scenario)
        self.assertEqual(
            report["scenario_profile"],
            {
                "disruption_type": "CONTAINER_PORT_CONGESTION",
                "region": "SOUTHEAST_ASIA",
                "transport_mode": "OCEAN",
                "severity_band": "HIGH",
            },
        )
        results = {item["cutoff_id"]: item for item in report["cutoff_results"]}
        self.assertFalse(
            results["T0_BEFORE_MPA_BERTH_WAIT_SOURCE_AVAILABLE"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T1_CONTAINER_BERTH_DELAY_CONFIRMED"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T2_STRONG_CAPACITY_DEMAND_CONTINUES"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            all(
                "MPA_CONTAINER_BERTH_WAIT_REDUCED_2024_09_04"
                in item["hidden_source_ids"]
                for item in report["cutoff_results"]
            )
        )

    def test_brazil_flood_adds_south_america_highways_without_recovery_leakage(self):
        scenario = json.loads(BRAZIL_FLOOD_SCENARIO.read_text(encoding="utf-8"))
        report = corpus_runner._REPLAY.run_replay(scenario)
        self.assertEqual(
            report["scenario_profile"],
            {
                "disruption_type": "FLOOD_DAMAGED_HIGHWAY_NETWORK",
                "region": "SOUTH_AMERICA",
                "transport_mode": "ROAD",
                "severity_band": "HIGH",
            },
        )
        results = {item["cutoff_id"]: item for item in report["cutoff_results"]}
        self.assertFalse(
            results["T0_BEFORE_FIRST_FLOOD_HIGHWAY_BULLETIN_AVAILABLE"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T1_FORTY_TOTAL_HIGHWAY_CLOSURES_CONFIRMED"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            results["T2_EXTENSIVE_HIGHWAY_RESTRICTIONS_CONTINUE"]
            ["comparison"]["decision_changed"]
        )
        self.assertTrue(
            all(
                "BRAZIL_DNIT_BR470_FIRST_SEGMENT_REOPENED_2024_06_22_1815"
                in item["hidden_source_ids"]
                for item in report["cutoff_results"]
            )
        )

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
