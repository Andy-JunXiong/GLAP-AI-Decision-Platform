"""Render a redacted local plan. This script performs no network call or write."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambda"))
from glap_temporal_boundary import sydney_business_date  # noqa: E402

from validate_action_complete_outcome_canary import load_contract, validate_contract


def build_plan() -> dict[str, object]:
    contract = load_contract()
    errors = validate_contract(contract)
    if errors:
        raise ValueError("; ".join(errors))
    phases = contract["phases"]
    return {
        "schema_version": "action-complete-outcome-canary-plan.v1",
        "status": contract["status"],
        "generated_on_sydney_date": sydney_business_date().isoformat(),
        "external_writes_executed": False,
        "authority": contract["authority"],
        "phase_order": contract["phase_order"],
        "phases": [
            {
                "phase": phase,
                "mode": phases[phase]["mode"],
                "authorization_required": "AUTHORIZATION_REQUIRED" in phases[phase]["mode"],
            }
            for phase in contract["phase_order"]
        ],
    }


def main() -> int:
    print(json.dumps(build_plan(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
