import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "governed_agent_runtime", ROOT / "ops" / "run_governed_agent_runtime.py"
)
runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(runtime)
FIXTURE = ROOT / "tests" / "fixtures" / "evaluation" / "agent_runtime_parity_v1.json"


def manifest():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class GovernedAgentRuntimeTests(unittest.TestCase):
    def test_schema_freezes_tools_budgets_redaction_and_authority(self):
        schema = json.loads(
            (ROOT / "docs" / "agent_runtime_experiment_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        runtime_contract = schema["$defs"]["runtimeContract"]["properties"]
        self.assertEqual(runtime_contract["authority_profile"]["const"], "EVALUATION_NO_MUTATION")
        self.assertEqual(runtime_contract["budgets"]["properties"]["max_tool_calls"]["const"], 4)
        self.assertFalse(runtime_contract["redaction"]["properties"]["credentials_allowed"]["const"])
        self.assertEqual(schema["$defs"]["approvalTool"]["properties"]["mode"]["const"], "SIMULATED_NO_AUTHORITY")

        trace_schema = json.loads(
            (ROOT / "docs" / "agent_runtime_host_trace_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        approval = trace_schema["properties"]["payload"]["properties"][
            "approval_result"
        ]["properties"]
        self.assertFalse(approval["authority_granted"]["const"])
        self.assertFalse(approval["operational_action_created"]["const"])

    def test_registered_hosts_receive_identical_inputs_tools_and_authority(self):
        report = runtime.run_experiment(manifest())
        self.assertEqual(report["host_parity"]["status"], "PASS")
        self.assertTrue(report["host_parity"]["identical_inputs"])
        self.assertTrue(report["host_parity"]["identical_tool_sequence"])
        self.assertTrue(report["host_parity"]["identical_authority"])
        self.assertEqual(report["hosts"][0]["input_bundle_sha256"], report["hosts"][1]["input_bundle_sha256"])

    def test_registry_freezes_distinct_local_implementation_paths(self):
        registry = runtime.load_adapter_registry(ROOT)
        registrations = registry["registrations"]
        self.assertEqual(len({item["module_path"] for item in registrations}), 2)
        self.assertEqual(len({item["implementation_group"] for item in registrations}), 2)
        self.assertEqual(len({item["source_sha256"] for item in registrations}), 2)
        report = runtime.run_experiment(manifest())
        self.assertTrue(report["host_parity"]["distinct_implementation_paths"])
        self.assertTrue(report["host_parity"]["registry_source_integrity"])

    def test_registry_schema_freezes_local_no_mutation_boundary(self):
        schema = json.loads(
            (ROOT / "docs" / "agent_runtime_host_registry_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        boundary = schema["properties"]["execution_boundary"]["properties"]
        self.assertFalse(boundary["network_access_allowed"]["const"])
        self.assertFalse(boundary["operational_writes_allowed"]["const"])
        self.assertFalse(boundary["dynamic_dependency_install_allowed"]["const"])

    def test_registry_rejects_source_tampering(self):
        registry_path = "docs/agent_runtime_host_registry_v1.json"
        adapter_paths = tuple(
            item["module_path"] for item in runtime.load_adapter_registry(ROOT)["registrations"]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative_path in (registry_path, *adapter_paths):
                target = root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative_path, target)
            changed = root / adapter_paths[1]
            changed.write_text(
                changed.read_text(encoding="utf-8")
                + "\ndef forbidden_operation():\n    return open('forbidden.txt')\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(runtime.ContractError, "source digest mismatch"):
                runtime.load_adapter_registry(root)
            registry_file = root / registry_path
            registry = json.loads(registry_file.read_text(encoding="utf-8"))
            registry["registrations"][1]["source_sha256"] = runtime._source_sha256(
                changed
            )
            registry_file.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(runtime.ContractError, "non-allowlisted call"):
                runtime.load_adapter_registry(root)

    def test_registry_rejects_authority_expansion(self):
        registry = runtime.load_adapter_registry(ROOT)
        changed = copy.deepcopy(registry)
        changed["execution_boundary"]["network_access_allowed"] = True
        with self.assertRaisesRegex(runtime.ContractError, "execution boundary is unsupported"):
            runtime.validate_adapter_registry(changed, ROOT)

    def test_input_bundle_freezes_complete_cutoff_inputs_and_runtime_envelope(self):
        bundle = runtime.build_input_bundle(manifest())
        runtime.verify_input_bundle(bundle)
        payload = bundle["payload"]
        self.assertEqual(
            [item["evidence_id"] for item in payload["cutoff_inputs"]["evidence"]],
            ["external-disruption-v1", "operational-watch-v1"],
        )
        self.assertEqual(
            [item["memory_id"] for item in payload["cutoff_inputs"]["decision_memory"]],
            ["matching-reviewed-memory-v1"],
        )
        self.assertEqual(
            payload["runtime_envelope"]["enabled_capabilities"],
            ["DECISION_MEMORY", "EXTERNAL_EVIDENCE"],
        )

    def test_input_bundle_is_order_independent_but_content_sensitive(self):
        original = manifest()
        reordered = copy.deepcopy(original)
        reordered["scenario"]["evidence"].reverse()
        reordered["scenario"]["decision_memory"].reverse()
        first = runtime.build_input_bundle(original)
        second = runtime.build_input_bundle(reordered)
        self.assertEqual(first["bundle_sha256"], second["bundle_sha256"])
        self.assertNotEqual(first["source_manifest_sha256"], second["source_manifest_sha256"])

        changed = copy.deepcopy(original)
        changed["scenario"]["evidence"][1]["severity"] = "MEDIUM"
        third = runtime.build_input_bundle(changed)
        self.assertNotEqual(first["bundle_sha256"], third["bundle_sha256"])

    def test_input_bundle_detects_payload_tampering(self):
        bundle = runtime.build_input_bundle(manifest())
        changed = copy.deepcopy(bundle)
        changed["payload"]["runtime_envelope"]["authority_profile"] = "OPERATIONAL"
        with self.assertRaisesRegex(runtime.ContractError, "authority is unsupported"):
            runtime.verify_input_bundle(changed)

        changed = copy.deepcopy(bundle)
        changed["payload"]["scenario"]["context_key"] = "CONTROLLED_CONTEXT_CHANGED"
        with self.assertRaisesRegex(runtime.ContractError, "payload digest mismatch"):
            runtime.verify_input_bundle(changed)

        changed = copy.deepcopy(bundle)
        changed["payload"]["cutoff_inputs"]["evidence"][0]["severity"] = "CRITICAL"
        changed["bundle_sha256"] = runtime._sha256(changed["payload"])
        with self.assertRaisesRegex(runtime.ContractError, "severity is unsupported"):
            runtime.verify_input_bundle(changed)

    def test_report_embeds_the_verified_bundle_and_hosts_bind_to_it(self):
        report = runtime.run_experiment(manifest())
        runtime.verify_input_bundle(report["input_bundle"])
        digest = report["input_bundle"]["bundle_sha256"]
        self.assertTrue(all(host["input_bundle_sha256"] == digest for host in report["hosts"]))
        self.assertEqual(len(report["host_traces"]), 2)
        for trace in report["host_traces"]:
            runtime.verify_host_trace(report["input_bundle"], trace)
            self.assertEqual(trace["payload"]["input_bundle_sha256"], digest)
            self.assertRegex(trace["payload"]["host"]["source_sha256"], r"^[a-f0-9]{64}$")

    def test_host_trace_detects_tool_order_and_result_set_tampering(self):
        report = runtime.run_experiment(manifest())
        bundle = report["input_bundle"]
        trace = report["host_traces"][0]

        changed = copy.deepcopy(trace)
        changed["payload"]["tool_calls"][0], changed["payload"]["tool_calls"][1] = (
            changed["payload"]["tool_calls"][1],
            changed["payload"]["tool_calls"][0],
        )
        changed["trace_sha256"] = runtime._sha256(changed["payload"])
        with self.assertRaisesRegex(runtime.ContractError, "tool sequence is invalid"):
            runtime.verify_host_trace(bundle, changed)

        changed = copy.deepcopy(trace)
        changed["payload"]["tool_calls"][0]["result_ids"].append(
            "post-cutoff-recovery-v1"
        )
        changed["trace_sha256"] = runtime._sha256(changed["payload"])
        with self.assertRaisesRegex(runtime.ContractError, "result IDs do not match"):
            runtime.verify_host_trace(bundle, changed)

    def test_host_trace_detects_proposal_approval_and_digest_tampering(self):
        report = runtime.run_experiment(manifest())
        bundle = report["input_bundle"]
        trace = report["host_traces"][0]

        changed = copy.deepcopy(trace)
        changed["payload"]["proposal"]["priority"] = "MEDIUM"
        changed["trace_sha256"] = runtime._sha256(changed["payload"])
        with self.assertRaisesRegex(runtime.ContractError, "proposal does not replay"):
            runtime.verify_host_trace(bundle, changed)

        changed = copy.deepcopy(trace)
        changed["payload"]["approval_result"]["authority_granted"] = True
        changed["trace_sha256"] = runtime._sha256(changed["payload"])
        with self.assertRaisesRegex(runtime.ContractError, "approval result is unsupported"):
            runtime.verify_host_trace(bundle, changed)

        changed = copy.deepcopy(trace)
        changed["trace_sha256"] = "0" * 64
        with self.assertRaisesRegex(runtime.ContractError, "payload digest mismatch"):
            runtime.verify_host_trace(bundle, changed)

    def test_host_trace_accepts_a_safe_future_adapter_identity_but_not_another_bundle(self):
        report = runtime.run_experiment(manifest())
        bundle = report["input_bundle"]
        trace = copy.deepcopy(report["host_traces"][0])
        trace["payload"]["host"]["adapter_version"] = "offline-candidate-adapter.v1"
        trace["trace_sha256"] = runtime._sha256(trace["payload"])
        runtime.verify_host_trace(bundle, trace)

        other_manifest = manifest()
        other_manifest["scenario"]["evidence"][1]["severity"] = "MEDIUM"
        other_bundle = runtime.build_input_bundle(other_manifest)
        with self.assertRaisesRegex(runtime.ContractError, "input bundle digest mismatch"):
            runtime.verify_host_trace(other_bundle, trace)

    def test_approval_is_simulated_and_never_creates_an_action(self):
        report = runtime.run_experiment(manifest())
        for host in report["hosts"]:
            self.assertEqual(host["approval_result"]["status"], "SIMULATED_PENDING_HUMAN_REVIEW")
            self.assertFalse(host["approval_result"]["authority_granted"])
            self.assertFalse(host["approval_result"]["operational_action_created"])
            self.assertEqual(host["operational_mutations"], [])

    def test_post_cutoff_inputs_are_excluded_from_both_hosts(self):
        report = runtime.run_experiment(manifest())
        self.assertEqual(report["input_window"]["post_cutoff_evidence_ids"], ["post-cutoff-recovery-v1"])
        self.assertEqual(report["input_window"]["post_cutoff_memory_ids"], ["post-cutoff-memory-v1"])
        rendered = json.dumps(report["hosts"])
        self.assertNotIn("post-cutoff-recovery-v1", rendered)
        self.assertNotIn("post-cutoff-memory-v1", rendered)
        bundle = json.dumps(report["input_bundle"])
        self.assertNotIn("post-cutoff-recovery-v1", bundle)
        self.assertNotIn("post-cutoff-memory-v1", bundle)

    def test_runtime_is_deterministic_and_does_not_claim_host_quality(self):
        first = runtime.run_experiment(manifest())
        second = runtime.run_experiment(manifest())
        self.assertEqual(first, second)
        self.assertIn("HOST_QUALITY_SUPERIORITY", first["claim_boundary"]["not_supported"])
        self.assertEqual(first["evaluation_layers"]["decision_quality"]["status"], "NOT_EVALUATED")
        self.assertEqual(first["evaluation_layers"]["capability_attribution"]["status"], "NOT_EVALUATED")

    def test_manifest_fails_closed_if_approval_gains_authority(self):
        changed = copy.deepcopy(manifest())
        changed["runtime_contract"]["tools"]["request_approval"]["mode"] = "OPERATIONAL_APPROVAL"
        with self.assertRaisesRegex(runtime.ContractError, "request_approval mode is unsupported"):
            runtime.run_experiment(changed)

    def test_manifest_fails_closed_if_host_capabilities_differ(self):
        changed = copy.deepcopy(manifest())
        changed["hosts"][1]["enabled_capabilities"] = ["EXTERNAL_EVIDENCE"]
        with self.assertRaisesRegex(runtime.ContractError, "identical frozen capability set"):
            runtime.run_experiment(changed)

    def test_manifest_fails_closed_if_budget_is_widened(self):
        changed = copy.deepcopy(manifest())
        changed["runtime_contract"]["budgets"]["max_tool_calls"] = 5
        with self.assertRaisesRegex(runtime.ContractError, "frozen v1 budget"):
            runtime.run_experiment(changed)

    def test_manifest_fails_closed_if_cutoff_eligible_inputs_exceed_budget(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["evidence"][2]["available_at"] = "2025-03-07T08:15:00+11:00"
        with self.assertRaisesRegex(runtime.ContractError, "input bundle evidence exceeds the v1 budget"):
            runtime.run_experiment(changed)

    def test_manifest_fails_closed_if_memory_attaches_outcome_evidence(self):
        changed = copy.deepcopy(manifest())
        changed["scenario"]["decision_memory"][0]["outcome_evidence_class"] = "OBSERVED_FACTUAL"
        with self.assertRaisesRegex(runtime.ContractError, "cannot attach Outcome evidence"):
            runtime.run_experiment(changed)


if __name__ == "__main__":
    unittest.main()
