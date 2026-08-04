"""Non-writing staging target used to verify pipeline control flow safely."""

from __future__ import annotations

from datetime import date
from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    event = event if isinstance(event, dict) else {}
    logical_run_date = event.get("logical_run_date") or event.get("run_date")
    if not isinstance(logical_run_date, str):
        raise ValueError("logical_run_date is required")
    date.fromisoformat(logical_run_date)
    return {
        "status": "ok",
        "logical_run_date": logical_run_date,
        "pipeline_stage": str(event.get("pipeline_stage") or "unknown")[:48],
        "stub": True,
        "writes_performed": 0,
    }
