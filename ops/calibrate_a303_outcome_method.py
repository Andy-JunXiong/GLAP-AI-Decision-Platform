"""Calibrate the frozen A303 outcome model against governed independent evidence.

The runner is local and read-only. Empty or insufficient evidence produces an
explicit evidence blocker; test fixtures never become calibration evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
INPUT_VERSION = "a303-outcome-calibration-input.v1"
POLICY_VERSION = "a303-outcome-calibration-policy.v1"
REPORT_VERSION = "a303-outcome-calibration-report.v1"
ROBUSTNESS_REPORT_VERSION = "a303-synthetic-outcome-robustness-report.v1"
SOURCE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")


class CalibrationError(ValueError):
    """Raised when calibration evidence or governance boundaries drift."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ROBUSTNESS = _load_module(
    "glap_a303_outcome_robustness_for_calibration",
    Path(__file__).with_name("evaluate_a303_outcome_robustness.py"),
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CalibrationError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    actual = set(value)
    _require(
        actual == expected,
        f"{field} fields changed: missing={sorted(expected - actual)}, "
        f"unexpected={sorted(actual - expected)}",
    )


def _canonical_digest(value: dict[str, Any]) -> str:
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


def _timestamp(value: object, field: str) -> datetime:
    _require(isinstance(value, str) and bool(value), f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalibrationError(f"{field} must be ISO-8601") from exc
    _require(parsed.tzinfo is not None, f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_policy(policy: dict[str, Any]) -> None:
    _exact_keys(
        policy,
        {"schema_version", "business_timezone", "simulator", "eligible_evidence", "thresholds", "authority", "claim_boundary"},
        "calibration policy",
    )
    _require(policy["schema_version"] == POLICY_VERSION, "unsupported calibration policy")
    _require(policy["business_timezone"] == "Australia/Sydney", "calibration timezone changed")
    eligible = policy["eligible_evidence"]
    _exact_keys(
        eligible,
        {
            "baseline_observation",
            "controlled_pair",
            "required_time_basis",
            "minimum_baseline_observations",
            "minimum_controlled_pairs",
        },
        "eligible evidence",
    )
    _require(
        set(eligible["baseline_observation"]) == {"OBSERVED_FACTUAL", "PROSPECTIVE_CONTROLLED"}
        and eligible["controlled_pair"] == ["PROSPECTIVE_CONTROLLED"]
        and eligible["required_time_basis"] == "ACTUAL_CALENDAR",
        "calibration evidence classes changed",
    )
    for field in ("minimum_baseline_observations", "minimum_controlled_pairs"):
        _require(
            isinstance(eligible[field], int) and not isinstance(eligible[field], bool) and eligible[field] >= 3,
            f"{field} must be at least three",
        )
    thresholds = policy["thresholds"]
    _exact_keys(
        thresholds,
        {
            "maximum_delay_mae_hours",
            "maximum_stockout_exposure_mae_days",
            "maximum_intervention_cost_mae_index",
            "minimum_treatment_direction_agreement_pct",
        },
        "calibration thresholds",
    )
    for field, value in thresholds.items():
        _number(value, field)
    authority = policy["authority"]
    _exact_keys(
        authority,
        {
            "mode",
            "network_access_allowed",
            "operational_writes_allowed",
            "action_mutations_allowed",
            "production_effect",
            "model_promotion_allowed",
        },
        "calibration authority",
    )
    _require(authority["mode"] == "LOCAL_READ_ONLY", "calibration must remain local read-only")
    _require(
        all(authority[field] is False for field in authority if field != "mode"),
        "calibration cannot gain network, mutation, production, or promotion authority",
    )
    boundary = policy["claim_boundary"]
    _exact_keys(boundary, {"supports", "does_not_support"}, "calibration claim boundary")
    _require(
        "FUTURE_EMPIRICAL_CALIBRATION_INTERFACE" in boundary["supports"]
        and {"MODEL_PROMOTION", "PRODUCTION_READINESS", "POLICY_ACTIVATION"}.issubset(
            set(boundary["does_not_support"])
        ),
        "calibration claim boundary expanded",
    )


def _metrics(value: object, field: str) -> dict[str, float]:
    _exact_keys(value, {"delay_hours", "stockout_exposure_days", "intervention_cost_index"}, field)
    assert isinstance(value, dict)
    return {
        "delay_hours": _number(value["delay_hours"], f"{field}.delay_hours"),
        "stockout_exposure_days": _number(value["stockout_exposure_days"], f"{field}.stockout_exposure_days"),
        "intervention_cost_index": _number(value["intervention_cost_index"], f"{field}.intervention_cost_index"),
    }


def _validate_modeled_report(report: dict[str, Any], simulator: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    _require(report.get("schema_version") == ROBUSTNESS_REPORT_VERSION, "unsupported modeled outcome report")
    _require(
        report.get("frozen_inputs", {}).get("simulator_digest") == _canonical_digest(simulator),
        "modeled report does not match the frozen outcome simulator",
    )
    _require(
        report.get("evaluation_layers", {}).get("business_outcome_effect", {}).get("outcome_evidence_class") == "SIMULATED_COUNTERFACTUAL"
        and report.get("evaluation_layers", {}).get("business_outcome_effect", {}).get("real_business_outcome_effect") == "NOT_EVALUATED",
        "modeled input must remain simulated counterfactual",
    )
    _require(report.get("operational_mutations") == [], "modeled report contains operational mutations")
    packages = report.get("scenario_stability")
    _require(isinstance(packages, list) and bool(packages), "modeled report has no package outcomes")
    package_map = {(item.get("scenario_id"), item.get("cutoff_id")): item for item in packages}
    _require(len(package_map) == len(packages), "modeled report contains duplicate scenario cutoffs")
    return package_map


def _modeled_metrics(package: dict[str, Any], variant_id: str) -> dict[str, float]:
    variants = {item["variant_id"]: item["metrics"] for item in package["base_case_variants"]}
    _require(variant_id in variants, f"modeled report is missing {variant_id}")
    metrics = variants[variant_id]
    return {
        "delay_hours": float(metrics["expected_delay_hours"]),
        "stockout_exposure_days": float(metrics["stockout_exposure_days"]),
        "intervention_cost_index": float(metrics["intervention_cost_index"]),
    }


def _loss(metrics: dict[str, float], simulator: dict[str, Any], package: dict[str, Any]) -> float:
    defaults = simulator["sensitivity_parameter_defaults"]
    fixed = simulator["fixed_parameters"]
    criticality_multiplier = float(
        fixed["sla_criticality_multipliers"][package["sla_criticality"]]
    )
    return (
        metrics["delay_hours"] / 24.0
        * float(defaults["service_impact_cost_per_delay_day_index"])
        * criticality_multiplier
        + metrics["stockout_exposure_days"]
        * float(defaults["stockout_penalty_per_exposed_day_index"])
        + metrics["intervention_cost_index"]
    )


def _mae(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def calibrate(
    simulator: dict[str, Any],
    modeled_report: dict[str, Any],
    evidence: dict[str, Any],
    policy: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess calibration readiness and, when eligible, compare modeled metrics."""

    _ROBUSTNESS.validate_simulator(simulator)
    validate_policy(policy)
    _require(
        policy["simulator"].get("schema_version") == simulator["schema_version"]
        and policy["simulator"].get("sha256") == _canonical_digest(simulator),
        "calibration policy does not bind the frozen simulator",
    )
    packages = _validate_modeled_report(modeled_report, simulator)
    _exact_keys(
        evidence,
        {
            "schema_version",
            "evidence_set_id",
            "collection_status",
            "independent_validation_attested",
            "observations",
            "operational_mutations",
        },
        "calibration input",
    )
    _require(evidence["schema_version"] == INPUT_VERSION, "unsupported calibration input")
    _require(
        isinstance(evidence["evidence_set_id"], str) and SAFE_ID.fullmatch(evidence["evidence_set_id"]) is not None,
        "unsafe calibration evidence-set ID",
    )
    _require(evidence["collection_status"] in {"DRAFT", "FROZEN"}, "invalid collection status")
    _require(evidence["operational_mutations"] == [], "calibration input cannot contain operational mutations")
    observations = evidence["observations"]
    _require(isinstance(observations, list), "calibration observations must be an array")
    if observations:
        _require(
            evidence["collection_status"] == "FROZEN" and evidence["independent_validation_attested"] is True,
            "non-empty calibration evidence must be frozen and independently attested",
        )
    else:
        _require(
            isinstance(evidence["independent_validation_attested"], bool),
            "independent validation attestation must be boolean",
        )

    current = now or datetime.now(ZoneInfo("Australia/Sydney"))
    _require(current.tzinfo is not None, "current time must include a timezone")
    current_utc = current.astimezone(timezone.utc)
    eligible = policy["eligible_evidence"]
    ids: set[str] = set()
    baseline_errors = {"delay": [], "stockout": [], "cost": []}
    treatment_errors = {"delay": [], "stockout": [], "cost": []}
    direction_matches: list[bool] = []
    kind_counts = {"BASELINE_OBSERVATION": 0, "CONTROLLED_PAIR": 0}

    common_keys = {
        "observation_id",
        "observation_kind",
        "scenario_id",
        "cutoff_id",
        "outcome_evidence_class",
        "time_basis",
        "observed_at",
        "source_available_at",
        "source_digest",
        "independent_evaluator_attested",
    }
    for item in observations:
        kind = item.get("observation_kind") if isinstance(item, dict) else None
        extra = (
            {"observed_variant_id", "metrics"}
            if kind == "BASELINE_OBSERVATION"
            else {"baseline_metrics", "a303_metrics"}
            if kind == "CONTROLLED_PAIR"
            else set()
        )
        _require(bool(extra), "unsupported calibration observation kind")
        _exact_keys(item, common_keys | extra, "calibration observation")
        observation_id = item["observation_id"]
        _require(isinstance(observation_id, str) and SAFE_ID.fullmatch(observation_id) is not None, "unsafe observation ID")
        _require(observation_id not in ids, "duplicate calibration observation ID")
        ids.add(observation_id)
        evidence_class = item["outcome_evidence_class"]
        _require(
            evidence_class in eligible["baseline_observation" if kind == "BASELINE_OBSERVATION" else "controlled_pair"],
            f"{kind} uses an ineligible evidence class",
        )
        _require(item["time_basis"] == eligible["required_time_basis"], "calibration requires ACTUAL_CALENDAR")
        _require(item["independent_evaluator_attested"] is True, "calibration observation lacks independent attestation")
        _require(isinstance(item["source_digest"], str) and SOURCE_DIGEST.fullmatch(item["source_digest"]) is not None, "invalid calibration source digest")
        observed_at = _timestamp(item["observed_at"], "observed_at")
        source_available_at = _timestamp(item["source_available_at"], "source_available_at")
        _require(observed_at <= source_available_at <= current_utc, "calibration source is future-dated or available before observation")
        key = (item["scenario_id"], item["cutoff_id"])
        _require(key in packages, "calibration observation is outside the modeled package set")
        package = packages[key]
        modeled_baseline = _modeled_metrics(package, "baseline-a303-off")

        if kind == "BASELINE_OBSERVATION":
            _require(item["observed_variant_id"] == "baseline-a303-off", "factual observation cannot claim an unchosen A303 variant")
            actual_baseline = _metrics(item["metrics"], "baseline metrics")
            kind_counts[kind] += 1
            baseline_errors["delay"].append(abs(modeled_baseline["delay_hours"] - actual_baseline["delay_hours"]))
            baseline_errors["stockout"].append(abs(modeled_baseline["stockout_exposure_days"] - actual_baseline["stockout_exposure_days"]))
            baseline_errors["cost"].append(abs(modeled_baseline["intervention_cost_index"] - actual_baseline["intervention_cost_index"]))
            continue

        _require(evidence_class == "PROSPECTIVE_CONTROLLED", "treatment calibration requires prospective controlled evidence")
        actual_baseline = _metrics(item["baseline_metrics"], "controlled baseline metrics")
        actual_a303 = _metrics(item["a303_metrics"], "controlled A303 metrics")
        modeled_a303 = _modeled_metrics(package, "glap-a303-on")
        kind_counts[kind] += 1
        baseline_errors["delay"].append(abs(modeled_baseline["delay_hours"] - actual_baseline["delay_hours"]))
        baseline_errors["stockout"].append(abs(modeled_baseline["stockout_exposure_days"] - actual_baseline["stockout_exposure_days"]))
        baseline_errors["cost"].append(abs(modeled_baseline["intervention_cost_index"] - actual_baseline["intervention_cost_index"]))
        treatment_errors["delay"].append(
            abs((modeled_baseline["delay_hours"] - modeled_a303["delay_hours"]) - (actual_baseline["delay_hours"] - actual_a303["delay_hours"]))
        )
        treatment_errors["stockout"].append(
            abs((modeled_baseline["stockout_exposure_days"] - modeled_a303["stockout_exposure_days"]) - (actual_baseline["stockout_exposure_days"] - actual_a303["stockout_exposure_days"]))
        )
        treatment_errors["cost"].append(
            abs((modeled_baseline["intervention_cost_index"] - modeled_a303["intervention_cost_index"]) - (actual_baseline["intervention_cost_index"] - actual_a303["intervention_cost_index"]))
        )
        modeled_delta = _loss(modeled_baseline, simulator, package) - _loss(modeled_a303, simulator, package)
        actual_delta = _loss(actual_baseline, simulator, package) - _loss(actual_a303, simulator, package)
        material = float(simulator["fixed_parameters"]["minimum_material_loss_delta"])
        modeled_direction = 1 if modeled_delta >= material else -1 if modeled_delta <= -material else 0
        actual_direction = 1 if actual_delta >= material else -1 if actual_delta <= -material else 0
        direction_matches.append(modeled_direction == actual_direction)

    baseline_count = len(baseline_errors["delay"])
    pair_count = kind_counts["CONTROLLED_PAIR"]
    baseline_metrics = {
        "eligible_observation_count": baseline_count,
        "delay_mae_hours": _mae(baseline_errors["delay"]),
        "stockout_exposure_mae_days": _mae(baseline_errors["stockout"]),
        "intervention_cost_mae_index": _mae(baseline_errors["cost"]),
    }
    agreement = round(sum(direction_matches) / len(direction_matches) * 100.0, 2) if direction_matches else None
    treatment_metrics = {
        "eligible_controlled_pair_count": pair_count,
        "delay_effect_mae_hours": _mae(treatment_errors["delay"]),
        "stockout_exposure_effect_mae_days": _mae(treatment_errors["stockout"]),
        "intervention_cost_effect_mae_index": _mae(treatment_errors["cost"]),
        "treatment_direction_agreement_pct": agreement,
    }
    thresholds = policy["thresholds"]
    blockers = []
    if baseline_count < eligible["minimum_baseline_observations"]:
        blockers.append("INSUFFICIENT_BASELINE_OBSERVATIONS")
    if pair_count < eligible["minimum_controlled_pairs"]:
        blockers.append("INSUFFICIENT_PROSPECTIVE_CONTROLLED_PAIRS")
    if not observations:
        status = "BLOCKED_EVIDENCE"
    elif blockers:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        checks_pass = (
            baseline_metrics["delay_mae_hours"] <= thresholds["maximum_delay_mae_hours"]
            and baseline_metrics["stockout_exposure_mae_days"] <= thresholds["maximum_stockout_exposure_mae_days"]
            and baseline_metrics["intervention_cost_mae_index"] <= thresholds["maximum_intervention_cost_mae_index"]
            and treatment_metrics["delay_effect_mae_hours"] <= thresholds["maximum_delay_mae_hours"]
            and treatment_metrics["stockout_exposure_effect_mae_days"] <= thresholds["maximum_stockout_exposure_mae_days"]
            and treatment_metrics["intervention_cost_effect_mae_index"] <= thresholds["maximum_intervention_cost_mae_index"]
            and agreement >= thresholds["minimum_treatment_direction_agreement_pct"]
        )
        status = "CALIBRATION_CHECKS_PASS" if checks_pass else "CALIBRATION_CHECKS_FAIL"

    as_of_date = current.astimezone(ZoneInfo("Australia/Sydney")).date().isoformat()
    return {
        "schema_version": REPORT_VERSION,
        "as_of_date": as_of_date,
        "evidence_set": {
            "evidence_set_id": evidence["evidence_set_id"],
            "collection_status": evidence["collection_status"],
            "independent_validation_attested": evidence["independent_validation_attested"],
            "observation_count": len(observations),
            "observation_kind_counts": kind_counts,
        },
        "method": {
            "schema_version": simulator["schema_version"],
            "method_digest": _canonical_digest(simulator),
            "calibration_policy_version": policy["schema_version"],
            "calibration_policy_digest": _canonical_digest(policy),
        },
        "readiness": {"status": status, "blockers": blockers},
        "calibration_metrics": {
            "baseline_level": baseline_metrics,
            "treatment_effect": treatment_metrics,
            "thresholds": thresholds,
        },
        "execution_boundary": policy["authority"],
        "claim_boundary": policy["claim_boundary"],
        "operational_mutations": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modeled-report", type=Path, required=True)
    parser.add_argument("--calibration-input", type=Path, required=True)
    parser.add_argument(
        "--simulator",
        type=Path,
        default=ROOT / "docs" / "a303_outcome_simulator_v1.json",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "docs" / "a303_outcome_calibration_policy_v1.json",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = calibrate(
        json.loads(args.simulator.read_text(encoding="utf-8")),
        json.loads(args.modeled_report.read_text(encoding="utf-8")),
        json.loads(args.calibration_input.read_text(encoding="utf-8")),
        json.loads(args.policy.read_text(encoding="utf-8")),
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
