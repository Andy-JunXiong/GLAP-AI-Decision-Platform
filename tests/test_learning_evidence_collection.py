"""Offline supplied-page fixtures, never an AWS collection or runtime attestation."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ops import prepare_learning_evidence_collection as collection
from ops import compare_learning_cardinality_evidence as comparison
from test_learning_cardinality_comparison import fixture


ROOT = Path(__file__).resolve().parents[1]


def config(phase="BEFORE"):
    return {"schema_version": collection.SCHEMA, "phase": phase,
            "logical_date": "2026-08-28", "database": "fixture_private_database",
            "outcome_snapshot_id": "111", "proposal_snapshot_id": "222"}


def page_response(kind, rows, header=True):
    columns = sorted(collection.FIELDS[kind])
    encoded = []
    if header:
        encoded.append({"Data": [{"VarCharValue": name} for name in columns]})
    for row in rows:
        cells = []
        for field in columns:
            value = row[field]
            if value is None:
                cells.append({})
            else:
                text = str(value).lower() if type(value) is bool else str(value)
                cells.append({"VarCharValue": text})
        encoded.append({"Data": cells})
    return {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": [
        {"Name": name, "Type": "varchar"} for name in columns]}, "Rows": encoded}}


def packet(phase="BEFORE"):
    source = fixture()["before" if phase == "BEFORE" else "after"]
    cfg = config(phase)
    queries = collection.render_queries(cfg)
    receipts = {}
    for kind, query in queries.items():
        query_id = "fixture-query-" + kind
        receipts[kind] = {
            "execution": {"query_id": query_id, "query": query, "state": "SUCCEEDED",
                          "engine_version": "Athena engine version 3", "result_reused": False},
            "pages": [{"query_id": query_id, "request_token": None,
                       "response": page_response(kind, source[kind])}],
        }
    return {"schema_version": collection.PACKET_SCHEMA, "config": cfg,
            "captured_at": source["captured_at"], "release": source["release"],
            "queries": receipts}


class LearningEvidenceCollectionTests(unittest.TestCase):
    def assert_unverified(self, data):
        report = collection.validate_packet(data)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertIsNone(report["row_counts"])
        self.assertFalse(report["runtime_verified"])
        return report

    def test_plan_has_no_execution_or_runtime_authority(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            report = collection.plan_summary()
        self.assertEqual(report["data_queries_per_phase"], 2)
        self.assertFalse(report["execution_available"])
        self.assertFalse(report["snapshot_ids_externally_verified"])
        self.assertFalse(any(report["authority"].values()))

    def test_exact_table_snapshot_query_preserves_all_operational_rows(self):
        queries = collection.render_queries(config())
        self.assertEqual(set(queries), {"outcomes", "proposals"})
        for kind, sql in queries.items():
            self.assertTrue(sql.startswith("SELECT "))
            self.assertIn(collection.TABLES[kind], sql)
            self.assertIn("FOR VERSION AS OF ", sql)
            self.assertIn("WHERE temporal_scope_id = 'OPERATIONAL'", sql)
            self.assertNotIn("LIMIT", sql)
            self.assertNotIn("as_of_date <=", sql)
            for field in collection.FIELDS[kind]:
                self.assertIn(f"CAST({field} AS VARCHAR) AS {field}", sql)

    def test_query_injection_snapshot_overflow_future_and_unknown_scope_are_rejected(self):
        for field, value in (("database", "db; DROP TABLE x"),
                             ("outcome_snapshot_id", "1 OR 1=1"),
                             ("proposal_snapshot_id", str(2**63)),
                             ("proposal_snapshot_id", 123),
                             ("logical_date", "2099-01-01"),
                             ("phase", "PRODUCTION")):
            data = packet()
            data["config"][field] = value
            self.assert_unverified(data)
        data = packet()
        data["config"]["table"] = "arbitrary_table"
        self.assert_unverified(data)

    def test_valid_pages_assemble_exact_comparator_input_without_runtime_claims(self):
        supplied = fixture()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            supplied["before"] = collection.assemble_snapshot(packet())
            supplied["after"] = collection.assemble_snapshot(packet("AFTER"))
            report = comparison.compare_evidence(supplied)
        self.assertEqual(report["status"], "CONSISTENT_WITH_BELOW_THRESHOLD_RULE")
        self.assertFalse(report["runtime_verified"])
        self.assertFalse(report["historical_anomaly_resolved"])
        self.assertEqual(report["counts"]["eligible_after"], 2)

    def test_multi_page_chain_is_complete_and_preserves_null_and_numeric_types(self):
        data = packet()
        receipt = data["queries"]["outcomes"]
        source = fixture()["before"]["outcomes"]
        receipt["pages"][0]["response"] = page_response("outcomes", source[:1])
        receipt["pages"][0]["response"]["NextToken"] = "fixture-page-2"
        receipt["pages"].append({"query_id": receipt["execution"]["query_id"],
            "request_token": "fixture-page-2", "response": page_response("outcomes", source[1:], False)})
        snapshot = collection.assemble_snapshot(data)
        self.assertEqual(snapshot["outcomes"], source)
        self.assertEqual(snapshot["proposals"], fixture()["before"]["proposals"])

    def test_missing_final_page_is_not_complete(self):
        data = packet()
        data["queries"]["outcomes"]["pages"][0]["response"]["NextToken"] = "fixture-more"
        self.assertEqual(self.assert_unverified(data)["reasons"], ["INCOMPLETE_PAGINATION"])

    def test_wrong_query_and_first_request_token_are_rejected(self):
        for key, value in (("query_id", "wrong-query"), ("request_token", "not-the-first-page")):
            data = packet()
            data["queries"]["outcomes"]["pages"][0][key] = value
            self.assert_unverified(data)

    def test_repeated_token_and_extra_page_cannot_hide_missing_results(self):
        data = packet()
        pages = data["queries"]["outcomes"]["pages"]
        pages.append(copy.deepcopy(pages[0]))
        self.assertEqual(self.assert_unverified(data)["reasons"], ["EXTRA_PAGE_AFTER_COMPLETION"])
        pages[0]["response"]["NextToken"] = "repeat"
        pages[1]["request_token"] = "repeat"
        pages[1]["response"] = page_response("outcomes", [], False)
        pages[1]["response"]["NextToken"] = "repeat"
        self.assertEqual(self.assert_unverified(data)["reasons"], ["INVALID_OR_REPEATED_TOKEN"])

    def test_failed_reused_or_changed_query_is_unverified(self):
        for key, value in (("state", "RUNNING"), ("state", "FAILED"),
                           ("result_reused", True), ("result_reused", 0),
                           ("engine_version", "Athena engine version 2"),
                           ("query", "SELECT * FROM wrong_table")):
            data = packet()
            data["queries"]["outcomes"]["execution"][key] = value
            self.assert_unverified(data)

    def test_same_query_id_cannot_stand_for_two_tables(self):
        data = packet()
        data["queries"]["proposals"]["execution"]["query_id"] = "fixture-query-outcomes"
        self.assertEqual(self.assert_unverified(data)["reasons"], ["QUERY_ID_REUSED"])

    def test_column_header_and_row_width_drift_fail_closed(self):
        for mode in ("column", "type", "header", "width", "no_header"):
            data = packet()
            result = data["queries"]["outcomes"]["pages"][0]["response"]["ResultSet"]
            if mode == "column":
                result["ResultSetMetadata"]["ColumnInfo"].reverse()
            elif mode == "type":
                result["ResultSetMetadata"]["ColumnInfo"][0]["Type"] = "integer"
            elif mode == "header":
                result["Rows"][0]["Data"][0] = {"VarCharValue": "wrong-header"}
            elif mode == "width":
                result["Rows"][1]["Data"].pop()
            else:
                result["Rows"].pop(0)
            self.assert_unverified(data)

    def test_malformed_numbers_booleans_nulls_and_nonfinite_values_fail_closed(self):
        for field, value in (("observed_outcome_count", "2.5"),
                             ("simulation_config_change", "False"),
                             ("success_rate_pct", "NaN"), ("proposal_id", None)):
            data = packet()
            index = sorted(collection.FIELDS["proposals"]).index(field)
            data["queries"]["proposals"]["pages"][0]["response"]["ResultSet"]["Rows"][1]["Data"][index] = (
                {} if value is None else {"VarCharValue": value})
            self.assert_unverified(data)

    def test_empty_table_requires_valid_header(self):
        data = packet()
        for kind in collection.TABLES:
            data["queries"][kind]["pages"][0]["response"] = page_response(kind, [])
        result = collection.validate_packet(data)
        self.assertEqual(result["row_counts"], {"outcomes": 0, "proposals": 0})
        data["queries"]["outcomes"]["pages"][0]["response"]["ResultSet"]["Rows"] = []
        self.assert_unverified(data)

    def test_row_and_page_caps_stop_without_truncating(self):
        data = packet()
        with patch.object(comparison, "MAX_ROWS", 1):
            self.assertEqual(self.assert_unverified(data)["reasons"], ["ROW_LIMIT_EXCEEDED"])
        data["queries"]["outcomes"]["pages"] *= collection.MAX_PAGES + 1
        self.assert_unverified(data)

    def test_future_capture_and_operational_scope_corruption_fail_closed(self):
        data = packet()
        data["captured_at"] = "2099-01-01T00:00:00Z"
        self.assert_unverified(data)
        data = packet()
        index = sorted(collection.FIELDS["outcomes"]).index("execution_mode")
        data["queries"]["outcomes"]["pages"][0]["response"]["ResultSet"]["Rows"][1]["Data"][index] = {
            "VarCharValue": "FUTURE_SIMULATION"}
        self.assert_unverified(data)

    def test_success_and_errors_emit_no_private_values_or_authority(self):
        for data in (packet(), {"secret-marker": "must-not-escape"}):
            result = collection.validate_packet(data)
            rendered = json.dumps(result)
            for marker in ("fixture-", "fixture_private_database", "SELECT", "must-not-escape",
                           "a" * 64, "b" * 64):
                self.assertNotIn(marker, rendered)
            self.assertFalse(result["cross_table_consistency_verified"])
            self.assertFalse(result["generator_path_verified"])
            self.assertFalse(any(result["authority"].values()))

    def test_json_boundary_rejects_duplicates_oversize_and_malformed_inputs(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{', b'\xff'):
            self.assertEqual(collection.validate_json(raw)["status"], "UNVERIFIED")
        with patch.object(collection, "MAX_BYTES", 2):
            self.assertEqual(collection.validate_json(b'null')["reasons"], ["INPUT_TOO_LARGE"])

    def test_default_cli_does_not_read_stdin_or_offer_execution(self):
        script = str(ROOT / "ops/prepare_learning_evidence_collection.py")
        run = subprocess.run([sys.executable, script], input=b'private-invalid-input', capture_output=True)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(json.loads(run.stdout)["status"], "LOCAL_PLAN_ONLY")
        self.assertEqual(run.stderr, b"")
        run = subprocess.run([sys.executable, script, "--validate-pages"],
                             input=json.dumps(packet()).encode(), capture_output=True)
        self.assertEqual(run.returncode, 0)
        self.assertFalse(json.loads(run.stdout)["runtime_verified"])
        self.assertNotIn(b"fixture-", run.stdout)
        run = subprocess.run([sys.executable, script, "--execute", "private-marker"],
                             capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(json.loads(run.stdout)["reasons"], ["INVALID_ARGUMENTS"])
        self.assertNotIn(b"private-marker", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
