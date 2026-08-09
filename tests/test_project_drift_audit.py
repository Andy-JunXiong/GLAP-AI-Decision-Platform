import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_project_drift", ROOT / "ops" / "audit_project_drift.py"
)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class ProjectDriftAuditTests(unittest.TestCase):
    def test_repository_baseline_has_no_detected_drift(self):
        report = AUDIT.run_audit(ROOT)
        self.assertEqual(report["overall_status"], "PASS")
        self.assertEqual(report["summary"]["drift"], 0)

    def test_action_operation_change_is_detected(self):
        contract = AUDIT.load_contract(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lambda").mkdir()
            (root / "docs").mkdir()
            (root / "lambda" / "glap_action_mutation.py").write_text(
                'if operation not in {"APPROVE", "REJECT", "COMPLETE"}:\n    pass\n',
                encoding="utf-8",
            )
            (root / "docs" / "implementation_roadmap.md").write_text(
                "approve/edit/reject/complete\n", encoding="utf-8"
            )
            (root / "TODO.md").write_text(
                "- [x] Add a governed Action edit event\n"
                "- [x] Extend authenticated Actions with an owner and due date\n",
                encoding="utf-8",
            )
            results = AUDIT.check_action_contract(root, contract)
        operation = next(item for item in results if item.check_id == "action_operations")
        self.assertEqual(operation.status, "DRIFT")

    def test_recurring_staging_trigger_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative_path in AUDIT.PROTECTED_MANUAL_WORKFLOWS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")
            scheduled = root / AUDIT.PROTECTED_MANUAL_WORKFLOWS[0]
            scheduled.write_text("on:\n  schedule:\n    - cron: '0 0 * * *'\n", encoding="utf-8")
            template = root / "infrastructure/stateful-lifecycle-staging.yaml"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text("Resources: {}\n", encoding="utf-8")
            results = AUDIT.check_manual_staging_boundary(root)
        workflow = next(item for item in results if item.check_id == "manual_staging_workflows")
        self.assertEqual(workflow.status, "DRIFT")

    def test_action_assignment_rollout_authority_expansion_is_detected(self):
        source = json.loads(
            (ROOT / "docs" / "action_assignment_rollout_contract.json").read_text(
                encoding="utf-8"
            )
        )
        source["authority"]["lambda_deployment_authorized"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "docs" / "action_assignment_rollout_contract.json"
            contract_path.parent.mkdir(parents=True)
            contract_path.write_text(json.dumps(source), encoding="utf-8")
            result = AUDIT.check_action_assignment_rollout(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_json_report_is_serializable(self):
        report = AUDIT.run_audit(ROOT)
        encoded = json.dumps(report)
        self.assertIn("project-drift-report.v1", encoded)


if __name__ == "__main__":
    unittest.main()
