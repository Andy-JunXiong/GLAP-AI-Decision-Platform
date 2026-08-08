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
            "dim_provider_v1",
            "fact_shipment_lifecycle_staging_v1",
            "fact_shipment_lifecycle_event_staging_v1",
            "fact_shipment_cost_staging_v1",
            "fact_shipment_lifecycle_metrics_staging_v1",
            "fact_shipment_signal_candidate_staging_v1",
            "fact_lifecycle_alert_staging_v1",
            "fact_lifecycle_action_staging_v1",
            "fact_lifecycle_outcome_staging_v1",
            "fact_policy_proposal_staging_v1",
            "fact_lifecycle_action_audit_staging_v1",
            "vw_lifecycle_action_current_staging_v1",
        ):
            with self.subTest(table=table):
                self.assertIn(table, ddl)
        self.assertNotIn("DROP TABLE", ddl.upper())
        self.assertNotIn("fact_shipment_v2 (", ddl)
        self.assertNotRegex(ddl, r"\binteger\b")
        for column in (
            "transport_mode string", "origin_handover_target_at timestamp",
            "destination_release_target_at timestamp", "chargeable_weight_kg decimal",
            "segment_type string", "leg_seq int",
        ):
            self.assertIn(column, ddl)

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

        multimodal = (
            ROOT / "sql" / "08_stateful_lifecycle_multimodal_seed.sql"
        ).read_text(encoding="utf-8")
        for marker in (
            "'MAERSK', 'Maersk'", "'KN', 'Kuehne+Nagel'", "'DHL', 'DHL'",
            "'DHL-PVG-SYD'", "'AIR_FREIGHT'", "'PER_CHARGEABLE_KG'",
            "SIMULATED_PROVIDER_PROFILE", "DATE '2026-09-02'",
        ):
            self.assertIn(marker, multimodal)

        q4_rollover = (
            ROOT / "sql" / "11_stateful_lifecycle_q4_rate_rollover.sql"
        ).read_text(encoding="utf-8")
        for marker in (
            "DATE '2026-10-01'",
            "DATE '2026-12-31'",
            "rate-2026-Q4-simulated-rollover-v1",
            "fx-2026-Q4-simulated-rollover-v1",
            "SIMULATED_Q3_ROLLOVER",
            "rate-2026-Q3-multimodal-v1",
        ):
            self.assertIn(marker, q4_rollover)
        self.assertEqual(q4_rollover.count("WHEN NOT MATCHED THEN INSERT"), 3)
        self.assertNotIn("WHEN MATCHED", q4_rollover)

    def test_sql_files_render_to_expected_statement_counts_after_comment_removal(self):
        def statements(path):
            sql = path.read_text(encoding="utf-8")
            sql = re.sub(r"^\s*--.*$", "", sql, flags=re.MULTILINE)
            return [statement for statement in sql.split(";") if statement.strip()]

        self.assertEqual(len(statements(ROOT / "sql" / "04_stateful_lifecycle_config.sql")), 17)
        self.assertEqual(len(statements(ROOT / "sql" / "05_stateful_lifecycle_seed.sql")), 5)
        self.assertEqual(len(statements(ROOT / "sql" / "06_stateful_lifecycle_validation.sql")), 2)
        self.assertEqual(
            len(statements(ROOT / "sql" / "07_stateful_lifecycle_compatibility_views.sql")),
            12,
        )
        self.assertEqual(
            len(statements(ROOT / "sql" / "08_stateful_lifecycle_multimodal_seed.sql")),
            7,
        )
        self.assertEqual(
            len(statements(ROOT / "sql" / "09_multimodal_ops_analytics.sql")),
            12,
        )
        self.assertEqual(
            len(statements(ROOT / "sql" / "10_multimodal_ops_validation.sql")),
            1,
        )
        self.assertEqual(
            len(statements(ROOT / "sql" / "11_stateful_lifecycle_q4_rate_rollover.sql")),
            3,
        )
        self.assertEqual(
            len(statements(ROOT / "sql" / "12_temporal_scope_backfill.sql")),
            5,
        )
        self.assertEqual(
            len(statements(ROOT / "sql" / "13_operational_baseline.sql")),
            1,
        )
        self.assertEqual(
            len(statements(ROOT / "sql" / "14_operational_baseline_validation.sql")),
            1,
        )

    def test_temporal_backfill_is_manual_bounded_and_verified(self):
        script = (ROOT / "ops" / "backfill_temporal_scope.ps1").read_text(
            encoding="utf-8"
        )
        workflow = (
            ROOT / ".github" / "workflows" / "deploy-stateful-lifecycle-staging.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("invalid_temporal_rows", script)
        self.assertIn("legacy_future_rows", script)
        self.assertIn("future_operational_view_rows", script)
        self.assertIn("Backfill and verify row-level temporal isolation", workflow)
        self.assertIn("./ops/backfill_temporal_scope.ps1", workflow)

    def test_operational_baseline_is_bounded_synthetic_and_fail_closed(self):
        baseline = (ROOT / "sql" / "13_operational_baseline.sql").read_text(
            encoding="utf-8"
        )
        validation = (
            ROOT / "sql" / "14_operational_baseline_validation.sql"
        ).read_text(encoding="utf-8")
        script = (ROOT / "ops" / "deploy_operational_baseline.ps1").read_text(
            encoding="utf-8"
        )
        workflow = (
            ROOT / ".github" / "workflows" / "deploy-stateful-lifecycle-staging.yml"
        ).read_text(encoding="utf-8")
        deployer = (
            ROOT / "ops" / "configure_stateful_lifecycle_deployer.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("vw_multimodal_operational_baseline_v1", baseline)
        self.assertIn("metric_date <= DATE '{{AS_OF_DATE}}'", baseline)
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", baseline)
        self.assertIn("execution_scenario_id IS NULL", baseline)
        self.assertIn("'TRANSPORT_MODE'", baseline)
        self.assertIn("'PROVIDER'", baseline)
        self.assertIn("'MARKET_LANE'", baseline)
        self.assertIn("false AS real_world_evidence", baseline)
        self.assertIn("'SIMULATED_MULTIMODAL_V1'", baseline)
        self.assertIn("'SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE'", baseline)
        self.assertIn("'ENGINEERING_EVALUATION_ONLY'", baseline)
        self.assertIn("sum(IF(delivery_observed, current_total_cost", baseline)
        self.assertIn("delivered_count = 0 AND cost_variance_pct IS NOT NULL", validation)
        self.assertNotRegex(
            baseline,
            r"(?i)(insert\s+into|merge\s+into|update\s+|delete\s+from|drop\s+)",
        )

        for check in (
            "missing_baseline_output",
            "missing_or_duplicate_all_dimension",
            "duplicate_dimension_key",
            "invalid_cutoff_or_temporal_contract",
            "invalid_evidence_classification",
            "overall_shipment_count_does_not_reconcile",
            "mode_shipment_count_does_not_reconcile",
            "provider_shipment_count_does_not_reconcile",
            "lane_shipment_count_does_not_reconcile",
            "invalid_baseline_metric_range",
        ):
            self.assertIn(f"'{check}'", validation)

        self.assertIn("[switch]$Apply", script)
        self.assertIn("Resolve-TemporalContext", script)
        self.assertIn("exactly 10 fail-closed checks", script)
        self.assertIn("Real-world evidence: False", script)
        self.assertIn("deploy-operational-baseline", workflow)
        self.assertIn("Deploy and validate operational as-of baseline", workflow)
        self.assertIn("Real-world evidence claimed: \\`false\\`", workflow)
        self.assertIn("vw_multimodal_operational_baseline_v1", deployer)

    def test_compatibility_views_cover_six_v2_domains_without_writing_current_tables(self):
        compatibility = (
            ROOT / "sql" / "07_stateful_lifecycle_compatibility_views.sql"
        ).read_text(encoding="utf-8")
        for view in (
            "vw_lifecycle_shipment_v2_compat",
            "vw_lifecycle_shipment_event_v2_compat",
            "vw_lifecycle_leg_metrics_v2_compat",
            "vw_lifecycle_cost_v2_compat",
            "vw_lifecycle_risk_v2_compat",
            "vw_lifecycle_product_allocation_v2_compat",
        ):
            with self.subTest(view=view):
                self.assertIn(f"VIEW {{{{SOURCE_DATABASE}}}}.{view}", compatibility)
        self.assertIn("SIMULATED_MULTIMODAL_V1", compatibility)
        self.assertIn("coalesce(transport_mode, 'OCEAN') AS ship_mode", compatibility)
        self.assertIn("SIM-PRODUCT-", compatibility)
        self.assertNotRegex(compatibility, r"(?i)(insert\s+into|merge\s+into|delete\s+from)")
        self.assertNotIn("VIEW {{SOURCE_DATABASE}}.fact_shipment_v2", compatibility)

    def test_multimodal_analytics_keep_shared_stages_and_mode_specific_units(self):
        analytics = (
            ROOT / "sql" / "09_multimodal_ops_analytics.sql"
        ).read_text(encoding="utf-8")
        for view in (
            "vw_multimodal_shipment_daily_v1",
            "vw_multimodal_ops_daily_v1",
            "vw_multimodal_provider_daily_v1",
            "vw_multimodal_mode_decision_v1",
            "vw_multimodal_forecast_feature_daily_v1",
            "vw_multimodal_outcome_label_v1",
        ):
            self.assertIn(f"VIEW {{{{SOURCE_DATABASE}}}}.{view}", analytics)
        self.assertIn("'CHARGEABLE_KG'", analytics)
        self.assertIn("'CONTAINER'", analytics)
        self.assertIn("origin_breach_flag", analytics)
        self.assertIn("p2p_breach_flag", analytics)
        self.assertIn("destination_breach_flag", analytics)
        self.assertIn("ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING", analytics)
        self.assertIn("'NO_FUTURE_DATA'", analytics)
        self.assertIn("'multimodal_forecast_feature_daily_v1'", analytics)
        self.assertIn("feature_day_of_week", analytics)
        self.assertIn("'ADVISORY_SIMULATION_ONLY'", analytics)
        self.assertIn("'AIR_CHARGEABLE_KG_VS_OCEAN_GROSS_KG'", analytics)
        self.assertIn("expected_cost_per_comparison_kg", analytics)

    def test_multimodal_analytics_validation_is_fail_closed(self):
        validation = (
            ROOT / "sql" / "10_multimodal_ops_validation.sql"
        ).read_text(encoding="utf-8")
        for check in (
            "duplicate_analytics_shipment_key",
            "mode_rollup_does_not_reconcile",
            "provider_rollup_does_not_reconcile",
            "invalid_mode_unit_contract",
            "invalid_sla_rate_contract",
            "air_decision_missing_ocean_reference",
            "duplicate_forecast_feature_key",
            "invalid_outcome_label_contract",
        ):
            self.assertIn(f"'{check}'", validation)

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
            "invalid_transport_contract",
            "missing_provider_coverage",
            "air_booking_share_out_of_range",
            "duplicate_alert_key",
            "invalid_alert_contract",
            "invalid_action_contract",
            "duplicate_outcome_key",
            "invalid_outcome_contract",
            "invalid_policy_proposal_contract",
            "duplicate_action_request_id",
            "invalid_action_audit_transition",
        ):
            with self.subTest(check=check):
                self.assertIn(check, validation)

    def test_deployment_is_plan_only_without_apply(self):
        script = (ROOT / "ops" / "deploy_stateful_lifecycle.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("Plan only", script)
        self.assertIn("-LiteralPath", script)
        self.assertIn("[switch]$AnalyticsOnly", script)
        self.assertIn("[switch]$Q4ConfigurationOnly", script)
        self.assertIn("AnalyticsOnly cannot be combined with IncludeSeed", script)
        self.assertIn(
            "Q4ConfigurationOnly cannot be combined with AnalyticsOnly or IncludeSeed",
            script,
        )
        self.assertIn("11_stateful_lifecycle_q4_rate_rollover.sql", script)

    def test_staging_template_is_unscheduled_and_prefix_scoped(self):
        template = (ROOT / "infrastructure" / "stateful-lifecycle-staging.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("glap-stateful-lifecycle-generator-staging", template)
        self.assertIn("LifecycleDataObjectArn", template)
        self.assertIn("RoleName: !Ref ExecutionRoleName", template)
        self.assertIn("fact_shipment_lifecycle_staging_v1", template)
        self.assertIn("fact_shipment_lifecycle_metrics_staging_v1", template)
        self.assertIn("fact_shipment_signal_candidate_staging_v1", template)
        self.assertIn("fact_lifecycle_alert_staging_v1", template)
        self.assertIn("fact_lifecycle_action_staging_v1", template)
        self.assertIn("fact_lifecycle_outcome_staging_v1", template)
        self.assertIn("fact_policy_proposal_staging_v1", template)
        self.assertIn("fact_lifecycle_action_audit_staging_v1", template)
        self.assertIn("vw_lifecycle_action_current_staging_v1", template)
        self.assertIn("glap-lifecycle-action-mutation-staging", template)
        mutation_role = template.split("  ActionMutationRole:", 1)[1].split(
            "  ActionMutationFunction:", 1
        )[0]
        self.assertIn("glue:UpdateTable", mutation_role)
        self.assertIn("dim_rate_tier_v1", template)
        self.assertIn("dim_provider_v1", template)
        self.assertIn("glap-stateful-lifecycle-controller-staging", template)
        self.assertIn("glap-stateful-lifecycle-quality-gate-staging", template)
        self.assertIn('"quality_contract":"lifecycle_v1"', template)
        self.assertIn('"quality_contract":"lifecycle_compat_v2"', template)
        self.assertIn('"quality_contract":"multimodal_analytics_v1"', template)
        self.assertIn("vw_multimodal_mode_decision_v1", template)
        self.assertIn("PipelineStatusObjectArn", template)
        self.assertIn("PipelineStatusObjectsArn", template)
        self.assertIn("PipelineStatusPrefix", template)
        self.assertIn("FindPrivateStatus", template)
        self.assertIn("ALLOW_FUTURE_SIMULATION", template)
        self.assertIn("PIPELINE_ENVIRONMENT: staging", template)
        self.assertNotIn("AWS::Scheduler::Schedule", template)
        self.assertNotIn("pipeline-reliability", template)

        package_script = (
            ROOT / "ops" / "deploy_stateful_lifecycle_stack.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("glap_governed_closed_loop.py", package_script)
        self.assertIn("glap_action_mutation.py", package_script)
        self.assertIn("ActionMutationArtifactKey", package_script)

    def test_replay_is_plan_only_and_seeds_only_first_day(self):
        script = (ROOT / "ops" / "replay_stateful_lifecycle_staging.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("$isFirst = $logicalDate -eq $dates[0]", script)
        self.assertIn("seed_population = $isFirst", script)
        self.assertIn('"OPERATIONAL", "FUTURE_SIMULATION"', script)
        self.assertIn("Resolve-TemporalContext", script)
        self.assertIn("time_basis = $temporalContext.time_basis", script)
        self.assertIn("--cli-read-timeout 900", script)
        self.assertIn("Remove-Item -LiteralPath $payloadPath", script)

    def test_controller_extension_is_plan_only_and_never_seeds(self):
        script = (
            ROOT / "ops" / "extend_stateful_lifecycle_controller_staging.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("[ValidateRange(1, 12)] [int]$Days = 12", script)
        self.assertIn("[ValidateRange(10, 55)] [int]$MaxElapsedMinutes = 50", script)
        self.assertIn("[switch]$RetryFailedRun", script)
        self.assertIn("RetryFailedRun requires exactly one logical date", script)
        self.assertIn("retry_failed_run = $true", script)
        self.assertIn("Credential safety budget exhausted before $day", script)
        self.assertIn("Resume from $day in a new invocation", script)
        self.assertIn("sanitized failure detail unavailable", script)
        self.assertIn("Pipeline failed at [a-z][a-z0-9_]{1,47}", script)
        self.assertIn("Seed population: False", script)
        self.assertIn("logical_run_date = $day", script)
        self.assertIn("scenario_id = $temporalContext.scenario_id", script)
        self.assertNotIn("seed_population =", script)
        self.assertIn("28, 5, 8", script)
        self.assertIn("Controller quality check failed", script)
        self.assertIn("--cli-read-timeout 900", script)
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
        self.assertIn("CAPABILITY_NAMED_IAM", stack)
        self.assertIn("glap_pipeline_controller.py", stack)
        self.assertIn("glap_data_quality_gate.py", stack)
        self.assertIn("glap_quality_contracts.py", stack)
        self.assertIn("glap_temporal_boundary.py", stack)
        self.assertIn("multimodal_ops_validation.sql", stack)
        self.assertIn("lifecycle_validation.sql", stack)
        self.assertIn("failureCount -ne 0", validation)
        self.assertIn('{{TEMPORAL_SCOPE_ID}}", $temporalScopeId', validation)
        self.assertIn('"SIMULATION:$($temporalContext.scenario_id)"', validation)
        self.assertIn('[ValidateSet("OPERATIONAL", "FUTURE_SIMULATION")]', validation)

    def test_lifecycle_workflow_is_manual_and_never_changes_production_alias(self):
        workflow = (
            ROOT / ".github" / "workflows" / "deploy-stateful-lifecycle-staging.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("default: plan", workflow)
        self.assertIn("AWS_STAGING_ROLE_ARN", workflow)
        self.assertIn("deploy-replay-validate", workflow)
        self.assertIn("deploy-integration-validate", workflow)
        self.assertIn("deploy-analytics-contract", workflow)
        self.assertIn("deploy-operational-baseline", workflow)
        self.assertIn("deploy-q4-configuration", workflow)
        self.assertIn("extend-integration-validate", workflow)
        self.assertIn("deploy-recovery-controller", workflow)
        self.assertIn("recover-failed-integration-date", workflow)
        self.assertIn("diagnose-integration-date", workflow)
        self.assertIn("execution_mode:", workflow)
        self.assertIn("FUTURE_SIMULATION", workflow)
        self.assertIn("Scenario ID", workflow)
        self.assertIn("Extend lifecycle through governed controller", workflow)
        self.assertIn("Recover one failed lifecycle date through governed controller", workflow)
        self.assertIn("Diagnose one lifecycle date without mutation", workflow)
        self.assertIn("QUALITY_GATE_FUNCTION", workflow)
        self.assertIn('pipeline_stage = "lifecycle_validation"', workflow)
        self.assertIn('quality_contract = "lifecycle_v1"', workflow)
        self.assertIn("Deployed lifecycle quality gate failed", workflow)
        self.assertIn("fact_lifecycle_outcome_staging_v1", workflow)
        self.assertIn("PARTITION BY outcome_id", workflow)
        self.assertIn("ORDER BY try_cast(dt AS date) DESC, as_of_date DESC", workflow)
        self.assertIn("Due Action Outcomes through", workflow)
        self.assertIn("The due-outcome aggregate query returned an unsafe result", workflow)
        self.assertIn("Remove-Item -LiteralPath $responsePath", workflow)
        self.assertIn("Deploy Q4 simulated rate configuration", workflow)
        self.assertIn("-Q4ConfigurationOnly", workflow)
        self.assertIn("-RetryFailedRun", workflow)
        self.assertIn('test "${{ inputs.replay_days }}" -le 12', workflow)
        self.assertIn(
            '$action -in @("plan", "extend-integration-validate", '
            '"recover-failed-integration-date")',
            workflow,
        )
        self.assertIn('Days = [Math]::Min([int]"${{ inputs.replay_days }}", 12)', workflow)
        self.assertIn("-MaxElapsedMinutes 50", workflow)
        self.assertIn("-AnalyticsOnly", workflow)
        self.assertIn("Deploy read-only analytics contract", workflow)
        self.assertIn("Validate lifecycle pipeline integration", workflow)
        self.assertIn("Verify deployed temporal truthfulness guard", workflow)
        self.assertIn("exceeds Sydney as_of_date", workflow)
        self.assertIn("temporal-boundary-smoke", workflow)
        self.assertIn('\\"dry_run\\":true', workflow)
        self.assertIn("lifecycle_validation", workflow)
        self.assertIn("input_validation", workflow)
        self.assertIn("get-bucket-location", workflow)
        self.assertNotIn("head-bucket", workflow)
        self.assertIn("stateful-lifecycle-staging/artifacts", workflow)
        self.assertIn("stateful-lifecycle-staging/data", workflow)
        self.assertIn("Production alias changed: \\`false\\`", workflow)
        self.assertNotIn("update-alias", workflow)
        self.assertNotIn("scheduler", workflow.lower())

    def test_forecast_backtest_is_manual_read_only_and_private(self):
        script = (
            ROOT / "ops" / "run_multimodal_forecast_backtest.ps1"
        ).read_text(encoding="utf-8")
        label_script = (
            ROOT / "ops" / "run_multimodal_label_readiness.ps1"
        ).read_text(encoding="utf-8")
        workflow = (
            ROOT / ".github" / "workflows" /
            "backtest-multimodal-forecast-staging.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("SELECT", script)
        self.assertIn("vw_multimodal_forecast_feature_daily_v1", script)
        self.assertIn("scan_budget_status", script)
        self.assertIn("temporal_context", script)
        self.assertIn("Resolve-TemporalContext", script)
        self.assertNotRegex(script, r"(?i)(insert\s+into|merge\s+into|delete\s+from)")
        self.assertIn("[switch]$Apply", label_script)
        self.assertIn("if (-not $Apply)", label_script)
        self.assertIn("vw_multimodal_outcome_label_v1", label_script)
        self.assertIn("outcome_status = 'OBSERVED'", label_script)
        self.assertIn("scan_budget_status", label_script)
        self.assertIn("label_observed_through_date <= DATE '$lastDay'", label_script)
        self.assertIn("temporal_context", label_script)
        self.assertNotRegex(label_script, r"(?i)(insert\s+into|merge\s+into|delete\s+from)")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("default: plan", workflow)
        self.assertIn("AWS_STAGING_ROLE_ARN", workflow)
        self.assertIn("retention-days: 14", workflow)
        self.assertIn("Public Pages publication: \\`false\\`", workflow)
        self.assertIn("Production writes: \\`false\\`", workflow)
        self.assertIn("execution_mode:", workflow)
        self.assertIn("FUTURE_SIMULATION", workflow)
        self.assertIn("Pending outcome labels used for training: \\`false\\`", workflow)
        self.assertIn("Assess supervised-label readiness", workflow)
        self.assertNotIn("schedule:", workflow)

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
        self.assertIn('role/${ExecutionRoleName}', script)
        self.assertIn('glap-stateful-lifecycle-generator-staging-role', script)
        self.assertIn('glap-stateful-lifecycle-controller-staging-role', script)
        self.assertIn('glap-stateful-lifecycle-quality-gate-staging-role', script)
        self.assertIn('vw_lifecycle_shipment_v2_compat', script)
        self.assertIn('${LifecycleDataBucket}/${dataPrefix}/*', script)
        self.assertIn('stateful-lifecycle-staging/artifacts', script)
        self.assertIn('stateful-lifecycle-staging/data', script)
        self.assertIn("Production alias or schedule permission: False", script)
        self.assertNotIn("lambda:UpdateAlias", script)
        self.assertNotIn("scheduler:", script.lower())
        self.assertIn("Remove-Item -LiteralPath $policyPath", script)


if __name__ == "__main__":
    unittest.main()
