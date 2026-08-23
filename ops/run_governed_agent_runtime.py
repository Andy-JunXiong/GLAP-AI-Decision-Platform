"""Validate host parity through the local governed Agent Runtime v1 adapter."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "agent-runtime-experiment.v1"
REPORT_VERSION = "agent-runtime-report.v1"
INPUT_BUNDLE_VERSION = "agent-runtime-input-bundle.v1"
INPUT_PAYLOAD_VERSION = "agent-runtime-input-payload.v1"
HOST_TRACE_VERSION = "agent-runtime-host-trace.v1"
INTERFACE_VERSION = "agent-runtime.v1"
HOST_ADAPTERS = {
    "deterministic-reference-adapter-a.v1",
    "independent-registered-adapter.v1",
}
HOST_REGISTRY_VERSION = "agent-runtime-host-registry.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HOST_REGISTRY_PATH = "docs/agent_runtime_host_registry_v1.json"
CAPABILITIES = {"EXTERNAL_EVIDENCE", "DECISION_MEMORY"}
ALLOWED_ADAPTER_CALLS = {"any", "bool", "enumerate", "len"}
TOOL_MODES = {
    "get_evidence": "LOCAL_READ_ONLY",
    "get_similar_decisions": "LOCAL_READ_ONLY",
    "propose_action": "EVALUATION_PROPOSAL_ONLY",
    "request_approval": "SIMULATED_NO_AUTHORITY",
}
FROZEN_BUDGETS = {
    "max_tool_calls": 4,
    "max_evidence_items": 2,
    "max_memory_items": 2,
    "max_proposal_characters": 1024,
}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
SYDNEY = ZoneInfo("Australia/Sydney")


class ContractError(ValueError):
    """Raised when runtime parity, authority, input, or budget rules drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    _require(set(value) == expected, f"{field} keys must be exactly {sorted(expected)}")


def _nonempty(value: object, field: str) -> None:
    _require(isinstance(value, str) and bool(value), f"{field} is required")


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{field} must include a UTC offset")
    return parsed


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _source_sha256(path: Path) -> str:
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_adapter_source(path: Path, display_path: str | None = None) -> None:
    """Inspect one import-free adapter before any local execution."""

    label = display_path or path.as_posix()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=label)
    _require(
        all(
            isinstance(node.func, ast.Name)
            and node.func.id in ALLOWED_ADAPTER_CALLS
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ),
        "adapter source contains a non-allowlisted call",
    )
    body = list(tree.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    _require(
        len(body) == 1
        and isinstance(body[0], ast.FunctionDef)
        and body[0].name == "run_adapter",
        "adapter source must contain only the run_adapter entrypoint",
    )
    entrypoint = body[0]
    _require(
        len(entrypoint.args.posonlyargs) == 0
        and len(entrypoint.args.args) == 1
        and not entrypoint.args.vararg
        and not entrypoint.args.kwonlyargs
        and not entrypoint.args.kwarg
        and not entrypoint.args.defaults,
        "adapter run_adapter must accept exactly one request argument",
    )
    _require(
        not entrypoint.decorator_list
        and entrypoint.returns is None
        and entrypoint.args.args[0].annotation is None,
        "adapter run_adapter cannot use decorators or annotations",
    )
    forbidden_nodes = (
        ast.AsyncFunctionDef,
        ast.Attribute,
        ast.Await,
        ast.ClassDef,
        ast.Delete,
        ast.Global,
        ast.Import,
        ast.ImportFrom,
        ast.Lambda,
        ast.NamedExpr,
        ast.Nonlocal,
        ast.Raise,
        ast.Try,
        ast.With,
        ast.Yield,
        ast.YieldFrom,
    )
    _require(
        not any(isinstance(node, forbidden_nodes) for node in ast.walk(tree)),
        "adapter source contains an unsupported capability",
    )
    nested_functions = [
        node for node in ast.walk(entrypoint) if isinstance(node, ast.FunctionDef)
    ]
    _require(
        nested_functions == [entrypoint],
        "adapter source cannot define nested entrypoints",
    )
    _require(
        not any(
            isinstance(node, ast.Name) and node.id.startswith("_")
            for node in ast.walk(tree)
        ),
        "adapter source cannot access private or dunder names",
    )
    _require(
        not any(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in ALLOWED_ADAPTER_CALLS
            for node in ast.walk(tree)
        ),
        "adapter source cannot shadow an allowlisted callable",
    )


def validate_adapter_registry(registry: dict[str, Any], root: Path) -> None:
    """Validate frozen registrations, source integrity, and local-only code paths."""

    _exact_keys(
        registry,
        {
            "schema_version",
            "interface_version",
            "execution_boundary",
            "registrations",
            "claim_boundary",
        },
        "adapter_registry",
    )
    _require(
        registry.get("schema_version") == HOST_REGISTRY_VERSION,
        "unsupported adapter registry schema_version",
    )
    _require(
        registry.get("interface_version") == INTERFACE_VERSION,
        "adapter registry interface is unsupported",
    )
    _require(
        registry.get("execution_boundary")
        == {
            "mode": "LOCAL_READ_ONLY",
            "network_access_allowed": False,
            "operational_writes_allowed": False,
            "dynamic_dependency_install_allowed": False,
        },
        "adapter registry execution boundary is unsupported",
    )
    registrations = registry.get("registrations")
    _require(
        isinstance(registrations, list) and len(registrations) == 2,
        "adapter registry v1 requires exactly two registrations",
    )
    registration_keys = {
        "adapter_version",
        "implementation_id",
        "implementation_group",
        "module_path",
        "entrypoint",
        "source_sha256",
        "enabled_capabilities",
        "execution_boundary",
    }
    for index, registration in enumerate(registrations):
        _exact_keys(registration, registration_keys, f"adapter_registry.registrations[{index}]")
        _require(
            registration.get("adapter_version") in HOST_ADAPTERS,
            "adapter registry contains an unsupported adapter version",
        )
        for field in ("implementation_id", "implementation_group"):
            value = registration.get(field)
            _require(
                isinstance(value, str) and bool(ID_PATTERN.fullmatch(value)),
                f"adapter registry {field} is invalid",
            )
        _require(
            registration.get("entrypoint") == "run_adapter",
            "adapter registry entrypoint is unsupported",
        )
        _require(
            registration.get("execution_boundary") == "EVALUATION_NO_MUTATION",
            "registered adapter authority is unsupported",
        )
        _require(
            set(registration.get("enabled_capabilities", [])) == CAPABILITIES,
            "registered adapter capabilities must match Agent Runtime v1",
        )
        module_path = registration.get("module_path")
        _require(isinstance(module_path, str), "registered adapter module_path is invalid")
        relative = Path(module_path)
        _require(
            not relative.is_absolute()
            and ".." not in relative.parts
            and relative.as_posix().startswith("ops/agent_runtime_adapters/")
            and relative.suffix == ".py",
            "registered adapter module_path is outside the local adapter boundary",
        )
        source_path = root / relative
        _require(source_path.is_file(), "registered adapter source is missing")
        digest = registration.get("source_sha256")
        _require(
            isinstance(digest, str)
            and bool(re.fullmatch(r"[a-f0-9]{64}", digest))
            and digest == _source_sha256(source_path),
            "registered adapter source digest mismatch",
        )
        validate_adapter_source(source_path, module_path)

    for field in (
        "adapter_version",
        "implementation_id",
        "implementation_group",
        "module_path",
        "source_sha256",
    ):
        values = [item[field] for item in registrations]
        _require(len(values) == len(set(values)), f"registered adapters must use distinct {field} values")
    _require(
        {item["adapter_version"] for item in registrations} == HOST_ADAPTERS,
        "adapter registry does not contain the frozen v1 adapter set",
    )
    claims = registry.get("claim_boundary")
    _exact_keys(claims, {"supported", "not_supported"}, "adapter_registry.claim_boundary")
    _require(
        set(claims.get("supported", []))
        == {
            "REGISTERED_SOURCE_INTEGRITY",
            "DISTINCT_LOCAL_IMPLEMENTATION_PATHS",
            "FROZEN_BUNDLE_REPLAY_PARITY",
        },
        "adapter registry supported claims drifted",
    )
    _require(
        {
            "HOST_AUTHENTICATION",
            "MODEL_IDENTITY",
            "HOST_QUALITY_SUPERIORITY",
            "OPERATIONAL_APPROVAL",
            "ACTION_CREATION",
            "DEPLOYED_RUNTIME_VERIFICATION",
            "PRODUCTION_READINESS",
        }
        <= set(claims.get("not_supported", [])),
        "adapter registry unsupported-claim boundary drifted",
    )


def load_adapter_registry(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    path = root / HOST_REGISTRY_PATH
    registry = json.loads(path.read_text(encoding="utf-8"))
    validate_adapter_registry(registry, root)
    return registry


def _load_registered_entrypoint(registration: dict[str, Any], root: Path) -> Any:
    path = root / registration["module_path"]
    module_name = f"glap_adapter_{registration['implementation_id']}_{registration['source_sha256'][:12]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    _require(spec is not None and spec.loader is not None, "registered adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    entrypoint = getattr(module, registration["entrypoint"], None)
    _require(callable(entrypoint), "registered adapter entrypoint is missing")
    return entrypoint


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Fail closed before either registered host runs."""

    _exact_keys(
        manifest,
        {"schema_version", "experiment_id", "purpose", "business_timezone", "execution_boundary", "scenario", "runtime_contract", "hosts", "evaluation_layers"},
        "manifest",
    )
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version")
    _require(
        isinstance(manifest.get("experiment_id"), str)
        and bool(ID_PATTERN.fullmatch(manifest["experiment_id"])),
        "experiment_id must match the v1 identifier pattern",
    )
    _require(manifest.get("purpose") == "HOST_PARITY_VALIDATION", "unsupported purpose")
    _require(manifest.get("business_timezone") == "Australia/Sydney", "business timezone must be Australia/Sydney")

    boundary = manifest.get("execution_boundary")
    _exact_keys(boundary, {"mode", "network_access_allowed", "operational_writes_allowed", "production_effect"}, "execution_boundary")
    _require(boundary.get("mode") == "LOCAL_READ_ONLY", "only LOCAL_READ_ONLY execution is allowed")
    for field in ("network_access_allowed", "operational_writes_allowed", "production_effect"):
        _require(boundary.get(field) is False, f"{field} must be false")

    scenario = manifest.get("scenario")
    _exact_keys(
        scenario,
        {"scenario_id", "scenario_mode", "cutoff_at", "evidence_classification", "context_key", "evidence", "decision_memory"},
        "scenario",
    )
    _nonempty(scenario.get("scenario_id"), "scenario_id")
    _nonempty(scenario.get("context_key"), "context_key")
    _require(scenario.get("scenario_mode") == "CONTROLLED_SYNTHETIC_REPLAY", "runtime v1 supports controlled synthetic replay only")
    _require(scenario.get("evidence_classification") == "SYNTHETIC_ENGINEERING_ONLY", "runtime v1 inputs must remain synthetic engineering only")
    cutoff = _timestamp(scenario.get("cutoff_at"), "scenario.cutoff_at")
    _require(
        cutoff.utcoffset() == cutoff.astimezone(SYDNEY).utcoffset(),
        "scenario.cutoff_at must use the Australia/Sydney UTC offset",
    )
    _require(
        cutoff.astimezone(SYDNEY).date() <= datetime.now(SYDNEY).date(),
        "controlled replay cutoff cannot be later than the current Sydney date",
    )

    evidence = scenario.get("evidence")
    _require(isinstance(evidence, list) and bool(evidence), "scenario evidence must be a non-empty list")
    evidence_ids: list[str] = []
    for index, item in enumerate(evidence):
        field = f"scenario.evidence[{index}]"
        _exact_keys(item, {"evidence_id", "evidence_type", "available_at", "provenance", "severity"}, field)
        evidence_id = item.get("evidence_id")
        _nonempty(evidence_id, f"{field}.evidence_id")
        evidence_ids.append(evidence_id)
        _require(item.get("evidence_type") in {"OPERATIONAL_SIGNAL", "EXTERNAL_EVENT"}, f"{evidence_id} has unsupported evidence_type")
        _timestamp(item.get("available_at"), f"{evidence_id}.available_at")
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{evidence_id} has unsupported provenance")
        _require(item.get("severity") in {"LOW", "MEDIUM", "HIGH"}, f"{evidence_id} has unsupported severity")
    _require(len(evidence_ids) == len(set(evidence_ids)), "evidence_id values must be unique")

    memories = scenario.get("decision_memory")
    _require(isinstance(memories, list) and bool(memories), "scenario decision_memory must be a non-empty list")
    memory_ids: list[str] = []
    for index, item in enumerate(memories):
        field = f"scenario.decision_memory[{index}]"
        _exact_keys(
            item,
            {"memory_id", "available_at", "provenance", "context_key", "prior_recommendation", "review_status", "outcome_evidence_class"},
            field,
        )
        memory_id = item.get("memory_id")
        _nonempty(memory_id, f"{field}.memory_id")
        memory_ids.append(memory_id)
        _timestamp(item.get("available_at"), f"{memory_id}.available_at")
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{memory_id} has unsupported provenance")
        _nonempty(item.get("context_key"), f"{memory_id}.context_key")
        _require(item.get("prior_recommendation") in {"MONITOR_EVIDENCE", "REQUEST_BOUNDED_REVIEW"}, f"{memory_id} has unsupported prior_recommendation")
        _require(item.get("review_status") == "SYNTHETIC_REVIEWED", f"{memory_id} is not reviewed synthetic memory")
        _require(item.get("outcome_evidence_class") == "NOT_EVALUATED", f"{memory_id} cannot attach Outcome evidence")
    _require(len(memory_ids) == len(set(memory_ids)), "memory_id values must be unique")

    runtime = manifest.get("runtime_contract")
    _exact_keys(runtime, {"interface_version", "authority_profile", "tools", "budgets", "redaction"}, "runtime_contract")
    _require(runtime.get("interface_version") == INTERFACE_VERSION, "unsupported runtime interface")
    _require(runtime.get("authority_profile") == "EVALUATION_NO_MUTATION", "runtime must use no-mutation authority")
    tools = runtime.get("tools")
    _exact_keys(tools, set(TOOL_MODES), "runtime_contract.tools")
    for name, mode in TOOL_MODES.items():
        _exact_keys(tools.get(name), {"mode", "max_calls"}, f"runtime_contract.tools.{name}")
        _require(tools[name].get("mode") == mode, f"{name} mode is unsupported")
        _require(tools[name].get("max_calls") == 1, f"{name} max_calls must be one")
    _require(runtime.get("budgets") == FROZEN_BUDGETS, "runtime budgets must match the frozen v1 budget")
    _require(
        runtime.get("redaction")
        == {"entity_identifiers_allowed": False, "credentials_allowed": False, "private_origins_allowed": False},
        "runtime redaction cannot expose protected values",
    )

    hosts = manifest.get("hosts")
    _require(isinstance(hosts, list) and len(hosts) == 2, "runtime v1 requires exactly two hosts")
    host_ids: list[str] = []
    adapters: set[str] = set()
    for index, host in enumerate(hosts):
        _exact_keys(host, {"host_id", "adapter_version", "enabled_capabilities"}, f"hosts[{index}]")
        _nonempty(host.get("host_id"), f"hosts[{index}].host_id")
        host_ids.append(host["host_id"])
        adapters.add(host.get("adapter_version"))
        capabilities = host.get("enabled_capabilities")
        _require(
            isinstance(capabilities, list)
            and len(capabilities) == len(CAPABILITIES)
            and set(capabilities) == CAPABILITIES,
            f"hosts[{index}] must enable the identical frozen capability set",
        )
    _require(len(host_ids) == len(set(host_ids)), "host_id values must be unique")
    _require(adapters == HOST_ADAPTERS, "hosts must use the two frozen registered adapters")

    layers = manifest.get("evaluation_layers")
    _exact_keys(layers, {"system_correctness", "capability_attribution", "decision_quality", "business_outcome_effect"}, "evaluation_layers")
    _require(layers.get("system_correctness") == "EVALUATE", "system correctness must be evaluated")
    for layer in ("capability_attribution", "decision_quality", "business_outcome_effect"):
        _require(layers.get(layer) == "NOT_EVALUATED", f"runtime v1 cannot evaluate {layer}")


def _eligible(items: list[dict[str, Any]], cutoff: datetime, id_field: str) -> tuple[list[dict[str, Any]], list[str]]:
    visible = [item for item in items if _timestamp(item["available_at"], f"{item[id_field]}.available_at") <= cutoff]
    visible_ids = {item[id_field] for item in visible}
    excluded = [item[id_field] for item in items if item[id_field] not in visible_ids]
    return visible, excluded


def build_input_bundle(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical host-shared input bundle after contract validation."""

    validate_manifest(manifest)
    scenario = manifest["scenario"]
    cutoff = _timestamp(scenario["cutoff_at"], "scenario.cutoff_at")
    evidence, _ = _eligible(scenario["evidence"], cutoff, "evidence_id")
    memories, _ = _eligible(scenario["decision_memory"], cutoff, "memory_id")
    runtime = manifest["runtime_contract"]
    payload = {
        "payload_version": INPUT_PAYLOAD_VERSION,
        "experiment_id": manifest["experiment_id"],
        "scenario": {
            "scenario_id": scenario["scenario_id"],
            "scenario_mode": scenario["scenario_mode"],
            "cutoff_at": scenario["cutoff_at"],
            "evidence_classification": scenario["evidence_classification"],
            "context_key": scenario["context_key"],
        },
        "runtime_envelope": {
            "interface_version": runtime["interface_version"],
            "authority_profile": runtime["authority_profile"],
            "tools": runtime["tools"],
            "budgets": runtime["budgets"],
            "redaction": runtime["redaction"],
            "enabled_capabilities": sorted(CAPABILITIES),
        },
        "cutoff_inputs": {
            "evidence": sorted(evidence, key=lambda item: item["evidence_id"]),
            "decision_memory": sorted(memories, key=lambda item: item["memory_id"]),
        },
    }
    bundle = {
        "schema_version": INPUT_BUNDLE_VERSION,
        "bundle_sha256": _sha256(payload),
        "source_manifest_sha256": _sha256(manifest),
        "payload": payload,
    }
    verify_input_bundle(bundle)
    return bundle


def verify_input_bundle(
    bundle: dict[str, Any], expected_sha256: str | None = None
) -> None:
    """Independently verify bundle structure, boundary, ordering, and digest."""

    _exact_keys(
        bundle,
        {"schema_version", "bundle_sha256", "source_manifest_sha256", "payload"},
        "input_bundle",
    )
    _require(
        bundle.get("schema_version") == INPUT_BUNDLE_VERSION,
        "unsupported input bundle schema_version",
    )
    for field in ("bundle_sha256", "source_manifest_sha256"):
        value = bundle.get(field)
        _require(
            isinstance(value, str) and bool(re.fullmatch(r"[a-f0-9]{64}", value)),
            f"input_bundle.{field} must be a SHA-256 digest",
        )
    payload = bundle.get("payload")
    _exact_keys(
        payload,
        {"payload_version", "experiment_id", "scenario", "runtime_envelope", "cutoff_inputs"},
        "input_bundle.payload",
    )
    _require(
        payload.get("payload_version") == INPUT_PAYLOAD_VERSION,
        "unsupported input payload version",
    )
    _require(
        isinstance(payload.get("experiment_id"), str)
        and bool(ID_PATTERN.fullmatch(payload["experiment_id"])),
        "input bundle experiment_id is invalid",
    )
    scenario = payload.get("scenario")
    _exact_keys(
        scenario,
        {"scenario_id", "scenario_mode", "cutoff_at", "evidence_classification", "context_key"},
        "input_bundle.payload.scenario",
    )
    _nonempty(scenario.get("scenario_id"), "input bundle scenario_id")
    _nonempty(scenario.get("context_key"), "input bundle context_key")
    _require(
        scenario.get("scenario_mode") == "CONTROLLED_SYNTHETIC_REPLAY",
        "input bundle scenario mode is unsupported",
    )
    _require(
        scenario.get("evidence_classification") == "SYNTHETIC_ENGINEERING_ONLY",
        "input bundle evidence classification is unsupported",
    )
    cutoff = _timestamp(scenario.get("cutoff_at"), "input_bundle.payload.scenario.cutoff_at")
    _require(
        cutoff.utcoffset() == cutoff.astimezone(SYDNEY).utcoffset(),
        "input bundle cutoff must use the Australia/Sydney UTC offset",
    )
    _require(
        cutoff.astimezone(SYDNEY).date() <= datetime.now(SYDNEY).date(),
        "input bundle cutoff cannot be later than the current Sydney date",
    )

    envelope = payload.get("runtime_envelope")
    _exact_keys(
        envelope,
        {"interface_version", "authority_profile", "tools", "budgets", "redaction", "enabled_capabilities"},
        "input_bundle.payload.runtime_envelope",
    )
    _require(envelope.get("interface_version") == INTERFACE_VERSION, "input bundle runtime interface is unsupported")
    _require(envelope.get("authority_profile") == "EVALUATION_NO_MUTATION", "input bundle authority is unsupported")
    _require(envelope.get("budgets") == FROZEN_BUDGETS, "input bundle budgets do not match v1")
    _require(
        envelope.get("redaction")
        == {"entity_identifiers_allowed": False, "credentials_allowed": False, "private_origins_allowed": False},
        "input bundle redaction is unsupported",
    )
    _require(envelope.get("enabled_capabilities") == sorted(CAPABILITIES), "input bundle capabilities are unsupported")
    tools = envelope.get("tools")
    _exact_keys(tools, set(TOOL_MODES), "input_bundle.payload.runtime_envelope.tools")
    for name, mode in TOOL_MODES.items():
        _require(
            tools.get(name) == {"mode": mode, "max_calls": 1},
            f"input bundle {name} contract is unsupported",
        )

    inputs = payload.get("cutoff_inputs")
    _exact_keys(inputs, {"evidence", "decision_memory"}, "input_bundle.payload.cutoff_inputs")
    evidence = inputs.get("evidence")
    memories = inputs.get("decision_memory")
    _require(isinstance(evidence, list), "input bundle evidence must be an array")
    _require(isinstance(memories, list), "input bundle decision_memory must be an array")
    _require(
        all(isinstance(item, dict) for item in evidence),
        "input bundle evidence items must be objects",
    )
    _require(
        all(isinstance(item, dict) for item in memories),
        "input bundle decision_memory items must be objects",
    )
    _require(
        len(evidence) <= FROZEN_BUDGETS["max_evidence_items"],
        "input bundle evidence exceeds the v1 budget",
    )
    _require(
        len(memories) <= FROZEN_BUDGETS["max_memory_items"],
        "input bundle decision_memory exceeds the v1 budget",
    )
    _require(
        evidence == sorted(evidence, key=lambda item: item.get("evidence_id", "")),
        "input bundle evidence must be sorted by evidence_id",
    )
    _require(
        memories == sorted(memories, key=lambda item: item.get("memory_id", "")),
        "input bundle decision_memory must be sorted by memory_id",
    )
    evidence_ids: list[str] = []
    for index, item in enumerate(evidence):
        _exact_keys(
            item,
            {"evidence_id", "evidence_type", "available_at", "provenance", "severity"},
            f"input_bundle.payload.cutoff_inputs.evidence[{index}]",
        )
        evidence_ids.append(item.get("evidence_id"))
        _nonempty(item.get("evidence_id"), f"input bundle evidence[{index}].evidence_id")
        _require(_timestamp(item.get("available_at"), f"{item['evidence_id']}.available_at") <= cutoff, f"{item['evidence_id']} is post-cutoff")
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{item['evidence_id']} provenance is unsupported")
        _require(
            item.get("evidence_type") in {"OPERATIONAL_SIGNAL", "EXTERNAL_EVENT"},
            f"{item['evidence_id']} evidence_type is unsupported",
        )
        _require(
            item.get("severity") in {"LOW", "MEDIUM", "HIGH"},
            f"{item['evidence_id']} severity is unsupported",
        )
    _require(len(evidence_ids) == len(set(evidence_ids)), "input bundle evidence IDs must be unique")
    memory_ids: list[str] = []
    for index, item in enumerate(memories):
        _exact_keys(
            item,
            {"memory_id", "available_at", "provenance", "context_key", "prior_recommendation", "review_status", "outcome_evidence_class"},
            f"input_bundle.payload.cutoff_inputs.decision_memory[{index}]",
        )
        memory_ids.append(item.get("memory_id"))
        _nonempty(item.get("memory_id"), f"input bundle memory[{index}].memory_id")
        _require(_timestamp(item.get("available_at"), f"{item['memory_id']}.available_at") <= cutoff, f"{item['memory_id']} is post-cutoff")
        _require(item.get("provenance") == "CONTROLLED_SYNTHETIC", f"{item['memory_id']} provenance is unsupported")
        _nonempty(item.get("context_key"), f"{item['memory_id']}.context_key")
        _require(
            item.get("prior_recommendation")
            in {"MONITOR_EVIDENCE", "REQUEST_BOUNDED_REVIEW"},
            f"{item['memory_id']} prior_recommendation is unsupported",
        )
        _require(item.get("review_status") == "SYNTHETIC_REVIEWED", f"{item['memory_id']} review status is unsupported")
        _require(item.get("outcome_evidence_class") == "NOT_EVALUATED", f"{item['memory_id']} cannot attach Outcome evidence")
    _require(len(memory_ids) == len(set(memory_ids)), "input bundle memory IDs must be unique")

    computed = _sha256(payload)
    _require(bundle["bundle_sha256"] == computed, "input bundle payload digest mismatch")
    if expected_sha256 is not None:
        _require(computed == expected_sha256, "input bundle does not match the expected digest")


def _run_host(
    manifest: dict[str, Any],
    host: dict[str, Any],
    evidence: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    input_bundle: dict[str, Any],
    registry: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    runtime = manifest["runtime_contract"]
    budgets = runtime["budgets"]
    _require(len(evidence) <= budgets["max_evidence_items"], "cutoff-eligible evidence exceeds the runtime budget")
    _require(len(memories) <= budgets["max_memory_items"], "cutoff-eligible memory exceeds the runtime budget")
    registration = next(
        item
        for item in registry["registrations"]
        if item["adapter_version"] == host["adapter_version"]
    )
    entrypoint = _load_registered_entrypoint(registration, root)
    adapter_result = entrypoint(
        {
            "interface_version": runtime["interface_version"],
            "input_bundle_sha256": input_bundle["bundle_sha256"],
            "context_key": manifest["scenario"]["context_key"],
            "evidence": evidence,
            "decision_memory": memories,
            "tool_modes": dict(TOOL_MODES),
            "budgets": dict(budgets),
        }
    )
    _exact_keys(
        adapter_result,
        {"tool_calls", "proposal", "approval_result", "operational_mutations"},
        f"adapter_result.{host['adapter_version']}",
    )
    tool_calls = adapter_result["tool_calls"]
    proposal = adapter_result["proposal"]
    _require(isinstance(tool_calls, list), "registered adapter tool_calls must be an array")
    _require(len(tool_calls) <= budgets["max_tool_calls"], "tool calls exceed the runtime budget")
    _require(
        len(json.dumps(proposal, sort_keys=True)) <= budgets["max_proposal_characters"],
        "proposal exceeds the runtime output budget",
    )
    return {
        "host_id": host["host_id"],
        "adapter_version": host["adapter_version"],
        "implementation_id": registration["implementation_id"],
        "implementation_group": registration["implementation_group"],
        "module_path": registration["module_path"],
        "source_sha256": registration["source_sha256"],
        "enabled_capabilities": list(host["enabled_capabilities"]),
        "input_bundle_sha256": input_bundle["bundle_sha256"],
        "tool_calls": tool_calls,
        "proposal": proposal,
        "approval_result": adapter_result["approval_result"],
        "operational_mutations": adapter_result["operational_mutations"],
    }


def _expected_proposal(
    evidence: list[dict[str, Any]], matching_memories: list[dict[str, Any]]
) -> dict[str, Any]:
    high_external = [
        item
        for item in evidence
        if item["evidence_type"] == "EXTERNAL_EVENT" and item["severity"] == "HIGH"
    ]
    request_review = bool(high_external or matching_memories)
    return {
        "status": "EVALUATION_PROPOSAL_ONLY",
        "recommendation": "REQUEST_BOUNDED_REVIEW" if request_review else "MONITOR_EVIDENCE",
        "priority": "HIGH" if request_review else "MEDIUM",
        "human_review_required": request_review,
        "rationale": (
            "Cutoff-eligible controlled evidence or reviewed memory supports a bounded simulated review request."
            if request_review
            else "No qualifying controlled input is visible; continue the evaluation-only evidence watch."
        ),
    }


def build_host_trace(
    input_bundle: dict[str, Any], execution: dict[str, Any]
) -> dict[str, Any]:
    """Create a content-addressed submission from one completed host execution."""

    verify_input_bundle(input_bundle)
    payload = {
        "input_bundle_sha256": input_bundle["bundle_sha256"],
        "host": {
            "host_id": execution["host_id"],
            "adapter_version": execution["adapter_version"],
            "implementation_id": execution["implementation_id"],
            "implementation_group": execution["implementation_group"],
            "source_sha256": execution["source_sha256"],
            "enabled_capabilities": sorted(execution["enabled_capabilities"]),
        },
        "tool_calls": execution["tool_calls"],
        "proposal": execution["proposal"],
        "approval_result": execution["approval_result"],
        "operational_mutations": execution["operational_mutations"],
    }
    trace = {
        "schema_version": HOST_TRACE_VERSION,
        "trace_sha256": _sha256(payload),
        "payload": payload,
    }
    verify_host_trace(input_bundle, trace)
    return trace


def verify_host_trace(
    input_bundle: dict[str, Any],
    trace: dict[str, Any],
    expected_trace_sha256: str | None = None,
) -> None:
    """Replay-verify a host trace against one frozen input bundle."""

    verify_input_bundle(input_bundle)
    _exact_keys(trace, {"schema_version", "trace_sha256", "payload"}, "host_trace")
    _require(trace.get("schema_version") == HOST_TRACE_VERSION, "unsupported host trace schema_version")
    trace_sha = trace.get("trace_sha256")
    _require(
        isinstance(trace_sha, str) and bool(re.fullmatch(r"[a-f0-9]{64}", trace_sha)),
        "host trace digest must be SHA-256",
    )
    payload = trace.get("payload")
    _exact_keys(
        payload,
        {"input_bundle_sha256", "host", "tool_calls", "proposal", "approval_result", "operational_mutations"},
        "host_trace.payload",
    )
    _require(
        payload.get("input_bundle_sha256") == input_bundle["bundle_sha256"],
        "host trace input bundle digest mismatch",
    )
    host = payload.get("host")
    _exact_keys(
        host,
        {
            "host_id",
            "adapter_version",
            "implementation_id",
            "implementation_group",
            "source_sha256",
            "enabled_capabilities",
        },
        "host_trace.payload.host",
    )
    _nonempty(host.get("host_id"), "host trace host_id")
    _require(
        isinstance(host.get("adapter_version"), str)
        and bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,127}", host["adapter_version"])),
        "host trace adapter_version is invalid",
    )
    for field in ("implementation_id", "implementation_group"):
        _require(
            isinstance(host.get(field), str) and bool(ID_PATTERN.fullmatch(host[field])),
            f"host trace {field} is invalid",
        )
    _require(
        isinstance(host.get("source_sha256"), str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", host["source_sha256"])),
        "host trace source_sha256 is invalid",
    )
    _require(
        host.get("enabled_capabilities") == sorted(CAPABILITIES),
        "host trace capabilities do not match the bundle",
    )

    calls = payload.get("tool_calls")
    _require(isinstance(calls, list) and len(calls) == 4, "host trace must contain four tool calls")
    expected_tools = list(TOOL_MODES)
    evidence = input_bundle["payload"]["cutoff_inputs"]["evidence"]
    memories = input_bundle["payload"]["cutoff_inputs"]["decision_memory"]
    context_key = input_bundle["payload"]["scenario"]["context_key"]
    matching_memories = [item for item in memories if item["context_key"] == context_key]
    expected_results = [
        [item["evidence_id"] for item in evidence],
        [item["memory_id"] for item in matching_memories],
        [],
        [],
    ]
    for index, call in enumerate(calls):
        _exact_keys(call, {"sequence", "tool", "mode", "result_ids"}, f"host_trace.payload.tool_calls[{index}]")
        _require(call.get("sequence") == index + 1, "host trace tool sequence is invalid")
        _require(call.get("tool") == expected_tools[index], "host trace tool order is invalid")
        _require(call.get("mode") == TOOL_MODES[expected_tools[index]], f"host trace {expected_tools[index]} mode is invalid")
        _require(call.get("result_ids") == expected_results[index], f"host trace {expected_tools[index]} result IDs do not match the bundle")

    expected_proposal = _expected_proposal(evidence, matching_memories)
    _require(payload.get("proposal") == expected_proposal, "host trace proposal does not replay from the bundle")
    _require(
        len(json.dumps(payload["proposal"], sort_keys=True))
        <= input_bundle["payload"]["runtime_envelope"]["budgets"]["max_proposal_characters"],
        "host trace proposal exceeds the bundle budget",
    )
    _require(
        payload.get("approval_result")
        == {"status": "SIMULATED_PENDING_HUMAN_REVIEW", "authority_granted": False, "operational_action_created": False},
        "host trace approval result is unsupported",
    )
    _require(payload.get("operational_mutations") == [], "host trace cannot contain operational mutations")
    computed = _sha256(payload)
    _require(trace_sha == computed, "host trace payload digest mismatch")
    if expected_trace_sha256 is not None:
        _require(computed == expected_trace_sha256, "host trace does not match the expected digest")


def run_experiment(
    manifest: dict[str, Any], repository_root: Path = REPOSITORY_ROOT
) -> dict[str, Any]:
    """Run two registered local implementations under one immutable envelope."""

    validate_manifest(manifest)
    registry = load_adapter_registry(repository_root)
    cutoff = _timestamp(manifest["scenario"]["cutoff_at"], "scenario.cutoff_at")
    input_bundle = build_input_bundle(manifest)
    evidence = input_bundle["payload"]["cutoff_inputs"]["evidence"]
    memories = input_bundle["payload"]["cutoff_inputs"]["decision_memory"]
    _, post_cutoff_evidence = _eligible(manifest["scenario"]["evidence"], cutoff, "evidence_id")
    _, post_cutoff_memories = _eligible(manifest["scenario"]["decision_memory"], cutoff, "memory_id")
    hosts = [
        _run_host(
            manifest,
            host,
            evidence,
            memories,
            input_bundle,
            registry,
            repository_root,
        )
        for host in manifest["hosts"]
    ]
    host_traces = [build_host_trace(input_bundle, execution) for execution in hosts]
    first, second = hosts
    identical_tool_sequence = [item["tool"] for item in first["tool_calls"]] == [item["tool"] for item in second["tool_calls"]]
    identical_inputs = first["input_bundle_sha256"] == second["input_bundle_sha256"]
    identical_authority = all(
        item["approval_result"]
        == {"status": "SIMULATED_PENDING_HUMAN_REVIEW", "authority_granted": False, "operational_action_created": False}
        for item in hosts
    )
    equivalent_proposal = first["proposal"] == second["proposal"]
    mutation_free = all(item["operational_mutations"] == [] for item in hosts)
    distinct_implementations = (
        len({item["implementation_id"] for item in hosts}) == 2
        and len({item["implementation_group"] for item in hosts}) == 2
        and len({item["module_path"] for item in hosts}) == 2
        and len({item["source_sha256"] for item in hosts}) == 2
    )
    parity_passed = all(
        (
            identical_tool_sequence,
            identical_inputs,
            identical_authority,
            equivalent_proposal,
            mutation_free,
            distinct_implementations,
        )
    )
    return {
        "schema_version": REPORT_VERSION,
        "experiment_id": manifest["experiment_id"],
        "scenario_id": manifest["scenario"]["scenario_id"],
        "cutoff_at": manifest["scenario"]["cutoff_at"],
        "evidence_classification": manifest["scenario"]["evidence_classification"],
        "execution_boundary": dict(manifest["execution_boundary"]),
        "runtime_contract": dict(manifest["runtime_contract"]),
        "adapter_registry": {
            "schema_version": registry["schema_version"],
            "registry_sha256": _sha256(registry),
            "registrations": [
                {
                    "adapter_version": item["adapter_version"],
                    "implementation_id": item["implementation_id"],
                    "implementation_group": item["implementation_group"],
                    "module_path": item["module_path"],
                    "source_sha256": item["source_sha256"],
                }
                for item in registry["registrations"]
            ],
            "claim_boundary": dict(registry["claim_boundary"]),
        },
        "input_bundle": input_bundle,
        "input_window": {
            "cutoff_eligible_evidence_ids": [item["evidence_id"] for item in evidence],
            "post_cutoff_evidence_ids": post_cutoff_evidence,
            "cutoff_eligible_memory_ids": [item["memory_id"] for item in memories],
            "post_cutoff_memory_ids": post_cutoff_memories,
        },
        "hosts": hosts,
        "host_traces": host_traces,
        "host_parity": {
            "status": "PASS" if parity_passed else "FAIL",
            "identical_tool_sequence": identical_tool_sequence,
            "identical_inputs": identical_inputs,
            "identical_budgets": True,
            "identical_authority": identical_authority,
            "equivalent_proposal": equivalent_proposal,
            "distinct_implementation_paths": distinct_implementations,
            "registry_source_integrity": True,
        },
        "evaluation_layers": {
            "system_correctness": {"status": "PASS" if parity_passed else "FAIL"},
            "capability_attribution": {"status": "NOT_EVALUATED", "reason": "Both hosts receive identical capabilities."},
            "decision_quality": {"status": "NOT_EVALUATED", "reason": "Registered-host parity is not a quality comparison."},
            "business_outcome_effect": {"status": "NOT_EVALUATED", "outcome_evidence_class": "NOT_EVALUATED"},
        },
        "operational_mutations": [],
        "claim_boundary": {
            "supported": [
                "LOCAL_AGENT_RUNTIME_CONTRACT",
                "REGISTERED_ADAPTER_PARITY_MECHANICS",
                "DISTINCT_LOCAL_IMPLEMENTATION_PATHS",
            ],
            "not_supported": [
                "HOST_QUALITY_SUPERIORITY",
                "MODEL_COMPARISON",
                "OPERATIONAL_APPROVAL",
                "ACTION_CREATION",
                "AUTONOMOUS_EXECUTION",
                "BUSINESS_OUTCOME_IMPROVEMENT",
                "DEPLOYED_RUNTIME_VERIFICATION",
                "PRODUCTION_READINESS",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_experiment(json.loads(args.manifest.read_text(encoding="utf-8")))
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["host_parity"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
