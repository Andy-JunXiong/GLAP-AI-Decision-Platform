import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "closed_loop", Path(__file__).parents[1] / "lambda" / "glap_governed_closed_loop.py"
)
closed_loop = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(closed_loop)
UTC = timezone.utc


def candidate(kind="SLA_BREACH", fingerprint="alert-1"):
    return {
        "signal_fingerprint": fingerprint, "shipment_id": "SHP-1", "signal_type": kind,
        "signal_grain": "SHIPMENT_MILESTONE" if kind == "SLA_BREACH" else "SHIPMENT_COST",
        "signal_dimension": "P2P_ARRIVAL" if kind == "SLA_BREACH" else "TOTAL_COST",
        "severity": "HIGH", "metric_name": "delay_hours", "metric_value": 48.0,
        "threshold_value": 0.0,
    }


class GovernedClosedLoopTests(unittest.TestCase):
    def test_alert_identity_opens_carries_and_resolves(self):
        opened = closed_loop.reconcile_alerts([candidate()], [], date(2026, 8, 4))[0]
        carried = closed_loop.reconcile_alerts([candidate()], [opened], date(2026, 8, 5))[0]
        self.assertEqual(carried["first_detected_date"], "2026-08-04")
        self.assertEqual(carried["last_detected_date"], "2026-08-05")
        resolved = closed_loop.reconcile_alerts([], [carried], date(2026, 8, 6))[0]
        self.assertEqual(resolved["status"], "RESOLVED")
        self.assertEqual(resolved["resolved_date"], "2026-08-06")

    def test_distinct_signal_types_create_distinct_actions(self):
        alerts = closed_loop.reconcile_alerts(
            [candidate(), candidate("COST_ANOMALY", "alert-2")], [], date(2026, 8, 6)
        )
        actions = closed_loop.propose_actions(alerts, "policy-v1")
        self.assertEqual({row["action_type"] for row in actions}, {"EXPEDITE_MILESTONE", "REVIEW_COST"})
        self.assertTrue(all(row["approval_required"] for row in actions))

    def test_action_requires_named_human_approval(self):
        alert = closed_loop.reconcile_alerts([candidate()], [], date(2026, 8, 6))[0]
        action = closed_loop.propose_actions([alert], "policy-v1")[0]
        with self.assertRaisesRegex(ValueError, "human reviewer"):
            closed_loop.record_action_approval(action, "system", datetime.now(UTC))
        approved = closed_loop.record_action_approval(action, "Alex Chen", datetime(2026, 8, 6, tzinfo=UTC))
        self.assertEqual(approved["approved_by"], "Alex Chen")

    def test_outcome_is_delayed_reproducible_and_context_dependent(self):
        alert = closed_loop.reconcile_alerts([candidate()], [], date(2026, 8, 6))[0]
        action = closed_loop.propose_actions([alert], "policy-v1")[0]
        action = closed_loop.record_action_approval(action, "Alex Chen", datetime(2026, 8, 6, tzinfo=UTC))
        action = closed_loop.complete_action(action, datetime(2026, 8, 6, tzinfo=UTC))
        pending = closed_loop.observe_outcome(action, alert, date(2026, 8, 8))
        self.assertEqual(pending["status"], "PENDING")
        context = {"shipment_stage": "IN_TRANSIT", "carrier": "MAERSK"}
        first = closed_loop.observe_outcome(action, alert, date(2026, 8, 9), context=context)
        second = closed_loop.observe_outcome(action, alert, date(2026, 8, 9), context=context)
        disrupted = closed_loop.observe_outcome(
            action, alert, date(2026, 8, 9), context={**context, "active_disruption": True, "execution_delay_hours": 48}
        )
        self.assertEqual(first, second)
        self.assertIn(first["status"], closed_loop.OUTCOME_STATES)
        self.assertNotEqual(first["status"], disrupted["status"])

    def test_policy_learning_stays_pending_until_human_approval(self):
        outcomes = [
            {"status": "SUCCESSFUL" if index % 2 else "FAILED"}
            for index in range(20)
        ]
        proposal = closed_loop.build_policy_proposal(outcomes, "policy-v1", date(2026, 8, 6))
        self.assertEqual(proposal["status"], "PENDING_HUMAN_REVIEW")
        self.assertFalse(proposal["simulation_config_change"])
        with self.assertRaisesRegex(ValueError, "human reviewer"):
            closed_loop.approve_policy_proposal(proposal, "model", "policy-v2", date(2026, 8, 7))
        approved = closed_loop.approve_policy_proposal(
            proposal, "Alex Chen", "policy-v2", date(2026, 8, 7)
        )
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["rollback_policy_version"], "policy-v1")

    def test_only_actual_calendar_closed_outcomes_are_eligible(self):
        rows = [
            {"status": "SUCCESSFUL", "observed_date": "2026-08-06", "execution_mode": "OPERATIONAL", "time_basis": "ACTUAL_CALENDAR"},
            {"status": "SUCCESSFUL", "observed_date": "2026-09-01", "execution_mode": "FUTURE_SIMULATION", "time_basis": "FUTURE_SIMULATION"},
            {"status": "PENDING", "observed_date": None, "execution_mode": "OPERATIONAL", "time_basis": "ACTUAL_CALENDAR"},
            {"status": "FAILED", "observed_date": "2026-08-07", "execution_mode": "OPERATIONAL", "time_basis": "ACTUAL_CALENDAR"},
        ]
        eligible = closed_loop.eligible_operational_outcomes(rows, date(2026, 8, 6))
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["observed_date"], "2026-08-06")


if __name__ == "__main__":
    unittest.main()
