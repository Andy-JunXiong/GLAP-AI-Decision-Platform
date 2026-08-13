from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LAMBDA_DIR = ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
os.environ.setdefault("ATHENA_OUTPUT", "s3://private-query-results/actions/")
SPEC = importlib.util.spec_from_file_location(
    "action_mutation", LAMBDA_DIR / "glap_action_mutation.py"
)
mutation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mutation)
NOW = datetime(2026, 8, 6, 10, 30, tzinfo=timezone.utc)


def event(operation="APPROVE", request_id="request-001", actor="Alex Chen"):
    payload = {
        "operation": operation,
        "action_id": "abc123def456",
        "request_id": request_id,
        "actor": actor,
        "reason": "Reviewed operational evidence",
    }
    if operation == "EDIT":
        payload.update({
            "action_owner": "Jordan Lee",
            "action_due_date": "2026-08-09",
            "logical_run_date": "2026-08-06",
        })
    return payload


class ActionMutationTests(unittest.TestCase):
    def test_approve_requires_proposed_and_records_human(self):
        row = mutation.plan_mutation(event(), {"status": "PROPOSED"}, NOW)
        self.assertEqual(row["previous_status"], "PROPOSED")
        self.assertEqual(row["new_status"], "APPROVED")
        self.assertEqual(row["approved_by"], "Alex Chen")
        self.assertEqual(row["approved_at"], NOW)

    def test_complete_preserves_approval_and_records_completion(self):
        approved_at = datetime(2026, 8, 6, 9, tzinfo=timezone.utc)
        row = mutation.plan_mutation(
            event("COMPLETE", "request-002"),
            {"status": "APPROVED", "approved_by": "Alex Chen", "approved_at": approved_at},
            NOW,
        )
        self.assertEqual(row["new_status"], "COMPLETED")
        self.assertEqual(row["approved_at"], approved_at)
        self.assertEqual(row["completed_at"], NOW)

    def test_edit_assigns_named_owner_and_due_date_without_approving(self):
        row = mutation.plan_mutation(event("EDIT"), {"status": "PROPOSED"}, NOW)
        self.assertEqual(row["new_status"], "EDITED")
        self.assertEqual(row["action_owner"], "Jordan Lee")
        self.assertEqual(row["action_due_date"].isoformat(), "2026-08-09")
        self.assertIsNone(row["approved_by"])

    def test_edit_rejects_automatic_owner_and_past_due_date(self):
        invalid_owner = event("EDIT")
        invalid_owner["action_owner"] = "system"
        with self.assertRaisesRegex(ValueError, "named human Action owner"):
            mutation.plan_mutation(invalid_owner, {"status": "PROPOSED"}, NOW)
        past_due = event("EDIT")
        past_due["action_due_date"] = "2026-08-05"
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            mutation.plan_mutation(past_due, {"status": "PROPOSED"}, NOW)

    def test_edited_action_can_be_approved_and_preserves_assignment(self):
        row = mutation.plan_mutation(
            event(),
            {
                "status": "EDITED", "action_owner": "Jordan Lee",
                "action_due_date": "2026-08-09",
            },
            NOW,
        )
        self.assertEqual(row["new_status"], "APPROVED")
        self.assertEqual(row["action_owner"], "Jordan Lee")
        self.assertEqual(row["action_due_date"].isoformat(), "2026-08-09")

    def test_invalid_transition_and_automatic_actor_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Invalid Action transition"):
            mutation.plan_mutation(event("COMPLETE"), {"status": "PROPOSED"}, NOW)
        with self.assertRaisesRegex(ValueError, "named human"):
            mutation.plan_mutation(event(actor="system"), {"status": "PROPOSED"}, NOW)

    def test_request_id_determines_stable_event_id(self):
        first = mutation.plan_mutation(event(), {"status": "PROPOSED"}, NOW)
        second = mutation.plan_mutation(event(), {"status": "PROPOSED"}, NOW)
        self.assertEqual(first["event_id"], second["event_id"])

    def test_queries_are_scope_bounded_and_insert_only(self):
        current = mutation.build_current_action_query("abc123def456", "OPERATIONAL")
        replay = mutation.build_idempotency_query("request-001", "OPERATIONAL")
        self.assertIn("vw_lifecycle_action_current_staging_v1", current)
        self.assertIn("temporal_scope_id = 'OPERATIONAL'", current)
        self.assertIn("request_id = 'request-001'", replay)
        row = mutation.plan_mutation(event(), {"status": "PROPOSED"}, NOW)
        row.update({
            "temporal_scope_id": "OPERATIONAL", "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR", "as_of_date": NOW.date(),
            "execution_scenario_id": None,
        })
        sql = mutation.build_audit_merge(row)
        self.assertIn("WHEN NOT MATCHED THEN INSERT", sql)
        self.assertNotIn("WHEN MATCHED", sql)
        self.assertIn("target.request_id = source.request_id", sql)
        self.assertIn("target.action_id = source.action_id", sql)
        self.assertIn("target.previous_status = source.previous_status", sql)
        self.assertIn("action_owner", sql)
        self.assertIn("action_due_date", sql)

    def test_competing_transition_fails_when_request_was_not_persisted(self):
        handler_event = event()
        handler_event.update({
            "logical_run_date": "2026-08-06",
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
        })
        current = [{
            "action_id": "abc123def456", "status": "PROPOSED",
            "approved_by": None, "approved_at": None, "completed_at": None,
            "action_owner": None, "action_due_date": None,
        }]
        fake_boto3 = types.SimpleNamespace(client=lambda *_args, **_kwargs: object())
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(
            mutation, "_run_query", side_effect=[[], current, [], []]
        ):
            with self.assertRaises(mutation.ActionConflictError):
                mutation.lambda_handler(handler_event, None)

    def test_edit_handler_response_is_json_serializable(self):
        handler_event = event("EDIT")
        handler_event.update({
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
        })
        current = [{
            "action_id": "abc123def456", "status": "PROPOSED",
            "approved_by": None, "approved_at": None, "completed_at": None,
            "action_owner": None, "action_due_date": None,
        }]
        confirmed = [{"event_id": "event-001"}]
        fake_boto3 = types.SimpleNamespace(client=lambda *_args, **_kwargs: object())
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(
            mutation, "_run_query", side_effect=[[], current, [], confirmed]
        ):
            result = mutation.lambda_handler(handler_event, None)

        self.assertEqual(result["action_due_date"], "2026-08-09")
        self.assertEqual(json.loads(json.dumps(result))["action_due_date"], "2026-08-09")


if __name__ == "__main__":
    unittest.main()
