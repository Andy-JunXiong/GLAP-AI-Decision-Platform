import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "lambda"
    / "glap_ai_agent_orchestrator.py"
)


def load_module(athena_client=None):
    client = athena_client or MagicMock()
    fake_boto3 = types.SimpleNamespace(client=MagicMock(return_value=client))
    sys.modules["boto3"] = fake_boto3

    spec = importlib.util.spec_from_file_location("agent_orchestrator", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        os.environ,
        {
            "ATHENA_DATABASE": "curated_iceberg",
            "ATHENA_OUTPUT": "s3://example/results/",
        },
        clear=False,
    ):
        spec.loader.exec_module(module)
    return module


class AgentOrchestratorTests(unittest.TestCase):
    def test_timeout_cancels_athena_query(self):
        client = MagicMock()
        client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "RUNNING"}}
        }
        module = load_module(client)

        with patch.object(module.time, "time", side_effect=[0, 2]), patch.object(
            module.time, "sleep"
        ):
            with self.assertRaises(TimeoutError):
                module.wait_for_query("query-1", timeout_seconds=1)

        client.stop_query_execution.assert_called_once_with(QueryExecutionId="query-1")

    def test_query_results_follow_pagination(self):
        client = MagicMock()
        metadata = {"ColumnInfo": [{"Label": "name"}]}
        client.get_query_results.side_effect = [
            {
                "ResultSet": {
                    "ResultSetMetadata": metadata,
                    "Rows": [
                        {"Data": [{"VarCharValue": "name"}]},
                        {"Data": [{"VarCharValue": "first"}]},
                    ],
                },
                "NextToken": "page-2",
            },
            {
                "ResultSet": {
                    "ResultSetMetadata": metadata,
                    "Rows": [{"Data": [{"VarCharValue": "second"}]}],
                }
            },
        ]
        module = load_module(client)

        self.assertEqual(
            module.get_query_results("query-1"),
            [{"name": "first"}, {"name": "second"}],
        )
        client.get_query_results.assert_called_with(
            QueryExecutionId="query-1", NextToken="page-2"
        )

    def test_existing_root_cause_can_resume_missing_decision(self):
        module = load_module()
        row = {
            "run_date": "2026-07-23",
            "entity_key": "DEHAM->AUSYD / MAERSK",
            "metric_name": "avg_leg_duration_days",
            "metric_value": "35.4",
            "baseline_value": "27.8",
            "z_score": "2.91",
        }
        existing = {
            "root_cause": "Existing explanation",
            "confidence_score": "0.8",
            "supporting_metric": "avg_leg_duration_days",
        }

        with patch.object(module, "record_exists", return_value=True), patch.object(
            module, "get_existing_root_cause", return_value=existing
        ):
            result = module.insert_root_cause_record(row)

        self.assertTrue(result["skipped"])
        self.assertEqual(result["confidence_score"], "0.8")

        with patch.object(module, "record_exists", return_value=False), patch.object(
            module, "run_query"
        ) as run_query:
            self.assertEqual(module.insert_decision_record(result), "inserted")
            run_query.assert_called_once()

    def test_handler_only_selects_unprocessed_anomalies(self):
        module = load_module()
        captured_sql = []

        def capture(sql):
            captured_sql.append(sql)
            return "query-1"

        with patch.object(module, "run_query", side_effect=capture), patch.object(
            module, "get_query_results", return_value=[]
        ):
            result = module.lambda_handler({}, None)

        self.assertEqual(result["decision_inserted"], 0)
        self.assertIn("anomaly.anomaly_flag = 1", captured_sql[0])
        self.assertIn("NOT EXISTS", captured_sql[0])
        self.assertIn("fact_ai_decision_explanations_v1", captured_sql[0])

    def test_dry_run_builds_preview_without_writes(self):
        module = load_module()
        anomaly = {
            "run_date": "2026-07-23",
            "entity_key": "DEHAM->AUSYD / MAERSK",
            "metric_name": "avg_leg_duration_days",
            "metric_value": "35.4",
            "baseline_value": "27.8",
            "z_score": "2.91",
        }

        with patch.object(module, "run_query", return_value="query-1"), patch.object(
            module, "get_query_results", return_value=[anomaly]
        ), patch.object(module, "insert_root_cause_record") as insert_root_cause:
            result = module.lambda_handler({"dry_run": True}, None)

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["anomalies_evaluated"], 1)
        self.assertEqual(result["previews"][0]["action_priority"], "HIGH")
        insert_root_cause.assert_not_called()


if __name__ == "__main__":
    unittest.main()
