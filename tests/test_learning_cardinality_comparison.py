"""Synthetic offline cases; these are not staging runtime observations."""

import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from ops import compare_learning_cardinality_evidence as comparator


ROOT = Path(__file__).resolve().parents[1]
TEMPORAL = {
    "temporal_scope_id": "OPERATIONAL", "execution_mode": "OPERATIONAL",
    "time_basis": "ACTUAL_CALENDAR", "as_of_date": "2026-08-27",
    "execution_scenario_id": None,
}


def outcome(identifier="fixture-outcome-1"):
    return {
        **TEMPORAL, "outcome_id": identifier, "action_id": "fixture-action",
        "alert_fingerprint": "fixture-alert", "shipment_id": "fixture-shipment",
        "dt": "2026-08-27", "observation_due_date": "2026-08-27",
        "status": "SUCCESSFUL", "observed_date": "2026-08-27",
        "effect_pct": 2.0, "outcome_version": "sim-v1", "provenance": "SIMULATED",
    }


def proposal(identifier="fixture-historical-proposal"):
    return {
        **TEMPORAL, "proposal_id": identifier, "source_policy_version": "fixture-v1",
        "status": "PENDING_HUMAN_REVIEW", "observed_outcome_count": 20,
        "success_rate_pct": 50.0, "proposed_change": "REVIEW_ACTION_RANKING_THRESHOLDS",
        "simulation_config_change": False, "effective_date": None, "approved_by": None,
        "approved_policy_version": None, "rollback_policy_version": "fixture-v1",
        "provenance": "SIMULATED_LEARNING_EVIDENCE", "created_date": "2026-08-27",
    }


def fixture():
    binding = {"source_commit": comparator.SOURCE_COMMIT,
               "artifact_sha256": "a" * 64, "configuration_sha256": "b" * 64}
    before = {"captured_at": "2026-08-28T00:00:00Z", "cutoff_date": "2026-08-28",
              "complete": True, "release": binding,
              "outcomes": [outcome(), outcome("fixture-outcome-2")],
              "proposals": [proposal()]}
    after = copy.deepcopy(before)
    after["captured_at"] = "2026-08-28T03:00:00Z"
    return {"schema_version": comparator.SCHEMA, "input_kind": "SYNTHETIC_FIXTURE",
            "before": before, "after": after,
            "run": {"started_at": "2026-08-28T01:00:00Z",
                    "finished_at": "2026-08-28T02:00:00Z", "logical_date": "2026-08-28",
                    "release": copy.deepcopy(binding), "generator_path_completed": True,
                    "exclusive_window": True}}


class LearningCardinalityComparisonTests(unittest.TestCase):
    def test_preserves_historical_anomaly_without_claiming_runtime_success(self):
        report = comparator.compare_evidence(fixture())
        self.assertEqual(report["status"], "CONSISTENT_WITH_BELOW_THRESHOLD_RULE")
        self.assertEqual(report["historical_proposals"], "PRESERVED_REVIEW_STILL_REQUIRED")
        self.assertEqual(report["counts"]["eligible_after"], 2)
        self.assertFalse(report["runtime_verified"])
        self.assertFalse(report["historical_anomaly_resolved"])
        self.assertFalse(any(report["authority"].values()))

    def test_empty_baseline_does_not_claim_anomaly_resolution(self):
        data = fixture()
        data["before"]["proposals"] = data["after"]["proposals"] = []
        result = comparator.compare_evidence(data)
        self.assertEqual(result["historical_proposals"], "NONE_IN_SUPPLIED_BASELINE")
        self.assertFalse(result["historical_anomaly_resolved"])

    def test_new_proposal_is_a_violation_even_with_equal_net_counts(self):
        data = fixture()
        data["after"]["proposals"] = [proposal("fixture-replacement")]
        result = comparator.compare_evidence(data)
        self.assertEqual(result["status"], "VIOLATION_IN_SUPPLIED_EVIDENCE")
        self.assertEqual(result["counts"]["new_proposals"], 1)
        self.assertEqual(result["counts"]["removed_proposals"], 1)

    def test_added_proposal_below_threshold_is_detected(self):
        data = fixture()
        data["after"]["proposals"].append(proposal("fixture-new"))
        self.assertIn("NEW_PROPOSAL_BELOW_THRESHOLD",
                      comparator.compare_evidence(data)["reasons"])

    def test_payload_changes_and_removal_are_not_hidden_by_identity(self):
        for field, value in (("success_rate_pct", 75.0), ("proposed_change", "changed")):
            with self.subTest(field=field):
                data = fixture()
                data["after"]["proposals"][0][field] = value
                self.assertIn("HISTORICAL_PROPOSAL_CHANGED_OR_MISSING",
                              comparator.compare_evidence(data)["reasons"])

    def test_activation_is_violation_even_when_present_in_both_snapshots(self):
        for field, value in (("status", "APPROVED"), ("approved_by", "fixture-reviewer"),
                             ("approved_policy_version", "fixture-v2"),
                             ("effective_date", "2026-08-28")):
            with self.subTest(field=field):
                data = fixture()
                for phase in ("before", "after"):
                    data[phase]["proposals"][0][field] = value
                self.assertIn("ACTIVATION_PRESENT", comparator.compare_evidence(data)["reasons"])

    def test_historical_outcome_versions_are_deduplicated(self):
        data = fixture()
        rows = [{**outcome(), "dt": f"2026-08-{day:02d}",
                 "observation_due_date": "2026-08-01", "observed_date": "2026-08-01"}
                for day in range(1, 28)]
        for phase in ("before", "after"):
            data[phase]["outcomes"] = copy.deepcopy(rows)
        self.assertEqual(comparator.compare_evidence(data)["counts"]["eligible_after"], 1)

    def test_latest_pending_excludes_earlier_closed_version(self):
        data = fixture()
        data["after"]["outcomes"].append({**outcome(), "dt": "2026-08-28",
            "as_of_date": "2026-08-28", "status": "PENDING",
            "observed_date": None, "effect_pct": None})
        result = comparator.compare_evidence(data)
        self.assertEqual(result["counts"]["eligible_after"], 1)
        self.assertEqual(result["status"], "CONSISTENT_WITH_BELOW_THRESHOLD_RULE")

    def test_conflicting_older_versions_are_rejected_in_every_order(self):
        old = {**outcome(), "effect_pct": 7}
        latest = {**outcome(), "dt": "2026-08-28", "as_of_date": "2026-08-28"}
        for rows in ([latest, outcome(), old], [outcome(), latest, old]):
            data = fixture()
            data["after"]["outcomes"] = rows
            self.assertEqual(comparator.compare_evidence(data)["reasons"],
                             ["CONFLICTING_OUTCOME_VERSIONS"])

    def test_outcome_history_cannot_disappear_or_change(self):
        for mutate in (lambda rows: rows.pop(),
                       lambda rows: rows[0].update(effect_pct=9.0)):
            data = fixture()
            mutate(data["after"]["outcomes"])
            self.assertIn("OUTCOME_HISTORY_CHANGED_OR_MISSING",
                          comparator.compare_evidence(data)["reasons"])

    def test_twenty_distinct_outcomes_are_outside_this_verification_scope(self):
        for phase in ("before", "after"):
            data = fixture()
            data[phase]["outcomes"] = [outcome(f"fixture-{i}") for i in range(20)]
            self.assertEqual(comparator.compare_evidence(data)["reasons"],
                             ["OUTSIDE_BELOW_THRESHOLD_SCOPE"])

    def test_missing_completeness_or_run_path_is_unverified(self):
        for phase, key in (("before", "complete"), ("after", "complete"),
                           ("run", "generator_path_completed"), ("run", "exclusive_window")):
            for value in (False, 1, "true", None):
                data = fixture()
                data[phase][key] = value
                self.assertEqual(comparator.compare_evidence(data)["status"], "UNVERIFIED")

    def test_release_binding_change_and_unapproved_source_are_rejected(self):
        for phase in ("before", "after", "run"):
            data = fixture()
            data[phase]["release"]["artifact_sha256"] = "c" * 64
            self.assertEqual(comparator.compare_evidence(data)["status"], "UNVERIFIED")
        data = fixture()
        for phase in ("before", "after", "run"):
            data[phase]["release"]["source_commit"] = "f" * 40
        self.assertEqual(comparator.compare_evidence(data)["reasons"], ["UNBOUND_SOURCE"])

    def test_temporal_and_observation_window_errors_fail_closed(self):
        for field, value in (("dt", "2099-01-01"), ("as_of_date", "2099-01-01"),
                             ("execution_scenario_id", "fixture-scenario"),
                             ("time_basis", "FUTURE_SIMULATION"),
                             ("observed_date", "2026-08-26"),
                             ("observed_date", "2099-01-01")):
            data = fixture()
            data["after"]["outcomes"][0][field] = value
            self.assertEqual(comparator.compare_evidence(data)["status"], "UNVERIFIED")

    def test_snapshot_order_and_sydney_date_are_enforced(self):
        for value in ("2026-08-28T01:30:00Z", "2099-01-01T00:00:00Z",
                      "2026-08-28T03:00:00", "2026-08-28T23:00:00Z"):
            data = fixture()
            data["after"]["captured_at"] = value
            self.assertEqual(comparator.compare_evidence(data)["status"], "UNVERIFIED")

    def test_unknown_fields_and_duplicate_proposals_are_unverified(self):
        data = fixture()
        data["minimum_outcomes"] = 1
        self.assertEqual(comparator.compare_evidence(data)["status"], "UNVERIFIED")
        data = fixture()
        data["after"]["proposals"].append(proposal())
        self.assertEqual(comparator.compare_evidence(data)["reasons"], ["DUPLICATE_PROPOSAL"])

    def test_reports_never_echo_identifiers_payloads_or_digests(self):
        data = fixture()
        data["after"]["proposals"][0]["approved_by"] = "protected-marker"
        text = json.dumps(comparator.compare_evidence(data))
        for protected in ("protected-marker", "fixture-", "a" * 64, "b" * 64,
                          comparator.SOURCE_COMMIT):
            self.assertNotIn(protected, text)
        data["after"]["captured_at"] = "protected-marker"
        self.assertNotIn("protected-marker", json.dumps(comparator.compare_evidence(data)))

    def test_json_duplicate_keys_nonfinite_and_oversize_inputs_fail_closed(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
                    b'{', b'\xff', b' ' * (comparator.MAX_BYTES + 1)):
            self.assertEqual(comparator.compare_json(raw)["status"], "UNVERIFIED")

    def test_invalid_field_types_do_not_escape_or_become_valid_evidence(self):
        for field, value in (("observed_outcome_count", True), ("success_rate_pct", float("inf")),
                             ("proposal_id", []), ("status", {})):
            data = fixture()
            data["after"]["proposals"][0][field] = value
            self.assertEqual(comparator.compare_evidence(data)["status"], "UNVERIFIED")

    def test_stdin_cli_emits_only_aggregate_report_and_meaningful_exit_codes(self):
        data = fixture()
        cases = [(json.dumps(data).encode(), 0)]
        data["after"]["proposals"].append(proposal("fixture-new"))
        cases.extend([(json.dumps(data).encode(), 1), (b'{', 2)])
        for raw, expected in cases:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "ops/compare_learning_cardinality_evidence.py")],
                input=raw, capture_output=True, check=False)
            self.assertEqual(completed.returncode, expected)
            self.assertEqual(completed.stderr, b"")
            self.assertFalse(json.loads(completed.stdout)["runtime_verified"])
            self.assertNotIn(b"fixture-", completed.stdout)

    def test_full_row_contract_matches_adapter_columns_without_importing_aws(self):
        tree = ast.parse((ROOT / "lambda/glap_lifecycle_athena_adapter.py").read_text())
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ("TEMPORAL_COLUMNS", "OUTCOME_COLUMNS", "POLICY_PROPOSAL_COLUMNS"):
                    fields = []
                    for item in node.value.elts:
                        fields.extend(values[item.value.id] if isinstance(item, ast.Starred)
                                      else [ast.literal_eval(item)])
                    values[name] = fields
        self.assertEqual(comparator.OUTCOME_FIELDS, set(values["OUTCOME_COLUMNS"]))
        self.assertEqual(comparator.PROPOSAL_FIELDS, set(values["POLICY_PROPOSAL_COLUMNS"]))


if __name__ == "__main__":
    unittest.main()
