import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("operations_api", ROOT / "lambda" / "glap_operations_api.py")
api = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(api)


def request(method="GET", path="/v1/actions", groups="viewer", body=None):
    return {
        "rawPath": path,
        "requestContext": {
            "requestId": "api-request-1",
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {
                "sub": "person-123", "name": "Alex Chen", "cognito:groups": groups,
            }}},
        },
        "body": json.dumps(body) if body else None,
    }


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
        self.assertNotIn("actions:approve", api.ROLE_PERMISSIONS["operator"])
        self.assertNotIn("actions:complete", api.ROLE_PERMISSIONS["approver"])
        self.assertIn("actions:complete", api.ROLE_PERMISSIONS["administrator"])

    def test_queue_query_is_operational_and_bounded(self):
        query = api.build_action_queue_query(50, "PROPOSED")
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", query)
        self.assertIn("status = 'PROPOSED'", query)
        self.assertIn("LIMIT 50", query)
        self.assertIn("alert_fingerprint", query)
        self.assertNotIn("owner", query)

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
        with patch.dict(sys.modules, {"boto3": fake_boto3}):
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
        with patch.dict(sys.modules, {"boto3": fake_boto3}):
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
