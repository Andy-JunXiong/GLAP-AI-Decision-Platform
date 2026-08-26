import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "sql" / "16_decision_action_binding_v1.sql"
VALIDATION = ROOT / "sql" / "17_decision_action_binding_validation.sql"
PLAN = ROOT / "ops" / "plan_decision_truth_staging_rollout.ps1"
RUNBOOK = ROOT / "docs" / "decision_truth_staging_rollout.md"


def statement_count(path: Path) -> int:
    sql = re.sub(r"(?m)^\s*--.*$", "", path.read_text(encoding="utf-8"))
    return len([statement for statement in sql.split(";") if statement.strip()])


class DecisionTruthStagingRolloutTests(unittest.TestCase):
    def test_migration_is_two_statement_additive_staging_only(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        upper = sql.upper()
        self.assertEqual(statement_count(MIGRATION), 2)
        self.assertIn("PLAN ONLY", upper)
        self.assertIn("FACT_LIFECYCLE_ACTION_STAGING_V1", upper)
        self.assertIn("VW_LIFECYCLE_ACTION_CURRENT_STAGING_V1", upper)
        for field in (
            "decision_brief_version",
            "selected_alternative",
            "selection_rationale",
        ):
            self.assertIn(field, sql)
        for operation in ("DROP", "DELETE", "INSERT", "UPDATE", "MERGE", "TRUNCATE"):
            self.assertNotRegex(upper, rf"\b{operation}\b")

    def test_post_migration_validation_is_one_read_only_aggregate(self):
        sql = VALIDATION.read_text(encoding="utf-8")
        upper = sql.upper()
        self.assertEqual(statement_count(VALIDATION), 1)
        for check_name in (
            "missing_action_binding_columns",
            "missing_action_current_binding_columns",
            "partial_action_binding",
            "invalid_decision_brief_v1_binding",
            "invalid_cost_decision_brief_v1_binding",
            "current_view_binding_mismatch",
        ):
            self.assertIn(check_name, sql)
        self.assertRegex(sql, r"SELECT check_name, failure_count\s+FROM checks")
        self.assertIn("alert_type = 'COST_ANOMALY'", sql)
        self.assertIn("action_type = 'REVIEW_COST'", sql)
        self.assertIn("selected_alternative = 'REVIEW_COST'", sql)
        for operation in ("ALTER", "CREATE", "DROP", "DELETE", "INSERT", "UPDATE", "MERGE", "TRUNCATE"):
            self.assertNotRegex(upper, rf"\b{operation}\b")

    def test_plan_renderer_has_no_aws_or_apply_path(self):
        script = PLAN.read_text(encoding="utf-8")
        lower = script.lower()
        self.assertIn("Mode: local render only", script)
        self.assertIn("Aggregate validation checks: 6", script)
        self.assertIn("COST_ANOMALY binding source present: True", script)
        self.assertIn("COST_ANOMALY staging producer released: True", script)
        self.assertIn("COST_ANOMALY staging readers released: True", script)
        self.assertIn("COST_ANOMALY runtime binding observed: False", script)
        self.assertIn("lifecycle producer", lower)
        self.assertIn("Operational continuation authorized: False", script)
        self.assertNotIn("[switch]$Apply", script)
        self.assertNotIn("& aws", lower)
        self.assertNotIn("start-query-execution", lower)
        self.assertNotIn("workflow run", lower)
        self.assertNotIn("invoke-webrequest", lower)

    def test_runbook_preserves_human_owned_release_order(self):
        document = RUNBOOK.read_text(encoding="utf-8")
        ordered_markers = (
            "reviews and applies only",
            "runs only the read-only",
            "deploys the current isolated\n   lifecycle producer",
            "runs the existing Operations API workflow",
            "ops/deploy_internal_operations_frontend.ps1",
            "Run the read-only staging contract verifier",
        )
        positions = [document.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Each numbered write is a separate human authority decision", document)
        self.assertIn("It may not perform", document)

    def test_runtime_proof_cannot_be_manufactured_or_overclaimed(self):
        document = RUNBOOK.read_text(encoding="utf-8")
        normalized = " ".join(document.split())
        self.assertIn("Existing Actions intentionally remain legacy-null", normalized)
        self.assertIn("Do not create, backfill, or mutate an Action merely to satisfy the test", normalized)
        self.assertIn("Existing `COST_ANOMALY` Actions remain unbound", normalized)
        self.assertIn("every newly bound `COST_ANOMALY` Action", normalized)
        self.assertIn("This remains synthetic staging engineering evidence", normalized)
        self.assertIn("The additive columns are retained", normalized)


if __name__ == "__main__":
    unittest.main()
