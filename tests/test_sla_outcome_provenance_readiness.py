import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "audit_sla_outcome_provenance_readiness_staging.ps1"
CONTRACT = ROOT / "docs" / "sla_outcome_provenance_readiness_v1.md"


class SlaOutcomeProvenanceReadinessTests(unittest.TestCase):
    def test_audit_is_read_only_aggregate_only_and_identifier_free(self):
        script = SCRIPT.read_text(encoding="utf-8")
        lower = script.lower()
        for marker in (
            "count(*) as proposal_count",
            "valid_completed_action_count",
            "valid_provenance_outcome_count",
            "protected counts, identifiers, actor values, and outcome values were not printed",
            "mutations executed: false",
        ):
            self.assertIn(marker, lower)
        for forbidden in (
            "write-host $query",
            "invoke-restmethod",
            "invoke-webrequest",
            "insert into",
            "merge into",
            "update ",
            "delete from",
        ):
            self.assertNotIn(forbidden, lower)

    def test_audit_is_actual_calendar_cutoff_bounded_before_aws(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "Get-SydneyBusinessDate",
            "Australia/Sydney",
            "Minimum created date is in the future; no AWS call was made",
            "temporal_scope_id = 'OPERATIONAL'",
            "execution_mode = 'OPERATIONAL'",
            "time_basis = 'ACTUAL_CALENDAR'",
            "execution_scenario_id IS NULL",
            "as_of_date <= DATE '$sydneyDateText'",
            "try_cast(outcome.dt AS date) <= DATE '$sydneyDateText'",
        ):
            self.assertIn(marker, script)
        self.assertLess(
            script.index("if ($minimumDate -gt $sydneyToday)"),
            script.index("$stack = Get-Stack"),
        )

    def test_audit_requires_exact_decision_pair_and_named_human_chain(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "decision_brief_version = 'decision-brief.v1'",
            "action_type = 'EXPEDITE_MILESTONE'",
            "selected_alternative = 'EXPEDITE_MILESTONE'",
            "selection_rationale IS NOT NULL",
            "events.approve_event_count = 1",
            "events.reject_event_count = 0",
            "events.complete_event_count = 1",
            "invalid_human_audit_event_count = 0",
            "event.request_id IS NULL",
            "length(trim(event.reason)) < 3",
            "('system', 'automation', 'model')",
        ):
            self.assertIn(marker, script)

    def test_audit_requires_latest_valid_outcome_provenance(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "PARTITION BY outcome.outcome_id",
            "outcome.row_rank = 1",
            "outcome.status = 'PENDING'",
            "outcome.observed_date IS NULL",
            "outcome.effect_pct IS NULL",
            "'SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE'",
            "is_finite(try_cast(outcome.effect_pct AS double))",
            "outcome.observed_date >= outcome.observation_due_date",
            "outcome.observed_date <= DATE '$sydneyDateText'",
            "outcome_without_valid_completion_count",
            "invalid_pending_outcome_count",
            "invalid_closed_outcome_count",
            "invalid_outcome_status_count",
        ):
            self.assertIn(marker, script)

    def test_audit_exposes_only_bounded_readiness_states(self):
        script = SCRIPT.read_text(encoding="utf-8")
        states = {
            "NO_BOUND_SLA_PROPOSAL",
            "WAITING_HUMAN_REVIEW",
            "WAITING_OUTCOME",
            "WAITING_OBSERVATION_DUE_DATE",
            "READY_FOR_OUTCOME_OBSERVATION",
            "READY_FOR_PROVENANCE_VERIFICATION",
            "BLOCKED_CONTRACT_DRIFT",
        }
        for state in states:
            self.assertIn(f'"{state}"', script)
        self.assertIn(
            'if ($readiness -eq "BLOCKED_CONTRACT_DRIFT")', script
        )

    def test_audit_cannot_manufacture_human_or_outcome_evidence(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotRegex(script, re.compile(r"workflow\s+run", re.IGNORECASE))
        for forbidden in ("APPROVE' VALUES", "COMPLETE' VALUES", "FUTURE_SIMULATION"):
            self.assertNotIn(forbidden, script)

    def test_contract_preserves_readiness_and_authority_boundaries(self):
        contract = " ".join(CONTRACT.read_text(encoding="utf-8").split())
        for marker in (
            "executed against `2026-08-27` staging; `WAITING_HUMAN_REVIEW`",
            "A natural SLA Decision-bound proposal exists",
            "no named-human completed SLA Action",
            "expected human governance wait state",
            "Expected absence is a readiness state, not invented evidence",
            "Only contract drift causes a non-zero audit exit",
            "exactly one named-human `APPROVE`",
            "exactly one named-human `COMPLETE`",
            "latest cutoff-eligible Outcome version",
            "never prints counts",
            "Every runtime audit therefore requires separate explicit human authorization",
            "does not establish human approval, execution, realised value, causality",
        ):
            self.assertIn(marker, contract)


if __name__ == "__main__":
    unittest.main()
