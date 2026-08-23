import importlib.util
import json
import shutil
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
    @staticmethod
    def _copy_paths(root: Path, paths: tuple[str, ...]) -> None:
        for relative_path in paths:
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative_path, target)

    def test_current_architecture_does_not_claim_external_action_execution(self):
        current = AUDIT.check_governed_action_outcome_boundary(ROOT)[0]
        self.assertEqual(current.status, "PASS")

        architecture = (ROOT / "docs" / "architecture_current.md").read_text(
            encoding="utf-8"
        )
        drifted = architecture.replace(
            "Append immutable Action audit event", "Execute diversion or escalation"
        ).replace(
            "Generate delayed simulated Outcome", "Measure cost and in-stock outcome"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "architecture_current.md").write_text(
                drifted, encoding="utf-8"
            )
            detected = AUDIT.check_governed_action_outcome_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_action_outcome_evidence_chain_authority_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "infrastructure/operations-api-staging.yaml",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            ".github/workflows/deploy-operations-api-staging.yml",
            "ops/deploy_internal_operations_frontend.ps1",
            "ops/verify_operations_staging.ps1",
            "ops/verify_operations_roles_staging.ps1",
            "CURRENT_DEVELOPMENT_STATUS.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_action_outcome_evidence_chain_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            template_path = root / "infrastructure" / "operations-api-staging.yaml"
            template_path.write_text(
                template_path.read_text(encoding="utf-8").replace(
                    "RouteKey: GET /v1/actions/{action_id}/evidence",
                    "RouteKey: POST /v1/actions/{action_id}/evidence",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_action_outcome_evidence_chain_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_learning_activation_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "infrastructure/operations-api-staging.yaml",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            ".github/workflows/deploy-operations-api-staging.yml",
            "ops/configure_operations_api_discovery.ps1",
            "ops/configure_operations_api_data_access.ps1",
            "ops/deploy_internal_operations_frontend.ps1",
            "ops/verify_operations_staging.ps1",
            "ops/verify_operations_roles_staging.ps1",
            "CURRENT_DEVELOPMENT_STATUS.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_learning_evidence_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda" / "glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"automatic_activation": False',
                    '"automatic_activation": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_learning_evidence_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_repository_baseline_has_no_detected_drift(self):
        report = AUDIT.run_audit(ROOT)
        self.assertEqual(report["overall_status"], "PASS")
        self.assertEqual(report["summary"]["drift"], 0)

    def test_new_evaluation_and_runtime_capabilities_are_declared(self):
        contract = AUDIT.load_contract(ROOT)
        capability_ids = {item["id"] for item in contract["capabilities"]}
        self.assertTrue(
            {
                "external_evidence_ablation",
                "decision_memory_ablation",
                "governed_agent_runtime_parity",
                "agent_runtime_host_registry",
                "agent_runtime_input_bundle",
                "agent_runtime_host_trace",
                "agent_runtime_adapter_conformance",
                "action_outcome_evidence_chain",
                "outcome_learning_evidence_gate",
            }
            <= capability_ids
        )

    def test_external_evidence_operational_authority_drift_is_detected(self):
        paths = (
            "ops/evaluate_external_evidence_capability.py",
            "tests/fixtures/evaluation/external_evidence_ablation_v1.json",
            "docs/evaluation_experiment_v2.schema.json",
            "docs/evaluation_architecture.md",
            "docs/temporal_truthfulness.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            manifest_path = root / paths[1]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["execution_boundary"]["operational_writes_allowed"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = AUDIT.check_capability_neutral_evaluation_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_agent_runtime_approval_authority_drift_is_detected(self):
        paths = (
            "ops/run_governed_agent_runtime.py",
            "tests/fixtures/evaluation/agent_runtime_parity_v1.json",
            "docs/agent_runtime_experiment_v1.schema.json",
            "docs/agent_runtime_host_registry_v1.json",
            "docs/agent_runtime_host_registry_v1.schema.json",
            "docs/agent_runtime_input_bundle_v1.schema.json",
            "docs/agent_runtime_host_trace_v1.schema.json",
            "ops/agent_runtime_adapters/reference_adapter_v1.py",
            "ops/agent_runtime_adapters/independent_adapter_v1.py",
            "docs/evaluation_architecture.md",
            "docs/architecture_current.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            manifest_path = root / paths[1]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["runtime_contract"]["tools"]["request_approval"]["mode"] = (
                "OPERATIONAL_APPROVAL"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            results = AUDIT.check_agent_runtime_boundary(root)
        self.assertTrue(all(item.status == "DRIFT" for item in results))

    def test_agent_runtime_registry_source_drift_is_detected(self):
        paths = (
            "ops/run_governed_agent_runtime.py",
            "tests/fixtures/evaluation/agent_runtime_parity_v1.json",
            "docs/agent_runtime_experiment_v1.schema.json",
            "docs/agent_runtime_host_registry_v1.json",
            "docs/agent_runtime_host_registry_v1.schema.json",
            "docs/agent_runtime_input_bundle_v1.schema.json",
            "docs/agent_runtime_host_trace_v1.schema.json",
            "ops/agent_runtime_adapters/reference_adapter_v1.py",
            "ops/agent_runtime_adapters/independent_adapter_v1.py",
            "docs/evaluation_architecture.md",
            "docs/architecture_current.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            adapter = root / "ops/agent_runtime_adapters/independent_adapter_v1.py"
            adapter.write_text(
                adapter.read_text(encoding="utf-8") + "\n# unregistered drift\n",
                encoding="utf-8",
            )
            results = AUDIT.check_agent_runtime_boundary(root)
        registry = next(
            item
            for item in results
            if item.check_id == "agent_runtime_host_registry_boundary"
        )
        self.assertEqual(registry.status, "DRIFT")

    def test_adapter_conformance_authority_drift_is_detected(self):
        paths = (
            "ops/verify_agent_runtime_adapter_package.py",
            "ops/run_governed_agent_runtime.py",
            "tests/test_agent_runtime_adapter_conformance.py",
            "tests/fixtures/evaluation/adapter_conformance_v1/package.json",
            "tests/fixtures/evaluation/adapter_conformance_v1/adapter.py",
            "tests/fixtures/evaluation/adapter_conformance_v1/input_bundle.json",
            "tests/fixtures/evaluation/adapter_conformance_v1/host_trace.json",
            "docs/agent_runtime_adapter_package_v1.schema.json",
            "docs/agent_runtime_input_bundle_v1.schema.json",
            "docs/agent_runtime_host_trace_v1.schema.json",
            "docs/evaluation_architecture.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            manifest_path = root / paths[3]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["execution_boundary"]["network_access_allowed"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = AUDIT.check_adapter_conformance_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

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
            (root / "DEVELOPMENT_PLAN.md").write_text(
                "approve/edit/reject/complete\n", encoding="utf-8"
            )
            (root / "CURRENT_DEVELOPMENT_STATUS.md").write_text(
                "Action assignment canary\n"
                "Operator `EDIT` recorded\n"
                "response fix release, stable retry, and separate approver decision remain\n",
                encoding="utf-8",
            )
            results = AUDIT.check_action_contract(root, contract)
        operation = next(item for item in results if item.check_id == "action_operations")
        self.assertEqual(operation.status, "DRIFT")

    def test_legacy_mixed_purpose_document_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "AGENTS.md": (
                    "## Documentation Operating Model\n"
                    "DEVELOPMENT_PLAN.md CURRENT_DEVELOPMENT_STATUS.md "
                    "docs/archive/status/\n"
                ),
                "DEVELOPMENT_PLAN.md": (
                    "## Product thesis\n## Delivery order\n## P3\n"
                ),
                "CURRENT_DEVELOPMENT_STATUS.md": (
                    "## Current product reality\n## Active slice\n"
                    "## Pending validation\n## Next Up\n"
                    "### Codex-run validation\n"
                    "### User-reported validation\n### Incomplete\n"
                ),
                "docs/archive/status/README.md": (
                    "This archive is not current authority.\n"
                ),
                "docs/archive/status/CHANGELOG.md": "# Changelog\n",
                "docs/archive/status/daily-logs/2026-08.md": "# Daily log\n",
            }
            for relative_path, content in paths.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            passing = AUDIT.check_documentation_operating_model(root)[0]
            self.assertEqual(passing.status, "PASS")
            (root / "TODO.md").write_text("mixed authority\n", encoding="utf-8")
            drifting = AUDIT.check_documentation_operating_model(root)[0]
        self.assertEqual(drifting.status, "DRIFT")

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

    def test_action_mutation_release_scope_expansion_is_detected(self):
        source = json.loads(
            (
                ROOT
                / "docs"
                / "action_mutation_staging_release_contract.json"
            ).read_text(encoding="utf-8")
        )
        source["selected_design"]["changed_parameters"].append(
            "GeneratorArtifactKey"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = (
                root / "docs" / "action_mutation_staging_release_contract.json"
            )
            contract_path.parent.mkdir(parents=True)
            contract_path.write_text(json.dumps(source), encoding="utf-8")
            proposal_source = (
                ROOT
                / "docs"
                / "action_mutation_staging_read_permission_proposal.json"
            ).read_text(encoding="utf-8")
            (root / "docs" / "action_mutation_staging_read_permission_proposal.json").write_text(
                proposal_source, encoding="utf-8"
            )
            result = AUDIT.check_action_mutation_release(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_a303_outcome_human_preference_gate_is_detected(self):
        filenames = (
            "a303_outcome_simulator_v1.json",
            "a303_outcome_sensitivity_protocol_v1.json",
            "a303_synthetic_capability_gate_v1.json",
            "a303_synthetic_outcome_robustness_result_v1.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir(parents=True)
            for filename in filenames:
                source = json.loads(
                    (ROOT / "docs" / filename).read_text(encoding="utf-8")
                )
                if filename == "a303_synthetic_capability_gate_v1.json":
                    source["decision_quality_handling"][
                        "human_preference_controls_simulator_eligibility"
                    ] = True
                (root / "docs" / filename).write_text(
                    json.dumps(source), encoding="utf-8"
                )
            result = AUDIT.check_a303_outcome_robustness_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_a303_calibration_evidence_expansion_is_detected(self):
        source = json.loads(
            (ROOT / "docs" / "a303_outcome_calibration_policy_v1.json").read_text(
                encoding="utf-8"
            )
        )
        source["eligible_evidence"]["controlled_pair"].append(
            "SIMULATED_COUNTERFACTUAL"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "docs" / "a303_outcome_calibration_policy_v1.json"
            contract_path.parent.mkdir(parents=True)
            contract_path.write_text(json.dumps(source), encoding="utf-8")
            result = AUDIT.check_a303_outcome_calibration_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_a303_v2_post_hoc_candidate_cannot_claim_confirmation(self):
        filenames = (
            "a303_v2_eligibility_guardrail_proposal.json",
            "a303_v2_guardrail_development_result_v1.json",
            "a303_synthetic_outcome_robustness_result_v1.json",
            "a303_outcome_simulator_v1.json",
            "a303_outcome_sensitivity_protocol_v1.json",
            "a303_synthetic_capability_gate_v1.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir(parents=True)
            for filename in filenames:
                source = json.loads(
                    (ROOT / "docs" / filename).read_text(encoding="utf-8")
                )
                if filename == "a303_v2_eligibility_guardrail_proposal.json":
                    source["validation_boundary"][
                        "same_corpus_can_satisfy_confirmatory_gate"
                    ] = True
                (root / "docs" / filename).write_text(
                    json.dumps(source), encoding="utf-8"
                )
            result = AUDIT.check_a303_v2_guardrail_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_a303_v1_retirement_cannot_be_reopened_by_drift(self):
        filenames = (
            "a303_v1_retirement_decision.json",
            "a303_synthetic_outcome_robustness_result_v1.json",
            "a303_v2_guardrail_development_result_v1.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir(parents=True)
            for filename in filenames:
                source = json.loads(
                    (ROOT / "docs" / filename).read_text(encoding="utf-8")
                )
                if filename == "a303_v1_retirement_decision.json":
                    source["reopening_rule"]["a303_v1_may_be_reactivated"] = True
                (root / "docs" / filename).write_text(
                    json.dumps(source), encoding="utf-8"
                )
            result = AUDIT.check_a303_v1_retirement_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_json_report_is_serializable(self):
        report = AUDIT.run_audit(ROOT)
        encoded = json.dumps(report)
        self.assertIn("project-drift-report.v1", encoded)


if __name__ == "__main__":
    unittest.main()
