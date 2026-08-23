"""Inspect and replay a self-contained offline Agent Runtime adapter package."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


_RUNTIME_PATH = Path(__file__).with_name("run_governed_agent_runtime.py")
_RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "agent_runtime_package_contract", _RUNTIME_PATH
)
if _RUNTIME_SPEC is None or _RUNTIME_SPEC.loader is None:
    raise RuntimeError("Agent Runtime package contract cannot be loaded")
runtime = importlib.util.module_from_spec(_RUNTIME_SPEC)
_RUNTIME_SPEC.loader.exec_module(runtime)


PACKAGE_VERSION = "agent-runtime-adapter-package.v1"
REPORT_VERSION = "agent-runtime-adapter-conformance-report.v1"
PACKAGE_FILES = {"package.json", "adapter.py", "input_bundle.json", "host_trace.json"}
SUPPORTED_CLAIMS = [
    "SOURCE_INSPECTION",
    "FROZEN_BUNDLE_REPLAY_CONFORMANCE",
    "SUBMITTED_TRACE_INTEGRITY",
]
UNSUPPORTED_CLAIMS = [
    "HOST_AUTHENTICATION",
    "MODEL_IDENTITY",
    "HOST_QUALITY_SUPERIORITY",
    "DECISION_QUALITY",
    "BUSINESS_OUTCOME_EFFECT",
    "OPERATIONAL_APPROVAL",
    "ACTION_CREATION",
    "DEPLOYED_RUNTIME_VERIFICATION",
    "PRODUCTION_READINESS",
]
EXECUTION_BOUNDARY = {
    "mode": "LOCAL_ISOLATED_REPLAY",
    "network_access_allowed": False,
    "operational_writes_allowed": False,
    "dynamic_dependency_install_allowed": False,
    "production_effect": False,
}


class PackageError(runtime.ContractError):
    """Raised when an offline adapter package fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    _require(set(value) == expected, f"{field} keys must be exactly {sorted(expected)}")


def _package_file(root: Path, relative: object, expected: str) -> Path:
    _require(relative == expected, f"package {expected} path is unsupported")
    path = root / expected
    _require(path.is_file() and not path.is_symlink(), f"package {expected} is missing or unsafe")
    _require(path.resolve().parent == root.resolve(), f"package {expected} escapes the package root")
    return path


def validate_package_manifest(manifest: dict[str, Any], root: Path) -> dict[str, Path]:
    """Validate the fixed package layout, identities, digests, and claim boundary."""

    _exact_keys(
        manifest,
        {
            "schema_version",
            "package_id",
            "interface_version",
            "host_id",
            "adapter",
            "artifacts",
            "execution_boundary",
            "claim_boundary",
        },
        "package",
    )
    _require(manifest.get("schema_version") == PACKAGE_VERSION, "unsupported package schema_version")
    for field in ("package_id", "host_id"):
        value = manifest.get(field)
        _require(
            isinstance(value, str) and bool(runtime.ID_PATTERN.fullmatch(value)),
            f"package {field} is invalid",
        )
    _require(manifest.get("interface_version") == runtime.INTERFACE_VERSION, "unsupported package interface")
    _require(manifest.get("execution_boundary") == EXECUTION_BOUNDARY, "package execution boundary is unsupported")

    adapter = manifest.get("adapter")
    _exact_keys(
        adapter,
        {
            "adapter_version",
            "implementation_id",
            "implementation_group",
            "module_path",
            "entrypoint",
            "source_sha256",
            "enabled_capabilities",
            "execution_boundary",
        },
        "package.adapter",
    )
    _require(
        isinstance(adapter.get("adapter_version"), str)
        and bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,127}", adapter["adapter_version"])),
        "package adapter_version is invalid",
    )
    for field in ("implementation_id", "implementation_group"):
        value = adapter.get(field)
        _require(
            isinstance(value, str) and bool(runtime.ID_PATTERN.fullmatch(value)),
            f"package adapter {field} is invalid",
        )
    _require(adapter.get("entrypoint") == "run_adapter", "package adapter entrypoint is unsupported")
    _require(
        adapter.get("enabled_capabilities") == sorted(runtime.CAPABILITIES),
        "package adapter capabilities are unsupported",
    )
    _require(
        adapter.get("execution_boundary") == "EVALUATION_NO_MUTATION",
        "package adapter authority is unsupported",
    )
    source_path = _package_file(root, adapter.get("module_path"), "adapter.py")
    source_sha256 = adapter.get("source_sha256")
    _require(
        isinstance(source_sha256, str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", source_sha256))
        and source_sha256 == runtime._source_sha256(source_path),
        "package adapter source digest mismatch",
    )
    runtime.validate_adapter_source(source_path, "adapter.py")

    artifacts = manifest.get("artifacts")
    _exact_keys(
        artifacts,
        {
            "input_bundle_path",
            "input_bundle_sha256",
            "host_trace_path",
            "host_trace_sha256",
        },
        "package.artifacts",
    )
    bundle_path = _package_file(root, artifacts.get("input_bundle_path"), "input_bundle.json")
    trace_path = _package_file(root, artifacts.get("host_trace_path"), "host_trace.json")
    for field in ("input_bundle_sha256", "host_trace_sha256"):
        value = artifacts.get(field)
        _require(
            isinstance(value, str) and bool(re.fullmatch(r"[a-f0-9]{64}", value)),
            f"package artifact {field} is invalid",
        )

    claims = manifest.get("claim_boundary")
    _exact_keys(claims, {"supported", "not_supported"}, "package.claim_boundary")
    _require(claims.get("supported") == SUPPORTED_CLAIMS, "package supported claims drifted")
    _require(claims.get("not_supported") == UNSUPPORTED_CLAIMS, "package unsupported claims drifted")
    return {"source": source_path, "bundle": bundle_path, "trace": trace_path}


_ISOLATED_RUNNER = r"""
import importlib.util
import json
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("offline_adapter", sys.argv[1])
if spec is None or spec.loader is None:
    raise RuntimeError("adapter cannot be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
request = json.load(sys.stdin)
first = module.run_adapter(request)
second = module.run_adapter(request)
json.dump([first, second], sys.stdout, sort_keys=True, separators=(",", ":"))
"""


def _run_isolated_adapter(source_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", _ISOLATED_RUNNER, str(source_path)],
            input=json.dumps(request, sort_keys=True, separators=(",", ":")),
            text=True,
            capture_output=True,
            cwd=source_path.parent,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PackageError("package adapter replay exceeded the offline time budget") from exc
    _require(completed.returncode == 0, "package adapter failed isolated replay")
    try:
        results = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PackageError("package adapter did not return JSON") from exc
    _require(
        isinstance(results, list) and len(results) == 2 and results[0] == results[1],
        "package adapter replay is not deterministic",
    )
    _require(isinstance(results[0], dict), "package adapter result must be an object")
    return results[0]


def verify_package(package_root: Path) -> dict[str, Any]:
    """Inspect, execute twice, and match a supplied trace without external access."""

    root = package_root.resolve()
    _require(root.is_dir(), "adapter package root must be a directory")
    actual_files = {
        item.name
        for item in root.iterdir()
        if not (item.name == "__pycache__" and item.is_dir())
    }
    _require(actual_files == PACKAGE_FILES, "adapter package must contain exactly the four v1 files")
    manifest_path = root / "package.json"
    _require(
        manifest_path.is_file() and not manifest_path.is_symlink(),
        "package manifest is missing or unsafe",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = validate_package_manifest(manifest, root)
    bundle = json.loads(paths["bundle"].read_text(encoding="utf-8"))
    expected_bundle_sha256 = manifest["artifacts"]["input_bundle_sha256"]
    runtime.verify_input_bundle(bundle, expected_sha256=expected_bundle_sha256)

    payload = bundle["payload"]
    envelope = payload["runtime_envelope"]
    request = {
        "interface_version": envelope["interface_version"],
        "input_bundle_sha256": bundle["bundle_sha256"],
        "context_key": payload["scenario"]["context_key"],
        "evidence": payload["cutoff_inputs"]["evidence"],
        "decision_memory": payload["cutoff_inputs"]["decision_memory"],
        "tool_modes": {
            name: contract["mode"] for name, contract in envelope["tools"].items()
        },
        "budgets": envelope["budgets"],
    }
    result = _run_isolated_adapter(paths["source"], request)
    adapter = manifest["adapter"]
    execution = {
        "host_id": manifest["host_id"],
        "adapter_version": adapter["adapter_version"],
        "implementation_id": adapter["implementation_id"],
        "implementation_group": adapter["implementation_group"],
        "source_sha256": adapter["source_sha256"],
        "enabled_capabilities": adapter["enabled_capabilities"],
        **result,
    }
    replay_trace = runtime.build_host_trace(bundle, execution)
    runtime.verify_host_trace(bundle, replay_trace)
    submitted_trace = json.loads(paths["trace"].read_text(encoding="utf-8"))
    expected_trace_sha256 = manifest["artifacts"]["host_trace_sha256"]
    runtime.verify_host_trace(
        bundle,
        submitted_trace,
        expected_trace_sha256=expected_trace_sha256,
    )
    _require(submitted_trace == replay_trace, "submitted host trace does not match isolated replay")
    _require(
        submitted_trace["payload"]["host"]
        == {
            "host_id": manifest["host_id"],
            "adapter_version": adapter["adapter_version"],
            "implementation_id": adapter["implementation_id"],
            "implementation_group": adapter["implementation_group"],
            "source_sha256": adapter["source_sha256"],
            "enabled_capabilities": adapter["enabled_capabilities"],
        },
        "submitted host identity does not match the package manifest",
    )
    return {
        "schema_version": REPORT_VERSION,
        "package_id": manifest["package_id"],
        "status": "PASS",
        "checks": {
            "fixed_package_layout": "PASS",
            "source_integrity": "PASS",
            "source_policy": "PASS",
            "input_bundle_integrity": "PASS",
            "deterministic_isolated_replay": "PASS",
            "submitted_trace_integrity": "PASS",
            "submitted_trace_matches_replay": "PASS",
            "no_mutation_authority": "PASS",
        },
        "adapter": {
            "adapter_version": adapter["adapter_version"],
            "implementation_id": adapter["implementation_id"],
            "implementation_group": adapter["implementation_group"],
            "source_sha256": adapter["source_sha256"],
        },
        "input_bundle_sha256": bundle["bundle_sha256"],
        "submitted_trace_sha256": submitted_trace["trace_sha256"],
        "replay_trace_sha256": replay_trace["trace_sha256"],
        "execution_boundary": manifest["execution_boundary"],
        "evaluation_layers": {
            "system_correctness": {"status": "PASS"},
            "capability_attribution": {"status": "NOT_EVALUATED"},
            "decision_quality": {"status": "NOT_EVALUATED"},
            "business_outcome_effect": {
                "status": "NOT_EVALUATED",
                "outcome_evidence_class": "NOT_EVALUATED",
            },
        },
        "operational_mutations": [],
        "claim_boundary": manifest["claim_boundary"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    return parser.parse_args()


def main() -> int:
    try:
        report = verify_package(parse_args().package)
    except (OSError, ValueError, SyntaxError, json.JSONDecodeError) as error:
        print(f"Adapter package conformance failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
