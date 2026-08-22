"""Screen post-hoc A303.v2 guardrail candidates without activating a rule.

The runner reuses the frozen v1 robustness space, keeps all opportunities and
controls visible, and applies an anti-abstention gate. Because the candidates
were designed from the v1 result, this output is development evidence only and
can never satisfy an independent or confirmatory gate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_VERSION = "a303-v2-eligibility-guardrail-proposal.v1"
REPORT_VERSION = "a303-v2-guardrail-development-report.v1"
RESULT_VERSION = "a303-synthetic-outcome-robustness-result.v1"
INTERPRETATIONS = (
    "MODEL_FAVORS_A303_ON",
    "MODEL_FAVORS_A303_OFF",
    "NO_MATERIAL_MODELED_DIFFERENCE",
)


class GuardrailCandidateError(ValueError):
    """Raised when a proposal, frozen input, or candidate boundary drifts."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ROBUSTNESS = _load_module(
    "glap_a303_outcome_robustness_for_v2_guardrail",
    Path(__file__).with_name("evaluate_a303_outcome_robustness.py"),
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardrailCandidateError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    actual = set(value)
    _require(
        actual == expected,
        f"{field} fields changed: missing={sorted(expected - actual)}, "
        f"unexpected={sorted(actual - expected)}",
    )


def validate_proposal(
    proposal: dict[str, Any],
    source_result: dict[str, Any],
    simulator: dict[str, Any],
    protocol: dict[str, Any],
    gate: dict[str, Any],
) -> None:
    _exact_keys(
        proposal,
        {
            "schema_version",
            "proposal_status",
            "design_classification",
            "source_result",
            "frozen_evaluation_inputs",
            "candidate_policies",
            "anti_abstention_gate",
            "validation_boundary",
            "decision_options",
            "authority",
            "claim_boundary",
        },
        "A303.v2 proposal",
    )
    _require(proposal["schema_version"] == PROPOSAL_VERSION, "unsupported A303.v2 proposal")
    _require(
        proposal["proposal_status"] == "DEVELOPMENT_ONLY_PENDING_HUMAN_DECISION"
        and proposal["design_classification"] == "POST_HOC_CANDIDATE_FROM_V1_ROBUSTNESS",
        "A303.v2 proposal maturity drifted",
    )
    source = proposal["source_result"]
    _require(source_result.get("schema_version") == RESULT_VERSION, "unsupported v1 source result")
    _require(
        source.get("schema_version") == RESULT_VERSION
        and source.get("sha256") == _ROBUSTNESS.canonical_digest(source_result)
        and source.get("required_capability_gate") == "NOT_ROBUST"
        and source_result.get("capability_gate", {}).get("synthetic_outcome_robustness") == "NOT_ROBUST",
        "A303.v2 proposal does not bind the failed v1 result",
    )
    frozen = proposal["frozen_evaluation_inputs"]
    _require(
        frozen
        == {
            "simulator_sha256": _ROBUSTNESS.canonical_digest(simulator),
            "sensitivity_protocol_sha256": _ROBUSTNESS.canonical_digest(protocol),
            "capability_gate_sha256": _ROBUSTNESS.canonical_digest(gate),
        },
        "A303.v2 proposal frozen inputs drifted",
    )
    candidates = proposal["candidate_policies"]
    _require(isinstance(candidates, list) and len(candidates) == 2, "proposal must contain exactly two candidates")
    _require(
        [item.get("candidate_id") for item in candidates]
        == ["a303-v2-central-safe", "a303-v2-stable-positive-only"],
        "A303.v2 candidate membership drifted",
    )
    for item in candidates:
        _exact_keys(
            item,
            {"candidate_id", "description", "eligibility_conditions"},
            f"candidate {item.get('candidate_id')}",
        )
    anti_abstention = proposal["anti_abstention_gate"]
    _exact_keys(
        anti_abstention,
        {
            "minimum_action_opportunity_count",
            "minimum_distinct_action_scenario_count",
            "minimum_action_subset_non_negative_pct",
            "maximum_action_subset_base_negative_count",
            "maximum_action_subset_central_negative_result_count",
            "negative_controls_must_remain_exact_zero",
            "rationale",
        },
        "anti-abstention gate",
    )
    _require(
        anti_abstention["minimum_action_opportunity_count"] >= 3
        and anti_abstention["minimum_distinct_action_scenario_count"] >= 3
        and anti_abstention["minimum_action_subset_non_negative_pct"] >= 90.0
        and anti_abstention["maximum_action_subset_base_negative_count"] == 0
        and anti_abstention["maximum_action_subset_central_negative_result_count"] == 0
        and anti_abstention["negative_controls_must_remain_exact_zero"] is True,
        "anti-abstention gate weakened",
    )
    boundary = proposal["validation_boundary"]
    _require(
        boundary.get("same_corpus_result_classification") == "POST_HOC_DEVELOPMENT_EVIDENCE"
        and boundary.get("same_corpus_can_satisfy_confirmatory_gate") is False
        and boundary.get("new_frozen_holdout_required_before_progression") is True
        and boundary.get("human_approval_required_to_create_new_rule_version") is True
        and boundary.get("human_approval_required_to_retire_current_rule") is True,
        "post-hoc validation boundary expanded",
    )
    authority = proposal["authority"]
    _require(authority.get("mode") == "LOCAL_READ_ONLY", "proposal must remain local read-only")
    _require(
        all(value is False for key, value in authority.items() if key != "mode"),
        "proposal gained rule, policy, production, mutation, or collection authority",
    )


def _is_eligible(candidate: dict[str, Any], package: dict[str, Any]) -> bool:
    conditions = candidate["eligibility_conditions"]
    if conditions.get("v1_decision_changed") is not True:
        raise GuardrailCandidateError("candidate must remain bound to v1 attributed changes")
    if candidate["candidate_id"] == "a303-v2-central-safe":
        _exact_keys(
            conditions,
            {
                "v1_decision_changed",
                "required_base_case_interpretation",
                "maximum_central_negative_combination_count",
            },
            "central-safe eligibility",
        )
        return (
            package["base_case_interpretation"]
            == conditions["required_base_case_interpretation"]
            and package["central_negative_combination_count"]
            <= conditions["maximum_central_negative_combination_count"]
        )
    _exact_keys(
        conditions,
        {"v1_decision_changed", "required_stability_classification"},
        "stable-positive eligibility",
    )
    return package["stability_classification"] == conditions["required_stability_classification"]


def _candidate_result(
    candidate: dict[str, Any],
    packages: list[dict[str, Any]],
    parameter_count: int,
    controls_pass: bool,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    selected = [item for item in packages if _is_eligible(candidate, item)]
    action_counts = {
        name: sum(item["combination_counts"][name] for item in selected)
        for name in INTERPRETATIONS
    }
    action_total = sum(action_counts.values())
    action_non_negative = (
        action_counts["MODEL_FAVORS_A303_ON"]
        + action_counts["NO_MATERIAL_MODELED_DIFFERENCE"]
    )
    action_non_negative_pct = (
        round(action_non_negative / action_total * 100.0, 2) if action_total else 0.0
    )
    abstention_count = len(packages) - len(selected)
    full_counts = dict(action_counts)
    full_counts["NO_MATERIAL_MODELED_DIFFERENCE"] += abstention_count * parameter_count
    full_total = sum(full_counts.values())
    full_non_negative_pct = round(
        (
            full_counts["MODEL_FAVORS_A303_ON"]
            + full_counts["NO_MATERIAL_MODELED_DIFFERENCE"]
        )
        / full_total
        * 100.0,
        2,
    )
    checks = {
        "minimum_action_opportunity_count": len(selected)
        >= thresholds["minimum_action_opportunity_count"],
        "minimum_distinct_action_scenario_count": len(
            {item["scenario_id"] for item in selected}
        )
        >= thresholds["minimum_distinct_action_scenario_count"],
        "minimum_action_subset_non_negative_pct": action_non_negative_pct
        >= thresholds["minimum_action_subset_non_negative_pct"],
        "maximum_action_subset_base_negative_count": sum(
            item["base_case_interpretation"] == "MODEL_FAVORS_A303_OFF"
            for item in selected
        )
        <= thresholds["maximum_action_subset_base_negative_count"],
        "maximum_action_subset_central_negative_result_count": sum(
            item["central_negative_combination_count"] for item in selected
        )
        <= thresholds["maximum_action_subset_central_negative_result_count"],
        "negative_controls_exact_zero": controls_pass,
    }
    passed = all(checks.values())
    disposition = (
        "ELIGIBLE_FOR_NEW_HOLDOUT_DESIGN"
        if passed
        else "REJECT_OR_FUNDAMENTALLY_REDESIGN"
    )
    return {
        "candidate_id": candidate["candidate_id"],
        "development_disposition": disposition,
        "confirmatory_eligibility": "NOT_ELIGIBLE_POST_HOC_SAME_CORPUS",
        "coverage": {
            "action_opportunity_count": len(selected),
            "distinct_action_scenario_count": len({item["scenario_id"] for item in selected}),
            "abstention_opportunity_count": abstention_count,
            "negative_control_count": 14,
        },
        "selected_action_opportunities": [
            {"scenario_id": item["scenario_id"], "cutoff_id": item["cutoff_id"]}
            for item in selected
        ],
        "action_subset": {
            "package_combination_count": action_total,
            "interpretation_counts": action_counts,
            "non_negative_pct": action_non_negative_pct,
            "base_negative_count": sum(
                item["base_case_interpretation"] == "MODEL_FAVORS_A303_OFF"
                for item in selected
            ),
            "central_negative_result_count": sum(
                item["central_negative_combination_count"] for item in selected
            ),
        },
        "full_opportunity_set": {
            "package_combination_count": full_total,
            "interpretation_counts": full_counts,
            "non_negative_pct": full_non_negative_pct,
            "warning": "Full-set neutrality includes guardrail abstentions and cannot replace the action-subset gate.",
        },
        "anti_abstention_checks": checks,
        "failed_checks": [name for name, passed_check in checks.items() if not passed_check],
    }


def run_candidate_screen(
    proposal: dict[str, Any],
    source_result: dict[str, Any],
    simulator: dict[str, Any],
    protocol: dict[str, Any],
    gate: dict[str, Any],
    decision_quality_source: dict[str, Any],
    review_bundle: dict[str, Any],
    corpus_manifest: dict[str, Any],
    scenario_directory: Path,
) -> dict[str, Any]:
    validate_proposal(proposal, source_result, simulator, protocol, gate)
    v1_report = _ROBUSTNESS.run_robustness(
        simulator,
        protocol,
        gate,
        decision_quality_source,
        review_bundle,
        corpus_manifest,
        scenario_directory,
    )
    _require(
        v1_report["capability_gate"]["synthetic_outcome_robustness"] == "NOT_ROBUST",
        "candidate screen requires the failed v1 robustness result",
    )
    controls = v1_report["negative_control_integrity"]
    controls_pass = controls["status"] == "PASS" and controls["non_zero_delta_count"] == 0
    parameter_count = v1_report["coverage"]["parameter_combination_count"]
    candidate_results = [
        _candidate_result(
            candidate,
            v1_report["scenario_stability"],
            parameter_count,
            controls_pass,
            proposal["anti_abstention_gate"],
        )
        for candidate in proposal["candidate_policies"]
    ]
    any_holdout_candidate = any(
        item["development_disposition"] == "ELIGIBLE_FOR_NEW_HOLDOUT_DESIGN"
        for item in candidate_results
    )
    return {
        "schema_version": REPORT_VERSION,
        "run_classification": "POST_HOC_DEVELOPMENT_EVIDENCE",
        "proposal_digest": _ROBUSTNESS.canonical_digest(proposal),
        "source_result_digest": _ROBUSTNESS.canonical_digest(source_result),
        "v1_reproduction": {
            "capability_gate": v1_report["capability_gate"]["synthetic_outcome_robustness"],
            "attributed_change_count": v1_report["coverage"]["attributed_change_count"],
            "negative_control_count": v1_report["coverage"]["negative_control_count"],
            "parameter_combination_count": parameter_count,
        },
        "candidate_results": candidate_results,
        "slice_conclusion": {
            "status": (
                "CANDIDATE_AVAILABLE_FOR_NEW_HOLDOUT_DESIGN"
                if any_holdout_candidate
                else "NO_A303_V2_GUARDRAIL_CANDIDATE_PASSES_DEVELOPMENT_GATE"
            ),
            "human_decision_required": True,
            "decision_options": [item["option"] for item in proposal["decision_options"]],
        },
        "validation_boundary": proposal["validation_boundary"],
        "execution_boundary": proposal["authority"],
        "claim_boundary": proposal["claim_boundary"],
        "operational_mutations": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-quality-evidence", type=Path, required=True)
    parser.add_argument(
        "--proposal",
        type=Path,
        default=ROOT / "docs" / "a303_v2_eligibility_guardrail_proposal.json",
    )
    parser.add_argument(
        "--source-result",
        type=Path,
        default=ROOT / "docs" / "a303_synthetic_outcome_robustness_result_v1.json",
    )
    parser.add_argument("--simulator", type=Path, default=ROOT / "docs" / "a303_outcome_simulator_v1.json")
    parser.add_argument("--sensitivity-protocol", type=Path, default=ROOT / "docs" / "a303_outcome_sensitivity_protocol_v1.json")
    parser.add_argument("--capability-gate", type=Path, default=ROOT / "docs" / "a303_synthetic_capability_gate_v1.json")
    parser.add_argument("--review-bundle", type=Path, default=ROOT / "blinded-review-survey" / "data" / "review-bundle.json")
    parser.add_argument("--corpus-manifest", type=Path, default=ROOT / "tests" / "fixtures" / "historical_replay" / "corpus_v1.json")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_candidate_screen(
        json.loads(args.proposal.read_text(encoding="utf-8")),
        json.loads(args.source_result.read_text(encoding="utf-8")),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
