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
            "INFRASTRUCTURE.md",
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

    def test_action_outcome_infrastructure_maturity_drift_is_detected(self):
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
            "INFRASTRUCTURE.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_action_outcome_evidence_chain_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            infrastructure_path = root / "INFRASTRUCTURE.md"
            infrastructure_path.write_text(
                infrastructure_path.read_text(encoding="utf-8").replace(
                    "32621697316",
                    "release-run-missing",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_action_outcome_evidence_chain_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_decision_truth_rollout_execution_authority_drift_is_detected(self):
        paths = (
            "sql/16_decision_action_binding_v1.sql",
            "sql/17_decision_action_binding_validation.sql",
            "ops/plan_decision_truth_staging_rollout.ps1",
            ".github/workflows/deploy-stateful-lifecycle-staging.yml",
            ".github/workflows/refactor-stateful-lifecycle-generator-staging.yml",
            "ops/deploy_stateful_lifecycle_stack.ps1",
            "ops/deploy_stateful_lifecycle_generator_stack.ps1",
            "ops/refactor_stateful_lifecycle_generator_stack.ps1",
            "infrastructure/stateful-lifecycle-generator-staging.yaml",
            "tests/test_decision_truth_staging_rollout.py",
            "tests/test_stateful_lifecycle_deployment.py",
            "docs/decision_truth_staging_rollout.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_decision_truth_staging_rollout_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            plan_path = root / "ops/plan_decision_truth_staging_rollout.ps1"
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8").replace(
                    "Operational continuation authorized: False",
                    "Operational continuation authorized: True",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_truth_staging_rollout_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_cost_anomaly_decision_brief_rate_card_honesty_drift_is_detected(self):
        paths = (
            "lambda/glap_governed_closed_loop.py",
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/cost_anomaly_decision_brief_v1.md",
            "tests/test_governed_closed_loop.py",
            "tests/test_lifecycle_athena_adapter.py",
            "tests/test_operations_api.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_cost_anomaly_decision_brief_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"rate_card_version": None',
                    '"rate_card_version": "invented-rate-card"',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_cost_anomaly_decision_brief_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_cost_anomaly_runtime_reconciler_mutation_drift_is_detected(self):
        paths = (
            "ops/reconcile_cost_anomaly_runtime_staging.ps1",
            "tests/test_cost_anomaly_runtime_evidence.py",
            "docs/cost_anomaly_runtime_evidence_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_cost_anomaly_runtime_evidence_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            reconciler_path = root / "ops/reconcile_cost_anomaly_runtime_staging.ps1"
            reconciler_path.write_text(
                reconciler_path.read_text(encoding="utf-8")
                + "\n# INSERT INTO protected_table\n",
                encoding="utf-8",
            )
            detected = AUDIT.check_cost_anomaly_runtime_evidence_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_sla_breach_runtime_reconciler_mutation_drift_is_detected(self):
        paths = (
            "ops/reconcile_sla_breach_runtime_staging.ps1",
            "tests/test_sla_breach_runtime_evidence.py",
            "docs/sla_breach_runtime_evidence_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_sla_breach_runtime_evidence_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            reconciler_path = root / "ops/reconcile_sla_breach_runtime_staging.ps1"
            reconciler_path.write_text(
                reconciler_path.read_text(encoding="utf-8")
                + "\n# UPDATE protected_table\n",
                encoding="utf-8",
            )
            detected = AUDIT.check_sla_breach_runtime_evidence_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_sla_outcome_provenance_readiness_mutation_drift_is_detected(self):
        paths = (
            "ops/audit_sla_outcome_provenance_readiness_staging.ps1",
            "tests/test_sla_outcome_provenance_readiness.py",
            "docs/sla_outcome_provenance_readiness_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_sla_outcome_provenance_readiness_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            audit_path = root / paths[0]
            audit_path.write_text(
                audit_path.read_text(encoding="utf-8")
                + "\n# INSERT INTO protected_table\n",
                encoding="utf-8",
            )
            detected = AUDIT.check_sla_outcome_provenance_readiness_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_sla_decision_review_handoff_binding_drift_is_detected(self):
        paths = (
            "decision-brief-demo/app/decision-review-handoff.ts",
            "decision-brief-demo/app/page.tsx",
            "decision-brief-demo/tests/rendered-html.test.mjs",
            "docs/sla_decision_review_handoff_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_sla_decision_review_handoff_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            resolver_path = root / paths[0]
            resolver_path.write_text(
                resolver_path.read_text(encoding="utf-8").replace(
                    "matchingRisks.length !== 1",
                    "matchingRisks.length > 1",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_sla_decision_review_handoff_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_decision_queue_discovery_waiting_boundary_drift_is_detected(self):
        paths = (
            "decision-brief-demo/app/decision-queue-filter.ts",
            "decision-brief-demo/app/page.tsx",
            "decision-brief-demo/tests/rendered-html.test.mjs",
            "docs/decision_queue_discovery_controls_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_decision_queue_discovery_controls_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            filter_path = root / paths[0]
            filter_path.write_text(
                filter_path.read_text(encoding="utf-8").replace(
                    'action.status === "PROPOSED" || action.status === "EDITED"',
                    'action.status !== "REJECTED"',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_queue_discovery_controls_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_decision_truth_generator_release_scope_drift_is_detected(self):
        paths = (
            "sql/16_decision_action_binding_v1.sql",
            "sql/17_decision_action_binding_validation.sql",
            "ops/plan_decision_truth_staging_rollout.ps1",
            ".github/workflows/deploy-stateful-lifecycle-staging.yml",
            ".github/workflows/refactor-stateful-lifecycle-generator-staging.yml",
            "ops/deploy_stateful_lifecycle_stack.ps1",
            "ops/deploy_stateful_lifecycle_generator_stack.ps1",
            "ops/refactor_stateful_lifecycle_generator_stack.ps1",
            "infrastructure/stateful-lifecycle-generator-staging.yaml",
            "tests/test_decision_truth_staging_rollout.py",
            "tests/test_stateful_lifecycle_deployment.py",
            "docs/decision_truth_staging_rollout.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_decision_truth_staging_rollout_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            workflow_path = (
                root / ".github/workflows/"
                "refactor-stateful-lifecycle-generator-staging.yml"
            )
            original_workflow = workflow_path.read_text(encoding="utf-8")
            workflow_path.write_text(
                original_workflow.replace(
                    "default: inspect-refactor",
                    "default: execute-refactor",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_truth_staging_rollout_boundary(root)[0]
            self.assertEqual(detected.status, "DRIFT")
            workflow_path.write_text(original_workflow, encoding="utf-8")
            template_path = (
                root / "infrastructure/stateful-lifecycle-generator-staging.yaml"
            )
            original_template = template_path.read_text(encoding="utf-8")
            template_path.write_text(
                original_template + "\nParameters:\n  Unsafe:\n    Type: String\n",
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_truth_staging_rollout_boundary(root)[0]
            self.assertEqual(detected.status, "DRIFT")
            template_path.write_text(original_template, encoding="utf-8")
            refactor_path = (
                root / "ops/refactor_stateful_lifecycle_generator_stack.ps1"
            )
            original_refactor = refactor_path.read_text(encoding="utf-8")
            refactor_path.write_text(
                original_refactor.replace(
                    "$stackCreates.Count -ne 1",
                    "$stackCreates.Count -lt 1",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_truth_staging_rollout_boundary(root)[0]
            self.assertEqual(detected.status, "DRIFT")
            refactor_path.write_text(original_refactor, encoding="utf-8")
            deployer_path = (
                root / "ops/deploy_stateful_lifecycle_generator_stack.ps1"
            )
            deployer_path.write_text(
                deployer_path.read_text(encoding="utf-8").replace(
                    "$changes.Count -ne 1",
                    "$changes.Count -lt 1",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_truth_staging_rollout_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_decision_provenance_causal_claim_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/outcome_review_decision_provenance_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_decision_provenance_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            contract_path = root / "docs/outcome_review_decision_provenance_v1.md"
            contract_path.write_text(
                contract_path.read_text(encoding="utf-8").replace(
                    "establish traceability, not causality",
                    "establish causal impact",
                ),
                encoding="utf-8",
            )
            causal_detected = AUDIT.check_outcome_decision_provenance_boundary(root)[0]
            self.assertEqual(causal_detected.status, "DRIFT")
            self._copy_paths(root, paths)
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    "ThreadPoolExecutor(max_workers=2",
                    "ThreadPoolExecutor(max_workers=3",
                ),
                encoding="utf-8",
            )
            concurrency_detected = (
                AUDIT.check_outcome_decision_provenance_boundary(root)[0]
            )
        self.assertEqual(causal_detected.status, "DRIFT")
        self.assertEqual(concurrency_detected.status, "DRIFT")

    def test_decision_contract_outcome_cohort_authority_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/decision_contract_outcome_cohort_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_decision_contract_outcome_cohort_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"causal_effect_estimate": False',
                    '"causal_effect_estimate": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_contract_outcome_cohort_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_sufficiency_automatic_threshold_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/outcome_cohort_evidence_sufficiency_v1.md",
            "docs/outcome_cohort_threshold_contract_v1.json",
            "docs/outcome_cohort_threshold_contract_v1.schema.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_evidence_sufficiency_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"automatic_threshold_selection": False',
                    '"automatic_threshold_selection": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_evidence_sufficiency_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_approved_threshold_contract_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/outcome_cohort_evidence_sufficiency_v1.md",
            "docs/outcome_cohort_threshold_contract_v1.json",
            "docs/outcome_cohort_threshold_contract_v1.schema.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            contract_path = root / "docs/outcome_cohort_threshold_contract_v1.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["thresholds"]["minimum_observed_outcomes"] = 21
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            detected = AUDIT.check_outcome_cohort_evidence_sufficiency_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_evidence_gap_authority_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/outcome_cohort_evidence_gap_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_evidence_gap_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"outcome_creation_authorized": False',
                    '"outcome_creation_authorized": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_evidence_gap_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_comparison_ranking_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/outcome_cohort_descriptive_comparison_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_descriptive_comparison_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"ranking_produced": False',
                    '"ranking_produced": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_descriptive_comparison_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_comparison_provenance_identifier_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/outcome_cohort_comparison_provenance_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_comparison_provenance_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"action_identifiers_exposed": False',
                    '"action_identifiers_exposed": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_comparison_provenance_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_comparison_fingerprint_trust_drift_is_detected(self):
        paths = (
            "lambda/glap_operations_api.py",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/outcome_cohort_comparison_fingerprint_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_comparison_fingerprint_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            api_path = root / "lambda/glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"source_authenticity_attested": False',
                    '"source_authenticity_attested": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_comparison_fingerprint_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_comparison_verifier_fail_closed_drift_is_detected(self):
        paths = (
            "decision-brief-demo/app/outcome-comparison-fingerprint.ts",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "decision-brief-demo/tests/rendered-html.test.mjs",
            "decision-brief-demo/package.json",
            "docs/outcome_cohort_comparison_verifier_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_comparison_verifier_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            verifier_path = (
                root
                / "decision-brief-demo/app/outcome-comparison-fingerprint.ts"
            )
            verifier_path.write_text(
                verifier_path.read_text(encoding="utf-8").replace(
                    "integrity.digital_signature === false",
                    "integrity.digital_signature !== false",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_comparison_verifier_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_comparison_diagnostic_collapse_is_detected(self):
        paths = (
            "decision-brief-demo/app/outcome-comparison-fingerprint.ts",
            "decision-brief-demo/app/page.tsx",
            "decision-brief-demo/app/operations.css",
            "decision-brief-demo/tests/rendered-html.test.mjs",
            "docs/outcome_cohort_comparison_diagnostics_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_comparison_diagnostics_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            verifier_path = (
                root
                / "decision-brief-demo/app/outcome-comparison-fingerprint.ts"
            )
            verifier_path.write_text(
                verifier_path.read_text(encoding="utf-8").replace(
                    'reason_code: "VERIFICATION_ERROR"',
                    'reason_code: "DIGEST_MISMATCH"',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_comparison_diagnostics_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_comparison_retry_scope_expansion_is_detected(self):
        paths = (
            "decision-brief-demo/app/outcome-comparison-fingerprint.ts",
            "decision-brief-demo/app/page.tsx",
            "decision-brief-demo/app/operations.css",
            "decision-brief-demo/tests/rendered-html.test.mjs",
            "docs/outcome_cohort_comparison_retry_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_comparison_retry_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            verifier_path = (
                root
                / "decision-brief-demo/app/outcome-comparison-fingerprint.ts"
            )
            verifier_path.write_text(
                verifier_path.read_text(encoding="utf-8").replace(
                    '"VERIFICATION_ERROR",\n]);',
                    '"VERIFICATION_ERROR",\n  "DIGEST_MISMATCH",\n]);',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_comparison_retry_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_outcome_cohort_comparison_envelope_authority_drift_is_detected(self):
        paths = (
            "decision-brief-demo/app/outcome-comparison-envelope.ts",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/tests/rendered-html.test.mjs",
            "docs/outcome_cohort_comparison_envelope_validator_v1.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_outcome_cohort_comparison_envelope_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            validator_path = (
                root
                / "decision-brief-demo/app/outcome-comparison-envelope.ts"
            )
            validator_path.write_text(
                validator_path.read_text(encoding="utf-8").replace(
                    "governance.action_recommended !== false",
                    "governance.action_recommended === false",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_outcome_cohort_comparison_envelope_boundary(root)[0]
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

    def test_production_readiness_evidence_maturity_drift_is_detected(self):
        paths = (
            "docs/production_readiness_contract.json",
            "docs/operations_production_readiness_evidence_v1.json",
            "docs/operations_production_readiness_evidence_v1.schema.json",
            "ops/evaluate_operations_production_readiness.py",
            "docs/operations_authenticated_read_load_plan_v1.json",
            "docs/operations_authenticated_read_load_plan_v1.schema.json",
            "docs/operations_authenticated_read_load_baseline_v1.schema.json",
            "ops/validate_operations_authenticated_read_load_plan.py",
            "ops/simulate_operations_authenticated_read_load.py",
            "ops/run_operations_authenticated_read_load_staging.ps1",
            "tests/test_operations_authenticated_read_load_plan.py",
            "tests/test_operations_authenticated_read_load_simulator.py",
            "tests/test_operations_authenticated_read_load_runner.py",
            "tests/test_operations_production_readiness.py",
            "docs/athena_cost_governance.md",
            "docs/incremental_refresh_contract.md",
            "docs/data_governance_operations.md",
            "docs/operations_api_v1.md",
            "docs/runbooks/operations_api_reliability.md",
            "CURRENT_DEVELOPMENT_STATUS.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_readiness_contract(root)[0]
            self.assertEqual(current.status, "PASS")
            evidence_path = (
                root / "docs" / "operations_production_readiness_evidence_v1.json"
            )
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["summary"]["production_readiness"] = True
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            detected = AUDIT.check_readiness_contract(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_authenticated_read_load_authority_and_diagnostic_drift_are_detected(self):
        paths = (
            "docs/production_readiness_contract.json",
            "docs/operations_production_readiness_evidence_v1.json",
            "docs/operations_production_readiness_evidence_v1.schema.json",
            "ops/evaluate_operations_production_readiness.py",
            "docs/operations_authenticated_read_load_plan_v1.json",
            "docs/operations_authenticated_read_load_plan_v1.schema.json",
            "docs/operations_authenticated_read_load_baseline_v1.schema.json",
            "ops/validate_operations_authenticated_read_load_plan.py",
            "ops/simulate_operations_authenticated_read_load.py",
            "ops/run_operations_authenticated_read_load_staging.ps1",
            "tests/test_operations_authenticated_read_load_plan.py",
            "tests/test_operations_authenticated_read_load_simulator.py",
            "tests/test_operations_authenticated_read_load_runner.py",
            "tests/test_operations_production_readiness.py",
            "docs/athena_cost_governance.md",
            "docs/incremental_refresh_contract.md",
            "docs/data_governance_operations.md",
            "docs/operations_api_v1.md",
            "docs/runbooks/operations_api_reliability.md",
            "CURRENT_DEVELOPMENT_STATUS.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_readiness_contract(root)[0]
            self.assertEqual(current.status, "PASS")
            plan_path = root / "docs" / "operations_authenticated_read_load_plan_v1.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["authorization"]["staging_load_run_authorized"] = True
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            authority_detected = AUDIT.check_readiness_contract(root)[0]

            plan["authorization"]["staging_load_run_authorized"] = False
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            self.assertEqual(AUDIT.check_readiness_contract(root)[0].status, "PASS")
            runner_path = (
                root / "ops" / "run_operations_authenticated_read_load_staging.ps1"
            )
            runner_path.write_text(
                runner_path.read_text(encoding="utf-8").replace(
                    "Redacted per-route latency diagnostic",
                    "Route latency details",
                ),
                encoding="utf-8",
            )
            diagnostic_detected = AUDIT.check_readiness_contract(root)[0]
        self.assertEqual(authority_detected.status, "DRIFT")
        self.assertEqual(diagnostic_detected.status, "DRIFT")

    def test_public_claim_truth_mapping_drift_is_detected(self):
        paths = (
            "docs/public_claim_manifest_v1.json",
            "ops/validate_public_claims.py",
            "tests/test_public_claims.py",
            "decision-brief-demo/app/page.tsx",
            "offline/glap-demo.html",
            "README.md",
            "docs/case_study_port_disruption.md",
            "docs/architecture_current.md",
            "docs/ops_snapshot.md",
            "DEVELOPMENT_PLAN.md",
            "CURRENT_DEVELOPMENT_STATUS.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_public_claim_truth(root)[0]
            self.assertEqual(current.status, "PASS")
            page = root / "decision-brief-demo/app/page.tsx"
            page.write_text(
                page.read_text(encoding="utf-8").replace(
                    'data-claim-id="next-outcomes-summary"',
                    'data-claim-id="unsupported-outcomes-summary"',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_public_claim_truth(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_stateful_cross_gap_recovery_maturity_cannot_regress(self):
        paths = (
            "docs/project_drift_contract.json",
            "CURRENT_DEVELOPMENT_STATUS.md",
            "docs/architecture_current.md",
            "INFRASTRUCTURE.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            contract = AUDIT.load_contract(root)
            current = AUDIT.check_stateful_recovery_evidence_boundary(root, contract)[0]
            self.assertEqual(current.status, "PASS")
            status_path = root / "CURRENT_DEVELOPMENT_STATUS.md"
            original_status = status_path.read_text(encoding="utf-8")
            status_path.write_text(
                original_status.replace("32671484061", "recovery-run-id-missing"),
                encoding="utf-8",
            )
            detected = AUDIT.check_stateful_recovery_evidence_boundary(root, contract)[0]
            self.assertEqual(detected.status, "DRIFT")
            status_path.write_text(
                original_status.replace("32672560594", "baseline-run-id-missing"),
                encoding="utf-8",
            )
            detected = AUDIT.check_stateful_recovery_evidence_boundary(root, contract)[0]
            self.assertEqual(detected.status, "DRIFT")
            status_path.write_text(
                original_status.replace("32682049141", "pages-run-id-missing"),
                encoding="utf-8",
            )
            detected = AUDIT.check_stateful_recovery_evidence_boundary(root, contract)[0]
            self.assertEqual(detected.status, "DRIFT")
            status_path.write_text(
                original_status.replace("32731582185", "latest-pages-run-missing"),
                encoding="utf-8",
            )
            detected = AUDIT.check_stateful_recovery_evidence_boundary(root, contract)[0]
            self.assertEqual(detected.status, "DRIFT")
            status_path.write_text(
                original_status.replace("32729202007", "latest-baseline-run-missing"),
                encoding="utf-8",
            )
            detected = AUDIT.check_stateful_recovery_evidence_boundary(root, contract)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_provider_label_readiness_authority_drift_is_detected(self):
        paths = (
            "docs/project_drift_contract.json",
            "lambda/glap_operations_api.py",
            "infrastructure/operations-api-staging.yaml",
            ".github/workflows/deploy-operations-api-staging.yml",
            "ops/configure_operations_api_discovery.ps1",
            "ops/configure_operations_api_data_access.ps1",
            "ops/deploy_internal_operations_frontend.ps1",
            "ops/verify_operations_staging.ps1",
            "ops/verify_operations_roles_staging.ps1",
            "decision-brief-demo/app/operations-api.ts",
            "decision-brief-demo/app/page.tsx",
            "docs/multimodal_forecast_feature_contract.md",
            "docs/temporal_truthfulness.md",
            "docs/operations_api_v1.md",
            "CURRENT_DEVELOPMENT_STATUS.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_provider_label_readiness_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            status_path = root / "CURRENT_DEVELOPMENT_STATUS.md"
            original_status = status_path.read_text(encoding="utf-8")
            status_path.write_text(
                original_status.replace("32809501684", "deploy-run-missing"),
                encoding="utf-8",
            )
            detected = AUDIT.check_provider_label_readiness_boundary(root)[0]
            self.assertEqual(detected.status, "DRIFT")
            status_path.write_text(original_status, encoding="utf-8")
            api_path = root / "lambda" / "glap_operations_api.py"
            api_path.write_text(
                api_path.read_text(encoding="utf-8").replace(
                    '"model_training_authorized": False',
                    '"model_training_authorized": True',
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_provider_label_readiness_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_deployed_evidence_maturity_requires_release_run(self):
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
            "INFRASTRUCTURE.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            status_path = root / "CURRENT_DEVELOPMENT_STATUS.md"
            status_path.write_text(
                status_path.read_text(encoding="utf-8").replace(
                    "32621697316",
                    "release-run-id-missing",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_action_outcome_evidence_chain_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

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
                "provider_label_readiness_dashboard",
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

    def test_action_evidence_refresh_reconciliation_cannot_be_hidden(self):
        source = json.loads(
            (ROOT / "docs" / "action_assignment_rollout_contract.json").read_text(
                encoding="utf-8"
            )
        )
        source["verified_release_evidence"][
            "evidence_refresh_interaction_canary_backend_reconciled"
        ] = False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "docs" / "action_assignment_rollout_contract.json"
            contract_path.parent.mkdir(parents=True)
            contract_path.write_text(json.dumps(source), encoding="utf-8")
            result = AUDIT.check_action_assignment_rollout(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_decision_quality_adjudication_resolution_drift_is_detected(self):
        paths = (
            "docs/decision_quality_adjudication_v1.schema.json",
            "docs/decision_quality_adjudication_cyclone_gabrielle_t1_v1.json",
            "docs/decision_quality_five_review_reconciliation_v1.schema.json",
            "docs/decision_quality_five_review_reconciliation_v1.json",
            "docs/decision_quality_five_review_corpus_summary_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_human_disposition_v1.schema.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "ops/validate_decision_quality_adjudication.py",
            "tests/test_decision_quality_adjudication.py",
            "blinded-review-survey/data/review-bundle.json",
            "docs/decision_quality_evaluation.md",
            "docs/architecture_current.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            record_path = (
                root
                / "docs"
                / "decision_quality_adjudication_cyclone_gabrielle_t1_v1.json"
            )
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["adjudication"]["status"] = "RESOLVED_HUMAN_ADJUDICATION"
            record["adjudication"]["resolution"] = "FAVORS_GLAP_A303_ON"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = AUDIT.check_decision_quality_adjudication_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_five_review_consensus_gate_expansion_is_detected(self):
        paths = (
            "docs/decision_quality_adjudication_v1.schema.json",
            "docs/decision_quality_adjudication_cyclone_gabrielle_t1_v1.json",
            "docs/decision_quality_five_review_reconciliation_v1.schema.json",
            "docs/decision_quality_five_review_reconciliation_v1.json",
            "docs/decision_quality_five_review_corpus_summary_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_human_disposition_v1.schema.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "ops/validate_decision_quality_adjudication.py",
            "tests/test_decision_quality_adjudication.py",
            "blinded-review-survey/data/review-bundle.json",
            "docs/decision_quality_evaluation.md",
            "docs/architecture_current.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            record_path = (
                root / "docs" / "decision_quality_five_review_reconciliation_v1.json"
            )
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["updated_result"]["result"] = "REVIEW_EVIDENCE_FAVORS_VARIANT"
            record["updated_result"]["favored_variant_id"] = "glap-a303-on"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = AUDIT.check_decision_quality_adjudication_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_five_review_full_corpus_count_drift_is_detected(self):
        paths = (
            "docs/decision_quality_adjudication_v1.schema.json",
            "docs/decision_quality_adjudication_cyclone_gabrielle_t1_v1.json",
            "docs/decision_quality_five_review_reconciliation_v1.schema.json",
            "docs/decision_quality_five_review_reconciliation_v1.json",
            "docs/decision_quality_five_review_corpus_summary_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_human_disposition_v1.schema.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "ops/validate_decision_quality_adjudication.py",
            "tests/test_decision_quality_adjudication.py",
            "blinded-review-survey/data/review-bundle.json",
            "docs/decision_quality_evaluation.md",
            "docs/architecture_current.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            record_path = (
                root / "docs" / "decision_quality_five_review_corpus_summary_v1.json"
            )
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["corpus_result"]["review_evidence_favors_variant_count"] = 15
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = AUDIT.check_decision_quality_adjudication_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_five_review_architecture_maturity_drift_is_detected(self):
        paths = (
            "docs/decision_quality_adjudication_v1.schema.json",
            "docs/decision_quality_adjudication_cyclone_gabrielle_t1_v1.json",
            "docs/decision_quality_five_review_reconciliation_v1.schema.json",
            "docs/decision_quality_five_review_reconciliation_v1.json",
            "docs/decision_quality_five_review_corpus_summary_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_human_disposition_v1.schema.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "ops/validate_decision_quality_adjudication.py",
            "tests/test_decision_quality_adjudication.py",
            "blinded-review-survey/data/review-bundle.json",
            "docs/decision_quality_evaluation.md",
            "docs/architecture_current.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            current = AUDIT.check_decision_quality_adjudication_boundary(root)[0]
            self.assertEqual(current.status, "PASS")
            architecture_path = root / "docs/architecture_current.md"
            architecture_path.write_text(
                architecture_path.read_text(encoding="utf-8").replace(
                    "Five compatible reviews per cutoff",
                    "Four compatible reviews per cutoff",
                ),
                encoding="utf-8",
            )
            detected = AUDIT.check_decision_quality_adjudication_boundary(root)[0]
        self.assertEqual(detected.status, "DRIFT")

    def test_five_review_human_disposition_winner_drift_is_detected(self):
        paths = (
            "docs/decision_quality_adjudication_v1.schema.json",
            "docs/decision_quality_adjudication_cyclone_gabrielle_t1_v1.json",
            "docs/decision_quality_five_review_reconciliation_v1.schema.json",
            "docs/decision_quality_five_review_reconciliation_v1.json",
            "docs/decision_quality_five_review_corpus_summary_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_human_disposition_v1.schema.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t1_v2.json",
            "docs/decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "ops/validate_decision_quality_adjudication.py",
            "tests/test_decision_quality_adjudication.py",
            "blinded-review-survey/data/review-bundle.json",
            "docs/decision_quality_evaluation.md",
            "docs/architecture_current.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            record_path = (
                root
                / "docs"
                / "decision_quality_human_disposition_cyclone_gabrielle_t2_v1.json"
            )
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["disposition"]["resolution"] = "FAVORS_GLAP_A303_ON"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = AUDIT.check_decision_quality_adjudication_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_action_complete_outcome_canary_authority_expansion_is_detected(self):
        paths = (
            "docs/action_complete_outcome_canary_v1.json",
            "docs/action_assignment_rollout_contract.json",
            "ops/validate_action_complete_outcome_canary.py",
            "ops/render_action_complete_outcome_canary_plan.py",
            "ops/preflight_action_complete_outcome_staging.ps1",
            "ops/reconcile_action_complete_staging.ps1",
            "ops/reconcile_pending_outcome_staging.ps1",
            "ops/check_observed_outcome_due_date.ps1",
            "ops/reconcile_observed_outcome_learning_staging.ps1",
            "tests/test_action_complete_outcome_canary.py",
            "lambda/glap_action_mutation.py",
            "lambda/glap_operations_api.py",
            "lambda/glap_governed_closed_loop.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            contract_path = root / "docs/action_complete_outcome_canary_v1.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["authority"]["named_human_complete_authorized"] = True
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            result = AUDIT.check_action_complete_outcome_canary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_public_evaluation_snapshot_boundary_and_authority_drift(self):
        paths = (
            "docs/public_evaluation_snapshot_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "blinded-review-survey/data/review-bundle.json",
            "ops/validate_decision_quality_adjudication.py",
            "ops/export_public_evaluation_snapshot.py",
            "offline/data/evaluation-snapshot.json",
            "offline/glap-demo.html",
            ".github/workflows/pages.yml",
            "tests/test_public_evaluation_snapshot.py",
            "tests/test_offline_demo.py",
            "docs/evaluation_architecture.md",
            "docs/ops_snapshot.md",
            "docs/temporal_truthfulness.md",
        )
        current = AUDIT.check_public_evaluation_snapshot_boundary(ROOT)[0]
        self.assertEqual(current.status, "PASS")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            snapshot_path = root / "offline" / "data" / "evaluation-snapshot.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["authority"]["action_mutation_allowed"] = True
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = AUDIT.check_public_evaluation_snapshot_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_public_evaluation_page_hardcoded_result_drift_is_detected(self):
        paths = (
            "docs/public_evaluation_snapshot_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "blinded-review-survey/data/review-bundle.json",
            "ops/validate_decision_quality_adjudication.py",
            "ops/export_public_evaluation_snapshot.py",
            "offline/data/evaluation-snapshot.json",
            "offline/glap-demo.html",
            ".github/workflows/pages.yml",
            "tests/test_public_evaluation_snapshot.py",
            "tests/test_offline_demo.py",
            "docs/evaluation_architecture.md",
            "docs/ops_snapshot.md",
            "docs/temporal_truthfulness.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            page_path = root / "offline" / "glap-demo.html"
            page = page_path.read_text(encoding="utf-8").replace(
                "Public aggregate only · snapshot unavailable",
                "Public aggregate only · 24 August 2026",
                1,
            )
            page_path.write_text(page, encoding="utf-8")
            result = AUDIT.check_public_evaluation_snapshot_boundary(root)[0]
        self.assertEqual(result.status, "DRIFT")

    def test_public_evaluation_pages_validation_gate_drift_is_detected(self):
        paths = (
            "docs/public_evaluation_snapshot_v1.schema.json",
            "docs/decision_quality_five_review_corpus_summary_v1.json",
            "docs/decision_quality_rubric_v1.json",
            "blinded-review-survey/data/review-bundle.json",
            "ops/validate_decision_quality_adjudication.py",
            "ops/export_public_evaluation_snapshot.py",
            "offline/data/evaluation-snapshot.json",
            "offline/glap-demo.html",
            ".github/workflows/pages.yml",
            "tests/test_public_evaluation_snapshot.py",
            "tests/test_offline_demo.py",
            "docs/evaluation_architecture.md",
            "docs/ops_snapshot.md",
            "docs/temporal_truthfulness.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_paths(root, paths)
            workflow_path = root / ".github" / "workflows" / "pages.yml"
            workflow = workflow_path.read_text(encoding="utf-8").replace(
                "python ops/export_public_evaluation_snapshot.py",
                "echo evaluation-validation-skipped",
            )
            workflow_path.write_text(workflow, encoding="utf-8")
            result = AUDIT.check_public_evaluation_snapshot_boundary(root)[0]
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
