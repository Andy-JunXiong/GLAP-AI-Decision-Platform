import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_runtime_adapter_conformance",
    ROOT / "ops" / "verify_agent_runtime_adapter_package.py",
)
conformance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(conformance)
FIXTURE = ROOT / "tests" / "fixtures" / "evaluation" / "adapter_conformance_v1"


class AgentRuntimeAdapterConformanceTests(unittest.TestCase):
    def package_copy(self, directory):
        target = Path(directory) / "package"
        shutil.copytree(FIXTURE, target)
        return target

    def test_fixture_passes_offline_conformance(self):
        report = conformance.verify_package(FIXTURE)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(value == "PASS" for value in report["checks"].values()))
        self.assertEqual(
            report["submitted_trace_sha256"], report["replay_trace_sha256"]
        )
        self.assertEqual(report["operational_mutations"], [])
        self.assertEqual(
            report["evaluation_layers"]["decision_quality"]["status"],
            "NOT_EVALUATED",
        )

    def test_schema_freezes_layout_authority_and_claim_boundary(self):
        schema = json.loads(
            (ROOT / "docs" / "agent_runtime_adapter_package_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        boundary = schema["properties"]["execution_boundary"]["properties"]
        self.assertFalse(boundary["network_access_allowed"]["const"])
        self.assertFalse(boundary["operational_writes_allowed"]["const"])
        self.assertFalse(boundary["dynamic_dependency_install_allowed"]["const"])
        self.assertFalse(boundary["production_effect"]["const"])
        self.assertEqual(
            schema["properties"]["adapter"]["$ref"], "#/$defs/adapter"
        )
        unsupported = schema["properties"]["claim_boundary"]["properties"][
            "not_supported"
        ]["const"]
        self.assertIn("HOST_AUTHENTICATION", unsupported)
        self.assertIn("DECISION_QUALITY", unsupported)
        self.assertIn("ACTION_CREATION", unsupported)

    def test_package_rejects_extra_files(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            (package / "README.md").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(
                conformance.PackageError, "exactly the four v1 files"
            ):
                conformance.verify_package(package)

    def test_package_rejects_source_digest_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            source = package / "adapter.py"
            source.write_text(
                source.read_text(encoding="utf-8") + "\n# changed\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                conformance.PackageError, "source digest mismatch"
            ):
                conformance.verify_package(package)

    def test_package_rejects_non_allowlisted_source_even_with_matching_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            source = package / "adapter.py"
            changed = source.read_text(encoding="utf-8").replace(
                "needs_review = any(", "needs_review = open("
            )
            source.write_text(changed, encoding="utf-8")
            manifest_path = package / "package.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["adapter"]["source_sha256"] = conformance.runtime._source_sha256(
                source
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                conformance.runtime.ContractError, "non-allowlisted call"
            ):
                conformance.verify_package(package)

    def test_package_rejects_allowlisted_callable_shadowing(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            source = package / "adapter.py"
            changed = source.read_text(encoding="utf-8").replace(
                '    evidence = request["evidence"]',
                '    any = request["evidence"]\n    evidence = request["evidence"]',
            )
            source.write_text(changed, encoding="utf-8")
            manifest_path = package / "package.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["adapter"]["source_sha256"] = conformance.runtime._source_sha256(
                source
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                conformance.runtime.ContractError, "cannot shadow"
            ):
                conformance.verify_package(package)

    def test_package_rejects_authority_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            manifest_path = package / "package.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["execution_boundary"]["network_access_allowed"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                conformance.PackageError, "execution boundary is unsupported"
            ):
                conformance.verify_package(package)

    def test_package_rejects_input_bundle_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            bundle_path = package / "input_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["payload"]["scenario"]["context_key"] = "CHANGED_CONTEXT"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaisesRegex(
                conformance.runtime.ContractError, "payload digest mismatch"
            ):
                conformance.verify_package(package)

    def test_package_rejects_submitted_trace_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            trace_path = package / "host_trace.json"
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["payload"]["approval_result"]["authority_granted"] = True
            trace["trace_sha256"] = conformance.runtime._sha256(trace["payload"])
            manifest_path = package / "package.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["host_trace_sha256"] = trace["trace_sha256"]
            trace_path.write_text(json.dumps(trace), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                conformance.runtime.ContractError, "approval result is unsupported"
            ):
                conformance.verify_package(package)

    def test_package_rejects_trace_that_does_not_match_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package_copy(directory)
            trace_path = package / "host_trace.json"
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["payload"]["host"]["host_id"] = "different-safe-host"
            trace["trace_sha256"] = conformance.runtime._sha256(trace["payload"])
            manifest_path = package / "package.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["host_trace_sha256"] = trace["trace_sha256"]
            trace_path.write_text(json.dumps(trace), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                conformance.PackageError, "does not match isolated replay"
            ):
                conformance.verify_package(package)


if __name__ == "__main__":
    unittest.main()
