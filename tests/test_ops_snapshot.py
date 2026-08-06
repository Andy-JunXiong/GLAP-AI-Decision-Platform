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


def athena_forecast_rows():
    common = {
        "observed_days": "28",
        "data_completeness_pct": "100.0",
        "latest_daily_shipments": "425",
        "average_daily_shipments": "420.0",
        "latest_risk_rate_pct": "2.0",
        "daily_volume_trend_pct": "0.5",
    }
    history = [
        {
            **common,
            "row_type": "history",
            "metric_date": f"2026-07-{day:02d}",
            "shipments_generated": str(390 + day),
            "shipments_at_risk": "8",
            "predicted_shipments_total": None,
        }
        for day in range(4, 32)
    ]
    forecast = [
        {
            **common,
            "row_type": "forecast",
            "metric_date": f"2026-08-{day:02d}",
            "predicted_shipments": str(425 + day),
            "lower_bound": str(400 + day),
            "upper_bound": str(450 + day),
            "predicted_at_risk": "9",
            "predicted_shipments_total": "3010",
        }
        for day in range(4, 11)
    ]
    return history + forecast


def operational_baseline_row(delivered_count: str = "0"):
    delivered = int(delivered_count)
    return {
        "dimension_type": "ALL",
        "dimension_value": "ALL",
        "baseline_as_of_date": "2026-08-03",
        "source_start_date": "2026-08-01",
        "source_max_metric_date": "2026-08-03",
        "shipment_count": "498",
        "new_booking_count": "48",
        "delivered_count": delivered_count,
        "on_time_delivery_count": "180" if delivered else "0",
        "late_delivery_count": "20" if delivered else "0",
        "on_time_delivery_rate_pct": "90.0" if delivered else None,
        "avg_delivery_delay_hours": "2.4" if delivered else None,
        "sla_breach_shipment_count": "7",
        "sla_breach_shipment_rate_pct": "1.41",
        "expected_cost_total": "100000.0",
        "current_cost_total": "103000.0",
        "cost_variance_pct": "3.0" if delivered else None,
        "signal_candidate_count": "41",
        "high_severity_signal_count": "28",
        "real_world_evidence": "false",
        "data_provenance": "SIMULATED_MULTIMODAL_V1",
        "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE",
        "decision_use": "ENGINEERING_EVALUATION_ONLY",
    }


class OpsSnapshotTests(unittest.TestCase):
    def test_query_uses_current_flywheel_contract_tables(self):
        query = exporter.build_query("curated_iceberg", "2026-08-04")
        for table in (
            "simulated_iceberg_m.fact_shipment_v2",
            "fact_ai_alerts_v3",
            "fact_ai_insights_v3",
            "fact_ai_decisions_v3",
            "fact_ai_actions_v2",
            "fact_ai_outcomes_v2",
            "fact_ai_learning_v1",
        ):
            with self.subTest(table=table):
                self.assertIn(table, query)
        for legacy_table in (
            "fact_shipment_events_extended_iceberg",
            "fact_ai_anomaly_scores_v1",
            "fact_ai_root_cause_v1",
            "fact_ai_decision_explanations_v1",
        ):
            with self.subTest(legacy_table=legacy_table):
                self.assertNotIn(legacy_table, query)
        self.assertNotIn("SELECT *", query.upper())
        self.assertIn("try_cast(dt AS date)", query)
        self.assertIn("shipment_risk_counts", query)
        self.assertIn("JOIN risk_keys", query)
        self.assertNotIn("upper(status)", query.lower())
        self.assertNotIn("max(CAST(event_time AS date))", query)
        self.assertIn("DATE '2026-08-04'", query)

    def test_forecast_query_runs_ols_in_athena_on_logical_dt(self):
        query = exporter.build_forecast_query(
            "curated_iceberg", "2026-08-04", history_days=28
        )
        self.assertIn("date_add('day', -27", query)
        self.assertIn("count(DISTINCT shipment_id)", query)
        self.assertIn("UNNEST(sequence(1, 7))", query)
        self.assertIn("residual_sigma", query)
        self.assertIn("try_cast(dt AS date)", query)
        self.assertIn("risk_observed", query)
        self.assertIn("JOIN risk_keys", query)
        self.assertNotIn("upper(status)", query.lower())
        self.assertNotIn("max(CAST(event_time AS date))", query)
        self.assertNotIn("SELECT *", query.upper())
        with self.assertRaises(ValueError):
            exporter.build_forecast_query("curated_iceberg", "2026-08-04", history_days=365)

    def test_existing_analytics_query_reuses_deployed_views(self):
        query = exporter.build_existing_analytics_query("curated_iceberg", "2026-08-04")
        self.assertIn("fact_ai_insights_v3", query)
        self.assertIn("root_cause_type", query)
        self.assertNotIn("root_cause_title", query)
        self.assertIn("fact_ai_actions_v2", query)
        self.assertNotIn("fact_ai_root_causes_v1", query)
        self.assertNotIn("v_ai_latest_decision_trace", query)
        self.assertNotIn("FROM curated_iceberg.fact_ai_decisions_v3", query)
        self.assertIn("SELECT DISTINCT route_id, carrier, alert_type", query)
        self.assertNotIn("v_ai_action_distribution", query)
        self.assertNotIn("v_ai_alert_distribution", query)
        self.assertIn("DATE '2026-08-04'", query)

    def test_operational_baseline_query_is_aggregate_only_and_date_bounded(self):
        query = exporter.build_operational_baseline_query(
            "simulated_iceberg_m", "2026-08-06"
        )
        self.assertIn("vw_multimodal_operational_baseline_v1", query)
        self.assertIn("dimension_type", query)
        self.assertIn("dimension_value", query)
        self.assertIn("'TRANSPORT_MODE'", query)
        self.assertIn("'PROVIDER'", query)
        self.assertIn("'MARKET_LANE'", query)
        self.assertIn("baseline_as_of_date <= DATE '2026-08-06'", query)
        self.assertIn("max(baseline_as_of_date)", query)
        self.assertIn("JOIN latest_baseline", query)
        self.assertNotIn("dimension_type = 'ALL'", query)
        self.assertNotIn("LIMIT 1", query)
        self.assertNotIn("shipment_id", query)

    def test_rejects_unsafe_database_identifier(self):
        with self.assertRaises(ValueError):
            exporter.build_query("curated_iceberg; DROP TABLE x", "2026-08-04")
        with self.assertRaises(ValueError):
            exporter.build_query("curated_iceberg", "2026-08-04'; DROP TABLE x")

    def test_analysis_date_prefers_governed_run_and_rejects_future_anchor(self):
        now = datetime(2026, 8, 4, 2, tzinfo=timezone.utc)
        self.assertEqual(
            exporter.resolve_analysis_date({"logical_run_date": "2026-08-04"}, now),
            datetime(2026, 8, 4).date(),
        )
        self.assertEqual(
            exporter.resolve_analysis_date({"logical_run_date": "2026-08-06"}, now),
            datetime(2026, 8, 4).date(),
        )

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
            "action_completion_rate_pct": "66.7",
            "outcomes_generated": "2",
            "learning_records_generated": "2",
            "avg_outcome_improvement_pct": "12.345",
            "avg_effectiveness_score": "0.84",
            "outcome_success_rate_pct": "75.0",
        }
        existing_assets = [
            {"dimension": "summary", "label": "risk_hotspots_tracked", "metric_count": "12"},
            {"dimension": "actions", "label": "MONITOR", "metric_count": "81"},
            {"dimension": "alerts", "label": "SLA_BREACH", "metric_count": "42"},
            {"dimension": "root_causes", "label": "Carrier delay", "metric_count": "17"},
        ]
        snapshot = exporter.build_snapshot(
            row,
            athena_forecast_rows(),
            existing_assets,
            operational_baseline_row(),
            now=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot["freshness"]["status"], "fresh")
        self.assertTrue(snapshot["provenance"]["is_connected"])
        self.assertEqual(snapshot["metrics"]["shipments_generated"], 468)
        self.assertEqual(snapshot["metrics"]["actions_generated"], 3)
        self.assertEqual(snapshot["analytics"]["action_completion_rate_pct"], 66.7)
        self.assertEqual(snapshot["analytics"]["calculation_engine"], "aws_athena_engine_v3")
        self.assertEqual(snapshot["analytics"]["existing_assets"]["risk_hotspots_tracked"], 12)
        self.assertEqual(
            snapshot["analytics"]["existing_assets"]["distributions"]["actions"][0],
            {"label": "MONITOR", "count": 81},
        )
        self.assertEqual(snapshot["forecast"]["status"], "ready")
        self.assertEqual(snapshot["forecast"]["calculation_engine"], "aws_athena_engine_v3")
        self.assertEqual(len(snapshot["forecast"]["points"]), 7)
        self.assertEqual(snapshot["schema_version"], "1.7")
        self.assertEqual(snapshot["provenance"]["outcome_evidence"], "simulated")
        self.assertEqual(snapshot["operational_baseline"]["status"], "available")
        self.assertEqual(
            snapshot["operational_baseline"]["maturity"]["status"], "NOT_READY"
        )
        self.assertIsNone(
            snapshot["operational_baseline"]["metrics"]["cost_variance_pct"]
        )
        self.assertEqual(snapshot["pipeline"]["query_checks_succeeded"], 4)
        serialized = json.dumps(snapshot)
        for forbidden in ("shipment_id", "entity_key", "account_id", "arn:", "s3://"):
            self.assertNotIn(forbidden, serialized.lower())

    def test_operational_baseline_readiness_is_fail_closed_and_truthful(self):
        ready = exporter.parse_operational_baseline(
            operational_baseline_row("200"), "2026-08-06"
        )
        self.assertEqual(ready["maturity"]["status"], "ENGINEERING_READY")
        self.assertEqual(ready["maturity"]["real_world_status"], "BLOCKED")
        self.assertFalse(ready["evidence"]["real_world_evidence"])
        self.assertEqual(ready["metrics"]["cost_variance_pct"], 3.0)

        unsafe = operational_baseline_row()
        unsafe["real_world_evidence"] = "true"
        with self.assertRaises(ValueError):
            exporter.parse_operational_baseline(unsafe, "2026-08-06")

        future = operational_baseline_row()
        future["baseline_as_of_date"] = "2026-08-07"
        with self.assertRaises(ValueError):
            exporter.parse_operational_baseline(future, "2026-08-06")

    def test_operational_baseline_rows_publish_safe_breakdowns(self):
        lane = {
            **operational_baseline_row(),
            "dimension_type": "MARKET_LANE",
            "dimension_value": "PUS-BNE",
            "shipment_count": "48",
            "new_booking_count": "5",
            "sla_breach_shipment_count": "2",
            "sla_breach_shipment_rate_pct": "4.17",
            "signal_candidate_count": "12",
            "high_severity_signal_count": "12",
            "expected_cost_total": "800000",
        }
        mode = {
            **operational_baseline_row(),
            "dimension_type": "TRANSPORT_MODE",
            "dimension_value": "OCEAN",
        }
        provider = {
            **operational_baseline_row(),
            "dimension_type": "PROVIDER",
            "dimension_value": "MAERSK",
        }
        baseline = exporter.parse_operational_baseline_rows(
            [operational_baseline_row(), lane, mode, provider], "2026-08-06"
        )
        self.assertEqual(baseline["breakdowns"]["market_lanes"][0]["name"], "PUS-BNE")
        self.assertEqual(baseline["breakdowns"]["market_lanes"][0]["shipment_count"], 48)
        self.assertEqual(baseline["outcome_labels"], {"observed": 0, "pending": 498, "total": 498})
        self.assertEqual(baseline["population_profile"]["transport_mode_count"], 1)
        self.assertEqual(baseline["population_profile"]["multimodal_status"], "SINGLE_MODE_OBSERVED")

        unsafe = dict(lane, dimension_value="PUS-BNE<script>")
        with self.assertRaises(ValueError):
            exporter.parse_operational_baseline_rows(
                [operational_baseline_row(), unsafe], "2026-08-06"
            )

        duplicate = dict(lane)
        with self.assertRaises(ValueError):
            exporter.parse_operational_baseline_rows(
                [operational_baseline_row(), lane, duplicate], "2026-08-06"
            )

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

    def test_verified_pipeline_run_is_required_when_gate_is_enabled(self):
        row = {
            "latest_shipment_date": "2026-08-04",
            "latest_alert_date": "2026-08-04",
            "latest_insight_date": "2026-08-04",
            "latest_decision_date": "2026-08-04",
            "latest_action_date": "2026-08-04",
            "latest_outcome_date": "2026-08-04",
            "latest_learning_date": "2026-08-04",
        }
        missing = exporter.build_snapshot(
            row,
            now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            pipeline_status_required=True,
        )
        self.assertEqual(missing["freshness"]["status"], "stale")
        self.assertEqual(missing["pipeline"]["status"], "unverified")
        self.assertEqual(missing["pipeline"]["failure_category"], "status_unavailable")

        pipeline_run = {
            "logical_run_date": "2026-08-04",
            "started_at": "2026-08-04T00:05:00Z",
            "completed_at": "2026-08-04T00:07:00Z",
            "status": "succeeded",
            "failed_stage": None,
            "failure_category": None,
            "stages": [
                {
                    "name": name,
                    "started_at": "2026-08-04T00:05:00Z",
                    "completed_at": "2026-08-04T00:07:00Z",
                    "duration_ms": 20000,
                    "status": "succeeded",
                    "failure_category": None,
                    "quality_checks": (
                        [
                            {"name": check, "status": "passed"}
                            for check in sorted(exporter.PIPELINE_QUALITY_CHECKS)
                        ]
                        if name in exporter.PIPELINE_QUALITY_STAGES
                        else []
                    ),
                }
                for name in exporter.PIPELINE_STAGE_ORDER
            ],
        }
        verified = exporter.build_snapshot(
            row,
            operational_baseline_row=operational_baseline_row(),
            now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            pipeline_run=pipeline_run,
            pipeline_status_required=True,
        )
        self.assertEqual(verified["freshness"]["status"], "fresh")
        self.assertEqual(verified["pipeline"]["status"], "current")
        self.assertEqual(verified["pipeline"]["duration_ms"], 120000)
        self.assertEqual(verified["pipeline"]["stage_count"], 6)
        self.assertEqual(verified["pipeline"]["stages_succeeded"], 6)
        self.assertEqual(verified["pipeline"]["quality_checks_succeeded"], 10)
        self.assertEqual(verified["pipeline"]["quality_checks_total"], 10)

        previous_day = dict(pipeline_run, logical_run_date="2026-08-03")
        stale_run = exporter.build_snapshot(
            row,
            now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            pipeline_run=previous_day,
            pipeline_status_required=True,
        )
        self.assertEqual(stale_run["freshness"]["status"], "stale")
        self.assertEqual(stale_run["pipeline"]["status"], "unverified")

    def test_incomplete_stage_or_quality_contract_cannot_report_current(self):
        row = {key: "2026-08-04" for key in exporter.STAGE_DATE_COLUMNS.values()}
        incomplete_run = {
            "logical_run_date": "2026-08-04",
            "status": "succeeded",
            "stages": [
                {
                    "name": "input_validation",
                    "status": "succeeded",
                    "quality_checks": [
                        {"name": name, "status": "passed"}
                        for name in sorted(exporter.PIPELINE_QUALITY_CHECKS)
                    ],
                }
            ],
        }
        snapshot = exporter.build_snapshot(
            row,
            operational_baseline_row=operational_baseline_row(),
            now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            pipeline_run=incomplete_run,
            pipeline_status_required=True,
        )
        self.assertEqual(snapshot["freshness"]["status"], "stale")
        self.assertEqual(snapshot["pipeline"]["status"], "unverified")
        self.assertEqual(snapshot["pipeline"]["stage_count"], 1)
        self.assertEqual(snapshot["pipeline"]["quality_checks_succeeded"], 5)

    def test_failed_pipeline_run_cannot_report_current(self):
        row = {
            key: "2026-08-04"
            for key in exporter.STAGE_DATE_COLUMNS.values()
        }
        failed = exporter.build_snapshot(
            row,
            now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            pipeline_run={
                "logical_run_date": "2026-08-04",
                "status": "failed",
                "failed_stage": "input_validation",
                "failure_category": "quality_gate_failed",
                "stages": [],
            },
            pipeline_status_required=True,
        )
        self.assertEqual(failed["freshness"]["status"], "stale")
        self.assertEqual(failed["pipeline"]["status"], "failed")
        self.assertEqual(failed["pipeline"]["failed_stage"], "input_validation")

    def test_future_simulation_pipeline_cannot_report_current(self):
        pipeline_run = {
            "logical_run_date": "2026-08-04",
            "execution_mode": "FUTURE_SIMULATION",
            "time_basis": "FUTURE_SIMULATION",
            "scenario_id": "q4-lifecycle-2026",
            "status": "succeeded",
            "started_at": "2026-08-04T00:00:00Z",
            "completed_at": "2026-08-04T00:01:00Z",
            "stages": [
                {
                    "name": "input_validation",
                    "status": "succeeded",
                    "quality_checks": [
                        {"name": name, "status": "passed"}
                        for name in exporter.PIPELINE_QUALITY_CHECKS
                    ],
                }
            ],
        }
        safe, verified = exporter._safe_pipeline_health(
            pipeline_run, datetime(2026, 8, 4).date(), required=True
        )
        self.assertFalse(verified)
        self.assertEqual(safe["status"], "unverified")
        self.assertEqual(safe["verification_mode"], "future_simulation_excluded")
        self.assertEqual(safe["execution_mode"], "FUTURE_SIMULATION")

    def test_pipeline_health_sanitizes_untrusted_public_fields(self):
        row = {key: "2026-08-04" for key in exporter.STAGE_DATE_COLUMNS.values()}
        snapshot = exporter.build_snapshot(
            row,
            now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            pipeline_run={
                "logical_run_date": "2026-08-04",
                "started_at": "arn:aws:lambda:private",
                "completed_at": "s3://private/path",
                "status": "failed",
                "failed_stage": "private/function/name",
                "failure_category": "private exception text",
                "stages": [{"name": "arn:private", "status": "failed"}],
            },
            pipeline_status_required=True,
        )
        serialized = json.dumps(snapshot["pipeline"]).lower()
        for forbidden in ("arn:", "s3://", "private/function", "exception text"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(snapshot["pipeline"]["failure_category"], "unexpected_failure")

    def test_pipeline_load_errors_are_reduced_to_safe_codes(self):
        class FakeClientError(Exception):
            response = {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "private bucket and role details",
                }
            }

        self.assertEqual(
            exporter._safe_pipeline_load_error(FakeClientError()),
            "access_denied",
        )
        self.assertEqual(
            exporter._safe_pipeline_load_error(RuntimeError("s3://private/path")),
            "unexpected_error",
        )

        class FlexibleChecksumError(Exception):
            pass

        self.assertEqual(
            exporter._safe_pipeline_load_error(FlexibleChecksumError("private detail")),
            "object_read_error",
        )

    def test_pipeline_status_read_retries_transient_client_failure(self):
        class Body:
            def read(self):
                return b'{"status":"succeeded"}'

        class Client:
            calls = 0

            def get_object(self, **_kwargs):
                self.calls += 1
                if self.calls < 3:
                    raise RuntimeError("transient")
                return {"Body": Body()}

        delays = []
        client = Client()
        result = exporter.load_pipeline_run(
            client,
            "s3://private-status/pipeline/latest.json",
            retry_delay_seconds=0.25,
            sleep_fn=delays.append,
        )
        self.assertEqual(result, {"status": "succeeded"})
        self.assertEqual(client.calls, 3)
        self.assertEqual(delays, [0.25, 0.5])

    def test_pipeline_status_invalid_json_fails_without_retry(self):
        class Body:
            def read(self):
                return b"not-json"

        class Client:
            calls = 0

            def get_object(self, **_kwargs):
                self.calls += 1
                return {"Body": Body()}

        client = Client()
        with self.assertRaises(json.JSONDecodeError):
            exporter.load_pipeline_run(
                client,
                "s3://private-status/pipeline/latest.json",
                sleep_fn=lambda _delay: None,
            )
        self.assertEqual(client.calls, 1)

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
        for table in exporter.CURRENT_SOURCE_TABLES:
            with self.subTest(table=table):
                self.assertIn(table, setup)
        self.assertIn("fact_shipment_v2", analyst_sql)
        for view in exporter.CURRENT_ANALYTICS_VIEWS:
            with self.subTest(view=view):
                self.assertIn(view, setup)
        self.assertIn("vw_multimodal_operational_baseline_v1", analyst_sql)
        self.assertIn("Database = @{ Name = $SourceDatabase }", setup)
        self.assertIn("DatabaseName = $SourceDatabase; Name = $tableName", setup)
        self.assertIn("InspectPipelineStatusBucket", setup)
        self.assertIn("ListPipelineStatusObject", setup)
        self.assertIn('"s3:prefix" = $pipelineStatusLocation.Prefix', setup)
        self.assertIn("UNNEST(sequence(1, 7))", analyst_sql)
        self.assertIn("avg_effectiveness_score", analyst_sql)


if __name__ == "__main__":
    unittest.main()
