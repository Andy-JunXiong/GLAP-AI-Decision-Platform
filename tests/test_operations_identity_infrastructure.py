from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OperationsIdentityInfrastructureTests(unittest.TestCase):
    def test_identity_and_internal_origin_are_dedicated_and_staging_only(self):
        template = (
            ROOT / "infrastructure" / "operations-identity-staging.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("AWS::Cognito::UserPool", template)
        self.assertIn("AWS::Cognito::UserPoolClient", template)
        self.assertIn("AWS::Cognito::UserPoolDomain", template)
        self.assertIn("AWS::Amplify::App", template)
        self.assertIn("AWS::Amplify::Branch", template)
        self.assertIn("AllowAdminCreateUserOnly: true", template)
        self.assertIn("GenerateSecret: false", template)
        self.assertIn("AllowedOAuthFlows: [code]", template)
        self.assertIn("ALLOW_ADMIN_USER_PASSWORD_AUTH", template)
        self.assertIn("MfaConfiguration: OPTIONAL", template)
        for role in ("viewer", "operator", "approver", "administrator"):
            self.assertIn(f"GroupName: {role}", template)
        self.assertIn("DeletionPolicy: Retain", template)
        self.assertGreaterEqual(
            template.count("!GetAtt InternalWebBranch.BranchName"), 3
        )
        self.assertNotIn("!Ref InternalWebBranch", template)
        self.assertNotIn("Repository:", template)
        self.assertNotIn("AWS::Scheduler::Schedule", template)
        self.assertNotIn("AWS::Lambda::Alias", template)

    def test_identity_and_frontend_deployments_are_plan_first(self):
        identity = (
            ROOT / "ops" / "deploy_operations_identity_stack.ps1"
        ).read_text(encoding="utf-8")
        frontend = (
            ROOT / "ops" / "deploy_internal_operations_frontend.ps1"
        ).read_text(encoding="utf-8")
        for script in (identity, frontend):
            self.assertIn("[switch]$Apply", script)
            self.assertIn("if (-not $Apply)", script)
            self.assertIn("Plan only", script)
            self.assertIn("Production", script)
        self.assertIn("cloudformation validate-template", identity)
        self.assertIn("Public Pages connection: False", identity)
        self.assertIn("amplify create-deployment", frontend)
        self.assertIn("amplify start-deployment", frontend)
        self.assertIn("NEXT_PUBLIC_GLAP_COGNITO_CLIENT_ID", frontend)
        self.assertIn(".Substring($sourceRoot.Length)", frontend)
        self.assertIn("System.IO.Compression", frontend)
        self.assertIn('.Replace("\\", "/")', frontend)
        self.assertIn("_next/static/", frontend)
        self.assertIn("portable path contract", frontend)
        self.assertIn("Action evidence contract", frontend)
        self.assertIn("Learning evidence contract", frontend)
        self.assertIn("Policy activation always requires a separate named-human approval", frontend)
        self.assertIn("synthetic policy-review evidence only", frontend)
        self.assertIn('$builtJavaScript.Contains("Evidence chain")', frontend)
        self.assertIn("never real logistics performance", frontend)
        self.assertNotRegex(frontend, r"(?m)^\s*Compress-Archive\b")
        self.assertNotIn("github", frontend.lower())

    def test_browser_authentication_uses_pkce_and_session_storage_only(self):
        auth = (
            ROOT / "decision-brief-demo" / "app" / "operations-auth.ts"
        ).read_text(encoding="utf-8")
        config = (
            ROOT / "decision-brief-demo" / "next.config.ts"
        ).read_text(encoding="utf-8")
        self.assertIn('code_challenge_method: "S256"', auth)
        self.assertIn('grant_type: "authorization_code"', auth)
        self.assertIn("returnedState !== expectedState", auth)
        self.assertIn("window.crypto.getRandomValues", auth)
        self.assertIn("window.sessionStorage", auth)
        self.assertNotIn("localStorage", auth)
        self.assertIn("GLAP_INTERNAL_STATIC_EXPORT", config)
        self.assertIn('output: process.env.', config)
        self.assertIn("tsconfig.internal.json", config)

    def test_runtime_verification_is_read_only_and_redacted(self):
        script = (
            ROOT / "ops" / "verify_operations_staging.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Unauthenticated API routes rejected with 401", script)
        self.assertIn("/v1/risks?limit=1", script)
        self.assertIn("/v1/outcomes?limit=1", script)
        self.assertIn("/v1/pipeline-health", script)
        self.assertIn("/v1/forecasts", script)
        self.assertIn("/v1/network", script)
        self.assertIn("/v1/shipments?limit=1", script)
        self.assertIn("CORS origin exact match", script)
        self.assertIn("Internal static assets reachable", script)
        self.assertIn("Accessible data states deployed", script)
        self.assertIn("Pipeline evidence is stale", script)
        self.assertIn("Some shipment evidence is still available", script)
        self.assertIn(".data-state", script)
        self.assertIn("API alarms present", script)
        self.assertIn("API alarms currently OK", script)
        self.assertIn("Redacted API access log present", script)
        self.assertIn("API throttle metric filter present", script)
        self.assertIn("Protected identifiers were not printed", script)
        self.assertIn("[switch]$RequireActionAssignment", script)
        self.assertIn("[switch]$RequireActionEvidence", script)
        self.assertIn("[switch]$RequireLearningEvidence", script)
        self.assertIn("Assign & edit", script)
        self.assertIn('$deployedJavaScript.Contains("EDITED")', script)
        self.assertIn("Action evidence controls deployed when required", script)
        self.assertIn("Learning evidence controls deployed when required", script)
        self.assertIn('$deployedJavaScript.Contains("Evidence chain")', script)
        self.assertIn("$expectedUnauthorizedCount", script)
        self.assertNotIn("put-", script.lower())
        self.assertNotIn("create-", script.lower())
        self.assertNotIn("update-", script.lower())
        self.assertNotIn("delete-", script.lower())
        self.assertNotIn("start-", script.lower())

    def test_role_matrix_verification_is_manual_isolated_and_self_cleaning(self):
        script = (
            ROOT / "ops" / "verify_operations_roles_staging.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("--message-action SUPPRESS", script)
        self.assertIn("example.invalid", script)
        self.assertIn("admin-delete-user", script)
        self.assertIn("finally", script)
        self.assertIn("viewer approve denied", script)
        self.assertIn("operator complete allowed by role", script)
        self.assertIn("approver complete denied", script)
        self.assertIn("administrator approve allowed by role", script)
        self.assertIn("viewer shipment entity denied", script)
        self.assertIn("operator shipment entity read allowed", script)
        self.assertIn("network temporal boundary valid", script)
        self.assertIn("shipment pagination valid", script)
        self.assertIn("Tokens and users were not printed", script)
        self.assertIn("RandomNumberGenerator]::Create()", script)
        self.assertIn("$generator.Dispose()", script)
        self.assertIn("[switch]$RequireActionAssignment", script)
        self.assertIn("[switch]$RequireActionEvidence", script)
        self.assertIn("[switch]$RequireLearningEvidence", script)
        self.assertIn("Require Action evidence role checks:", script)
        self.assertIn("Require Learning evidence role checks:", script)
        self.assertIn("Learning evidence governance boundary valid", script)
        self.assertIn('$Operation -eq "EDIT"', script)
        self.assertIn('$body.action_owner = "Isolated Role Check"', script)
        self.assertIn("$body.action_due_date", script)
        self.assertIn('(Action-Status "viewer" "EDIT") -eq 403', script)
        self.assertIn(
            '(Action-Status "operator" "EDIT") -notin @(401, 403)', script
        )
        self.assertIn('(Action-Status "approver" "EDIT") -eq 403', script)
        self.assertIn(
            '(Action-Status "administrator" "EDIT") -notin @(401, 403)', script
        )
        self.assertNotIn("logical_run_date = $logicalDate", script)
        self.assertNotIn("RandomNumberGenerator]::Fill", script)
        self.assertNotIn("Write-Host $tokens", script)


if __name__ == "__main__":
    unittest.main()
