import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_action_mutation_staging_release",
    ROOT / "ops" / "validate_action_mutation_staging_release.py",
)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(validator)


class ActionMutationStagingReleaseTests(unittest.TestCase):
    def test_repository_release_contract_is_proposed_and_bounded(self):
        self.assertEqual(validator.validate_contract(validator.load_contract()), [])

    def test_read_permission_proposal_is_single_action_and_not_authority(self):
        proposal = validator.load_permission_proposal()
        self.assertEqual(validator.validate_permission_proposal(proposal), [])
        proposal["requested_capability"]["actions"] = ["lambda:*"]
        self.assertIn(
            "read-permission proposal is not limited to one read action",
            validator.validate_permission_proposal(proposal),
        )

    def test_read_permission_proposal_cannot_grant_agent_iam_authority(self):
        proposal = validator.load_permission_proposal()
        proposal["authority"]["agent_iam_change_authorized"] = True
        self.assertIn(
            "read-permission proposal expands protected authority",
            validator.validate_permission_proposal(proposal),
        )

    def test_read_permission_approval_cannot_include_release_execution(self):
        proposal = validator.load_permission_proposal()
        proposal["approval_scope"]["prepare_or_execute_release_approved"] = True
        self.assertIn(
            "read-permission approval scope expanded or became ambiguous",
            validator.validate_permission_proposal(proposal),
        )

    def test_direct_lambda_update_cannot_be_enabled(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["cloudformation_ownership"][
            "direct_update_function_code_allowed"
        ] = True
        self.assertIn(
            "direct Lambda code update must remain prohibited",
            validator.validate_contract(contract),
        )

    def test_change_set_cannot_include_another_resource(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["selected_design"]["allowed_changes"].append(
            {
                "action": "Modify",
                "logical_resource_id": "LifecycleGeneratorFunction",
                "resource_type": "AWS::Lambda::Function",
                "replacement": "False",
                "scope": ["Properties"],
            }
        )
        self.assertIn(
            "change set is not limited to one non-replacing Lambda modification",
            validator.validate_contract(contract),
        )

    def test_execution_authority_cannot_be_claimed(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["authority"]["change_set_execution_authorized"] = True
        self.assertIn(
            "release contract expands or omits protected authority",
            validator.validate_contract(contract),
        )

    def test_read_only_success_cannot_grant_release_write_authority(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["current_blockers"]["release_write_authority_approved"] = True
        self.assertIn(
            "read-only verification cannot grant release write authority",
            validator.validate_contract(contract),
        )

    def test_plan_workflow_is_manual_and_has_no_aws_write_command(self):
        workflow = (
            ROOT / ".github" / "workflows" / "plan-action-mutation-staging.yml"
        ).read_text(encoding="utf-8")
        script = (
            ROOT / "ops" / "plan_action_mutation_staging_release.ps1"
        ).read_text(encoding="utf-8")
        combined = (workflow + "\n" + script).lower()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertNotIn("  schedule:", workflow)
        self.assertIn("[switch]$InspectAws", script)
        for command in (
            "s3 cp",
            "create-change-set",
            "execute-change-set",
            "update-function-code",
            "cloudformation deploy",
            "aws iam ",
        ):
            self.assertNotIn(command, combined)
        self.assertNotIn("[switch]$Apply", script)


if __name__ == "__main__":
    unittest.main()
