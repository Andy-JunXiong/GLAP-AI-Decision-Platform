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


if __name__ == "__main__":
    unittest.main()
