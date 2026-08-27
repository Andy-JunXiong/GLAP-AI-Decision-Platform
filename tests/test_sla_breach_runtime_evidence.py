import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "reconcile_sla_breach_runtime_staging.ps1"
CONTRACT = ROOT / "docs" / "sla_breach_runtime_evidence_v1.md"


class SlaBreachRuntimeEvidenceTests(unittest.TestCase):
    def test_reconciler_is_aggregate_only_and_read_only(self):
        script = SCRIPT.read_text(encoding="utf-8")
        lower = script.lower()
        for marker in (
            "count(*) as candidate_action_count",
            "source_match_count",
            "eligible_source_count",
            "valid_binding_count",
            "invalid_binding_count",
            "immutable_proposal_count",
            "current_view_binding_match_count",
            "legacy_bound_sla_action_count",
            "protected identifiers were not printed",
        ):
            self.assertIn(marker, lower)
        self.assertNotIn("write-host $query", lower)
        self.assertNotIn("invoke-restmethod", lower)
        self.assertNotIn("invoke-webrequest", lower)
        for statement in ("insert into", "merge into", "update ", "delete from"):
            self.assertNotIn(statement, lower)

    def test_reconciler_enforces_all_seven_sla_source_pairs(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for dimension, metric in (
            ("ORIGIN_GATE_IN", "gate_in_delay_hours"),
            ("ORIGIN_HANDOVER", "origin_delay_hours"),
            ("P2P_DEPARTURE", "departure_delay_hours"),
            ("P2P_ARRIVAL", "arrival_delay_hours"),
            ("DESTINATION_DISCHARGE", "discharge_delay_hours"),
            ("DESTINATION_RELEASE", "destination_release_delay_hours"),
            ("FINAL_DELIVERY", "delivery_delay_hours"),
        ):
            self.assertIn(
                f"alert.alert_dimension = '{dimension}' AND alert.metric_name = '{metric}'",
                script,
            )
        for marker in (
            "alert.alert_type = 'SLA_BREACH'",
            "alert.alert_grain = 'SHIPMENT_MILESTONE'",
            "alert.status = 'OPEN'",
            "is_finite(try_cast(alert.metric_value AS double))",
            "try_cast(alert.metric_value AS double) > try_cast(alert.threshold_value AS double)",
        ):
            self.assertIn(marker, script)
    def test_reconciler_enforces_exact_binding_and_rationale_inputs(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "decision_brief_version = 'decision-brief.v1'",
            "action_type = 'EXPEDITE_MILESTONE'",
            "selected_alternative = 'EXPEDITE_MILESTONE'",
            "Review an expedite intervention for ",
            "alert_dimension",
            "rationale_present_valid",
            "rationale_prefix_valid",
            "rationale_suffix_valid",
            "rationale_numeric_token_valid",
            "rationale_numeric_equality_valid",
            "round(metric_value - threshold_value, 2)",
        ):
            self.assertIn(marker, script)
        self.assertNotIn("regexp_like", script)
        self.assertNotIn("regexp_extract", script)
        self.assertIn("FROM binding_diagnostics", script)

    def test_optional_binding_diagnostic_splits_five_components(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "[switch]$BindingDiagnostic",
            "brief_version_valid",
            "action_type_valid",
            "selected_alternative_valid",
            "rationale_shape_valid",
            "rationale_value_valid",
            'if ($BindingDiagnostic -or $RationaleDiagnostic)',
            '"Every SLA proposal has decision-brief.v1"',
            '"Every SLA proposal has EXPEDITE_MILESTONE Action type"',
            '"Every SLA proposal selects EXPEDITE_MILESTONE"',
            '"Every SLA rationale has the exact milestone-bound shape"',
            '"Every SLA rationale has the calculated breach value"',
        ):
            self.assertIn(marker, script)

    def test_optional_rationale_diagnostic_avoids_regex_for_five_subchecks(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "[switch]$RationaleDiagnostic",
            "expected_rationale_prefix",
            "expected_rationale_suffix",
            "rationale_present_valid",
            "rationale_prefix_valid",
            "rationale_suffix_valid",
            "rationale_numeric_token_valid",
            "rationale_numeric_equality_valid",
            'if ($RationaleDiagnostic)',
            '"Every SLA rationale is present"',
            '"Every SLA rationale has the exact milestone prefix"',
            '"Every SLA rationale has the exact governed suffix"',
            '"Every SLA rationale has a finite non-negative numeric token"',
            '"Every SLA rationale numeric token equals the calculated breach"',
        ):
            self.assertIn(marker, script)
        diagnostic = script.split("if ($RationaleDiagnostic)", 1)[1]
        self.assertNotIn("regexp_extract", diagnostic)
        self.assertNotIn("regexp_like", diagnostic)
        self.assertNotIn("ends_with(", script)
        self.assertIn("substr(", script)

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
        self.assertLess(
            script.index("if ($minimumDate -gt $sydneyToday)"),
            script.index("$stack = Get-Stack"),
        )

    def test_reconciler_requires_natural_proposal_and_preserves_human_gate(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            '"At least one naturally generated SLA proposal exists"',
            '"Every SLA proposal has exactly one eligible source Alert"',
            "status = 'PROPOSED'",
            "approval_required",
            "approved_by IS NULL",
            "approved_at IS NULL",
            "completed_at IS NULL",
            '"Pre-release SLA Actions remain legacy-null"',
        ):
            self.assertIn(marker, script)
        self.assertNotRegex(script, re.compile(r"workflow\s+run", re.IGNORECASE))

    def test_contract_preserves_authority_and_maturity(self):
        contract = " ".join(CONTRACT.read_text(encoding="utf-8").split())
        for marker in (
            "corrected full reconciliation passed against `2026-08-27` staging",
            "exactly one same-date open `SLA_BREACH` Alert",
            "seven governed milestone/delay-metric pairs",
            "calculated hours above threshold",
            "does not invoke the Generator",
            "does not create, backfill, edit, approve, reject, or complete an Action",
            "Future simulation cannot satisfy the gate",
            "every run is an external AWS operation requiring separate human authorization",
            "no root cause is established",
            "Binding diagnostic result — 2026-08-27",
            "Exact milestone-bound rationale shape and calculated breach value failed",
            "cannot distinguish a persisted rationale-text difference from a verifier-expression difference",
            "optional `-RationaleDiagnostic` mode",
            "`ENDS_WITH_EXPRESSION`",
            "`length` plus `substr` comparison",
            "returned all five rationale-only booleans true",
            "`[A-Z_]+`",
            "digit-bearing `P2P_DEPARTURE` and `P2P_ARRIVAL`",
            "contains no rationale regex",
            "Corrected full reconciliation result",
            "returned all seven aggregate booleans true",
            "synthetic staging runtime evidence",
        ):
            self.assertIn(marker, contract)


if __name__ == "__main__":
    unittest.main()
