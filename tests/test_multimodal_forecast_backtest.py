from datetime import date, timedelta
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "backtest_multimodal_forecast.py"
SPEC = importlib.util.spec_from_file_location("backtest_multimodal_forecast", MODULE_PATH)
backtest = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = backtest
SPEC.loader.exec_module(backtest)


def observations(days=30, value=lambda index: float(index + 1)):
    start = date(2026, 7, 1)
    return [
        backtest.Observation(start + timedelta(days=index), "OCEAN", "MAERSK", value(index))
        for index in range(days)
    ]


class MultimodalForecastBacktestTests(unittest.TestCase):
    def test_all_models_use_only_past_rows(self):
        predictions = backtest.rolling_backtest(observations(20), minimum_history=14)
        self.assertEqual(len(predictions), 6 * 4)
        self.assertEqual({row.model for row in predictions}, set(backtest.MODEL_NAMES))
        self.assertTrue(all(row.training_end < row.feature_date for row in predictions))

    def test_expected_predictions_for_linear_history(self):
        first = backtest.rolling_backtest(observations(15), minimum_history=14)
        by_model = {row.model: row for row in first}
        self.assertEqual(by_model["recent_level"].predicted, 14.0)
        self.assertEqual(by_model["moving_average_7d"].predicted, 11.0)
        self.assertEqual(by_model["weekday_seasonal"].predicted, 4.5)
        self.assertAlmostEqual(by_model["ols_trend"].predicted, 15.0)
        self.assertEqual(by_model["recent_level"].training_rows, 1)
        self.assertEqual(by_model["moving_average_7d"].training_rows, 7)
        self.assertEqual(by_model["weekday_seasonal"].training_rows, 2)
        self.assertEqual(by_model["ols_trend"].training_rows, 14)

    def test_metrics_define_mape_only_for_nonzero_actuals(self):
        rows = observations(17, value=lambda index: 0.0 if index >= 14 else 2.0)
        metrics = backtest.summarize(backtest.rolling_backtest(rows, minimum_history=14))
        self.assertTrue(all(item["mape_pct"] is None for item in metrics))
        self.assertTrue(all(item["mape_defined_count"] == 0 for item in metrics))
        self.assertTrue(all(0 <= item["interval_coverage_pct"] <= 100 for item in metrics))
        self.assertTrue(all(item["normalized_mae_pct"] is None for item in metrics))

    def test_csv_contract_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.csv"
            path.write_text(
                "feature_date,transport_mode,provider_code,new_booking_count\n"
                "2026-08-01,AIR,DHL,3\n2026-08-01,AIR,DHL,4\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                backtest.load_observations(path)

    def test_strict_csv_contract_rejects_wrong_version_and_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.csv"
            path.write_text(
                "feature_date,transport_mode,provider_code,new_booking_count,"
                "feature_cutoff_date,feature_contract_version,leakage_policy\n"
                "2026-08-01,AIR,DHL,3,2026-07-31,wrong,NO_FUTURE_DATA\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "feature_contract_version"):
                backtest.load_observations(path, require_contract=True)

    def test_csv_contract_rejects_non_finite_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.csv"
            path.write_text(
                "feature_date,transport_mode,provider_code,new_booking_count\n"
                "2026-08-01,AIR,DHL,nan\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "finite"):
                backtest.load_observations(path)

    def test_report_exposes_insufficient_history(self):
        report = backtest.build_report(observations(14), minimum_history=14)
        self.assertEqual(report["status"], "insufficient_history")
        self.assertEqual(report["metrics"], [])
        self.assertFalse(report["coverage"][0]["eligible_for_evaluation"])

    def test_report_records_contract_and_evaluation_policy(self):
        report = backtest.build_report(observations(15), minimum_history=14)
        self.assertEqual(report["feature_contract_version"], "multimodal_forecast_feature_daily_v1")
        self.assertEqual(report["evaluation_policy"], "ROLLING_ONE_STEP_AHEAD_NO_FUTURE_DATA")
        self.assertEqual(len(report["metrics"]), 4)
        self.assertEqual(report["status"], "ready")
        self.assertTrue(all(item["normalized_mae_pct"] is not None for item in report["metrics"]))
        self.assertEqual(report["recommendations"][0]["selected_model"], "recent_level")
        self.assertEqual(
            report["recommendations"][0]["selection_reason"],
            "INSUFFICIENT_SELECTION_WINDOWS_RETAIN_SIMPLE_BENCHMARK",
        )

    def test_consistent_challenger_can_replace_simple_benchmark(self):
        report = backtest.build_report(observations(30), minimum_history=14)
        recommendation = report["recommendations"][0]
        self.assertEqual(recommendation["selected_model"], "ols_trend")
        self.assertEqual(
            recommendation["selection_reason"],
            "LOWER_MAE_RMSE_AND_AT_LEAST_60_PCT_POINT_WINS",
        )

    def test_coverage_reports_missing_days_and_drift(self):
        rows = observations(15, value=lambda index: float(10 + index))
        rows.pop(5)
        result = backtest.coverage(rows, minimum_history=14)[0]
        self.assertEqual(result["missing_calendar_days"], 1)
        self.assertLess(result["calendar_completeness_pct"], 100)
        self.assertIsNotNone(result["booking_count_recent_vs_prior_7d_pct"])


if __name__ == "__main__":
    unittest.main()
