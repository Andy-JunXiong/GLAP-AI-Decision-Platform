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
    def test_query_uses_only_verified_public_contract_tables(self):
        query = exporter.build_query("curated_iceberg")
        self.assertIn("fact_shipment_events_extended_iceberg", query)
        self.assertIn("fact_ai_anomaly_scores_v1", query)
        self.assertIn("fact_ai_root_cause_v1", query)
        self.assertIn("fact_ai_decision_explanations_v1", query)
        self.assertNotIn("SELECT *", query.upper())

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
            "latest_run_date": "2026-08-03",
            "shipments_generated": "468",
            "shipments_at_risk": "15",
            "alerts_generated": "3",
            "root_causes_generated": "3",
            "decisions_generated": "3",
        }
        snapshot = exporter.build_snapshot(
            row,
            now=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot["freshness"]["status"], "fresh")
        self.assertTrue(snapshot["provenance"]["is_connected"])
        self.assertEqual(snapshot["metrics"]["shipments_generated"], 468)
        self.assertIsNone(snapshot["metrics"]["actions_generated"])
        serialized = json.dumps(snapshot)
        for forbidden in ("shipment_id", "entity_key", "account_id", "arn:", "s3://"):
            self.assertNotIn(forbidden, serialized.lower())

    def test_committed_fallback_is_explicitly_not_live(self):
        path = ROOT / "offline" / "data" / "ops-snapshot.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(snapshot["provenance"]["is_connected"])
        self.assertEqual(snapshot["provenance"]["connection"], "repository_fallback")
        self.assertEqual(snapshot["freshness"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
