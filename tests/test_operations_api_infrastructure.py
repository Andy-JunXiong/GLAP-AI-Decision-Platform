from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OperationsApiInfrastructureTests(unittest.TestCase):
    def test_api_is_jwt_protected_and_staging_scoped(self):
        template = (ROOT / "infrastructure" / "operations-api-staging.yaml").read_text(encoding="utf-8")
        self.assertIn("AuthorizerType: JWT", template)
        self.assertEqual(template.count("AuthorizationType: JWT"), 2)
        self.assertIn("GET /v1/actions", template)
        self.assertIn("POST /v1/actions/{action_id}/events", template)
        self.assertIn("glap-operations-api-staging", template)
        self.assertNotIn("AWS::Scheduler::Schedule", template)
        self.assertNotIn("AWS::Lambda::Alias", template)

    def test_reliability_and_least_privilege_controls_exist(self):
        template = (ROOT / "infrastructure" / "operations-api-staging.yaml").read_text(encoding="utf-8")
        self.assertIn("ReservedConcurrentExecutions: 10", template)
        self.assertIn("DeadLetterConfig", template)
        self.assertIn("OperationsApiFailureAlarm", template)
        self.assertIn("OperationsApiThrottleAlarm", template)
        self.assertIn("vw_lifecycle_action_current_staging_v1", template)
        self.assertNotIn("glue:UpdateTable", template)
        self.assertNotIn("s3:DeleteObject", template)

    def test_deployment_is_manual_plan_first(self):
        script = (ROOT / "ops" / "deploy_operations_api_stack.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("Plan only", script)
        self.assertIn("glap_operations_api.py", script)
        self.assertIn("Public Pages write access: False", script)
        self.assertNotIn("update-alias", script.lower())

        workflow = (ROOT / ".github" / "workflows" / "deploy-operations-api-staging.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("default: plan", workflow)
        self.assertIn("GLAP_OPERATIONS_JWT_ISSUER", workflow)
        self.assertIn("GLAP_OPERATIONS_JWT_AUDIENCE", workflow)
        self.assertIn("GLAP_OPERATIONS_INTERNAL_ORIGIN", workflow)
        self.assertIn("AWS_STAGING_ROLE_ARN", workflow)
        self.assertIn("if: inputs.action == 'deploy'", workflow)
        self.assertIn("Public Pages write access: \\`false\\`", workflow)
        self.assertNotIn("schedule:", workflow)


if __name__ == "__main__":
    unittest.main()
