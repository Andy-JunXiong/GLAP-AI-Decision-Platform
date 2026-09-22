"""Synthetic provenance receipts; no AWS observations or trusted attestation."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ops import validate_learning_evidence_provenance as provenance
from ops import prepare_learning_evidence_collection as collection
from test_learning_evidence_collection import packet, page_response
from test_learning_cardinality_comparison import fixture, outcome, proposal


ROOT = Path(__file__).resolve().parents[1]


def replace_rows(data, phase, kind, rows):
    data[phase]["queries"][kind]["pages"][0]["response"] = page_response(kind, rows)


def evidence_fixture():
    before, after = packet(), packet("AFTER")
    after["config"]["outcome_snapshot_id"] = "112"
    for phase, source in (("before", before), ("after", after)):
        sql = collection.render_queries(source["config"])
        for kind, receipt in source["queries"].items():
            query_id = f"fixture-{phase}-{kind}"
            receipt["execution"].update(query_id=query_id, query=sql[kind])
            receipt["pages"][0]["query_id"] = query_id
    tables = {}
    for kind, base_id, final_id in (("outcomes", "111", "112"), ("proposals", "222", "222")):
        table_uuid = "fixture-table-" + kind
        node = {"snapshot_id": base_id, "parent_snapshot_id": None,
                "committed_at": "2026-08-27T12:00:00Z", "writer_invocation_id": None,
                "table_uuid": table_uuid, "schema_sha256": "c" * 64}
        nodes = [node]
        if final_id != base_id:
            nodes.append({**node, "snapshot_id": final_id, "parent_snapshot_id": base_id,
                          "committed_at": "2026-08-28T01:30:00Z",
                          "writer_invocation_id": "fixture-invocation"})
        tables[kind] = {
            "database": before["config"]["database"], "table": collection.TABLES[kind],
            "table_uuid_before": table_uuid, "table_uuid_after": table_uuid,
            "schema_sha256_before": "c" * 64, "schema_sha256_after": "c" * 64,
            "history_complete": True, "snapshots": nodes,
            "before": {"opened_at": "2026-08-27T23:20:00Z",
                       "closed_at": "2026-08-27T23:55:00Z", "head_at_open": base_id,
                       "head_at_close": base_id, "query_started_at": "2026-08-27T23:30:00Z",
                       "query_finished_at": "2026-08-27T23:40:00Z",
                       "query_id": f"fixture-before-{kind}"},
            "after": {"opened_at": "2026-08-28T02:10:00Z",
                      "closed_at": "2026-08-28T02:55:00Z", "head_at_open": final_id,
                      "head_at_close": final_id, "query_started_at": "2026-08-28T02:20:00Z",
                      "query_finished_at": "2026-08-28T02:30:00Z",
                      "query_id": f"fixture-after-{kind}"},
        }
    result = {
        "schema_version": provenance.SCHEMA, "input_kind": "SYNTHETIC_FIXTURE",
        "before": before, "after": after, "tables": tables,
        "run": {"run_id": "fixture-run", "invocation_id": "fixture-invocation",
                "function_name": provenance.FUNCTION_NAME, "logical_date": "2026-08-28",
                "release": copy.deepcopy(before["release"]),
                "started_at": "2026-08-28T01:00:00Z", "finished_at": "2026-08-28T02:00:00Z",
                "status": "SUCCEEDED", "dry_run": False, "write_statements": 1,
                "execution_mode": "OPERATIONAL", "time_basis": "ACTUAL_CALENDAR",
                "scenario_id": None, "as_of_date": "2026-08-28",
                "outcome_rows_created": 1, "policy_proposal_rows_created": 0},
    }
    replace_rows(result, "after", "outcomes", fixture()["before"]["outcomes"] + [
        {**outcome(), "dt": "2026-08-28", "as_of_date": "2026-08-28"}])
    return result


def add_proposal_violation(data):
    data["after"]["config"]["proposal_snapshot_id"] = "223"
    data["after"]["queries"]["proposals"]["execution"]["query"] = collection.render_queries(
        data["after"]["config"])["proposals"]
    table = data["tables"]["proposals"]
    table["after"].update(head_at_open="223", head_at_close="223")
    table["snapshots"].append({**table["snapshots"][0], "snapshot_id": "223",
        "parent_snapshot_id": "222", "committed_at": "2026-08-28T01:40:00Z",
        "writer_invocation_id": "fixture-invocation"})
    replace_rows(data, "after", "proposals", [proposal(), {
        **proposal("fixture-new-proposal"), "created_date": "2026-08-28", "as_of_date": "2026-08-28"}])
    data["run"]["policy_proposal_rows_created"] = 1


class LearningEvidenceProvenanceTests(unittest.TestCase):
    def assert_unverified(self, data, reason=None):
        result = provenance.validate_evidence(data)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIsNone(result["comparison"])
        self.assertIsNone(result["counts"])
        if reason:
            self.assertEqual(result["reasons"], [reason])
        return result

    def test_composes_pages_snapshot_history_and_run_without_runtime_claims(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            report = provenance.validate_evidence(evidence_fixture())
        self.assertEqual(report["status"], "RECEIPTS_AND_COMPARISON_CONSISTENT")
        self.assertEqual(report["counts"], {"bound_queries": 4, "bound_tables": 2,
                                          "new_snapshots": 1, "new_outcome_versions": 1})
        self.assertEqual(report["comparison"]["historical_proposals"], "PRESERVED_REVIEW_STILL_REQUIRED")
        for key in ("aws_receipts_authenticated", "runtime_verified", "exclusive_window_verified",
                    "cross_table_consistency_verified", "generator_path_verified",
                    "historical_anomaly_resolved", "execution_available"):
            self.assertFalse(report[key])
        self.assertFalse(any(report["authority"].values()))

    def test_new_below_threshold_proposal_remains_a_comparison_violation(self):
        data = evidence_fixture()
        add_proposal_violation(data)
        report = provenance.validate_evidence(data)
        self.assertEqual(report["status"], "RECEIPTS_CONSISTENT_COMPARISON_VIOLATION")
        self.assertIn("NEW_PROPOSAL_BELOW_THRESHOLD", report["comparison"]["reasons"])

    def test_incomplete_history_or_extra_attestation_is_rejected(self):
        data = evidence_fixture()
        data["tables"]["outcomes"]["history_complete"] = False
        self.assert_unverified(data, "INCOMPLETE_SNAPSHOT_HISTORY")
        data = evidence_fixture()
        data["runtime_verified"] = True
        self.assert_unverified(data, "INVALID_SHAPE")

    def test_run_must_be_successful_targeted_and_non_dry(self):
        for field, value in (("function_name", "other-function"), ("status", "FAILED"),
                             ("dry_run", True), ("dry_run", 0), ("write_statements", 0)):
            data = evidence_fixture()
            data["run"][field] = value
            self.assert_unverified(data)

    def test_dates_phases_release_and_invocation_ids_bind(self):
        for field, value in (("logical_date", "2026-08-27"),
                             ("invocation_id", "unrelated-invocation"),
                             ("finished_at", "2099-01-01T00:00:00Z")):
            data = evidence_fixture()
            data["run"][field] = value
            self.assert_unverified(data)
        data = evidence_fixture()
        data["after"]["config"]["phase"] = "BEFORE"
        self.assert_unverified(data, "PHASE_DATE_OR_RELEASE_MISMATCH")

    def test_invocation_scope_cannot_be_inferred_from_operational_rows(self):
        for field, value in (("execution_mode", "FUTURE_SIMULATION"),
                             ("time_basis", "FUTURE_SIMULATION"),
                             ("scenario_id", "fixture-scenario"), ("as_of_date", "2026-08-27")):
            data = evidence_fixture()
            data["run"][field] = value
            self.assert_unverified(data, "INVALID_INVOCATION_SCOPE")

    def test_new_rows_cannot_be_backdated_to_another_run(self):
        data = evidence_fixture()
        add_proposal_violation(data)
        replace_rows(data, "after", "proposals", [proposal(), proposal("fixture-new-proposal")])
        self.assert_unverified(data, "NEW_ROW_DATE_MISMATCH")
        data = evidence_fixture()
        data["run"]["release"]["artifact_sha256"] = "d" * 64
        self.assert_unverified(data, "PHASE_DATE_OR_RELEASE_MISMATCH")

    def test_query_cannot_be_reused_for_the_after_phase(self):
        data = evidence_fixture()
        receipt = data["after"]["queries"]["outcomes"]
        receipt["execution"]["query_id"] = "fixture-before-outcomes"
        receipt["pages"][0]["query_id"] = "fixture-before-outcomes"
        self.assert_unverified(data, "QUERY_REUSED_ACROSS_PHASES")

    def test_receipt_query_mismatch_is_unverified(self):
        data = evidence_fixture()
        data["tables"]["proposals"]["after"]["query_id"] = "unrelated-query"
        self.assert_unverified(data, "QUERY_RECEIPT_UNBOUND")

    def test_table_identity_and_schema_changes_fail_closed(self):
        for field, value in (("database", "other_database"), ("table", "other_table"),
                             ("table_uuid_after", "other-uuid"),
                             ("schema_sha256_after", "f" * 64)):
            data = evidence_fixture()
            data["tables"]["outcomes"][field] = value
            self.assert_unverified(data)

    def test_snapshot_lineage_gap_branch_and_cycle_are_rejected(self):
        for parent in (None, "999", "112"):
            data = evidence_fixture()
            data["tables"]["outcomes"]["snapshots"][1]["parent_snapshot_id"] = parent
            self.assert_unverified(data)
        data = evidence_fixture()
        history = data["tables"]["outcomes"]["snapshots"]
        history.append({**history[1], "snapshot_id": "113", "parent_snapshot_id": "111"})
        self.assert_unverified(data, "SNAPSHOT_LINEAGE_GAP_OR_BRANCH")

    def test_every_intermediate_commit_must_match_invocation_and_window(self):
        for field, value in (("writer_invocation_id", "other-writer"),
                             ("writer_invocation_id", None),
                             ("committed_at", "2026-08-28T00:30:00Z"),
                             ("committed_at", "2026-08-28T02:30:00Z"),
                             ("table_uuid", "other-table"), ("schema_sha256", "e" * 64)):
            data = evidence_fixture()
            data["tables"]["outcomes"]["snapshots"][1][field] = value
            self.assert_unverified(data)

    def test_baseline_parent_cannot_form_a_cycle_with_a_later_snapshot(self):
        data = evidence_fixture()
        data["tables"]["outcomes"]["snapshots"][0]["parent_snapshot_id"] = "112"
        self.assert_unverified(data, "DUPLICATE_OR_CYCLIC_SNAPSHOT")

    def test_old_query_cannot_be_relabelled_with_todays_capture_timestamp(self):
        data = evidence_fixture()
        data["tables"]["outcomes"]["before"].update(
            opened_at="2026-08-26T01:00:00Z", query_started_at="2026-08-26T01:10:00Z",
            query_finished_at="2026-08-26T01:20:00Z", closed_at="2026-08-26T01:30:00Z")
        self.assert_unverified(data, "CROSS_DATE_COLLECTION_WINDOW")

    def test_head_change_during_collection_is_not_ignored(self):
        data = evidence_fixture()
        data["tables"]["outcomes"]["before"]["head_at_close"] = "112"
        self.assert_unverified(data, "COLLECTION_HEAD_CHANGED_OR_UNBOUND")

    def test_individually_valid_windows_need_shared_cross_table_fence(self):
        data = evidence_fixture()
        data["tables"]["proposals"]["before"].update(
            opened_at="2026-08-27T23:45:00Z", query_started_at="2026-08-27T23:46:00Z",
            query_finished_at="2026-08-27T23:50:00Z")
        self.assert_unverified(data, "NO_SHARED_COLLECTION_FENCE")

    def test_after_collection_cannot_overlap_the_run(self):
        data = evidence_fixture()
        data["tables"]["outcomes"]["after"]["opened_at"] = "2026-08-28T01:59:00Z"
        self.assert_unverified(data, "AFTER_COLLECTION_OVERLAPS_RUN")

    def test_baseline_snapshot_must_precede_collection(self):
        data = evidence_fixture()
        data["tables"]["outcomes"]["snapshots"][0]["committed_at"] = "2026-08-28T00:00:00Z"
        self.assert_unverified(data, "BASELINE_SNAPSHOT_UNBOUND")

    def test_run_counts_cannot_be_substituted_for_data_differences(self):
        for field, value in (("outcome_rows_created", 2), ("policy_proposal_rows_created", 1),
                             ("outcome_rows_created", True)):
            data = evidence_fixture()
            data["run"][field] = value
            self.assert_unverified(data)

    def test_same_snapshot_cannot_return_different_rows(self):
        data = evidence_fixture()
        data["after"]["config"]["outcome_snapshot_id"] = "111"
        data["after"]["queries"]["outcomes"]["execution"]["query"] = collection.render_queries(
            data["after"]["config"])["outcomes"]
        data["tables"]["outcomes"]["after"].update(head_at_open="111", head_at_close="111")
        data["tables"]["outcomes"]["snapshots"].pop()
        self.assert_unverified(data, "SAME_SNAPSHOT_DIFFERENT_ROWS")

    def test_valid_unchanged_relevant_tables_do_not_prove_path_execution(self):
        data = evidence_fixture()
        data["after"]["config"]["outcome_snapshot_id"] = "111"
        data["after"]["queries"]["outcomes"]["execution"]["query"] = collection.render_queries(
            data["after"]["config"])["outcomes"]
        data["tables"]["outcomes"]["after"].update(head_at_open="111", head_at_close="111")
        data["tables"]["outcomes"]["snapshots"].pop()
        data["run"]["outcome_rows_created"] = 0
        replace_rows(data, "after", "outcomes", fixture()["before"]["outcomes"])
        report = provenance.validate_evidence(data)
        self.assertEqual(report["status"], "RECEIPTS_AND_COMPARISON_CONSISTENT")
        self.assertFalse(report["generator_path_verified"])

    def test_page_layer_failures_and_threshold_escape_remain_unverified(self):
        data = evidence_fixture()
        data["after"]["queries"]["outcomes"]["pages"][0]["response"]["NextToken"] = "missing"
        self.assert_unverified(data, "INCOMPLETE_PAGINATION")
        data = evidence_fixture()
        replace_rows(data, "after", "outcomes", [outcome(f"fixture-{i}") for i in range(20)])
        self.assert_unverified(data, "COMPARISON_UNVERIFIED")

    def test_reports_never_echo_private_receipt_data(self):
        for data in (evidence_fixture(), {"private-marker": "must-not-escape"}):
            text = json.dumps(provenance.validate_evidence(data))
            for marker in ("fixture-", "fixture_private_database", "SELECT", "c" * 64,
                           "must-not-escape", provenance.FUNCTION_NAME):
                self.assertNotIn(marker, text)

    def test_input_bounds_duplicate_keys_and_unknown_shape_fail_closed(self):
        for raw in (b'{"x":1,"x":2}', b'{', b'\xff', b'{"x":NaN}'):
            self.assertEqual(provenance.validate_json(raw)["status"], "UNVERIFIED")
        with patch.object(provenance, "MAX_BYTES", 2):
            self.assertEqual(provenance.validate_json(b'null')["reasons"], ["INPUT_TOO_LARGE"])
        data = evidence_fixture()
        with patch.object(provenance, "MAX_SNAPSHOTS", 1):
            self.assert_unverified(data, "INVALID_SNAPSHOT_HISTORY")

    def test_cli_exit_codes_and_safe_unknown_arguments(self):
        script = str(ROOT / "ops/validate_learning_evidence_provenance.py")
        data = evidence_fixture()
        cases = [(json.dumps(data).encode(), 0)]
        add_proposal_violation(data)
        cases.extend([(json.dumps(data).encode(), 1), (b'null', 2)])
        for raw, code in cases:
            completed = subprocess.run([sys.executable, script], input=raw, capture_output=True)
            self.assertEqual(completed.returncode, code)
            self.assertEqual(completed.stderr, b"")
            self.assertFalse(json.loads(completed.stdout)["runtime_verified"])
            self.assertNotIn(b"fixture-", completed.stdout)
        completed = subprocess.run([sys.executable, script, "--execute", "private-marker"],
                                   capture_output=True)
        self.assertEqual(completed.returncode, 2)
        self.assertNotIn(b"private-marker", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
