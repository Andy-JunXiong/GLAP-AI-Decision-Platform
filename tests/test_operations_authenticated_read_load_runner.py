from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "ops" / "run_operations_authenticated_read_load_staging.ps1"


class OperationsAuthenticatedReadLoadRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = RUNNER_PATH.read_text(encoding="utf-8")

    def test_runner_is_plan_first_with_a_separate_named_human_gate(self):
        self.assertIn("[switch]$Apply", self.source)
        self.assertIn("[switch]$AuthorizedSustainedReadLoad", self.source)
        self.assertIn("if (-not $Apply)", self.source)
        self.assertIn("AWS calls executed: False", self.source)
        self.assertIn("External requests executed: False", self.source)
        self.assertIn(
            "Apply requires -AuthorizedSustainedReadLoad from a named human",
            self.source,
        )
        self.assertLess(
            self.source.index("if (-not $Apply)"),
            self.source.index("$awsScope ="),
        )

    def test_runner_revalidates_the_immutable_plan_before_preview_or_apply(self):
        self.assertIn(
            "validate_operations_authenticated_read_load_plan.py", self.source
        )
        self.assertIn("--plan $resolvedPlanPath --format json", self.source)
        self.assertIn("Authenticated read-load plan validation failed", self.source)
        self.assertIn("$plan.status", self.source)
        self.assertIn("$plan.load_shape", self.source)

    def test_runner_is_get_only_and_blocks_entity_or_mutation_routes(self):
        self.assertIn('if ($route.method -ne "GET")', self.source)
        self.assertIn("NON_ALLOWLISTED_ROUTE", self.source)
        self.assertIn("UNEXPECTED_HTTP_METHOD", self.source)
        self.assertIn("/events|/shipments", self.source)
        self.assertIn("-Method GET", self.source)
        self.assertNotIn("-Method POST", self.source)
        self.assertNotIn("Invoke-RestMethod", self.source)

    def test_runner_uses_one_ephemeral_viewer_and_suppresses_email(self):
        for marker in (
            "admin-create-user",
            "--message-action SUPPRESS",
            "admin-set-user-password",
            "--group-name viewer",
            "ADMIN_USER_PASSWORD_AUTH",
            "Process memory only",
            "admin-delete-user",
            "cognito-idp list-users",
            "Test-UserAbsent",
            "finally",
            "$accessToken = $null",
            "$password = $null",
            "$login = $null",
            "removed and confirmed",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_cleanup_confirmation_does_not_depend_on_expected_cli_failure(self):
        self.assertNotIn("admin-get-user", self.source)
        self.assertIn("$LASTEXITCODE -ne 0 -or -not $usersJson", self.source)
        self.assertIn("$users.Username -contains $Username", self.source)

    def test_runner_has_deterministic_pacing_and_no_retry_loop(self):
        self.assertIn("$scheduledRequests", self.source)
        self.assertIn("$plan.load_shape.ramp_up_seconds", self.source)
        self.assertIn("* 1000", self.source)
        self.assertIn("* 500", self.source)
        self.assertIn("[System.Diagnostics.Stopwatch]::StartNew()", self.source)
        self.assertIn("Start-Sleep -Milliseconds", self.source)
        self.assertNotIn("retries_per_request++", self.source)
        self.assertNotIn("Retry-", self.source)

    def test_all_fail_closed_abort_gates_are_enforced(self):
        for reason in (
            "AUTHORIZATION_FAILURE",
            "NON_ALLOWLISTED_ROUTE",
            "UNEXPECTED_HTTP_METHOD",
            "THROTTLE_RATE_EXCEEDED",
            "SERVER_ERROR_RATE_EXCEEDED",
            "CONSECUTIVE_FAILURES_EXCEEDED",
            "P95_LATENCY_EXCEEDED",
            "IDENTITY_CLEANUP_FAILED",
            "RESULT_RECONCILIATION_FAILED",
        ):
            with self.subTest(reason=reason):
                self.assertIn(reason, self.source)
        self.assertIn("$statusCode -in @(401, 403)", self.source)
        self.assertIn("$completed -ge 20", self.source)
        self.assertIn("max_429_rate_pct", self.source)
        self.assertIn("max_5xx_rate_pct", self.source)
        self.assertIn("max_consecutive_failures", self.source)
        self.assertIn("max_p95_latency_ms", self.source)

    def test_result_is_aggregate_only_validated_and_not_persisted(self):
        self.assertIn("--baseline $baselinePath", self.source)
        self.assertIn("GetTempPath", self.source)
        self.assertIn("Remove-Item -LiteralPath $baselinePath", self.source)
        self.assertIn("[System.IO.File]::WriteAllText", self.source)
        self.assertIn("[System.Text.UTF8Encoding]::new($false)", self.source)
        self.assertNotIn("-Encoding utf8NoBOM", self.source)
        self.assertIn("$baselineJson = $null", self.source)
        self.assertIn("Persisted result artifact: False", self.source)
        self.assertIn("operational_mutation_executed = $false", self.source)
        self.assertIn("production_accessed = $false", self.source)
        self.assertIn("recurring_schedule_created = $false", self.source)
        for protected in (
            "Authorization =",
            "Bearer $accessToken",
            "--username $username",
            "$endpoint$($route.path)",
        ):
            self.assertNotIn(f'Write-Host "{protected}', self.source)

    def test_runner_contains_no_deployment_or_schedule_mutation(self):
        for forbidden in (
            "update-stack",
            "create-stack",
            "update-alias",
            "publish-version",
            "scheduler create",
            "put-rule",
            "update-function-configuration",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source.lower())


if __name__ == "__main__":
    unittest.main()
