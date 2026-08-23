from datetime import date, datetime, timezone
import importlib.util
from pathlib import Path
import os
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAMBDA_DIR = ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
os.environ.setdefault("ATHENA_OUTPUT", "s3://private-query-results/lifecycle/")
MODULE_PATH = LAMBDA_DIR / "glap_lifecycle_athena_adapter.py"
SPEC = importlib.util.spec_from_file_location("lifecycle_athena_adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)


class LifecycleAthenaAdapterTests(unittest.TestCase):
    def test_configuration_queries_are_date_bounded_and_allowlisted(self):
        queries = adapter.build_configuration_queries(date(2026, 8, 4))
        self.assertEqual(set(queries), {"targets", "routes", "rates", "fx"})
        for query in queries.values():
            self.assertIn("DATE '2026-08-04'", query)
            self.assertNotIn("SELECT *", query.upper())
        self.assertIn("effective_from <=", queries["rates"])
        self.assertIn("effective_to IS NULL", queries["rates"])
        self.assertIn("transport_mode", queries["targets"])
        self.assertIn("p2p_target_hours", queries["routes"])
        self.assertIn("transport_mode", queries["rates"])

    def test_legacy_ocean_snapshot_is_coerced_into_multimodal_contract(self):
        row = {column: None for column in adapter.SNAPSHOT_COLUMNS}
        row.update(
            {
                "shipment_id": "SHP-1", "carrier": "MAERSK", "container_count": "2",
                "gate_in_target_at": "2026-09-01 12:00:00",
                "discharge_target_at": "2026-09-20 12:00:00",
                "terminal_state": "false",
            }
        )
        snapshot = adapter._coerce_snapshot(row)
        self.assertEqual(snapshot["transport_mode"], "OCEAN")
        self.assertEqual(snapshot["origin_location_type"], "PORT")
        self.assertEqual(snapshot["origin_handover_target_at"], snapshot["gate_in_target_at"])
        self.assertEqual(snapshot["destination_release_target_at"], snapshot["discharge_target_at"])
        self.assertEqual(snapshot["gross_weight_kg"], 48000.0)
        self.assertEqual(snapshot["piece_count"], 200)

    def test_active_snapshot_reads_latest_prior_non_terminal_population(self):
        query = adapter.build_active_snapshot_query(
            date(2026, 8, 4), "SIMULATION:capacity-shock"
        )
        self.assertIn("max(try_cast(prior_snapshot.dt AS date))", query)
        self.assertIn("< DATE '2026-08-04'", query)
        self.assertIn("terminal_state = false", query)
        self.assertIn("lifecycle_status = 'OPEN'", query)
        self.assertEqual(
            query.count("temporal_scope_id = 'SIMULATION:capacity-shock'"), 2
        )
        self.assertNotIn("DATE '2026-08-03'", query)
        self.assertNotIn("SELECT *", query.upper())

    def test_closed_loop_state_queries_are_scope_and_date_bounded(self):
        queries = adapter.build_closed_loop_state_queries(
            date(2026, 8, 6), "SIMULATION:capacity-shock"
        )
        self.assertEqual(
            set(queries), {"previous_alerts", "actions", "outcomes", "proposals"}
        )
        self.assertIn(
            "max(try_cast(prior_alert.dt AS date))", queries["previous_alerts"]
        )
        self.assertIn("< DATE '2026-08-06'", queries["previous_alerts"])
        self.assertNotIn("DATE '2026-08-05'", queries["previous_alerts"])
        for query in queries.values():
            self.assertIn("SIMULATION:capacity-shock", query)
            self.assertNotIn("SELECT *", query.upper())

    def test_closed_loop_rows_are_idempotent_and_outcomes_are_delayed(self):
        logical_date = date(2026, 8, 6)
        signals = [{
            "signal_fingerprint": "alert-1", "shipment_id": "SHP-1",
            "signal_type": "SLA_BREACH", "signal_grain": "SHIPMENT_MILESTONE",
            "signal_dimension": "P2P_ARRIVAL", "severity": "HIGH",
            "metric_name": "arrival_delay_hours", "metric_value": 48.0,
            "threshold_value": 0.0,
        }]
        snapshots = [{
            "shipment_id": "SHP-1", "lifecycle_stage": "IN_TRANSIT",
            "carrier": "MAERSK", "journey_exception_type": "P2P_DELAY",
        }]
        completed_action = {
            "action_id": "action-completed", "alert_fingerprint": "alert-1",
            "shipment_id": "SHP-1", "action_type": "EXPEDITE_MILESTONE",
            "alert_type": "SLA_BREACH", "alert_severity": "HIGH",
            "status": "COMPLETED", "approved_by": "Alex Chen",
            "completed_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
        }
        rows = adapter.build_closed_loop_rows(
            logical_date, signals, snapshots, [], [completed_action], [], set()
        )
        self.assertEqual(len(rows["alerts"]), 1)
        self.assertEqual(len(rows["actions"]), 1)
        self.assertEqual(rows["outcomes"][0]["status"], "PENDING")
        self.assertEqual(rows["outcomes"][0]["observation_due_date"], date(2026, 8, 8))
        replay = adapter.build_closed_loop_rows(
            logical_date,
            signals,
            snapshots,
            [],
            [completed_action, rows["actions"][0]],
            rows["outcomes"],
            set(),
        )
        self.assertEqual(replay["actions"], [])
        self.assertEqual(replay["outcomes"], [])

    def test_closed_loop_tables_use_temporal_scope_in_merge_keys(self):
        cases = (
            (adapter.ALERT_TABLE, adapter.ALERT_COLUMNS, ("temporal_scope_id", "alert_fingerprint", "dt")),
            (adapter.ACTION_TABLE, adapter.ACTION_COLUMNS, ("temporal_scope_id", "action_id")),
            (adapter.OUTCOME_TABLE, adapter.OUTCOME_COLUMNS, ("temporal_scope_id", "outcome_id", "dt")),
            (adapter.POLICY_PROPOSAL_TABLE, adapter.POLICY_PROPOSAL_COLUMNS, ("temporal_scope_id", "proposal_id")),
        )
        for table, columns, keys in cases:
            with self.subTest(table=table):
                row = {column: None for column in columns}
                row.update({key: f"value-{index}" for index, key in enumerate(keys)})
                sql = adapter.build_merge_sql(table, columns, keys, [row])[0]
                for key in keys:
                    self.assertIn(f"target.{key} = source.{key}", sql)

    def test_merge_is_retry_safe_and_escapes_values(self):
        rows = [{"event_id": "EV-1", "shipment_id": "SHP'1"}]
        statements = adapter.build_merge_sql(
            "fact_shipment_lifecycle_event_staging_v1",
            ("event_id", "shipment_id"),
            ("event_id",),
            rows,
        )
        self.assertEqual(len(statements), 1)
        self.assertIn("MERGE INTO", statements[0])
        self.assertIn("WHEN NOT MATCHED", statements[0])
        self.assertIn("'SHP''1'", statements[0])
        self.assertNotIn("WHEN MATCHED", statements[0])

    def test_explicit_recovery_updates_existing_non_key_values(self):
        rows = [{"event_id": "EV-1", "shipment_id": "SHP-1"}]
        statements = adapter.build_merge_sql(
            "fact_shipment_lifecycle_event_staging_v1",
            ("event_id", "shipment_id"),
            ("event_id",),
            rows,
            update_matched=True,
        )
        matched_clause = next(
            line for line in statements[0].splitlines() if line.startswith("WHEN MATCHED")
        )
        self.assertIn("shipment_id = source.shipment_id", matched_clause)
        self.assertNotIn("event_id = source.event_id", matched_clause)
        self.assertIn("WHEN NOT MATCHED", statements[0])

    def test_merge_batches_at_one_hundred_rows(self):
        rows = [{"event_id": f"EV-{index}"} for index in range(201)]
        statements = adapter.build_merge_sql("events", ("event_id",), ("event_id",), rows)
        self.assertEqual(len(statements), 3)

    def test_sql_literals_preserve_utc_timestamp_and_boolean_types(self):
        timestamp = datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc)
        self.assertEqual(adapter._sql_literal(timestamp), "TIMESTAMP '2026-08-04 01:02:03'")
        self.assertEqual(adapter._sql_literal(True), "true")
        self.assertEqual(adapter._sql_literal(None), "NULL")

    def test_configuration_rejects_unsafe_table_identifier(self):
        original = adapter.SNAPSHOT_TABLE
        try:
            adapter.SNAPSHOT_TABLE = "x; DROP TABLE y"
            with self.assertRaisesRegex(ValueError, "Invalid snapshot table"):
                adapter.validate_configuration()
        finally:
            adapter.SNAPSHOT_TABLE = original

    def test_temporal_provenance_is_permanent_and_uses_non_null_scope(self):
        rows = [{"shipment_id": "SHP-1"}]
        adapter.apply_temporal_provenance(
            rows,
            {
                "execution_mode": "FUTURE_SIMULATION",
                "time_basis": "FUTURE_SIMULATION",
                "as_of_date": "2026-08-06",
                "scenario_id": "capacity-shock",
            },
        )
        self.assertEqual(rows[0]["temporal_scope_id"], "SIMULATION:capacity-shock")
        self.assertEqual(rows[0]["as_of_date"], date(2026, 8, 6))
        self.assertEqual(rows[0]["execution_scenario_id"], "capacity-shock")

    def test_query_results_are_read_across_athena_pages(self):
        class PagedClient:
            def start_query_execution(self, **_kwargs):
                return {"QueryExecutionId": "query-1"}

            def get_query_execution(self, **_kwargs):
                return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

            def get_query_results(self, **kwargs):
                metadata = {"ColumnInfo": [{"Name": "shipment_id"}]}
                if "NextToken" not in kwargs:
                    return {
                        "ResultSet": {
                            "ResultSetMetadata": metadata,
                            "Rows": [
                                {"Data": [{"VarCharValue": "shipment_id"}]},
                                {"Data": [{"VarCharValue": "SHP-1"}]},
                            ],
                        },
                        "NextToken": "page-2",
                    }
                return {
                    "ResultSet": {
                        "ResultSetMetadata": metadata,
                        "Rows": [{"Data": [{"VarCharValue": "SHP-2"}]}],
                    }
                }

        self.assertEqual(
            adapter._run_query(PagedClient(), "SELECT shipment_id FROM snapshots"),
            [{"shipment_id": "SHP-1"}, {"shipment_id": "SHP-2"}],
        )


if __name__ == "__main__":
    unittest.main()
