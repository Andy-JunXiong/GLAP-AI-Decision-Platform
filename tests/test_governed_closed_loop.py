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
        "severity": "HIGH",
        "metric_name": "arrival_delay_hours" if kind == "SLA_BREACH" else "cost_variance_pct",
        "metric_value": 48.0,
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

    def test_sla_action_preserves_decision_brief_binding(self):
        alert = closed_loop.reconcile_alerts([candidate()], [], date(2026, 8, 6))[0]
        action = closed_loop.propose_actions([alert], "policy-v1")[0]
        self.assertEqual(action["decision_brief_version"], "decision-brief.v1")
        self.assertEqual(action["selected_alternative"], "EXPEDITE_MILESTONE")
        self.assertEqual(
            action["selection_rationale"],
            "Review an expedite intervention for P2P_ARRIVAL; the governed delay is 48 hours above threshold.",
        )
        self.assertEqual(action["status"], "PROPOSED")
        self.assertTrue(action["approval_required"])

    def test_cost_action_preserves_decision_brief_binding_and_source_contract(self):
        alerts = closed_loop.reconcile_alerts(
            [candidate("COST_ANOMALY", "alert-cost")], [], date(2026, 8, 6)
        )
        cost_action = closed_loop.propose_actions(alerts, "policy-v1")[0]
        self.assertEqual(cost_action["decision_brief_version"], "decision-brief.v1")
        self.assertEqual(cost_action["selected_alternative"], "REVIEW_COST")
        self.assertEqual(
            cost_action["selection_rationale"],
            "Review the governed cost basis under stateful-cost-variance.v1; "
            "total cost variance is 48 percentage points above threshold.",
        )

    def test_invalid_decision_brief_binding_is_not_invented(self):
        invalid_cost = closed_loop.reconcile_alerts(
            [candidate("COST_ANOMALY", "alert-cost-invalid")], [], date(2026, 8, 6)
        )[0]
        invalid_cost["metric_name"] = "arrival_delay_hours"
        with self.assertRaisesRegex(ValueError, "grain, dimension, and metric"):
            closed_loop.propose_actions([invalid_cost], "policy-v1")

        invalid_alert = closed_loop.reconcile_alerts([candidate()], [], date(2026, 8, 6))[0]
        invalid_alert["metric_name"] = "delivery_delay_hours"
        with self.assertRaisesRegex(ValueError, "metric and milestone"):
            closed_loop.propose_actions([invalid_alert], "policy-v1")

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
            {
                "outcome_id": f"outcome-{index}",
                "dt": "2026-08-06",
                "status": "SUCCESSFUL" if index % 2 else "FAILED",
            }
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

    def test_policy_threshold_counts_latest_logical_outcomes_not_history_rows(self):
        versions = [
            {
                "outcome_id": "outcome-one",
                "dt": f"2026-08-{index:02d}",
                "status": "SUCCESSFUL",
            }
            for index in range(1, 21)
        ]
        proposal = closed_loop.build_policy_proposal(
            versions, "policy-v1", date(2026, 8, 20)
        )
        self.assertIsNone(proposal)

        distinct = [
            {
                "outcome_id": f"outcome-{index}",
                "dt": "2026-08-20",
                "status": "SUCCESSFUL",
            }
            for index in range(20)
        ]
        proposal = closed_loop.build_policy_proposal(
            distinct, "policy-v1", date(2026, 8, 20)
        )
        self.assertEqual(proposal["observed_outcome_count"], 20)

    def test_latest_pending_version_excludes_earlier_closed_version(self):
        outcomes = [
            {
                "outcome_id": "outcome-one",
                "dt": "2026-08-19",
                "status": "SUCCESSFUL",
            },
            {
                "outcome_id": "outcome-one",
                "dt": "2026-08-20",
                "status": "PENDING",
            },
        ]
        proposal = closed_loop.build_policy_proposal(
            outcomes, "policy-v1", date(2026, 8, 20), minimum_observed=1
        )
        self.assertIsNone(proposal)

    def test_outcome_version_selection_fails_closed_on_temporal_or_key_drift(self):
        with self.assertRaisesRegex(ValueError, "future version"):
            closed_loop.latest_outcome_versions(
                [{"outcome_id": "outcome-one", "dt": "2026-08-21"}],
                date(2026, 8, 20),
            )
        with self.assertRaisesRegex(ValueError, "conflicting versions"):
            closed_loop.latest_outcome_versions(
                [
                    {
                        "outcome_id": "outcome-one",
                        "dt": "2026-08-20",
                        "status": "PENDING",
                    },
                    {
                        "outcome_id": "outcome-one",
                        "dt": "2026-08-20",
                        "status": "SUCCESSFUL",
                    },
                ],
                date(2026, 8, 20),
            )

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
