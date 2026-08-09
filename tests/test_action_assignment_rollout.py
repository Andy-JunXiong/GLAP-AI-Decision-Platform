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
    def test_repository_rollout_contract_is_valid_and_plan_only(self):
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


if __name__ == "__main__":
    unittest.main()
