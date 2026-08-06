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
        self.assertIn("RoleName: glap-operations-api-staging-role", template)
        self.assertIn("QueueName: glap-operations-api-staging-dlq", template)
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
        self.assertIn("CAPABILITY_NAMED_IAM", script)
        self.assertIn("Public Pages write access: False", script)
        self.assertNotIn("update-alias", script.lower())

        workflow = (ROOT / ".github" / "workflows" / "deploy-operations-api-staging.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("push:", workflow)
        self.assertIn("branches:\n      - main", workflow)
        self.assertIn("default: plan", workflow)
        self.assertIn("GLAP_OPERATIONS_JWT_ISSUER", workflow)
        self.assertIn("GLAP_OPERATIONS_JWT_AUDIENCE", workflow)
        self.assertIn("GLAP_OPERATIONS_INTERNAL_ORIGIN", workflow)
        self.assertIn("AWS_STAGING_ROLE_ARN", workflow)
        self.assertIn("Resolve protected staging configuration privately", workflow)
        self.assertIn("::add-mask::$issuer", workflow)
        self.assertIn('} >> "$GITHUB_ENV"', workflow)
        self.assertIn("Expected exactly one Cognito pool candidate", workflow)
        self.assertIn("Expected exactly one internal HTTPS origin candidate", workflow)
        discovery = workflow.split(
            "Resolve protected staging configuration privately", 1
        )[1].split("Validate protected staging configuration", 1)[0]
        self.assertNotIn("GITHUB_STEP_SUMMARY", discovery)
        self.assertNotIn("describe-user-pool-client", discovery)
        self.assertLess(
            workflow.index("Configure AWS staging credentials"),
            workflow.index("Resolve protected staging configuration privately"),
        )
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.action == 'deploy'", workflow)
        self.assertIn("Public Pages write access: \\`false\\`", workflow)
        self.assertNotIn("schedule:", workflow)

    def test_deployer_bootstrap_is_separate_plan_only_and_staging_scoped(self):
        script = (
            ROOT / "ops" / "configure_operations_api_deployer.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("Plan only", script)
        self.assertIn("GLAPOperationsApiStagingDeploy", script)
        self.assertIn('"cognito-idp:ListUserPools"', script)
        self.assertIn('"cognito-idp:ListUserPoolClients"', script)
        self.assertIn('"amplify:ListApps"', script)
        self.assertIn('"apigateway:GET"', script)
        self.assertIn('stack/${StackName}/*', script)
        self.assertIn('role/${ExecutionRoleName}', script)
        self.assertIn('"lambda:PutFunctionConcurrency"', script)
        self.assertIn('"iam:UpdateAssumeRolePolicy"', script)
        self.assertIn('${ArtifactBucket}/${artifactPrefix}/*', script)
        self.assertIn("Self-modifying deployer permission: False", script)
        self.assertNotIn('role/${RoleName}', script)
        self.assertNotIn("lambda:UpdateAlias", script)
        self.assertNotIn("scheduler:", script.lower())
        self.assertIn("Remove-Item -LiteralPath $policyPath", script)


if __name__ == "__main__":
    unittest.main()
