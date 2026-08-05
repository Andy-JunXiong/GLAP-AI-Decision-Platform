from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StatefulLifecycleDeploymentTests(unittest.TestCase):
    def test_schema_is_isolated_and_contains_versioned_business_contracts(self):
        ddl = (ROOT / "sql" / "04_stateful_lifecycle_config.sql").read_text(encoding="utf-8")
        for table in (
            "dim_lifecycle_target_v1",
            "dim_route_service_v1",
            "dim_rate_card_v1",
            "dim_rate_tier_v1",
            "dim_fx_rate_v1",
            "fact_shipment_lifecycle_staging_v1",
            "fact_shipment_lifecycle_event_staging_v1",
            "fact_shipment_cost_staging_v1",
            "fact_shipment_lifecycle_metrics_staging_v1",
            "fact_shipment_signal_candidate_staging_v1",
        ):
            with self.subTest(table=table):
                self.assertIn(table, ddl)
        self.assertNotIn("DROP TABLE", ddl.upper())
        self.assertNotIn("fact_shipment_v2 (", ddl)

    def test_seed_records_approved_targets_routes_and_synthetic_provenance(self):
        seed = (ROOT / "sql" / "05_stateful_lifecycle_seed.sql").read_text(encoding="utf-8")
        for marker in (
            "'BOOKING_TO_GATE_IN', '*', '*', 7",
            "'GATE_IN_TO_ETD', '*', '*', 1",
            "'ATA_TO_DISCHARGED', '*', '*', 3",
            "'DISCHARGED_TO_DELIVERED', '*', '*', 4",
            "'CNSHA-AUSYD-QILIN'",
            "'CNSHA-AUSYD-DRAGON'",
            "'SYNTHETIC_MARKET_CALIBRATED'",
            "'CALIBRATED_ASSUMPTION'",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, seed)

    def test_sql_files_render_to_expected_statement_counts_after_comment_removal(self):
        def statements(path):
            sql = path.read_text(encoding="utf-8")
            sql = re.sub(r"^\s*--.*$", "", sql, flags=re.MULTILINE)
            return [statement for statement in sql.split(";") if statement.strip()]

        self.assertEqual(len(statements(ROOT / "sql" / "04_stateful_lifecycle_config.sql")), 10)
        self.assertEqual(len(statements(ROOT / "sql" / "05_stateful_lifecycle_seed.sql")), 5)
        self.assertEqual(len(statements(ROOT / "sql" / "06_stateful_lifecycle_validation.sql")), 2)

    def test_validation_fails_on_immutable_milestone_and_cost_breaks(self):
        validation = (ROOT / "sql" / "06_stateful_lifecycle_validation.sql").read_text(
            encoding="utf-8"
        )
        for check in (
            "p2p_commitment_mutated",
            "actual_milestone_mutated",
            "invalid_milestone_order",
            "cost_detail_does_not_reconcile",
            "ambiguous_rate_card",
            "invalid_rate_tier",
            "metric_snapshot_mismatch",
            "invalid_signal_contract",
        ):
            with self.subTest(check=check):
                self.assertIn(check, validation)

    def test_deployment_is_plan_only_without_apply(self):
        script = (ROOT / "ops" / "deploy_stateful_lifecycle.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("Plan only", script)
        self.assertIn("-LiteralPath", script)

    def test_staging_template_is_unscheduled_and_prefix_scoped(self):
        template = (ROOT / "infrastructure" / "stateful-lifecycle-staging.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("glap-stateful-lifecycle-generator-staging", template)
        self.assertIn("LifecycleDataObjectArn", template)
        self.assertIn("fact_shipment_lifecycle_staging_v1", template)
        self.assertIn("fact_shipment_lifecycle_metrics_staging_v1", template)
        self.assertIn("fact_shipment_signal_candidate_staging_v1", template)
        self.assertIn("glue:UpdateTable", template)
        self.assertIn("dim_rate_tier_v1", template)
        self.assertNotIn("AWS::Scheduler::Schedule", template)
        self.assertNotIn("pipeline-reliability", template)

    def test_replay_is_plan_only_and_seeds_only_first_day(self):
        script = (ROOT / "ops" / "replay_stateful_lifecycle_staging.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("$isFirst = $logicalDate -eq $dates[0]", script)
        self.assertIn("seed_population = $isFirst", script)
        self.assertIn("Remove-Item -LiteralPath $payloadPath", script)

    def test_oidc_compatible_stack_and_validation_commands_are_plan_only(self):
        stack = (ROOT / "ops" / "deploy_stateful_lifecycle_stack.ps1").read_text(
            encoding="utf-8"
        )
        validation = (ROOT / "ops" / "validate_stateful_lifecycle_staging.ps1").read_text(
            encoding="utf-8"
        )
        for script in (stack, validation):
            self.assertIn("[switch]$Apply", script)
            self.assertIn("if (-not $Apply)", script)
            self.assertIn("[string]$Profile = $env:AWS_PROFILE", script)
        self.assertIn("Athena engine version 3", stack)
        self.assertIn("--no-fail-on-empty-changeset", stack)
        self.assertIn("failureCount -ne 0", validation)

    def test_lifecycle_workflow_is_manual_and_never_changes_production_alias(self):
        workflow = (
            ROOT / ".github" / "workflows" / "deploy-stateful-lifecycle-staging.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("default: plan", workflow)
        self.assertIn("AWS_STAGING_ROLE_ARN", workflow)
        self.assertIn("deploy-replay-validate", workflow)
        self.assertIn("get-bucket-location", workflow)
        self.assertNotIn("head-bucket", workflow)
        self.assertIn("stateful-lifecycle-staging/artifacts", workflow)
        self.assertIn("stateful-lifecycle-staging/data", workflow)
        self.assertIn("Production alias changed: \\`false\\`", workflow)
        self.assertNotIn("update-alias", workflow)
        self.assertNotIn("scheduler", workflow.lower())

    def test_deployer_policy_bootstrap_is_plan_only_and_staging_scoped(self):
        script = (
            ROOT / "ops" / "configure_stateful_lifecycle_deployer.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("Plan only", script)
        self.assertIn('"athena:GetWorkGroup"', script)
        self.assertIn('"cloudformation:CreateChangeSet"', script)
        self.assertIn('"iam:PassRole"', script)
        self.assertIn('${StackName}-LifecycleGeneratorRole-*', script)
        self.assertIn('${LifecycleDataBucket}/${dataPrefix}/*', script)
        self.assertIn('stateful-lifecycle-staging/artifacts', script)
        self.assertIn('stateful-lifecycle-staging/data', script)
        self.assertIn("Production alias or schedule permission: False", script)
        self.assertNotIn("lambda:UpdateAlias", script)
        self.assertNotIn("scheduler:", script.lower())
        self.assertIn("Remove-Item -LiteralPath $policyPath", script)


if __name__ == "__main__":
    unittest.main()
