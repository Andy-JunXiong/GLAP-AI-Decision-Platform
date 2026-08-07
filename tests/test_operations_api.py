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
    def test_safe_aws_error_diagnostic_omits_exception_message(self):
        class AwsFailure(Exception):
            response = {"Error": {"Code": "AccessDeniedException", "Message": "private path"}}

        self.assertEqual(api._safe_aws_error_code(AwsFailure()), "AccessDeniedException")
        self.assertNotIn("private", api._safe_aws_error_code(AwsFailure()))

    def test_permission_matrix_is_separated(self):
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


if __name__ == "__main__":
    unittest.main()
