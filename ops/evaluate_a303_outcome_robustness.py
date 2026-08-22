"""Run the pre-specified A303 synthetic outcome robustness evaluation.

Human Decision Quality is reported as a parallel evidence layer and never
controls simulator eligibility. The runner is deterministic, local, read-only,
and evaluates all attributed changes plus all simulator negative controls.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SIMULATOR_VERSION = "a303-outcome-simulator.v1"
PROTOCOL_VERSION = "a303-outcome-sensitivity-protocol.v1"
GATE_VERSION = "a303-synthetic-capability-gate.v1"
REPORT_VERSION = "a303-synthetic-outcome-robustness-report.v1"
QUALITY_SUMMARY_VERSION = "decision-quality-corpus-summary.v1"
REVIEW_BUNDLE_VERSION = "historical-replay-review-bundle.v3"
PARAMETER_NAMES = (
    "mitigation_incremental_cost_index",
    "avoided_dwell_fraction",
    "reroute_success_probability",
    "stockout_penalty_per_exposed_day_index",
    "service_impact_cost_per_delay_day_index",
)
INTERPRETATIONS = (
    "MODEL_FAVORS_A303_ON",
    "MODEL_FAVORS_A303_OFF",
    "NO_MATERIAL_MODELED_DIFFERENCE",
)


class RobustnessError(ValueError):
    """Raised when a frozen input, simulator, or integrity boundary drifts."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CORPUS = _load_module(
    "glap_historical_replay_corpus_for_robustness",
    Path(__file__).with_name("run_historical_replay_corpus.py"),
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RobustnessError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    actual = set(value)
    _require(
        actual == expected,
        f"{field} fields changed: missing={sorted(expected - actual)}, "
        f"unexpected={sorted(actual - expected)}",
    )


def canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _number(value: object, field: str, *, maximum: float | None = None) -> float:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{field} must be numeric",
    )
    result = float(value)
    _require(math.isfinite(result) and result >= 0.0, f"{field} must be finite and non-negative")
    if maximum is not None:
        _require(result <= maximum, f"{field} must not exceed {maximum}")
    return result


def validate_simulator(simulator: dict[str, Any]) -> None:
    _exact_keys(
        simulator,
        {
            "schema_version",
            "business_timezone",
            "scenario_evidence_class",
            "outcome_evidence_class",
            "coverage_contract",
            "formulas",
            "fixed_parameters",
            "sensitivity_parameter_defaults",
            "units",
            "assumptions",
            "authority",
            "claim_boundary",
        },
        "outcome simulator",
    )
    _require(simulator["schema_version"] == SIMULATOR_VERSION, "unsupported simulator")
    _require(simulator["business_timezone"] == "Australia/Sydney", "simulator timezone changed")
    _require(
        simulator["scenario_evidence_class"] == "HYBRID_HISTORICAL_REPLAY"
        and simulator["outcome_evidence_class"] == "SIMULATED_COUNTERFACTUAL",
        "simulator evidence class changed",
    )
    coverage = simulator["coverage_contract"]
    _exact_keys(
        coverage,
        {
            "frozen_scenario_count",
            "frozen_decision_package_count",
            "expected_attributed_change_count",
            "expected_negative_control_count",
            "human_decision_quality_required_for_simulation",
            "negative_control_expected_delta",
        },
        "simulator coverage contract",
    )
    _require(
        coverage == {
            "frozen_scenario_count": 10,
            "frozen_decision_package_count": 30,
            "expected_attributed_change_count": 16,
            "expected_negative_control_count": 14,
            "human_decision_quality_required_for_simulation": False,
            "negative_control_expected_delta": 0.0,
        },
        "simulator coverage contract drifted",
    )
    defaults = simulator["sensitivity_parameter_defaults"]
    _exact_keys(defaults, set(PARAMETER_NAMES), "simulator sensitivity defaults")
    for name, value in defaults.items():
        _number(value, name, maximum=1.0 if name in {"avoided_dwell_fraction", "reroute_success_probability"} else None)
    fixed = simulator["fixed_parameters"]
    _exact_keys(
        fixed,
        {
            "mode_base_delay_hours",
            "severity_multipliers",
            "no_alternate_delay_penalty_hours",
            "no_alternate_capacity_effectiveness_multiplier",
            "no_alternate_capacity_cost_multiplier",
            "sla_criticality_multipliers",
            "minimum_material_loss_delta",
        },
        "simulator fixed parameters",
    )
    _exact_keys(fixed["mode_base_delay_hours"], {"AIR", "OCEAN", "RAIL", "ROAD"}, "mode delays")
    _exact_keys(fixed["severity_multipliers"], {"LOW", "MEDIUM", "HIGH"}, "severity multipliers")
    _exact_keys(fixed["sla_criticality_multipliers"], {"LOW", "MEDIUM", "HIGH"}, "criticality multipliers")
    for field in (
        "no_alternate_delay_penalty_hours",
        "no_alternate_capacity_effectiveness_multiplier",
        "no_alternate_capacity_cost_multiplier",
        "minimum_material_loss_delta",
    ):
        _number(fixed[field], field, maximum=1.0 if "multiplier" in field else None)
    authority = simulator["authority"]
    _require(authority.get("mode") == "LOCAL_READ_ONLY", "simulator must remain local read-only")
    _require(
        all(value is False for key, value in authority.items() if key != "mode"),
        "simulator cannot gain network, mutation, production, or promotion authority",
    )
    unsupported = set(simulator["claim_boundary"].get("does_not_support", []))
    _require(
        {"REAL_LOGISTICS_PERFORMANCE", "EMPIRICAL_CALIBRATION", "PRODUCTION_READINESS"}.issubset(unsupported),
        "simulator claim boundary expanded",
    )


def validate_protocol(protocol: dict[str, Any], simulator: dict[str, Any]) -> None:
    _require(protocol.get("schema_version") == PROTOCOL_VERSION, "unsupported sensitivity protocol")
    _require(
        protocol.get("simulator", {}).get("schema_version") == SIMULATOR_VERSION
        and protocol.get("simulator", {}).get("sha256") == canonical_digest(simulator),
        "sensitivity protocol does not bind the frozen simulator",
    )
    design = protocol.get("design", {})
    _require(
        design.get("method") == "FULL_FACTORIAL_LOW_BASE_HIGH"
        and design.get("parameter_count") == 5
        and design.get("level_count_per_parameter") == 3
        and design.get("expected_combination_count") == 243
        and design.get("central_range_definition")
        == "BASE_CONFIGURATION_PLUS_ONE_PARAMETER_AT_A_TIME_LOW_OR_HIGH"
        and design.get("expected_central_combination_count") == 11
        and design.get("ranges_frozen_before_confirmatory_run") is True
        and design.get("post_hoc_range_changes_require_new_protocol_version") is True,
        "sensitivity design drifted",
    )
    parameters = protocol.get("parameters")
    _exact_keys(parameters, set(PARAMETER_NAMES), "sensitivity parameters")
    for name in PARAMETER_NAMES:
        item = parameters[name]
        _exact_keys(
            item,
            {"low", "base", "high", "unit", "rationale_class", "rationale", "expected_monotonic_direction_for_a303_value"},
            f"sensitivity parameter {name}",
        )
        low = _number(item["low"], f"{name}.low")
        base = _number(item["base"], f"{name}.base")
        high = _number(item["high"], f"{name}.high")
        _require(low < base < high, f"{name} levels must be strictly ordered")
        _require(base == float(simulator["sensitivity_parameter_defaults"][name]), f"{name} base differs from simulator")
        if name in {"avoided_dwell_fraction", "reroute_success_probability"}:
            _require(high <= 1.0, f"{name} must stay on the unit interval")
        _require(item["rationale_class"] == "SYNTHETIC_PLAUSIBILITY_ASSUMPTION", f"{name} rationale cannot claim calibration")
    authority = protocol.get("authority", {})
    _require(authority.get("mode") == "LOCAL_READ_ONLY", "sensitivity must remain local read-only")
    _require(all(value is False for key, value in authority.items() if key != "mode"), "sensitivity authority expanded")


def validate_gate(gate: dict[str, Any], simulator: dict[str, Any], protocol: dict[str, Any]) -> None:
    _require(gate.get("schema_version") == GATE_VERSION, "unsupported capability gate")
    _require(
        gate.get("simulator", {}).get("sha256") == canonical_digest(simulator)
        and gate.get("sensitivity_protocol", {}).get("sha256") == canonical_digest(protocol),
        "capability gate does not bind the frozen simulator and protocol",
    )
    integrity = gate.get("integrity_prerequisites", {})
    _require(
        integrity.get("expected_attributed_change_count") == 16
        and integrity.get("expected_negative_control_count") == 14
        and integrity.get("negative_control_required_delta") == 0.0
        and integrity.get("negative_control_tolerance") == 0.0
        and integrity.get("negative_controls_must_pass_every_parameter_combination") is True,
        "capability integrity prerequisites drifted",
    )
    handling = gate.get("decision_quality_handling", {})
    _require(
        handling.get("status_reported_separately") is True
        and handling.get("human_preference_controls_simulator_eligibility") is False
        and handling.get("original_reviews_may_be_overwritten") is False,
        "Decision Quality was coupled to simulator eligibility",
    )
    authority = gate.get("authority", {})
    _require(authority.get("mode") == "LOCAL_READ_ONLY", "capability gate must remain local read-only")
    _require(all(value is False for key, value in authority.items() if key != "mode"), "capability gate authority expanded")


def _quality_summary(source: dict[str, Any], review_bundle: dict[str, Any]) -> dict[str, Any]:
    summary = source.get("corpus_summary", source)
    _require(isinstance(summary, dict) and summary.get("schema_version") == QUALITY_SUMMARY_VERSION, "unsupported Decision Quality summary")
    _require(review_bundle.get("schema_version") == REVIEW_BUNDLE_VERSION, "only the frozen v3 review bundle is eligible")
    bundle_payload = {key: value for key, value in review_bundle.items() if key != "bundle_digest"}
    _require(review_bundle.get("bundle_digest") == canonical_digest(bundle_payload), "review bundle digest mismatch")
    _require(
        summary.get("bundle_id") == review_bundle.get("bundle_id")
        and summary.get("bundle_digest") == review_bundle.get("bundle_digest"),
        "Decision Quality summary does not match the frozen review bundle",
    )
    packages = review_bundle.get("packages")
    package_summaries = summary.get("package_summaries")
    _require(isinstance(packages, list) and len(packages) == 30, "review bundle must contain 30 packages")
    _require(isinstance(package_summaries, list) and len(package_summaries) == 30, "Decision Quality summary must cover 30 packages")
    package_map = {item.get("review_id"): item for item in packages}
    summary_map = {item.get("review_id"): item for item in package_summaries}
    _require(len(package_map) == 30 and set(package_map) == set(summary_map), "Decision Quality package membership drifted")
    for review_id, item in summary_map.items():
        _require(item.get("package_digest") == package_map[review_id].get("package_digest"), f"Decision Quality digest mismatch for {review_id}")
    _require(summary.get("reviewer_count") == 4, "robustness slice requires the governed four-review aggregate")
    return summary


def _parameter_combinations(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    levels = []
    for name in PARAMETER_NAMES:
        parameter = protocol["parameters"][name]
        levels.append((("low", float(parameter["low"])), ("base", float(parameter["base"])), ("high", float(parameter["high"]))))
    combinations = []
    for index, selected in enumerate(itertools.product(*levels), start=1):
        level_names = {name: value[0] for name, value in zip(PARAMETER_NAMES, selected)}
        values = {name: value[1] for name, value in zip(PARAMETER_NAMES, selected)}
        non_base = sum(level != "base" for level in level_names.values())
        combinations.append(
            {
                "combination_id": f"P{index:03d}",
                "levels": level_names,
                "values": values,
                "is_base": non_base == 0,
                "is_central": non_base <= 1,
            }
        )
    return combinations


def simulate_variant(
    recommendation: str,
    state: dict[str, Any],
    profile: dict[str, Any],
    severity: str,
    simulator: dict[str, Any],
    parameters: dict[str, float],
) -> dict[str, float]:
    fixed = simulator["fixed_parameters"]
    alternate = state["alternate_capacity_available"] is True
    gross_delay = float(fixed["mode_base_delay_hours"][profile["transport_mode"]]) * float(
        fixed["severity_multipliers"][severity]
    )
    if not alternate:
        gross_delay += float(fixed["no_alternate_delay_penalty_hours"])
    if recommendation == "RISK_MITIGATION":
        effectiveness = (
            parameters["avoided_dwell_fraction"]
            * parameters["reroute_success_probability"]
            * (1.0 if alternate else float(fixed["no_alternate_capacity_effectiveness_multiplier"]))
        )
        expected_delay = gross_delay * (1.0 - effectiveness)
        intervention_cost = parameters["mitigation_incremental_cost_index"] * (
            1.0 if alternate else float(fixed["no_alternate_capacity_cost_multiplier"])
        )
    else:
        _require(recommendation == "MONITOR", "simulator supports only MONITOR and RISK_MITIGATION")
        expected_delay = gross_delay
        intervention_cost = 0.0
    criticality = state["sla_criticality"]
    delay_days = expected_delay / 24.0
    delay_loss = (
        delay_days
        * parameters["service_impact_cost_per_delay_day_index"]
        * float(fixed["sla_criticality_multipliers"][criticality])
    )
    exposed_days = max(0.0, delay_days - float(state["inventory_cover_days"]))
    stockout_loss = exposed_days * parameters["stockout_penalty_per_exposed_day_index"]
    total_loss = delay_loss + stockout_loss + intervention_cost
    values = {
        "gross_delay_hours": gross_delay,
        "expected_delay_hours": expected_delay,
        "stockout_exposure_days": exposed_days,
        "delay_loss_index": delay_loss,
        "stockout_loss_index": stockout_loss,
        "intervention_cost_index": intervention_cost,
        "total_modeled_loss_index": total_loss,
    }
    _require(all(math.isfinite(value) for value in values.values()), "simulator produced a non-finite metric")
    return {key: round(value, 6) for key, value in values.items()}


def _interpret(delta: float, material: float) -> str:
    if delta >= material:
        return "MODEL_FAVORS_A303_ON"
    if delta <= -material:
        return "MODEL_FAVORS_A303_OFF"
    return "NO_MATERIAL_MODELED_DIFFERENCE"


def _count_interpretations(items: list[str]) -> dict[str, int]:
    return {name: items.count(name) for name in INTERPRETATIONS}


def _percentage(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100.0, 2) if denominator else 0.0


def _dq_counts(
    quality_summary: dict[str, Any],
    review_bundle: dict[str, Any],
    changed_keys: set[tuple[str, str]],
) -> dict[str, int]:
    packages = {item["review_id"]: item for item in review_bundle["packages"]}
    counts = {"FAVORS_A303_ON": 0, "FAVORS_A303_OFF": 0, "INCONCLUSIVE": 0}
    for item in quality_summary["package_summaries"]:
        scenario = packages[item["review_id"]]["scenario"]
        if (scenario["scenario_id"], scenario["cutoff_id"]) not in changed_keys:
            continue
        if item.get("result") == "REVIEW_EVIDENCE_FAVORS_VARIANT" and item.get("favored_variant_id") == "glap-a303-on":
            counts["FAVORS_A303_ON"] += 1
        elif item.get("result") == "REVIEW_EVIDENCE_FAVORS_VARIANT" and item.get("favored_variant_id") == "baseline-a303-off":
            counts["FAVORS_A303_OFF"] += 1
        else:
            counts["INCONCLUSIVE"] += 1
    _require(sum(counts.values()) == 16, "Decision Quality attributed coverage drifted")
    return counts


def run_robustness(
    simulator: dict[str, Any],
    protocol: dict[str, Any],
    gate: dict[str, Any],
    decision_quality_source: dict[str, Any],
    review_bundle: dict[str, Any],
    corpus_manifest: dict[str, Any],
    scenario_directory: Path,
) -> dict[str, Any]:
    validate_simulator(simulator)
    validate_protocol(protocol, simulator)
    validate_gate(gate, simulator, protocol)
    quality_summary = _quality_summary(decision_quality_source, review_bundle)
    corpus_report = _CORPUS.run_corpus(corpus_manifest, scenario_directory)
    scenario_reports = {item["scenario_id"]: item for item in corpus_report["scenario_reports"]}
    package_by_key = {
        (item["scenario"]["scenario_id"], item["scenario"]["cutoff_id"]): item
        for item in review_bundle["packages"]
    }
    combinations = _parameter_combinations(protocol)
    _require(len(combinations) == 243, "sensitivity combination count drifted")
    _require(sum(item["is_central"] for item in combinations) == 11, "central combination count drifted")
    base_combination = next(item for item in combinations if item["is_base"])
    material = float(simulator["fixed_parameters"]["minimum_material_loss_delta"])
    attributed: dict[tuple[str, str], dict[str, Any]] = {}
    controls: dict[tuple[str, str], dict[str, Any]] = {}

    for scenario_id, scenario_report in scenario_reports.items():
        for cutoff in scenario_report["cutoff_results"]:
            key = (scenario_id, cutoff["cutoff_id"])
            _require(key in package_by_key, "corpus package is missing from the frozen review bundle")
            package = package_by_key[key]
            scenario = package["scenario"]
            variants = {item["variant_id"]: item for item in cutoff["variants"]}
            _require(set(variants) == {"baseline-a303-off", "glap-a303-on"}, "paired variants drifted")
            target = attributed if cutoff["comparison"]["decision_changed"] else controls
            target[key] = {
                "scenario_id": scenario_id,
                "cutoff_id": cutoff["cutoff_id"],
                "cutoff_at": scenario["cutoff_at"],
                "transport_mode": scenario["scenario_profile"]["transport_mode"],
                "sla_criticality": scenario["operational_state"]["sla_criticality"],
                "state": scenario["operational_state"],
                "profile": scenario["scenario_profile"],
                "severity": cutoff["derived_risk"]["severity"],
                "baseline_recommendation": variants["baseline-a303-off"]["recommendation"],
                "a303_recommendation": variants["glap-a303-on"]["recommendation"],
                "combination_results": [],
            }

    _require(len(attributed) == 16 and len(controls) == 14, "frozen attribution counts drifted")
    for item in controls.values():
        _require(
            item["baseline_recommendation"] == item["a303_recommendation"],
            "negative control decisions are not identical",
        )

    global_interpretations: list[str] = []
    central_negative_count = 0
    control_failures = []
    for combination in combinations:
        parameters = combination["values"]
        for group_name, group in (("ATTRIBUTED", attributed), ("NEGATIVE_CONTROL", controls)):
            for key, item in group.items():
                baseline = simulate_variant(
                    item["baseline_recommendation"], item["state"], item["profile"], item["severity"], simulator, parameters
                )
                challenger = simulate_variant(
                    item["a303_recommendation"], item["state"], item["profile"], item["severity"], simulator, parameters
                )
                delta = round(baseline["total_modeled_loss_index"] - challenger["total_modeled_loss_index"], 6)
                interpretation = _interpret(delta, material)
                result = {
                    "combination_id": combination["combination_id"],
                    "is_base": combination["is_base"],
                    "is_central": combination["is_central"],
                    "delta": delta,
                    "interpretation": interpretation,
                }
                item["combination_results"].append(result)
                if group_name == "ATTRIBUTED":
                    global_interpretations.append(interpretation)
                    if combination["is_central"] and interpretation == "MODEL_FAVORS_A303_OFF":
                        central_negative_count += 1
                elif delta != 0.0 or baseline != challenger:
                    control_failures.append(
                        {"scenario_id": key[0], "cutoff_id": key[1], "combination_id": combination["combination_id"], "delta": delta}
                    )
    _require(not control_failures, "simulator negative control produced a non-zero paired outcome delta")

    base_interpretations = []
    scenario_stability = []
    flip_boundaries = []
    base_parameters = base_combination["values"]
    stability_rules = gate["scenario_stability_rules"]
    for key, item in attributed.items():
        interpretations = [result["interpretation"] for result in item["combination_results"]]
        counts = _count_interpretations(interpretations)
        positive_pct = _percentage(counts["MODEL_FAVORS_A303_ON"], len(interpretations))
        negative_pct = _percentage(counts["MODEL_FAVORS_A303_OFF"], len(interpretations))
        central_negative = sum(
            result["is_central"] and result["interpretation"] == "MODEL_FAVORS_A303_OFF"
            for result in item["combination_results"]
        )
        base_result = next(result for result in item["combination_results"] if result["is_base"])
        base_interpretations.append(base_result["interpretation"])
        base_baseline_metrics = simulate_variant(
            item["baseline_recommendation"],
            item["state"],
            item["profile"],
            item["severity"],
            simulator,
            base_parameters,
        )
        base_a303_metrics = simulate_variant(
            item["a303_recommendation"],
            item["state"],
            item["profile"],
            item["severity"],
            simulator,
            base_parameters,
        )
        stable_positive_rule = stability_rules["STABLE_POSITIVE"]
        stable_negative_rule = stability_rules["STABLE_NEGATIVE"]
        if (
            positive_pct >= float(stable_positive_rule["minimum_positive_combination_pct"])
            and central_negative <= int(stable_positive_rule["maximum_central_negative_combination_count"])
        ):
            classification = "STABLE_POSITIVE"
        elif negative_pct >= float(stable_negative_rule["minimum_negative_combination_pct"]):
            classification = "STABLE_NEGATIVE"
        else:
            classification = "PARAMETER_SENSITIVE"
        scenario_stability.append(
            {
                "scenario_id": key[0],
                "cutoff_id": key[1],
                "sla_criticality": item["sla_criticality"],
                "base_case_interpretation": base_result["interpretation"],
                "base_case_delta": base_result["delta"],
                "base_case_variants": [
                    {
                        "variant_id": "baseline-a303-off",
                        "recommendation": item["baseline_recommendation"],
                        "metrics": base_baseline_metrics,
                    },
                    {
                        "variant_id": "glap-a303-on",
                        "recommendation": item["a303_recommendation"],
                        "metrics": base_a303_metrics,
                    },
                ],
                "combination_counts": counts,
                "positive_combination_pct": positive_pct,
                "negative_combination_pct": negative_pct,
                "central_negative_combination_count": central_negative,
                "stability_classification": classification,
            }
        )
        parameter_boundaries = []
        for parameter_name in PARAMETER_NAMES:
            points = []
            def delta_at(parameter_value: float) -> float:
                values = dict(base_parameters)
                values[parameter_name] = parameter_value
                baseline = simulate_variant(
                    item["baseline_recommendation"], item["state"], item["profile"], item["severity"], simulator, values
                )
                challenger = simulate_variant(
                    item["a303_recommendation"], item["state"], item["profile"], item["severity"], simulator, values
                )
                return baseline["total_modeled_loss_index"] - challenger["total_modeled_loss_index"]

            for level in ("low", "base", "high"):
                values = dict(base_parameters)
                values[parameter_name] = float(protocol["parameters"][parameter_name][level])
                delta = round(delta_at(values[parameter_name]), 6)
                points.append({"level": level, "value": values[parameter_name], "delta": delta, "interpretation": _interpret(delta, material)})
            low_value = points[0]["value"]
            high_value = points[-1]["value"]
            low_delta = delta_at(low_value)
            high_delta = delta_at(high_value)
            break_even = None
            if low_delta == 0.0:
                break_even = low_value
            elif high_delta == 0.0:
                break_even = high_value
            elif low_delta * high_delta < 0.0:
                left, right = low_value, high_value
                left_delta = low_delta
                for _ in range(60):
                    midpoint = (left + right) / 2.0
                    midpoint_delta = delta_at(midpoint)
                    if abs(midpoint_delta) < 1e-12:
                        left = right = midpoint
                        break
                    if left_delta * midpoint_delta <= 0.0:
                        right = midpoint
                    else:
                        left = midpoint
                        left_delta = midpoint_delta
                break_even = (left + right) / 2.0
            direction = protocol["parameters"][parameter_name][
                "expected_monotonic_direction_for_a303_value"
            ]
            if break_even is not None:
                operator = "GREATER_THAN" if direction in {"INCREASING", "NON_DECREASING"} else "LESS_THAN"
                net_positive_condition = {
                    "operator": operator,
                    "threshold": round(break_even, 6),
                    "unit": protocol["parameters"][parameter_name]["unit"],
                }
            elif low_delta > 0.0 and high_delta > 0.0:
                net_positive_condition = {"operator": "POSITIVE_ACROSS_FROZEN_RANGE"}
            elif low_delta < 0.0 and high_delta < 0.0:
                net_positive_condition = {"operator": "NEGATIVE_ACROSS_FROZEN_RANGE"}
            else:
                net_positive_condition = {"operator": "ZERO_OR_FLAT_ACROSS_FROZEN_RANGE"}
            parameter_boundaries.append(
                {
                    "parameter": parameter_name,
                    "points": points,
                    "flip_detected": len({point["interpretation"] for point in points}) > 1,
                    "zero_delta_break_even_value": round(break_even, 6) if break_even is not None else None,
                    "net_positive_condition": net_positive_condition,
                }
            )
        flip_boundaries.append({"scenario_id": key[0], "cutoff_id": key[1], "parameters": parameter_boundaries})

    global_counts = _count_interpretations(global_interpretations)
    global_non_negative = global_counts["MODEL_FAVORS_A303_ON"] + global_counts["NO_MATERIAL_MODELED_DIFFERENCE"]
    global_non_negative_pct = _percentage(global_non_negative, len(global_interpretations))
    base_counts = _count_interpretations(base_interpretations)
    stability_counts = {
        name: sum(item["stability_classification"] == name for item in scenario_stability)
        for name in ("STABLE_POSITIVE", "PARAMETER_SENSITIVE", "STABLE_NEGATIVE")
    }
    robust_rule = gate["robustness_rules"]["ROBUST"]
    conditional_rule = gate["robustness_rules"]["CONDITIONALLY_ROBUST"]
    robust = (
        global_non_negative_pct >= float(robust_rule["minimum_global_non_negative_pct"])
        and base_counts["MODEL_FAVORS_A303_OFF"] <= int(robust_rule["maximum_base_case_negative_count"])
        and central_negative_count <= int(robust_rule["maximum_central_negative_result_count"])
        and stability_counts["STABLE_POSITIVE"] >= int(robust_rule["minimum_stable_positive_package_count"])
        and stability_counts["STABLE_NEGATIVE"] <= int(robust_rule["maximum_stable_negative_package_count"])
    )
    conditional = (
        global_non_negative_pct >= float(conditional_rule["minimum_global_non_negative_pct"])
        and base_counts["MODEL_FAVORS_A303_OFF"] <= int(conditional_rule["maximum_base_case_negative_count"])
    )
    robustness_status = "ROBUST" if robust else "CONDITIONALLY_ROBUST" if conditional else "NOT_ROBUST"
    changed_keys = set(attributed)
    decision_quality_counts = _dq_counts(quality_summary, review_bundle, changed_keys)
    current_sydney_date = datetime.now(ZoneInfo("Australia/Sydney")).date().isoformat()
    return {
        "schema_version": REPORT_VERSION,
        "as_of_date": current_sydney_date,
        "run_classification": "PRE_SPECIFIED_SYNTHETIC_ROBUSTNESS_EVALUATION",
        "frozen_inputs": {
            "simulator_digest": canonical_digest(simulator),
            "sensitivity_protocol_digest": canonical_digest(protocol),
            "capability_gate_digest": canonical_digest(gate),
            "review_bundle_digest": review_bundle["bundle_digest"],
        },
        "coverage": {
            "scenario_count": 10,
            "decision_package_count": 30,
            "attributed_change_count": 16,
            "negative_control_count": 14,
            "parameter_combination_count": len(combinations),
            "central_combination_count": sum(item["is_central"] for item in combinations),
        },
        "negative_control_integrity": {
            "status": "PASS",
            "packages_checked": 14,
            "combinations_per_package": len(combinations),
            "paired_comparisons_checked": 14 * len(combinations),
            "non_zero_delta_count": 0,
        },
        "base_case": {"attributed_package_counts": base_counts},
        "global_robustness": {
            "attributed_package_combination_count": len(global_interpretations),
            "interpretation_counts": global_counts,
            "global_non_negative_pct": global_non_negative_pct,
            "central_negative_result_count": central_negative_count,
        },
        "scenario_stability": sorted(scenario_stability, key=lambda item: (item["scenario_id"], item["cutoff_id"])),
        "decision_flip_boundaries": sorted(flip_boundaries, key=lambda item: (item["scenario_id"], item["cutoff_id"])),
        "capability_gate": {
            "synthetic_outcome_robustness": robustness_status,
            "scenario_stability_counts": stability_counts,
            "thresholds_frozen_before_run": True,
        },
        "evaluation_layers": {
            "system_correctness": {"status": "PASS_LOCAL_DETERMINISTIC_READ_ONLY"},
            "capability_attribution": {"status": "PASS_LOCAL_PAIRED_REPLAY", "attributed_change_count": 16},
            "decision_quality": {"status": "EVALUATED_MIXED", "counts": decision_quality_counts},
            "business_outcome_effect": {
                "status": "EVALUATED_SIMULATION_ONLY",
                "outcome_evidence_class": "SIMULATED_COUNTERFACTUAL",
                "real_business_outcome_effect": "NOT_EVALUATED",
            },
        },
        "execution_boundary": simulator["authority"],
        "claim_boundary": {
            "supports": [
                "SYNTHETIC_COUNTERFACTUAL_OUTCOME_ROBUSTNESS",
                "SYNTHETIC_DECISION_FLIP_BOUNDARIES",
                "SIMULATOR_NEGATIVE_CONTROL_VALIDATION",
            ],
            "does_not_support": ["REAL_LOGISTICS_PERFORMANCE", "EMPIRICAL_CALIBRATION", "PRODUCTION_READINESS", "MODEL_PROMOTION", "POLICY_ACTIVATION"],
        },
        "operational_mutations": [],
    }


def render_markdown(report: dict[str, Any]) -> str:
    base = report["base_case"]["attributed_package_counts"]
    global_result = report["global_robustness"]
    stability = report["capability_gate"]["scenario_stability_counts"]
    dq = report["evaluation_layers"]["decision_quality"]["counts"]
    return "\n".join(
        [
            "# A303 Synthetic Outcome Robustness v1",
            "",
            f"- Classification: `{report['capability_gate']['synthetic_outcome_robustness']}`",
            f"- Coverage: {report['coverage']['scenario_count']} scenarios / {report['coverage']['decision_package_count']} packages / {report['coverage']['attributed_change_count']} attributed changes / {report['coverage']['negative_control_count']} controls",
            f"- Base case: {base['MODEL_FAVORS_A303_ON']} positive / {base['MODEL_FAVORS_A303_OFF']} negative / {base['NO_MATERIAL_MODELED_DIFFERENCE']} neutral",
            f"- Global non-negative: {global_result['global_non_negative_pct']}% across {global_result['attributed_package_combination_count']} attributed package-combinations",
            f"- Scenario stability: {stability['STABLE_POSITIVE']} stable-positive / {stability['PARAMETER_SENSITIVE']} parameter-sensitive / {stability['STABLE_NEGATIVE']} stable-negative",
            f"- Negative controls: {report['negative_control_integrity']['paired_comparisons_checked']} exact-zero checks passed",
            f"- Decision Quality: {dq['FAVORS_A303_ON']} ON / {dq['FAVORS_A303_OFF']} OFF / {dq['INCONCLUSIVE']} inconclusive",
            "- Real Business Outcome Effect: `NOT_EVALUATED`",
            "",
            "All economic values and parameter ranges are synthetic plausibility assumptions. This report does not establish realised savings, real logistics performance, empirical calibration, production readiness, policy activation, or model promotion.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-quality-evidence", type=Path, required=True)
    parser.add_argument("--simulator", type=Path, default=ROOT / "docs" / "a303_outcome_simulator_v1.json")
    parser.add_argument("--sensitivity-protocol", type=Path, default=ROOT / "docs" / "a303_outcome_sensitivity_protocol_v1.json")
    parser.add_argument("--capability-gate", type=Path, default=ROOT / "docs" / "a303_synthetic_capability_gate_v1.json")
    parser.add_argument("--review-bundle", type=Path, default=ROOT / "blinded-review-survey" / "data" / "review-bundle.json")
    parser.add_argument("--corpus-manifest", type=Path, default=ROOT / "tests" / "fixtures" / "historical_replay" / "corpus_v1.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_robustness(
        json.loads(args.simulator.read_text(encoding="utf-8")),
        json.loads(args.sensitivity_protocol.read_text(encoding="utf-8")),
        json.loads(args.capability_gate.read_text(encoding="utf-8")),
        json.loads(args.decision_quality_evidence.read_text(encoding="utf-8")),
        json.loads(args.review_bundle.read_text(encoding="utf-8")),
        json.loads(args.corpus_manifest.read_text(encoding="utf-8")),
        args.corpus_manifest.parent,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
