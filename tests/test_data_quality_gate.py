import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


LAMBDA_DIR = Path(__file__).resolve().parents[1] / "lambda"
MODULE_PATH = LAMBDA_DIR / "glap_data_quality_gate.py"
if str(LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDA_DIR))


def load_module(athena_client=None):
    client = athena_client or MagicMock()
    fake_boto3 = types.SimpleNamespace(client=MagicMock(return_value=client))
    sys.modules["boto3"] = fake_boto3
    spec = importlib.util.spec_from_file_location("data_quality_gate", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with patch.dict(
        os.environ,
        {
            "ATHENA_DATABASE": "curated_iceberg",
            "ATHENA_SOURCE_DATABASE": "simulated_iceberg_m",
            "ATHENA_OUTPUT": "s3://example/results/",
        },
        clear=False,
    ):
        spec.loader.exec_module(module)
    return module


PASSING_METRICS = {
    "required_tables": "6",
    "populated_tables": "6",
    "current_tables": "6",
    "total_rows": "2400",
    "duplicate_business_keys": "0",
    "observed_volume": "450",
    "previous_volume": "440",
}


class DataQualityGateTests(unittest.TestCase):
    def test_input_query_uses_all_current_v2_inputs_and_business_keys(self):
        module = load_module()
        query = module.build_input_quality_query("2026-08-04")
        for table in (
            "fact_shipment_v2",
            "fact_shipment_event_v2",
            "fact_shipment_leg_metrics_core_v2",
            "fact_shipment_cost_v2",
            "fact_shipment_risk_v2",
            "shipment_product_allocation_v2",
        ):
            self.assertIn(table, query)
        self.assertIn("DATE '2026-08-04'", query)
        self.assertIn("duplicate_count", query)
        self.assertNotIn("SELECT *", query.upper())

    def test_output_query_uses_current_public_contract_tables(self):
        module = load_module()
        query = module.build_output_quality_query("2026-08-04")
        for table in (
            "fact_ai_alerts_v3",
            "fact_ai_insights_v3",
            "fact_ai_decisions_v3",
            "fact_ai_actions_v2",
            "fact_ai_outcomes_v2",
            "fact_ai_learning_v1",
        ):
            self.assertIn(table, query)
        self.assertIn("simulated_iceberg_m.fact_shipment_v2", query)
        self.assertNotIn("SELECT *", query.upper())

    def test_lifecycle_compatibility_query_uses_all_six_read_only_views(self):
        module = load_module()
        query = module.build_input_quality_query(
            "2026-09-01", quality_contract="lifecycle_compat_v2"
        )
        for view in (
            "vw_lifecycle_shipment_v2_compat",
            "vw_lifecycle_shipment_event_v2_compat",
            "vw_lifecycle_leg_metrics_v2_compat",
            "vw_lifecycle_cost_v2_compat",
            "vw_lifecycle_risk_v2_compat",
            "vw_lifecycle_product_allocation_v2_compat",
        ):
            self.assertIn(view, query)
        self.assertNotIn("fact_shipment_v2", query)

    def test_rejects_unsafe_database_and_invalid_date(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.build_input_quality_query("2026-08-04", "db; DROP TABLE x")
        with self.assertRaises(ValueError):
            module.build_output_quality_query("04-08-2026")

    def test_passing_metrics_emit_exact_quality_contract(self):
        module = load_module()
        checks, metrics = module.evaluate_quality_metrics(PASSING_METRICS, 50)
        self.assertEqual(set(checks), set(module.QUALITY_CHECK_NAMES))
        self.assertTrue(all(status == "passed" for status in checks.values()))
        self.assertEqual(metrics["volume_change_pct"], 2.27)

    def test_duplicate_and_volume_spike_fail_closed(self):
        module = load_module()
        row = dict(
            PASSING_METRICS,
            duplicate_business_keys="2",
            observed_volume="900",
        )
        checks, _ = module.evaluate_quality_metrics(row, 50)
        self.assertEqual(checks["duplicate_business_keys"], "failed")
        self.assertEqual(checks["abnormal_volume_change"], "failed")

    def test_missing_previous_volume_fails_baseline_gate(self):
        module = load_module()
        row = dict(PASSING_METRICS, previous_volume="0")
        checks, metrics = module.evaluate_quality_metrics(row, 50)
        self.assertEqual(checks["abnormal_volume_change"], "failed")
        self.assertIsNone(metrics["volume_change_pct"])

    def test_handler_selects_input_and_output_queries(self):
        module = load_module()
        with patch.object(module, "run_query", return_value=PASSING_METRICS) as run_query:
            input_result = module.lambda_handler(
                {"logical_run_date": "2026-08-04", "pipeline_stage": "input_validation"},
                None,
            )
            output_result = module.lambda_handler(
                {"run_date": "2026-08-04", "pipeline_stage": "output_validation"},
                None,
            )
        self.assertEqual(input_result["status"], "success")
        self.assertEqual(output_result["status"], "success")
        self.assertEqual(run_query.call_count, 2)

    def test_lifecycle_handler_emits_exact_multimodal_check_contract(self):
        module = load_module()
        failures = {name: 0 for name in module.LIFECYCLE_CHECK_NAMES}
        with patch.object(
            module, "run_lifecycle_validation", return_value=failures
        ) as validate:
            result = module.lambda_handler(
                {
                    "logical_run_date": "2026-09-01",
                    "pipeline_stage": "lifecycle_validation",
                    "quality_contract": "lifecycle_v1",
                },
                None,
            )
        self.assertEqual(set(result["quality_checks"]), set(module.LIFECYCLE_CHECK_NAMES))
        self.assertTrue(all(value == "passed" for value in result["quality_checks"].values()))
        self.assertEqual(result["metrics"]["check_count"], 20)
        validate.assert_called_once_with(
            "2026-09-01", "simulated_iceberg_m", "OPERATIONAL"
        )

    def test_multimodal_analytics_handler_emits_exact_check_contract(self):
        module = load_module()
        failures = {name: 0 for name in module.MULTIMODAL_ANALYTICS_CHECK_NAMES}
        with patch.object(
            module, "run_multimodal_analytics_validation", return_value=failures
        ) as validate:
            result = module.lambda_handler(
                {
                    "logical_run_date": "2026-09-07",
                    "pipeline_stage": "analytics_validation",
                    "quality_contract": "multimodal_analytics_v1",
                },
                None,
            )
        self.assertEqual(
            set(result["quality_checks"]),
            set(module.MULTIMODAL_ANALYTICS_CHECK_NAMES),
        )
        self.assertTrue(
            all(value == "passed" for value in result["quality_checks"].values())
        )
        self.assertEqual(result["metrics"]["check_count"], 8)
        validate.assert_called_once_with(
            "2026-09-07", "simulated_iceberg_m", "OPERATIONAL"
        )

    def test_multimodal_analytics_query_is_single_safe_statement(self):
        module = load_module()
        query = module.render_multimodal_analytics_validation_query(
            "2026-09-07", "simulated_iceberg_m"
        )
        self.assertIn("DATE '2026-09-07'", query)
        self.assertIn("vw_multimodal_mode_decision_context_v1", query)
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", query)
        self.assertNotIn("{{", query)
        with self.assertRaises(ValueError):
            module.render_multimodal_analytics_validation_query(
                "2026-09-07", "unsafe;drop"
            )

    def test_future_simulation_quality_queries_are_scenario_isolated(self):
        module = load_module()
        query = module.build_input_quality_query(
            "2026-09-07",
            "simulated_iceberg_m",
            "lifecycle_compat_v2",
            "SIMULATION:capacity-shock",
        )
        self.assertIn("vw_lifecycle_shipment_v2_compat_context", query)
        self.assertIn("temporal_scope_id = 'SIMULATION:capacity-shock'", query)
        analytics = module.render_multimodal_analytics_validation_query(
            "2026-09-07",
            "simulated_iceberg_m",
            temporal_scope_id="SIMULATION:capacity-shock",
        )
        self.assertIn("temporal_scope_id = 'SIMULATION:capacity-shock'", analytics)

    def test_validation_result_rejects_duplicate_checks(self):
        module = load_module()
        response = {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": "check_name"}, {"VarCharValue": "failure_count"}]},
                    {"Data": [{"VarCharValue": "duplicate"}, {"VarCharValue": "0"}]},
                    {"Data": [{"VarCharValue": "duplicate"}, {"VarCharValue": "0"}]},
                ]
            }
        }
        with self.assertRaises(ValueError):
            module.parse_validation_result(response)

    def test_parse_result_requires_one_data_row(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.parse_athena_result({"ResultSet": {"Rows": []}})


if __name__ == "__main__":
    unittest.main()
