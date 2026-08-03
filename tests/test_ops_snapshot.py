from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "export_ops_snapshot.py"
SPEC = importlib.util.spec_from_file_location("export_ops_snapshot", MODULE_PATH)
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(exporter)


class OpsSnapshotTests(unittest.TestCase):
    def test_query_uses_current_flywheel_contract_tables(self):
        query = exporter.build_query("curated_iceberg")
        for table in exporter.CURRENT_CONTRACT_TABLES:
            with self.subTest(table=table):
                self.assertIn(table, query)
        for legacy_table in (
            "fact_ai_anomaly_scores_v1",
            "fact_ai_root_cause_v1",
            "fact_ai_decision_explanations_v1",
        ):
            with self.subTest(legacy_table=legacy_table):
                self.assertNotIn(legacy_table, query)
        self.assertNotIn("SELECT *", query.upper())

    def test_history_query_is_bounded_and_aggregate_only(self):
        query = exporter.build_history_query("curated_iceberg", history_days=28)
        self.assertIn("date_add('day', -27", query)
        self.assertIn("count(DISTINCT shipment_id)", query)
        self.assertNotIn("SELECT *", query.upper())
        with self.assertRaises(ValueError):
            exporter.build_history_query("curated_iceberg", history_days=365)

    def test_rejects_unsafe_database_identifier(self):
        with self.assertRaises(ValueError):
            exporter.build_query("curated_iceberg; DROP TABLE x")

    def test_parses_athena_result(self):
        response = {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": "latest_run_date"}, {"VarCharValue": "alerts_generated"}]},
                    {"Data": [{"VarCharValue": "2026-08-03"}, {"VarCharValue": "4"}]},
                ]
            }
        }
        self.assertEqual(
            exporter.parse_athena_result(response),
            {"latest_run_date": "2026-08-03", "alerts_generated": "4"},
        )

    def test_builds_fresh_sanitized_snapshot(self):
        row = {
            "latest_shipment_date": "2026-08-03",
            "latest_alert_date": "2026-08-03",
            "latest_insight_date": "2026-08-03",
            "latest_decision_date": "2026-08-03",
            "latest_action_date": "2026-08-03",
            "latest_outcome_date": "2026-08-03",
            "latest_learning_date": "2026-08-03",
            "shipments_generated": "468",
            "shipments_at_risk": "15",
            "alerts_generated": "3",
            "root_causes_generated": "3",
            "decisions_generated": "3",
            "actions_generated": "3",
            "actions_completed": "2",
            "actions_open": "1",
            "outcomes_generated": "2",
            "learning_records_generated": "2",
            "avg_outcome_improvement_pct": "12.345",
            "avg_effectiveness_score": "0.84",
            "outcome_success_rate_pct": "75.0",
        }
        history = [
            {
                "metric_date": f"2026-07-{day:02d}" if day <= 31 else f"2026-08-{day - 31:02d}",
                "shipments_generated": str(400 + day),
                "shipments_at_risk": "10",
            }
            for day in range(7, 35)
        ]
        snapshot = exporter.build_snapshot(
            row,
            history,
            now=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot["freshness"]["status"], "fresh")
        self.assertTrue(snapshot["provenance"]["is_connected"])
        self.assertEqual(snapshot["metrics"]["shipments_generated"], 468)
        self.assertEqual(snapshot["metrics"]["actions_generated"], 3)
        self.assertEqual(snapshot["analytics"]["action_completion_rate_pct"], 66.7)
        self.assertEqual(snapshot["forecast"]["status"], "ready")
        self.assertEqual(len(snapshot["forecast"]["points"]), 7)
        self.assertEqual(snapshot["schema_version"], "1.1")
        serialized = json.dumps(snapshot)
        for forbidden in ("shipment_id", "entity_key", "account_id", "arn:", "s3://"):
            self.assertNotIn(forbidden, serialized.lower())

    def test_partial_pipeline_is_not_reported_fresh(self):
        row = {
            "latest_shipment_date": "2026-08-03",
            "latest_alert_date": "2026-08-03",
            "latest_insight_date": "2026-03-07",
            "latest_decision_date": "2026-03-07",
            "latest_action_date": "2026-08-03",
            "latest_outcome_date": "2026-08-03",
            "latest_learning_date": "2026-08-03",
        }
        snapshot = exporter.build_snapshot(
            row,
            now=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot["freshness"]["status"], "stale")
        self.assertEqual(snapshot["pipeline"]["status"], "partial_or_stale")
        self.assertEqual(snapshot["stage_freshness"]["decisions"]["status"], "stale")

    def test_committed_fallback_is_explicitly_not_live(self):
        path = ROOT / "offline" / "data" / "ops-snapshot.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(snapshot["provenance"]["is_connected"])
        self.assertEqual(snapshot["provenance"]["connection"], "repository_fallback")
        self.assertEqual(snapshot["freshness"]["status"], "stale")

    def test_role_and_analyst_sql_follow_the_current_contract(self):
        setup = (ROOT / "ops" / "configure_ops_snapshot_access.ps1").read_text(encoding="utf-8")
        analyst_sql = (ROOT / "sql" / "03_ops_analytics.sql").read_text(encoding="utf-8")
        for table in exporter.CURRENT_CONTRACT_TABLES:
            with self.subTest(table=table):
                self.assertIn(table, setup)
                self.assertIn(table, analyst_sql)
        self.assertIn("UNNEST(sequence(1, 7))", analyst_sql)
        self.assertIn("avg_effectiveness_score", analyst_sql)


if __name__ == "__main__":
    unittest.main()
