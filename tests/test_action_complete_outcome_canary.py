import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_action_complete_outcome_canary",
    ROOT / "ops" / "validate_action_complete_outcome_canary.py",
)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(validator)


class ActionCompleteOutcomeCanaryTests(unittest.TestCase):
    def test_repository_contract_is_valid_and_not_authorized(self):
        contract = validator.load_contract()
        self.assertEqual(validator.validate_contract(contract), [])
        self.assertTrue(all(value is False for value in contract["authority"].values()))
        self.assertEqual(
            contract["status"],
            "OBSERVED_OUTCOME_FAILED_CLOSED_SOURCE_FIX_DEPLOYED_RUNTIME_RECHECK_PENDING",
        )

    def test_runtime_observation_preserves_failed_closed_learning_result(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["runtime_observation"][
            "zero_policy_proposal_below_threshold_check_passed"
        ] = True
        self.assertIn(
            "observed Outcome runtime evidence or failed-closed Learning result has drifted",
            validator.validate_contract(contract),
        )

    def test_deployed_forward_fix_cannot_claim_runtime_recheck_or_rewrite_evidence(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["local_forward_fix"]["post_deploy_runtime_reconciliation_executed"] = True
        contract["local_forward_fix"]["stored_proposal_deleted_or_rewritten"] = True
        self.assertIn(
            "latest-logical-Outcome release maturity is incomplete or overclaimed",
            validator.validate_contract(contract),
        )

    def test_observation_preparation_cannot_claim_execution_or_observation(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["runtime_observation_preparation"]["observed_outcome_continuation_executed"] = True
        contract["runtime_observation_preparation"]["observed_result_claimed"] = True
        self.assertIn(
            "observation verifier preparation is incomplete or overclaimed",
            validator.validate_contract(contract),
        )

    def test_runtime_pending_outcome_cannot_claim_observation_or_new_authority(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["runtime_pending_outcome"]["unobserved_outcome_count"] = 0
        contract["runtime_pending_outcome"]["observed_outcome_continuation_authorized"] = True
        self.assertIn(
            "verified pending Outcome evidence is incomplete or overclaimed",
            validator.validate_contract(contract),
        )

    def test_runtime_completion_cannot_claim_agent_execution_or_outcome(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["runtime_completion"]["agent_execution"] = True
        contract["runtime_completion"]["outcome_count_before_continuation"] = 1
        self.assertIn(
            "verified named-human COMPLETE evidence is incomplete or overclaimed",
            validator.validate_contract(contract),
        )

    def test_runtime_preflight_cannot_hide_mutation_or_outcome(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["runtime_preflight"]["complete_event_count"] = 1
        contract["runtime_preflight"]["action_mutation_executed"] = True
        self.assertIn(
            "verified aggregate preflight evidence is incomplete or overclaimed",
            validator.validate_contract(contract),
        )

    def test_agent_or_human_authority_expansion_fails_closed(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["authority"]["agent_action_mutation_authorized"] = True
        self.assertIn(
            "all mutation, deployment, production, policy, and model authority must remain false",
            validator.validate_contract(contract),
        )
        contract = copy.deepcopy(validator.load_contract())
        contract["authority"]["named_human_complete_authorized"] = True
        self.assertIn(
            "all mutation, deployment, production, policy, and model authority must remain false",
            validator.validate_contract(contract),
        )

    def test_phase_order_cannot_skip_pending_evidence(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["phase_order"].remove("read_only_pending_reconciliation")
        self.assertIn("phase order is incomplete or reordered", validator.validate_contract(contract))

    def test_preflight_and_completion_reconciliation_are_exact(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["phases"]["read_only_preflight"]["mode"] = "WRITE"
        contract["phases"]["read_only_complete_reconciliation"]["expected_complete_event_count"] = 2
        errors = validator.validate_contract(contract)
        self.assertIn("preflight must remain read-only and exact-state gated", errors)
        self.assertIn(
            "completion reconciliation must remain read-only and exact-count gated",
            errors,
        )

    def test_complete_requires_signed_human_and_stable_retry(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["phases"]["named_human_complete"]["actor_source"] = "CLIENT_INPUT"
        contract["phases"]["named_human_complete"]["same_request_id_retry_only"] = False
        self.assertIn(
            "COMPLETE must remain a separately authorized, identity-derived, idempotent human step",
            validator.validate_contract(contract),
        )

    def test_future_simulation_cannot_satisfy_outcome_gate(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["phases"]["separately_authorized_observed_outcome_generation"]["future_simulation_allowed"] = True
        self.assertIn(
            "observed Outcome generation cannot use future simulation",
            validator.validate_contract(contract),
        )

    def test_pending_outcome_cannot_claim_observation(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["phases"]["read_only_pending_reconciliation"]["expected_observed_date"] = "2026-08-28"
        self.assertIn(
            "pending Outcome must remain unobserved and explicitly simulated",
            validator.validate_contract(contract),
        )

    def test_learning_cannot_activate_policy_or_claim_real_performance(self):
        contract = copy.deepcopy(validator.load_contract())
        contract["phases"]["read_only_outcome_learning_reconciliation"]["automatic_policy_activation_allowed"] = True
        self.assertIn(
            "Learning reconciliation must remain read-only, synthetic, and review-gated",
            validator.validate_contract(contract),
        )

    def test_renderer_is_redacted_and_performs_no_external_write(self):
        result = subprocess.run(
            [sys.executable, "ops/render_action_complete_outcome_canary_plan.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        plan = json.loads(result.stdout)
        self.assertFalse(plan["external_writes_executed"])
        self.assertTrue(all(value is False for value in plan["authority"].values()))
        rendered = result.stdout.lower()
        for field in validator.PROTECTED_FIELDS:
            self.assertNotIn(f'"{field}"', rendered)

    def test_runtime_preflight_is_aggregate_only_and_read_only(self):
        script = (
            ROOT / "ops" / "preflight_action_complete_outcome_staging.ps1"
        ).read_text(encoding="utf-8")
        lower = script.lower()
        self.assertIn("count(*) as candidate_action_count", lower)
        self.assertIn("current.status = 'approved'", lower)
        self.assertIn("events.complete_event_count = 0", lower)
        self.assertIn("coalesce(sum(outcome_count), 0) as outcome_count", lower)
        self.assertIn("protected identifiers were not printed", lower)
        self.assertNotIn("write-host $query", lower)
        self.assertNotIn("invoke-restmethod", lower)
        self.assertNotIn("invoke-webrequest", lower)
        for statement in ("insert into", "merge into", "update ", "delete from"):
            self.assertNotIn(statement, lower)

    def test_complete_reconciliation_is_aggregate_only_and_read_only(self):
        script = (
            ROOT / "ops" / "reconcile_action_complete_staging.ps1"
        ).read_text(encoding="utf-8")
        lower = script.lower()
        self.assertIn("count(*) as candidate_action_count", lower)
        self.assertIn("current.status = 'completed'", lower)
        self.assertIn("events.complete_event_count = 1", lower)
        self.assertIn("events.named_complete_actor_count = 1", lower)
        self.assertIn("coalesce(sum(outcome_count), 0) as outcome_count", lower)
        self.assertIn("protected identifiers were not printed", lower)
        self.assertNotIn("write-host $query", lower)
        self.assertNotIn("invoke-restmethod", lower)
        self.assertNotIn("invoke-webrequest", lower)
        for statement in ("insert into", "merge into", "update ", "delete from"):
            self.assertNotIn(statement, lower)

    def test_pending_outcome_reconciliation_is_temporal_and_read_only(self):
        script = (
            ROOT / "ops" / "reconcile_pending_outcome_staging.ps1"
        ).read_text(encoding="utf-8")
        lower = script.lower()
        self.assertIn("outcome.status = 'pending'", lower)
        self.assertIn("outcome.observed_date is null", lower)
        self.assertIn("outcome.effect_pct is null", lower)
        self.assertIn("outcome.provenance = 'simulated'", lower)
        self.assertIn("date_add('day', 3, candidate.completed_date)", lower)
        self.assertIn("protected identifiers were not printed", lower)
        self.assertNotIn("write-host $query", lower)
        self.assertNotIn("invoke-restmethod", lower)
        self.assertNotIn("invoke-webrequest", lower)
        for statement in ("insert into", "merge into", "update ", "delete from"):
            self.assertNotIn(statement, lower)

    def test_observation_due_date_gate_is_local_system_derived_and_fail_closed(self):
        script = (
            ROOT / "ops" / "check_observed_outcome_due_date.ps1"
        ).read_text(encoding="utf-8")
        lower = script.lower()
        self.assertIn("get-sydneybusinessdate", lower)
        self.assertIn("australia/sydney", lower)
        self.assertIn("aus eastern standard time", lower)
        self.assertIn("runtime_pending_outcome.observation_due_date", lower)
        self.assertIn("blocked: observation due date has not been reached", lower)
        self.assertIn("external writes executed: false", lower)
        for token in (" aws ", "athena", "invoke-restmethod", "invoke-webrequest"):
            self.assertNotIn(token, lower)

    def test_observed_outcome_learning_reconciliation_is_temporal_and_read_only(self):
        script = (
            ROOT / "ops" / "reconcile_observed_outcome_learning_staging.ps1"
        ).read_text(encoding="utf-8")
        lower = script.lower()
        self.assertLess(
            lower.index("observation due date has not been reached"),
            lower.index("$awsscope"),
        )
        for marker in (
            "partition by outcome.outcome_id",
            "outcome.row_rank = 1",
            "outcome.observed_date >= outcome.observation_due_date",
            "eligible outcome count advanced by exactly one",
            "policy review threshold remains unmet",
            "no policy proposal exists below the threshold",
            "no policy proposal is activated",
            "protected identifiers were not printed",
        ):
            self.assertIn(marker, lower)
        self.assertNotIn("write-host $query", lower)
        for statement in ("insert into", "merge into", "update ", "delete from"):
            self.assertNotIn(statement, lower)


if __name__ == "__main__":
    unittest.main()
