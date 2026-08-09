"""Validate the plan-only GLAP production-readiness governance contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "production_readiness_contract.json"
EXPECTED_VIEWS = {
    "vw_multimodal_shipment_daily_v1",
    "vw_multimodal_ops_daily_v1",
    "vw_multimodal_provider_daily_v1",
    "vw_multimodal_mode_decision_v1",
    "vw_multimodal_forecast_feature_daily_v1",
    "vw_multimodal_outcome_label_v1",
    "vw_multimodal_operational_baseline_v1",
}
FORBIDDEN_AUTHORITY = {
    "recurring_schedule_enabled",
    "production_alias_change_authorized",
    "production_table_write_authorized",
    "policy_activation_authorized",
    "model_promotion_authorized",
}


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "production-readiness-contract.v1":
        errors.append("unsupported schema_version")
    if contract.get("status") != "DESIGNED_NOT_DEPLOYED":
        errors.append("contract must remain explicitly not deployed")
    if contract.get("business_timezone") != "Australia/Sydney":
        errors.append("business timezone must remain Australia/Sydney")
    if contract.get("evidence_boundary") != "SYNTHETIC_ENGINEERING_ONLY":
        errors.append("evidence boundary must remain synthetic engineering only")

    authority = contract.get("authority", {})
    if authority.get("named_human_owner_required") is not True:
        errors.append("named human ownership must be required")
    for field in FORBIDDEN_AUTHORITY:
        if authority.get(field) is not False:
            errors.append(f"{field} must remain false")

    athena = contract.get("athena", {})
    if athena.get("workgroup_state") != "HUMAN_APPROVAL_REQUIRED":
        errors.append("Athena workgroup change must require human approval")
    if athena.get("engine_version") != 3:
        errors.append("Athena engine version 3 is required")
    if athena.get("encryption_required") is not True:
        errors.append("Athena result encryption is required")
    if athena.get("default_query_scan_budget_bytes") != 104857600:
        errors.append("existing governed query budget must remain 100 MiB")
    for query_class in athena.get("query_classes", []):
        budget = query_class.get("budget_bytes")
        enforcement = query_class.get("enforcement")
        if budget is None and enforcement != "MEASURE_BASELINE_BEFORE_WORKGROUP_CUTOFF":
            errors.append(f"{query_class.get('id')} lacks a measured-baseline gate")
        if budget is not None and (not isinstance(budget, int) or budget <= 0):
            errors.append(f"{query_class.get('id')} has an invalid budget")

    if set(contract.get("incremental_views", [])) != EXPECTED_VIEWS:
        errors.append("incremental view inventory is incomplete or unexpected")
    retention = contract.get("retention_proposals", [])
    if not retention or any(not isinstance(item.get("days"), int) or item["days"] <= 0 for item in retention):
        errors.append("retention proposals must use positive day counts")
    return errors


def main() -> int:
    errors = validate_contract(load_contract())
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    print("PASS: production-readiness contract is plan-only, bounded, and internally consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
