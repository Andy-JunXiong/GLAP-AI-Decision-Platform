"""Validate the repository-local human decision to retire A303.v1."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DECISION_VERSION = "a303-v1-retirement-decision.v1"


class RetirementDecisionError(ValueError):
    """Raised when the retirement decision or its evidence boundary drifts."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RetirementDecisionError(message)


def _exact_keys(value: object, expected: set[str], field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    actual = set(value)
    _require(
        actual == expected,
        f"{field} fields changed: missing={sorted(expected - actual)}, "
        f"unexpected={sorted(actual - expected)}",
    )


def _digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_retirement(
    decision: dict[str, Any],
    robustness_result: dict[str, Any],
    guardrail_result: dict[str, Any],
) -> dict[str, Any]:
    _exact_keys(
        decision,
        {
            "schema_version",
            "decision_status",
            "sydney_decision_date",
            "decision_source",
            "decision",
            "scope",
            "evidence_basis",
            "downstream_effect",
            "reopening_rule",
            "authority_boundary",
            "operational_mutations",
        },
        "retirement decision",
    )
    _require(decision["schema_version"] == DECISION_VERSION, "unsupported retirement decision")
    _require(
        decision["decision_status"] == "HUMAN_DECISION_RECORDED"
        and decision["decision_source"]
        == "EXPLICIT_HUMAN_PROJECT_OWNER_SESSION_SELECTION_OPTION_1"
        and decision["decision"] == "RETIRE_A303_V1_FROM_PROGRESSION",
        "A303.v1 retirement decision drifted",
    )
    scope = decision["scope"]
    _exact_keys(scope, {"rule_contract", "applies_to", "does_not_delete_or_rewrite"}, "retirement scope")
    _require(scope["rule_contract"] == "A303.v1", "retirement scope changed rule")
    _require(
        set(scope["applies_to"])
        == {
            "FURTHER_THRESHOLD_TUNING",
            "NEW_A303_V1_HOLDOUT",
            "PROSPECTIVE_OUTCOME_COLLECTION",
            "A303_V1_CALIBRATION",
            "RULE_OR_POLICY_ACTIVATION",
            "PRODUCTION_PROGRESSION",
        },
        "retirement progression boundary weakened",
    )
    _require(
        set(scope["does_not_delete_or_rewrite"])
        == {
            "FOUR_REVIEW_DECISION_QUALITY_EVIDENCE",
            "EXPLORATORY_CONDITIONAL_RUN",
            "V1_SYNTHETIC_ROBUSTNESS_RESULT",
            "V2_GUARDRAIL_DEVELOPMENT_RESULT",
            "ORIGINAL_REVIEW_SUBMISSIONS",
        },
        "retirement evidence preservation boundary drifted",
    )
    evidence = decision["evidence_basis"]
    _require(isinstance(evidence, list) and len(evidence) == 2, "retirement requires two evidence results")
    _require(
        evidence
        == [
            {
                "schema_version": "a303-synthetic-outcome-robustness-result.v1",
                "sha256": _digest(robustness_result),
                "finding": "NOT_ROBUST",
            },
            {
                "schema_version": "a303-v2-guardrail-development-result.v1",
                "sha256": _digest(guardrail_result),
                "finding": "NO_A303_V2_GUARDRAIL_CANDIDATE_PASSES_DEVELOPMENT_GATE",
            },
        ],
        "retirement evidence digest or finding drifted",
    )
    downstream = decision["downstream_effect"]
    _require(
        downstream
        == {
            "a303_v1_development_status": "RETIRED_FROM_PROGRESSION",
            "a303_v1_calibration_status": "CLOSED_NOT_APPLICABLE",
            "a303_v1_prospective_collection_status": "NOT_AUTHORIZED",
            "calibration_interface_status": "RETAINED_AS_INACTIVE_REUSABLE_INFRASTRUCTURE",
            "evaluation_history_status": "PRESERVED_READ_ONLY",
            "deployed_runtime_change": "NONE_A303_V1_WAS_NOT_DEPLOYED",
        },
        "retirement downstream effect drifted",
    )
    reopening = decision["reopening_rule"]
    _require(
        reopening
        == {
            "a303_v1_may_be_reactivated": False,
            "fundamentally_new_rule_requires_new_version": True,
            "new_explicit_human_authorization_required": True,
            "new_frozen_development_and_holdout_evidence_required": True,
        },
        "retirement reopening rule weakened",
    )
    authority = decision["authority_boundary"]
    _require(
        authority.get("scope") == "REPOSITORY_LOCAL_DEVELOPMENT_DIRECTION"
        and all(value is False for key, value in authority.items() if key != "scope"),
        "retirement decision gained operational authority",
    )
    _require(decision["operational_mutations"] == [], "retirement decision contains operational mutations")
    return {
        "schema_version": "a303-v1-retirement-validation.v1",
        "status": "PASS",
        "decision": decision["decision"],
        "development_status": downstream["a303_v1_development_status"],
        "evidence_history": downstream["evaluation_history_status"],
        "operational_mutations": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decision",
        type=Path,
        default=ROOT / "docs" / "a303_v1_retirement_decision.json",
    )
    parser.add_argument(
        "--robustness-result",
        type=Path,
        default=ROOT / "docs" / "a303_synthetic_outcome_robustness_result_v1.json",
    )
    parser.add_argument(
        "--guardrail-result",
        type=Path,
        default=ROOT / "docs" / "a303_v2_guardrail_development_result_v1.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_retirement(
        json.loads(args.decision.read_text(encoding="utf-8")),
        json.loads(args.robustness_result.read_text(encoding="utf-8")),
        json.loads(args.guardrail_result.read_text(encoding="utf-8")),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
