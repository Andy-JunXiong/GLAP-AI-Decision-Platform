import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("operations_api", ROOT / "lambda" / "glap_operations_api.py")
api = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(api)


def request(method="GET", path="/v1/actions", groups="viewer", body=None, query=None):
    return {
        "rawPath": path,
        "requestContext": {
            "requestId": "api-request-1",
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {
                "sub": "person-123", "name": "Alex Chen", "cognito:groups": groups,
            }}},
        },
        "queryStringParameters": query,
        "body": json.dumps(body) if body else None,
    }


def pipeline_run(logical_run_date="2026-08-07"):
    stages = []
    for name in api.PIPELINE_STAGE_ORDER:
        checks = []
        if name in api.PIPELINE_QUALITY_STAGES:
            checks = [{"name": check, "status": "passed"} for check in api.PIPELINE_QUALITY_CHECKS]
        stages.append({
            "name": name,
            "status": "succeeded",
            "started_at": "2026-08-07T00:00:00Z",
            "completed_at": "2026-08-07T00:00:01Z",
            "duration_ms": 1000,
            "quality_checks": checks,
            "function_name": "must-not-be-exposed",
        })
    return {
        "logical_run_date": logical_run_date,
        "execution_mode": "OPERATIONAL",
        "time_basis": "ACTUAL_CALENDAR",
        "status": "succeeded",
        "started_at": "2026-08-07T00:00:00Z",
        "completed_at": "2026-08-07T00:00:06Z",
        "stages": stages,
        "private_resource_arn": "arn:aws:lambda:private",
    }


def forecast_rows(days=90, end=date(2026, 8, 7)):
    start = end - timedelta(days=days - 1)
    return [
        {
            "feature_date": (start + timedelta(days=index)).isoformat(),
            "shipment_count": str(400 + index),
            "eligible_date": "1",
        }
        for index in range(days)
    ]


class OperationsApiTests(unittest.TestCase):
    def test_failure_metric_is_exact_and_best_effort(self):
        class CloudWatchClient:
            request = None

            def put_metric_data(self, **kwargs):
                self.request = kwargs

        client = CloudWatchClient()
        self.assertTrue(api._record_failure_metric(client))
        self.assertEqual(client.request["Namespace"], "GLAP/OperationsApi")
        self.assertEqual(client.request["MetricData"][0]["MetricName"], "ServiceUnavailable")

        class FailingClient:
            def put_metric_data(self, **_kwargs):
                raise RuntimeError("private failure")

        self.assertFalse(api._record_failure_metric(FailingClient()))

    def test_safe_aws_error_diagnostic_omits_exception_message(self):
        class AwsFailure(Exception):
            response = {"Error": {"Code": "AccessDeniedException", "Message": "private path"}}

        self.assertEqual(api._safe_aws_error_code(AwsFailure()), "AccessDeniedException")
        self.assertNotIn("private", api._safe_aws_error_code(AwsFailure()))

    def test_permission_matrix_is_separated(self):
        for role in api.ROLE_PERMISSIONS.values():
            self.assertIn("risks:read", role)
            self.assertIn("outcomes:read", role)
            self.assertIn("health:read", role)
            self.assertIn("forecasts:read", role)
            self.assertIn("network:read", role)
        self.assertNotIn("shipments:read", api.ROLE_PERMISSIONS["viewer"])
        self.assertIn("shipments:read", api.ROLE_PERMISSIONS["operator"])
        self.assertIn("shipments:read", api.ROLE_PERMISSIONS["approver"])
        self.assertNotIn("actions:approve", api.ROLE_PERMISSIONS["operator"])
        self.assertIn("actions:edit", api.ROLE_PERMISSIONS["operator"])
        self.assertNotIn("actions:edit", api.ROLE_PERMISSIONS["approver"])
        self.assertNotIn("actions:complete", api.ROLE_PERMISSIONS["approver"])
        self.assertIn("actions:complete", api.ROLE_PERMISSIONS["administrator"])

    def test_queue_query_is_operational_and_bounded(self):
        query = api.build_action_queue_query(50, "PROPOSED")
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", query)
        self.assertIn("status = 'PROPOSED'", query)
        self.assertIn("LIMIT 50", query)
        self.assertIn("alert_fingerprint", query)
        self.assertIn("action_owner", query)
        self.assertIn("action_due_date", query)
        self.assertIn("status = 'EDITED'", api.build_action_queue_query(50, "EDITED"))

    def test_risk_query_is_operational_actual_calendar_and_sydney_bounded(self):
        query = api.build_risk_hotspots_query(25, "OPEN", "2026-08-07")
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", query)
        self.assertIn("execution_mode = 'OPERATIONAL'", query)
        self.assertIn("time_basis = 'ACTUAL_CALENDAR'", query)
        self.assertIn("as_of_date <= DATE '2026-08-07'", query)
        self.assertIn("try_cast(dt AS date) <= DATE '2026-08-07'", query)
        self.assertIn("row_number() OVER", query)
        self.assertIn("row_rank = 1 AND status = 'OPEN'", query)
        self.assertIn("LIMIT 25", query)
        self.assertNotIn("FUTURE_SIMULATION", query)

    def test_risk_query_rejects_invalid_status_and_cutoff(self):
        with self.assertRaises(ValueError):
            api.build_risk_hotspots_query(25, "PENDING", "2026-08-07")
        with self.assertRaises(ValueError):
            api.build_risk_hotspots_query(25, "OPEN", "tomorrow")

    def test_outcome_query_separates_pending_from_observed_evidence(self):
        query = api.build_outcome_review_query(50, "PENDING", "2026-08-07")
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", query)
        self.assertIn("execution_mode = 'OPERATIONAL'", query)
        self.assertIn("time_basis = 'ACTUAL_CALENDAR'", query)
        self.assertIn("as_of_date <= DATE '2026-08-07'", query)
        self.assertIn("try_cast(dt AS date) <= DATE '2026-08-07'", query)
        self.assertIn("status = 'PENDING' AND observed_date IS NULL", query)
        self.assertIn("observed_date <= DATE '2026-08-07'", query)
        self.assertIn("'NOT_OBSERVED'", query)
        self.assertIn("'OBSERVED_ACTUAL_CALENDAR'", query)
        self.assertIn("outcome_status = 'PENDING'", query)
        self.assertIn("LEFT JOIN", query)
        self.assertIn("LIMIT 50", query)

    def test_outcome_query_rejects_invalid_status_and_cutoff(self):
        with self.assertRaises(ValueError):
            api.build_outcome_review_query(50, "OBSERVED", "2026-08-07")
        with self.assertRaises(ValueError):
            api.build_outcome_review_query(50, "PENDING", "tomorrow")

    def test_forecast_query_is_operational_actual_calendar_and_sydney_bounded(self):
        query = api.build_forecast_series_query("2026-08-07")
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", query)
        self.assertIn("execution_mode = 'OPERATIONAL'", query)
        self.assertIn("time_basis = 'ACTUAL_CALENDAR'", query)
        self.assertIn("as_of_date <= params.as_of_date", query)
        self.assertIn("source.feature_date <= params.as_of_date", query)
        self.assertIn("vw_multimodal_forecast_feature_daily_v1", query)
        self.assertNotIn("FUTURE_SIMULATION", query)

    def test_network_queries_are_latest_operational_actual_calendar_and_bounded(self):
        summary = api.build_network_summary_query(
            "2026-08-07", mode="air", provider="dhl", lane="pvg-syd"
        )
        self.assertIn("vw_multimodal_shipment_daily_v1", summary)
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", summary)
        self.assertIn("execution_mode = 'OPERATIONAL'", summary)
        self.assertIn("time_basis = 'ACTUAL_CALENDAR'", summary)
        self.assertIn("as_of_date <= DATE '2026-08-07'", summary)
        self.assertIn("metric_date <= DATE '2026-08-07'", summary)
        self.assertIn("transport_mode = 'AIR'", summary)
        self.assertIn("carrier = 'DHL'", summary)
        self.assertIn("market_lane = 'PVG-SYD'", summary)
        self.assertIn("row_rank = 1", summary)
        self.assertNotIn("expected_total_cost", summary)
        self.assertNotIn("origin_port", summary)

        detail = api.build_shipment_drilldown_query(
            25, "2026-08-07", status="open", after="SHIP-0007"
        )
        self.assertIn("lifecycle_status = 'OPEN'", detail)
        self.assertIn("shipment_id > 'SHIP-0007'", detail)
        self.assertIn("LIMIT 26", detail)
        self.assertNotIn("FUTURE_SIMULATION", detail)

    def test_network_filters_and_page_tokens_fail_closed(self):
        with self.assertRaises(ValueError):
            api.build_network_summary_query("tomorrow")
        with self.assertRaises(ValueError):
            api.build_network_summary_query("2026-08-07", provider="DHL' OR 1=1")
        with self.assertRaises(ValueError):
            api.build_network_summary_query("2026-08-07", lane="unsafe")
        with self.assertRaises(ValueError):
            api.build_shipment_drilldown_query(25, "2026-08-07", status="FUTURE")
        token = api._encode_page_token("SHIP-0007")
        self.assertEqual(api._decode_page_token(token), "SHIP-0007")
        with self.assertRaises(ValueError):
            api._decode_page_token("not+a+token")

    def test_viewer_gets_network_summary_without_entity_access(self):
        rows = [{"transport_mode": "AIR", "provider_code": "DHL", "market_lane": "PVG-SYD"}]
        fake_boto3 = types.SimpleNamespace(client=lambda _service: object())
        with patch.dict(sys.modules, {"boto3": fake_boto3}), \
             patch.object(api, "_query_rows", return_value=rows), \
             patch.object(api, "_sydney_date", return_value="2026-08-07"):
            response = api.lambda_handler(request(path="/v1/network"), None)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(body["entity_access"])
        self.assertEqual(body["source"]["execution_mode"], "OPERATIONAL")
        self.assertEqual(body["as_of_date"], "2026-08-07")

    def test_shipment_entities_are_role_restricted_and_paginated(self):
        denied = api.lambda_handler(request(path="/v1/shipments", groups="viewer"), None)
        self.assertEqual(denied["statusCode"], 403)

        rows = [
            {"shipment_id": "SHIP-0001", "market_lane": "PVG-SYD"},
            {"shipment_id": "SHIP-0002", "market_lane": "PVG-SYD"},
        ]
        fake_boto3 = types.SimpleNamespace(client=lambda _service: object())
        with patch.dict(sys.modules, {"boto3": fake_boto3}), \
             patch.object(api, "_query_rows", return_value=rows), \
             patch.object(api, "_sydney_date", return_value="2026-08-07"):
            response = api.lambda_handler(
                request(path="/v1/shipments", groups="operator", query={"limit": "1"}), None
            )
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual([item["shipment_id"] for item in body["items"]], ["SHIP-0001"])
        self.assertEqual(api._decode_page_token(body["next_token"]), "SHIP-0001")

    def test_forecast_contract_separates_projection_from_historical_evaluation(self):
        contract = api.build_forecast_contract(forecast_rows(), "2026-08-07")
        self.assertEqual(contract["source"]["execution_mode"], "OPERATIONAL")
        self.assertEqual(contract["source"]["time_basis"], "ACTUAL_CALENDAR")
        self.assertEqual(contract["forecast"]["execution_mode"], "FUTURE_SIMULATION")
        self.assertEqual(contract["forecast"]["time_basis"], "MODEL_PROJECTION")
        self.assertEqual(contract["forecast"]["scenario_id"], "internal-advisory-forecast-2026-08-07")
        self.assertEqual(contract["forecast"]["status"], "ready")
        self.assertEqual(len(contract["forecast"]["points"]), 7)
        self.assertTrue(all(point["date"] > "2026-08-07" for point in contract["forecast"]["points"]))
        self.assertTrue(all(
            point["evidence_status"] == "ADVISORY_FORECAST_NOT_OBSERVED"
            for point in contract["forecast"]["points"]
        ))
        self.assertEqual(contract["accuracy"]["status"], "engineering_evidence")
        self.assertEqual(contract["accuracy"]["model_promotion_status"], "BLOCKED")
        self.assertFalse(contract["forecast"]["production_effect"])
        self.assertTrue(all(item["date"] <= "2026-08-07" for item in contract["history"]))

    def test_forecast_contract_fails_closed_when_operational_history_is_incomplete(self):
        rows = forecast_rows(35)
        rows[-1]["eligible_date"] = "0"
        contract = api.build_forecast_contract(rows, "2026-08-07")
        self.assertEqual(contract["forecast"]["status"], "insufficient_operational_history")
        self.assertEqual(contract["forecast"]["points"], [])
        self.assertEqual(contract["accuracy"]["status"], "insufficient_operational_history")
        self.assertIsNone(contract["accuracy"]["metrics"])

    def test_viewer_can_read_forecast_contract(self):
        class AthenaClient:
            def start_query_execution(self, **kwargs):
                self.query = kwargs["QueryString"]
                return {"QueryExecutionId": "query-forecast"}

            def get_query_execution(self, **_kwargs):
                return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

            def get_query_results(self, **_kwargs):
                columns = ["feature_date", "shipment_count", "eligible_date"]
                data = forecast_rows()
                return {"ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": name} for name in columns]},
                    "Rows": [
                        {"Data": [{"VarCharValue": name} for name in columns]},
                        *[{"Data": [{"VarCharValue": row[name]} for name in columns]} for row in data],
                    ],
                }}

        client = AthenaClient()
        fake_boto3 = types.SimpleNamespace(client=lambda _service: client)
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(
            api, "_sydney_date", return_value="2026-08-07"
        ):
            response = api.lambda_handler(request(path="/v1/forecasts"), None)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["forecast"]["status"], "ready")
        self.assertEqual(body["accuracy"]["model_promotion_status"], "BLOCKED")

    def test_viewer_can_read_risks(self):
        class AthenaClient:
            def start_query_execution(self, **kwargs):
                self.query = kwargs["QueryString"]
                return {"QueryExecutionId": "query-1"}

            def get_query_execution(self, **_kwargs):
                return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

            def get_query_results(self, **_kwargs):
                return {
                    "ResultSet": {
                        "ResultSetMetadata": {"ColumnInfo": [{"Name": "alert_fingerprint"}]},
                        "Rows": [
                            {"Data": [{"VarCharValue": "alert_fingerprint"}]},
                            {"Data": [{"VarCharValue": "alert-123"}]},
                        ],
                    }
                }

        client = AthenaClient()
        fake_boto3 = types.SimpleNamespace(client=lambda _service: client)
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(api, "_sydney_date", return_value="2026-08-07"):
            response = api.lambda_handler(request(path="/v1/risks"), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["items"][0]["alert_fingerprint"], "alert-123")
        self.assertIn("as_of_date <= DATE '2026-08-07'", client.query)

    def test_viewer_can_read_outcomes(self):
        class AthenaClient:
            def start_query_execution(self, **kwargs):
                self.query = kwargs["QueryString"]
                return {"QueryExecutionId": "query-1"}

            def get_query_execution(self, **_kwargs):
                return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

            def get_query_results(self, **_kwargs):
                return {
                    "ResultSet": {
                        "ResultSetMetadata": {"ColumnInfo": [{"Name": "outcome_id"}]},
                        "Rows": [
                            {"Data": [{"VarCharValue": "outcome_id"}]},
                            {"Data": [{"VarCharValue": "outcome-123"}]},
                        ],
                    }
                }

        client = AthenaClient()
        fake_boto3 = types.SimpleNamespace(client=lambda _service: client)
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(api, "_sydney_date", return_value="2026-08-07"):
            response = api.lambda_handler(request(path="/v1/outcomes"), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["items"][0]["outcome_id"], "outcome-123")
        self.assertIn("observed_date <= DATE '2026-08-07'", client.query)

    def test_pipeline_health_is_six_stage_current_and_redacted(self):
        health = api.sanitize_pipeline_health(pipeline_run(), "2026-08-07")
        self.assertEqual(health["status"], "current")
        self.assertEqual(health["freshness_status"], "current")
        self.assertEqual([stage["name"] for stage in health["stages"]], list(api.PIPELINE_STAGE_ORDER))
        self.assertEqual(health["stages_succeeded"], 6)
        self.assertEqual(health["quality_checks_succeeded"], 10)
        self.assertEqual(health["quality_checks_total"], 10)
        serialized = json.dumps(health)
        self.assertNotIn("function_name", serialized)
        self.assertNotIn("private_resource_arn", serialized)
        self.assertNotIn("s3://", serialized)

    def test_future_pipeline_run_is_never_current_evidence(self):
        health = api.sanitize_pipeline_health(pipeline_run("2026-08-08"), "2026-08-07")
        self.assertEqual(health["status"], "unverified")
        self.assertEqual(health["freshness_status"], "future_invalid")
        self.assertIsNone(health["logical_run_date"])

    def test_viewer_can_read_pipeline_health_from_exact_private_object(self):
        class S3Client:
            request = None

            def get_object(self, **kwargs):
                self.request = kwargs
                return {"Body": io.BytesIO(json.dumps(pipeline_run()).encode("utf-8"))}

        client = S3Client()
        fake_boto3 = types.SimpleNamespace(client=lambda service: client)
        with patch.dict(sys.modules, {"boto3": fake_boto3}), \
             patch.object(api, "PIPELINE_STATUS_S3_URI", "s3://private-status/pipeline/latest.json"), \
             patch.object(api, "_sydney_date", return_value="2026-08-07"):
            response = api.lambda_handler(request(path="/v1/pipeline-health"), None)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(client.request, {"Bucket": "private-status", "Key": "pipeline/latest.json"})
        self.assertEqual(body["status"], "current")
        self.assertNotIn("private-status", response["body"])

    def test_missing_identity_fails_closed(self):
        event = request()
        event["requestContext"]["authorizer"] = {}
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 403)

    def test_api_gateway_string_encoded_group_claims_are_supported(self):
        _, _, json_permissions = api._identity(request(groups='["operator"]'))
        _, _, bracket_permissions = api._identity(request(groups="[approver]"))
        self.assertIn("actions:complete", json_permissions)
        self.assertNotIn("actions:approve", json_permissions)
        self.assertIn("actions:approve", bracket_permissions)
        self.assertNotIn("actions:complete", bracket_permissions)

    def test_cognito_access_token_username_is_a_signed_actor_fallback(self):
        event = request(groups='["operator"]')
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        claims.pop("name")
        claims["username"] = "signed-staging-user"
        subject, actor, permissions = api._identity(event)
        self.assertEqual(subject, "person-123")
        self.assertEqual(actor, "signed-staging-user")
        self.assertIn("actions:complete", permissions)

    def test_operator_cannot_approve(self):
        response = api.lambda_handler(request("POST", "/v1/actions/action-123/events", "operator", {
            "operation": "APPROVE", "request_id": "request-123", "reason": "Reviewed evidence"
        }), None)
        self.assertEqual(response["statusCode"], 403)

    def test_operator_can_edit_assignment_but_approver_cannot(self):
        class LambdaClient:
            sent = None

            def invoke(self, **kwargs):
                self.sent = json.loads(kwargs["Payload"])
                return {"Payload": io.BytesIO(b'{"status":"success"}')}

        client = LambdaClient()
        fake_boto3 = types.SimpleNamespace(client=lambda _service: client)
        body = {
            "operation": "EDIT", "request_id": "request-edit-123",
            "reason": "Assign for operational follow-up",
            "action_owner": "Jordan Lee", "action_due_date": "2026-08-09",
            "logical_run_date": "2026-08-08",
        }
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(
            api, "_sydney_date", return_value="2026-08-09"
        ):
            response = api.lambda_handler(
                request("POST", "/v1/actions/action-123/events", "operator", body), None
            )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(client.sent["actor"], "Alex Chen")
        self.assertEqual(client.sent["action_owner"], "Jordan Lee")
        self.assertEqual(client.sent["action_due_date"], "2026-08-09")
        self.assertEqual(client.sent["logical_run_date"], "2026-08-09")
        denied = api.lambda_handler(
            request("POST", "/v1/actions/action-123/events", "approver", body), None
        )
        self.assertEqual(denied["statusCode"], 403)

    def test_approver_identity_overrides_any_client_actor(self):
        class LambdaClient:
            sent = None
            def invoke(self, **kwargs):
                self.sent = json.loads(kwargs["Payload"])
                return {"Payload": io.BytesIO(b'{"status":"success"}')}
        client = LambdaClient()
        fake_boto3 = types.SimpleNamespace(client=lambda service: client)
        event = request("POST", "/v1/actions/action-123/events", "approver", {
            "operation": "APPROVE", "request_id": "request-123", "reason": "Reviewed evidence",
            "logical_run_date": "2026-08-07", "actor": "system",
        })
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(
            api, "_sydney_date", return_value="2026-08-09"
        ):
            response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(client.sent["actor"], "Alex Chen")
        self.assertEqual(client.sent["execution_mode"], "OPERATIONAL")

    def test_downstream_domain_failures_are_safe_http_responses(self):
        class LambdaClient:
            payload = {"errorType": "ValueError", "errorMessage": "Action was not found"}

            def invoke(self, **_kwargs):
                return {
                    "FunctionError": "Unhandled",
                    "Payload": io.BytesIO(json.dumps(self.payload).encode("utf-8")),
                }

        client = LambdaClient()
        fake_boto3 = types.SimpleNamespace(client=lambda _service: client)
        mutation_request = request(
            "POST", "/v1/actions/action-123/events", "approver",
            {"operation": "APPROVE", "request_id": "request-123", "reason": "Reviewed evidence"},
        )
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(
            api, "_sydney_date", return_value="2026-08-09"
        ):
            self.assertEqual(api.lambda_handler(mutation_request, None)["statusCode"], 404)
            client.payload = {
                "errorType": "ActionConflictError",
                "errorMessage": "private transition detail",
            }
            conflict = api.lambda_handler(mutation_request, None)
        self.assertEqual(conflict["statusCode"], 409)
        self.assertNotIn("private", conflict["body"])


if __name__ == "__main__":
    unittest.main()
