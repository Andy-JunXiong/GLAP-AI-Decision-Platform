import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_action_assignment_rollout",
    ROOT / "ops" / "validate_action_assignment_rollout.py",
)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(validator)


class ActionAssignmentRolloutTests(unittest.TestCase):
    def test_repository_rollout_contract_is_valid_and_approval_bounded(self):
        self.assertEqual(validator.validate_contract(validator.load_contract()), [])

    def test_authority_expansion_fails_closed(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["authority"]["lambda_deployment_authorized"] = True
        self.assertIn(
            "lambda_deployment_authorized must remain false",
            validator.validate_contract(contract),
        )

    def test_release_order_cannot_skip_schema_validation(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["release_order"].remove("post_migration_validation")
        self.assertIn(
            "release order is incomplete or reordered",
            validator.validate_contract(contract),
        )

    def test_rollback_cannot_erase_edit_evidence(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["rollback"]["delete_audit_events_allowed"] = True
        self.assertIn(
            "rollback cannot delete or rewrite governed evidence",
            validator.validate_contract(contract),
        )

    def test_schema_plan_is_render_only_and_has_no_aws_execution_path(self):
        script = (
            ROOT / "ops" / "plan_action_assignment_schema.ps1"
        ).read_text(encoding="utf-8")
        lower = script.lower()
        self.assertIn("[switch]$ShowSql", script)
        self.assertIn("Mode: local render only", script)
        self.assertIn("Migration statements: 2", script)
        self.assertIn("Validation statements: 1", script)
        self.assertNotIn("[switch]$Apply", script)
        self.assertNotIn("start-query-execution", lower)
        self.assertNotIn("cloudformation deploy", lower)
        self.assertNotIn("deploy_stateful_lifecycle", lower)

    def test_schema_plan_path_cannot_be_changed_to_an_executor(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["release_paths"]["schema_plan"] = "AUTOMATIC_APPLY"
        self.assertIn(
            "schema migration planning must remain local and non-executing",
            validator.validate_contract(contract),
        )

    def test_completed_canary_cannot_hide_verified_steps_or_claim_complete(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["canary"]["operator_edit_completed"] = False
        contract["canary"]["stable_request_id_retry_completed"] = False
        contract["canary"]["named_approver_decision_completed"] = False
        contract["canary"]["action_complete_completed"] = True
        errors = validator.validate_contract(contract)
        self.assertIn(
            "canary must retain the completed operator EDIT evidence",
            errors,
        )
        self.assertIn(
            "verified stable request-ID retry evidence is hidden",
            errors,
        )
        self.assertIn(
            "verified separate approver decision evidence is hidden",
            errors,
        )
        self.assertIn(
            "Action COMPLETE must remain pending and separately authorized",
            errors,
        )

    def test_frontend_release_cannot_claim_an_unrun_refresh_interaction_canary(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["verified_release_evidence"][
            "evidence_refresh_interaction_canary_executed"
        ] = True
        self.assertIn(
            "verified mutation release evidence is incomplete or expands authority",
            validator.validate_contract(contract),
        )


if __name__ == "__main__":
    unittest.main()
