import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "reconcile_cost_anomaly_runtime_staging.ps1"
CONTRACT = ROOT / "docs" / "cost_anomaly_runtime_evidence_v1.md"


class CostAnomalyRuntimeEvidenceTests(unittest.TestCase):
    def test_reconciler_is_aggregate_only_and_read_only(self):
        script = SCRIPT.read_text(encoding="utf-8")
        lower = script.lower()
        for marker in (
            "count(*) as candidate_action_count",
            "eligible_source_count",
            "valid_binding_count",
            "invalid_binding_count",
            "immutable_proposal_count",
            "current_view_binding_match_count",
            "legacy_bound_cost_action_count",
            "protected identifiers were not printed",
        ):
            self.assertIn(marker, lower)
        self.assertNotIn("write-host $query", lower)
        self.assertNotIn("invoke-restmethod", lower)
        self.assertNotIn("invoke-webrequest", lower)
        for statement in ("insert into", "merge into", "update ", "delete from"):
            self.assertNotIn(statement, lower)

    def test_reconciler_enforces_cost_source_and_exact_binding(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "alert_grain = 'SHIPMENT_COST'",
            "alert_dimension = 'TOTAL_COST'",
            "metric_name = 'cost_variance_pct'",
            "alert_status = 'OPEN'",
            "is_finite(try_cast(metric_value AS double))",
            "try_cast(metric_value AS double) > try_cast(threshold_value AS double)",
            "decision_brief_version = 'decision-brief.v1'",
            "action_type = 'REVIEW_COST'",
            "selected_alternative = 'REVIEW_COST'",
            "stateful-cost-variance.v1",
        ):
            self.assertIn(marker, script)

    def test_reconciler_is_actual_calendar_and_future_fail_closed(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "Get-SydneyBusinessDate",
            "Australia/Sydney",
            "AUS Eastern Standard Time",
            "Minimum created date is in the future; no AWS call was made",
            "temporal_scope_id = 'OPERATIONAL'",
            "execution_mode = 'OPERATIONAL'",
            "time_basis = 'ACTUAL_CALENDAR'",
            "execution_scenario_id IS NULL",
            "action.as_of_date <= DATE '$sydneyDateText'",
        ):
            self.assertIn(marker, script)

    def test_reconciler_requires_natural_proposal_and_preserves_human_gate(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            '"At least one naturally generated Cost proposal exists"',
            "status = 'PROPOSED'",
            "approval_required",
            "approved_by IS NULL",
            "approved_at IS NULL",
            "completed_at IS NULL",
            '"Pre-release Cost Actions remain legacy-null"',
        ):
            self.assertIn(marker, script)
        self.assertNotRegex(script, re.compile(r"workflow\s+run", re.IGNORECASE))

    def test_contract_preserves_authority_and_maturity(self):
        contract = " ".join(CONTRACT.read_text(encoding="utf-8").split())
        for marker in (
            "executed against staging on `2026-08-27`; failed closed",
            "bounded actual-calendar cohort contained zero Cost proposals",
            "established no runtime Decision-binding evidence",
            "does not invoke the Generator",
            "does not create, backfill, edit, approve, reject, or complete an Action",
            "At least one naturally generated proposal",
            "Future simulation cannot satisfy the gate",
            "Athena writes its query-result object",
            "any future rerun requires separate human authorization",
        ):
            self.assertIn(marker, contract)


if __name__ == "__main__":
    unittest.main()
