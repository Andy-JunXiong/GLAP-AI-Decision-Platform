"""Run and summarize a governed, local historical replay corpus."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


_REPLAY_SPEC = importlib.util.spec_from_file_location(
    "glap_historical_replay_scenario",
    Path(__file__).with_name("run_historical_replay.py"),
)
if _REPLAY_SPEC is None or _REPLAY_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Unable to load historical replay scenario runner")
_REPLAY = importlib.util.module_from_spec(_REPLAY_SPEC)
_REPLAY_SPEC.loader.exec_module(_REPLAY)

ReplayContractError = _REPLAY.ReplayContractError
SCHEMA_VERSION = "historical-replay-corpus.v1"
REPORT_VERSION = "historical-replay-corpus-report.v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayContractError(message)


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    _require(set(value) == expected, f"{field} contains missing or unsupported fields")


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate corpus membership, selection, benchmark, and authority contracts."""

    _exact_keys(
        manifest,
        {
            "schema_version", "corpus_id", "status", "evidence_classification",
            "selection_policy", "benchmark_gate", "scenarios", "authority",
            "claim_boundary",
        },
        "corpus manifest",
    )
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "unsupported corpus schema")
    _require(manifest.get("status") == "PILOT_NOT_BENCHMARK", "corpus status overstates maturity")
    _require(
        manifest.get("evidence_classification") == "HYBRID_HISTORICAL_REPLAY",
        "corpus evidence classification is invalid",
    )

    selection = manifest.get("selection_policy", {})
    _exact_keys(
        selection,
        {"policy_version", "frozen_at", "inclusion_criteria", "exclusion_criteria"},
        "selection policy",
    )
    _require(selection.get("policy_version") == "historical-replay-selection.v1", "selection policy version is invalid")
    for field in ("inclusion_criteria", "exclusion_criteria"):
        values = selection.get(field)
        _require(isinstance(values, list) and bool(values), f"{field} must not be empty")
        _require(len(values) == len(set(values)), f"{field} contains duplicates")
    _REPLAY._timestamp(selection.get("frozen_at"), "selection_policy.frozen_at")

    gate = manifest.get("benchmark_gate", {})
    gate_fields = {
        "minimum_scenarios", "minimum_disruption_types", "minimum_regions",
        "minimum_transport_modes", "minimum_severity_bands",
        "required_reviews_per_variant",
    }
    _exact_keys(gate, gate_fields, "benchmark gate")
    for field in gate_fields:
        _require(isinstance(gate.get(field), int) and gate[field] > 0, f"{field} must be a positive integer")

    scenarios = manifest.get("scenarios")
    _require(isinstance(scenarios, list) and bool(scenarios), "corpus needs scenario entries")
    _require(all(isinstance(item, dict) for item in scenarios), "every scenario entry must be an object")
    scenario_ids: list[str] = []
    scenario_files: list[str] = []
    for entry in scenarios:
        _exact_keys(entry, {"scenario_id", "file"}, "scenario entry")
        scenario_id = entry.get("scenario_id")
        filename = entry.get("file")
        _require(isinstance(scenario_id, str) and bool(scenario_id), "scenario entry needs an ID")
        _require(isinstance(filename, str) and bool(filename), "scenario entry needs a file")
        path = Path(filename)
        _require(path.name == filename and path.suffix == ".json", "scenario file must be a local JSON basename")
        scenario_ids.append(scenario_id)
        scenario_files.append(filename)
    _require(len(scenario_ids) == len(set(scenario_ids)), "corpus scenario IDs must be unique")
    _require(len(scenario_files) == len(set(scenario_files)), "corpus scenario files must be unique")

    authority = manifest.get("authority", {})
    _exact_keys(
        authority,
        {"profile", "network_access_allowed", "operational_writes_allowed", "production_effect"},
        "corpus authority",
    )
    _require(authority.get("profile") == "EVALUATION_NO_MUTATION", "corpus requires no-mutation authority")
    for field in ("network_access_allowed", "operational_writes_allowed", "production_effect"):
        _require(authority.get(field) is False, f"corpus {field} must be false")


def run_corpus(manifest: dict[str, Any], scenario_directory: Path) -> dict[str, Any]:
    """Validate, replay, and summarize every frozen scenario in a manifest."""

    validate_manifest(manifest)
    scenario_reports: list[dict[str, Any]] = []
    for entry in manifest["scenarios"]:
        scenario_path = scenario_directory / entry["file"]
        _require(scenario_path.is_file(), f"scenario file is missing: {entry['file']}")
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        _require(scenario.get("scenario_id") == entry["scenario_id"], f"scenario ID differs from manifest: {entry['file']}")
        scenario_reports.append(_REPLAY.run_replay(scenario))

    profiles = [report["scenario_profile"] for report in scenario_reports]
    disruption_types = sorted({item["disruption_type"] for item in profiles})
    regions = sorted({item["region"] for item in profiles})
    transport_modes = sorted({item["transport_mode"] for item in profiles})
    severity_bands = sorted({item["severity_band"] for item in profiles})
    cutoff_results = [
        cutoff
        for report in scenario_reports
        for cutoff in report["cutoff_results"]
    ]
    attributed_count = sum(item["comparison"]["decision_changed"] for item in cutoff_results)
    gate = manifest["benchmark_gate"]
    gate_results = {
        "scenario_count": len(scenario_reports) >= gate["minimum_scenarios"],
        "disruption_type_count": len(disruption_types) >= gate["minimum_disruption_types"],
        "region_count": len(regions) >= gate["minimum_regions"],
        "transport_mode_count": len(transport_modes) >= gate["minimum_transport_modes"],
        "severity_band_count": len(severity_bands) >= gate["minimum_severity_bands"],
        "independent_reviews": False,
    }
    benchmark_eligible = all(gate_results.values())

    return {
        "schema_version": REPORT_VERSION,
        "corpus_id": manifest["corpus_id"],
        "status": manifest["status"],
        "evidence_classification": manifest["evidence_classification"],
        "selection_policy_version": manifest["selection_policy"]["policy_version"],
        "summary": {
            "scenario_count": len(scenario_reports),
            "cutoff_count": len(cutoff_results),
            "attributed_cutoff_count": attributed_count,
            "no_delta_cutoff_count": len(cutoff_results) - attributed_count,
        },
        "coverage": {
            "disruption_types": disruption_types,
            "regions": regions,
            "transport_modes": transport_modes,
            "severity_bands": severity_bands,
        },
        "benchmark_gate": {
            "requirements": gate,
            "checks": gate_results,
            "eligible": benchmark_eligible,
            "status": "MET" if benchmark_eligible else "NOT_MET",
        },
        "scenario_reports": scenario_reports,
        "decision_quality": {
            "status": "NOT_EVALUATED",
            "reason": "No independent blinded expert reviews are attached.",
        },
        "claim_boundary": manifest["claim_boundary"],
        "operational_mutations": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = run_corpus(manifest, args.manifest.parent)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
