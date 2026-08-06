"""Shared temporal-truthfulness rules for operational and simulation runs."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


OPERATIONAL = "OPERATIONAL"
FUTURE_SIMULATION = "FUTURE_SIMULATION"
ALLOWED_EXECUTION_MODES = {OPERATIONAL, FUTURE_SIMULATION}
SAFE_SCENARIO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _first_sunday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def _sydney_offset_without_tzdata(now_utc: datetime) -> timedelta:
    """Apply the current NSW DST rule when an OS has no IANA timezone data."""
    year = now_utc.year
    dst_end_local = _first_sunday(year, 4)
    dst_start_local = _first_sunday(year, 10)
    dst_end_utc = datetime(
        year, 4, dst_end_local.day, 3, tzinfo=timezone.utc
    ) - timedelta(hours=11)
    dst_start_utc = datetime(
        year, 10, dst_start_local.day, 2, tzinfo=timezone.utc
    ) - timedelta(hours=10)
    return timedelta(hours=11 if now_utc < dst_end_utc or now_utc >= dst_start_utc else 10)


def sydney_business_date(now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        return now.astimezone(ZoneInfo("Australia/Sydney")).date()
    except ZoneInfoNotFoundError:
        now_utc = now.astimezone(timezone.utc)
        return (now_utc + _sydney_offset_without_tzdata(now_utc)).date()


def resolve_temporal_context(
    logical_run_date: str,
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
    allow_future_simulation: bool | None = None,
    environment: str | None = None,
) -> dict[str, str | None]:
    logical_date = date.fromisoformat(logical_run_date)
    as_of_date = sydney_business_date(now)
    execution_mode = str(event.get("execution_mode") or OPERATIONAL).strip().upper()
    if execution_mode not in ALLOWED_EXECUTION_MODES:
        raise ValueError("execution_mode must be OPERATIONAL or FUTURE_SIMULATION")

    supplied_as_of = event.get("as_of_date")
    if supplied_as_of is not None and str(supplied_as_of) != as_of_date.isoformat():
        raise ValueError("as_of_date is system-derived and must match the Sydney business date")

    if execution_mode == OPERATIONAL:
        if logical_date > as_of_date:
            raise ValueError(
                f"Operational logical_run_date {logical_date.isoformat()} exceeds "
                f"Sydney as_of_date {as_of_date.isoformat()}"
            )
        if event.get("scenario_id"):
            raise ValueError("OPERATIONAL runs must not set scenario_id")
        expected_basis = "ACTUAL_CALENDAR"
        scenario_id = None
    else:
        allowed = (
            allow_future_simulation
            if allow_future_simulation is not None
            else _enabled(os.getenv("ALLOW_FUTURE_SIMULATION"))
        )
        deployment_environment = str(
            environment if environment is not None else os.getenv("PIPELINE_ENVIRONMENT", "")
        ).strip().lower()
        if not allowed or deployment_environment != "staging":
            raise ValueError("FUTURE_SIMULATION is allowed only in an explicitly enabled staging environment")
        scenario_id = str(event.get("scenario_id") or "").strip()
        if not SAFE_SCENARIO_ID.fullmatch(scenario_id):
            raise ValueError("FUTURE_SIMULATION requires a safe scenario_id of 3 to 64 characters")
        expected_basis = "FUTURE_SIMULATION"

    supplied_basis = event.get("time_basis")
    if supplied_basis is not None and str(supplied_basis) != expected_basis:
        raise ValueError("time_basis does not match execution_mode")

    return {
        "execution_mode": execution_mode,
        "time_basis": expected_basis,
        "as_of_date": as_of_date.isoformat(),
        "scenario_id": scenario_id,
    }
