"""Deterministic GLAP shipment lifecycle engine for the AWS staging slice.

The engine is intentionally storage-agnostic. AWS integration reads/writes the
versioned Iceberg contracts while tests and 28-day replay use the same pure
functions. ETD and ETA are the single immutable P2P commitments. ATD and ATA
are written once when their actual milestone is observed.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from typing import Any, Iterable


UTC = timezone.utc
TERMINAL_STAGES = {"DELIVERED", "CANCELLED"}
STAGE_ORDER = {
    "BOOKED": 0,
    "ORIGIN_PROCESSING": 1,
    "GATE_IN": 2,
    "IN_TRANSIT": 3,
    "ARRIVED_PORT": 4,
    "DESTINATION_PROCESSING": 5,
    "DELIVERED": 6,
}
REQUIRED_TARGETS = {
    "BOOKING_TO_GATE_IN",
    "GATE_IN_TO_ETD",
    "ATA_TO_DISCHARGED",
    "DISCHARGED_TO_DELIVERED",
}
MULTIMODAL_TARGETS = {
    "BOOKING_TO_ORIGIN_HANDOVER",
    "ORIGIN_HANDOVER_TO_DEPARTURE",
    "ARRIVAL_TO_DESTINATION_RELEASE",
    "DESTINATION_RELEASE_TO_DELIVERY",
}
# A 17-shipment deterministic cycle yields 17.65% DHL Air and splits the
# remaining Ocean bookings evenly between Maersk and KN (41.18% each).
PROVIDER_CYCLE = (
    "DHL", "MAERSK", "KN", "MAERSK", "KN", "MAERSK",
    "DHL", "KN", "MAERSK", "KN", "MAERSK", "KN",
    "DHL", "MAERSK", "KN", "MAERSK", "KN",
)


def _stable_int(*parts: object, modulo: int) -> int:
    value = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(value).digest()[:8], "big") % modulo


def _at_noon(value: date) -> datetime:
    return datetime.combine(value, time(12), tzinfo=UTC)


def _days(value: datetime, count: int) -> datetime:
    return value + timedelta(days=count)


def validate_targets(targets: dict[str, int], transport_mode: str | None = None) -> None:
    if REQUIRED_TARGETS <= set(targets):
        if any(not isinstance(targets[name], int) or targets[name] < 0 for name in REQUIRED_TARGETS):
            raise ValueError("Lifecycle target days must be non-negative integers")
        return
    modes = (transport_mode,) if transport_mode else ("OCEAN", "AIR")
    required = {f"{mode}:{stage}" for mode in modes for stage in MULTIMODAL_TARGETS}
    missing = required - set(targets)
    if missing:
        raise ValueError(f"Missing lifecycle targets: {', '.join(sorted(missing))}")
    if any(not isinstance(targets[name], int) or targets[name] < 0 for name in required):
        raise ValueError("Lifecycle target hours must be non-negative integers")


def _target_hours(
    targets: dict[str, int], transport_mode: str, stage: str, legacy_stage: str
) -> int:
    key = f"{transport_mode}:{stage}"
    if key in targets:
        return int(targets[key])
    if legacy_stage in targets:
        return int(targets[legacy_stage]) * 24
    raise ValueError(f"Missing lifecycle target: {key}")


def validate_routes(routes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in routes]
    if not rows:
        raise ValueError("At least one active route service is required")
    identities: set[str] = set()
    for row in rows:
        required = {
            "route_service_id",
            "origin_port",
            "destination_port",
            "carrier",
            "service_code",
            "service_level",
            "p2p_target_days",
            "config_version",
        }
        if required - set(row):
            raise ValueError("Route service contract is incomplete")
        if row["route_service_id"] in identities:
            raise ValueError("Duplicate route_service_id")
        identities.add(row["route_service_id"])
        mode = str(row.get("transport_mode") or "OCEAN").upper()
        if mode not in {"OCEAN", "AIR"}:
            raise ValueError("transport_mode must be OCEAN or AIR")
        row["transport_mode"] = mode
        row["provider_type"] = row.get("provider_type") or (
            "OCEAN_CARRIER" if row["carrier"] == "MAERSK" else "LOGISTICS_PROVIDER"
        )
        row["origin_location_type"] = row.get("origin_location_type") or (
            "AIRPORT" if mode == "AIR" else "PORT"
        )
        row["destination_location_type"] = row.get("destination_location_type") or (
            "AIRPORT" if mode == "AIR" else "PORT"
        )
        row["operating_carrier"] = row.get("operating_carrier") or row["carrier"]
        row["equipment_type"] = row.get("equipment_type") or (
            "AIR_CARGO" if mode == "AIR" else "40HC"
        )
        if row.get("p2p_target_hours") is None:
            if not isinstance(row.get("p2p_target_days"), int) or row["p2p_target_days"] <= 0:
                raise ValueError("Route requires positive p2p_target_hours or p2p_target_days")
            row["p2p_target_hours"] = int(row["p2p_target_days"]) * 24
        row["p2p_target_hours"] = int(row["p2p_target_hours"])
        if row["p2p_target_hours"] <= 0:
            raise ValueError("p2p_target_hours must be positive")
    return rows


def _select_route(
    routes: list[dict[str, Any]], booking_date: date, sequence: int, seed_version: str
) -> dict[str, Any]:
    providers = {str(row["carrier"]).upper() for row in routes}
    shipment_id = f"SHP-{booking_date:%Y%m%d}-{sequence:04d}"
    if {"MAERSK", "KN", "DHL"} <= providers:
        slot = (booking_date.toordinal() * 16 + sequence - 1) % len(PROVIDER_CYCLE)
        provider = PROVIDER_CYCLE[slot]
        candidates = [row for row in routes if str(row["carrier"]).upper() == provider]
    else:
        candidates = routes
    return candidates[_stable_int(seed_version, shipment_id, "route", modulo=len(candidates))]


def calculate_tiered_charge(charge_days: int, tiers: Iterable[dict[str, Any]]) -> float:
    """Apply inclusive day-number tiers; free tiers use a zero daily rate."""

    if charge_days <= 0:
        return 0.0
    total = 0.0
    last_to = 0
    for tier in sorted(tiers, key=lambda row: int(row["from_day"])):
        start = int(tier["from_day"])
        end_value = tier.get("to_day")
        end = int(end_value) if end_value is not None else charge_days
        if start != last_to + 1:
            raise ValueError("Rate tiers must be continuous and non-overlapping")
        if end < start:
            raise ValueError("Rate tier end must not precede start")
        used_end = min(end, charge_days)
        if used_end >= start:
            total += (used_end - start + 1) * float(tier["daily_rate"])
        last_to = end
        if used_end == charge_days:
            break
    if last_to < charge_days:
        raise ValueError("Rate tiers do not cover all charge days")
    return round(total, 2)


def calculate_expected_cost(
    shipment: dict[str, Any],
    rate_cards: Iterable[dict[str, Any]],
    fx_rates: dict[tuple[str, str], float],
    reporting_currency: str = "AUD",
) -> tuple[float, list[dict[str, Any]]]:
    """Select the most specific rate per charge and return auditable lines."""

    booking_at = shipment.get("booking_at")
    if not isinstance(booking_at, datetime):
        raise ValueError("Shipment booking_at is required to lock a Rate Card")
    booking_date = booking_at.date()

    def as_date(value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    matching: dict[str, tuple[int, dict[str, Any]]] = {}
    dimensions = (
        "transport_mode", "origin_port", "destination_port", "carrier",
        "service_code", "equipment_type",
    )
    transport_mode = str(shipment.get("transport_mode") or "OCEAN")
    for rate in rate_cards:
        if rate.get("status", "ACTIVE") != "ACTIVE":
            continue
        effective_from = as_date(rate.get("effective_from"))
        effective_to = as_date(rate.get("effective_to"))
        if effective_from and booking_date < effective_from:
            continue
        if effective_to and booking_date > effective_to:
            continue
        rate_mode = str(rate.get("transport_mode") or "OCEAN")
        if rate_mode not in {"*", transport_mode}:
            continue
        if any(
            str(rate.get(name, "*")) not in {"*", str(shipment.get(name))}
            for name in dimensions if name != "transport_mode"
        ):
            continue
        basis = rate.get("calculation_basis")
        if basis not in {
            "PER_SHIPMENT", "PER_CONTAINER", "PER_TEU", "PER_PIECE",
            "PER_CHARGEABLE_KG", "PERCENT_OF_BASE",
        }:
            raise ValueError("Unsupported rate calculation basis")
        score = sum(str(rate.get(name, "*")) != "*" for name in dimensions)
        code = str(rate["charge_code"])
        if code not in matching or score > matching[code][0]:
            matching[code] = (score, rate)
        elif score == matching[code][0]:
            raise ValueError(f"Ambiguous active rate for {code}")

    base_code = "AIR_FREIGHT" if transport_mode == "AIR" else "OCEAN_FREIGHT"
    if base_code not in matching:
        raise ValueError(f"No active {base_code} rate matches shipment")
    base_rate = matching[base_code][1]
    base_quantity = (
        float(shipment["chargeable_weight_kg"])
        if transport_mode == "AIR" else float(shipment["container_count"])
    )
    base_amount = float(base_rate["amount"]) * base_quantity
    lines: list[dict[str, Any]] = []
    total = 0.0
    for code, (_, rate) in sorted(matching.items()):
        basis = rate["calculation_basis"]
        if basis == "PER_SHIPMENT":
            quantity = 1.0
            source_amount = float(rate["amount"])
        elif basis == "PER_CONTAINER":
            quantity = float(shipment["container_count"])
            source_amount = float(rate["amount"]) * quantity
        elif basis == "PER_TEU":
            quantity = float(shipment["container_count"]) * 2.0
            source_amount = float(rate["amount"]) * quantity
        elif basis == "PER_PIECE":
            quantity = float(shipment["piece_count"])
            source_amount = float(rate["amount"]) * quantity
        elif basis == "PER_CHARGEABLE_KG":
            quantity = float(shipment["chargeable_weight_kg"])
            source_amount = float(rate["amount"]) * quantity
        else:
            quantity = 1.0
            source_amount = base_amount * float(rate["percentage_rate"])
        currency = str(rate["currency"])
        try:
            fx_rate = float(fx_rates[(currency, reporting_currency)])
        except KeyError as exc:
            raise ValueError(f"Missing FX rate {currency}/{reporting_currency}") from exc
        reporting_amount = round(source_amount * fx_rate, 2)
        total += reporting_amount
        lines.append(
            {
                "charge_code": code,
                "calculation_basis": basis,
                "quantity": quantity,
                "unit_rate": float(rate.get("amount") or 0),
                "source_amount": round(source_amount, 2),
                "source_currency": currency,
                "fx_rate": fx_rate,
                "amount": reporting_amount,
                "currency": reporting_currency,
                "rate_card_id": rate["rate_card_id"],
                "rate_card_version": rate["config_version"],
                "cost_status": "EXPECTED",
            }
        )
    return round(total, 2), lines


def _exception(shipment_id: str, seed_version: str) -> tuple[str | None, int]:
    # One journey-level draw produces a stable 5% exception cohort.
    cohort = _stable_int(seed_version, shipment_id, "exception", modulo=100)
    if cohort >= 5:
        return None, 0
    kinds = ("ORIGIN_DELAY", "P2P_DELAY", "DESTINATION_DELAY")
    kind = kinds[_stable_int(seed_version, shipment_id, "kind", modulo=len(kinds))]
    hours = 24 * (1 + _stable_int(seed_version, shipment_id, "hours", modulo=4))
    return kind, hours


def create_shipment(
    booking_date: date,
    sequence: int,
    routes: Iterable[dict[str, Any]],
    targets: dict[str, int],
    seed_version: str = "lifecycle-2026.09-multimodal-v1",
    rate_card_version: str = "rate-2026.08-v1",
    rate_cards: Iterable[dict[str, Any]] | None = None,
    fx_rates: dict[tuple[str, str], float] | None = None,
) -> dict[str, Any]:
    route_rows = validate_routes(routes)
    route_rows = [
        row for row in route_rows
        if (not row.get("effective_from") or booking_date >= date.fromisoformat(str(row["effective_from"])))
        and (not row.get("effective_to") or booking_date <= date.fromisoformat(str(row["effective_to"])))
    ]
    if not route_rows:
        raise ValueError("No route service is effective on booking date")
    shipment_id = f"SHP-{booking_date:%Y%m%d}-{sequence:04d}"
    route = _select_route(route_rows, booking_date, sequence, seed_version)
    transport_mode = str(route["transport_mode"])
    validate_targets(targets, transport_mode)
    booking_at = _at_noon(booking_date)
    origin_target_hours = _target_hours(
        targets, transport_mode, "BOOKING_TO_ORIGIN_HANDOVER", "BOOKING_TO_GATE_IN"
    )
    departure_hours = _target_hours(
        targets, transport_mode, "ORIGIN_HANDOVER_TO_DEPARTURE", "GATE_IN_TO_ETD"
    )
    origin_handover_target_at = booking_at + timedelta(hours=origin_target_hours)
    etd = origin_handover_target_at + timedelta(hours=departure_hours)
    eta = etd + timedelta(hours=int(route["p2p_target_hours"]))
    exception_type, exception_hours = _exception(shipment_id, seed_version)
    if transport_mode == "AIR":
        container_count = 0
        piece_count = 1 + _stable_int(seed_version, shipment_id, "pieces", modulo=12)
        gross_weight_kg = float(
            40 + _stable_int(seed_version, shipment_id, "gross-kg", modulo=961)
        )
        volume_cbm = round(
            0.2 + _stable_int(seed_version, shipment_id, "volume-litres", modulo=5801) / 1000,
            3,
        )
        chargeable_weight_kg = round(max(gross_weight_kg, volume_cbm * 167.0), 2)
    else:
        container_count = 1 + _stable_int(seed_version, shipment_id, "containers", modulo=3)
        piece_count = container_count * 100
        gross_weight_kg = float(container_count * 24000)
        volume_cbm = round(container_count * 67.7, 2)
        chargeable_weight_kg = gross_weight_kg
    shipment = {
        "shipment_id": shipment_id,
        "booking_at": booking_at,
        "transport_mode": transport_mode,
        "provider_type": route["provider_type"],
        "operating_carrier": route["operating_carrier"],
        "origin_location_type": route["origin_location_type"],
        "destination_location_type": route["destination_location_type"],
        "origin_handover_target_at": origin_handover_target_at,
        "origin_handover_at": None,
        "destination_release_target_at": None,
        "destination_release_at": None,
        "gate_in_target_at": origin_handover_target_at if transport_mode == "OCEAN" else None,
        "gate_in_at": None,
        "etd": etd,
        "atd": None,
        "eta": eta,
        "ata": None,
        "discharge_target_at": None,
        "discharged_at": None,
        "delivery_target_at": None,
        "delivered_at": None,
        "lifecycle_stage": "BOOKED",
        "lifecycle_status": "OPEN",
        "terminal_state": False,
        "origin_port": route["origin_port"],
        "destination_port": route["destination_port"],
        "carrier": route["carrier"],
        "route_service_id": route["route_service_id"],
        "route_config_version": route["config_version"],
        "rate_card_version": rate_card_version,
        "rate_locked_at": booking_at,
        "service_code": route["service_code"],
        "service_level": route["service_level"],
        "equipment_type": route["equipment_type"],
        "container_count": container_count,
        "piece_count": piece_count,
        "gross_weight_kg": gross_weight_kg,
        "volume_cbm": volume_cbm,
        "chargeable_weight_kg": chargeable_weight_kg,
        "journey_exception_type": exception_type,
        "journey_exception_hours": exception_hours,
        "simulation_seed": seed_version,
        "created_at": booking_at,
        "updated_at": booking_at,
    }
    shipment["expected_total_cost"] = None
    shipment["accrued_total_cost"] = 0.0
    shipment["actual_total_cost"] = None
    shipment["cost_currency"] = "AUD"
    shipment["expected_cost_lines"] = []
    if rate_cards is not None:
        total, lines = calculate_expected_cost(shipment, rate_cards, fx_rates or {})
        shipment["expected_total_cost"] = total
        shipment["expected_cost_lines"] = lines
        versions = {line["rate_card_version"] for line in lines}
        if len(versions) != 1:
            raise ValueError("A Booking must lock one coherent Rate Card version")
        shipment["rate_card_version"] = versions.pop()
    return shipment


def _actual_milestones(shipment: dict[str, Any], targets: dict[str, int]) -> dict[str, datetime]:
    transport_mode = str(shipment.get("transport_mode") or "OCEAN")
    exception = shipment.get("journey_exception_type")
    delay = timedelta(hours=int(shipment.get("journey_exception_hours") or 0))
    origin_handover = shipment["origin_handover_target_at"] + (
        delay if exception == "ORIGIN_DELAY" else timedelta()
    )
    departure_hours = _target_hours(
        targets, transport_mode, "ORIGIN_HANDOVER_TO_DEPARTURE", "GATE_IN_TO_ETD"
    )
    atd = max(shipment["etd"], origin_handover + timedelta(hours=departure_hours))
    planned_p2p = shipment["eta"] - shipment["etd"]
    ata = atd + planned_p2p
    if exception == "P2P_DELAY":
        ata += delay
    release_hours = _target_hours(
        targets, transport_mode, "ARRIVAL_TO_DESTINATION_RELEASE", "ATA_TO_DISCHARGED"
    )
    delivery_hours = _target_hours(
        targets, transport_mode, "DESTINATION_RELEASE_TO_DELIVERY", "DISCHARGED_TO_DELIVERED"
    )
    destination_release = ata + timedelta(hours=release_hours)
    delivered = destination_release + timedelta(hours=delivery_hours)
    if exception == "DESTINATION_DELAY":
        delivered += delay
    return {
        "origin_handover_at": origin_handover,
        "atd": atd,
        "ata": ata,
        "destination_release_at": destination_release,
        "delivered_at": delivered,
    }


def _milestone_performance(
    target: datetime | None, actual: datetime | None, cutoff: datetime
) -> tuple[str, float | None]:
    if target is None:
        return "NOT_APPLICABLE", None
    if actual is not None:
        delay = max(0.0, (actual - target).total_seconds() / 3600.0)
        return ("LATE" if delay > 0 else "ON_TIME"), round(delay, 2)
    if cutoff > target:
        return "OVERDUE", round((cutoff - target).total_seconds() / 3600.0, 2)
    return "PENDING", None


def calculate_lifecycle_metrics(snapshot: dict[str, Any], logical_date: date) -> dict[str, Any]:
    """Calculate auditable Origin, P2P and Destination milestone performance."""

    cutoff = datetime.combine(logical_date, time.max, tzinfo=UTC)
    origin_status, origin_delay = _milestone_performance(
        snapshot.get("origin_handover_target_at", snapshot.get("gate_in_target_at")),
        snapshot.get("origin_handover_at", snapshot.get("gate_in_at")), cutoff,
    )
    departure_status, departure_delay = _milestone_performance(
        snapshot.get("etd"), snapshot.get("atd"), cutoff
    )
    arrival_status, arrival_delay = _milestone_performance(
        snapshot.get("eta"), snapshot.get("ata"), cutoff
    )
    release_status, release_delay = _milestone_performance(
        snapshot.get("destination_release_target_at", snapshot.get("discharge_target_at")),
        snapshot.get("destination_release_at", snapshot.get("discharged_at")), cutoff,
    )
    delivery_status, delivery_delay = _milestone_performance(
        snapshot.get("delivery_target_at"), snapshot.get("delivered_at"), cutoff
    )
    mode = str(snapshot.get("transport_mode") or "OCEAN")
    origin_stage = "ORIGIN_HANDOVER" if mode == "AIR" else "ORIGIN_GATE_IN"
    release_stage = "DESTINATION_RELEASE" if mode == "AIR" else "DESTINATION_DISCHARGE"
    statuses = {
        origin_stage: origin_status,
        "P2P_DEPARTURE": departure_status,
        "P2P_ARRIVAL": arrival_status,
        release_stage: release_status,
        "FINAL_DELIVERY": delivery_status,
    }
    breached = [stage for stage, status in statuses.items() if status in {"LATE", "OVERDUE"}]
    planned_p2p_hours = (
        round((snapshot["eta"] - snapshot["etd"]).total_seconds() / 3600.0, 2)
        if snapshot.get("eta") and snapshot.get("etd") else None
    )
    actual_p2p_hours = (
        round((snapshot["ata"] - snapshot["atd"]).total_seconds() / 3600.0, 2)
        if snapshot.get("ata") and snapshot.get("atd") else None
    )
    return {
        "shipment_id": snapshot["shipment_id"],
        "dt": logical_date.isoformat(),
        "lifecycle_stage": snapshot["lifecycle_stage"],
        "lifecycle_status": snapshot["lifecycle_status"],
        "origin_performance": origin_status,
        "origin_delay_hours": origin_delay,
        "gate_in_performance": origin_status,
        "gate_in_delay_hours": origin_delay,
        "departure_performance": departure_status,
        "departure_delay_hours": departure_delay,
        "arrival_performance": arrival_status,
        "arrival_delay_hours": arrival_delay,
        "destination_release_performance": release_status,
        "destination_release_delay_hours": release_delay,
        "discharge_performance": release_status,
        "discharge_delay_hours": release_delay,
        "delivery_performance": delivery_status,
        "delivery_delay_hours": delivery_delay,
        "planned_p2p_hours": planned_p2p_hours,
        "actual_p2p_hours": actual_p2p_hours,
        "sla_breach_flag": bool(breached),
        "sla_breach_stages": ",".join(breached) if breached else None,
        "computed_at": _at_noon(logical_date),
    }


def build_candidate_signals(
    snapshot: dict[str, Any], metrics: dict[str, Any], cost_threshold_pct: float = 10.0
) -> list[dict[str, Any]]:
    """Build stable, aggregate-ready signal candidates for downstream alerts."""

    delay_fields = {
        "ORIGIN_GATE_IN": "gate_in_delay_hours",
        "ORIGIN_HANDOVER": "origin_delay_hours",
        "P2P_DEPARTURE": "departure_delay_hours",
        "P2P_ARRIVAL": "arrival_delay_hours",
        "DESTINATION_DISCHARGE": "discharge_delay_hours",
        "DESTINATION_RELEASE": "destination_release_delay_hours",
        "FINAL_DELIVERY": "delivery_delay_hours",
    }
    signals: list[dict[str, Any]] = []
    for stage in (metrics.get("sla_breach_stages") or "").split(","):
        if not stage:
            continue
        metric_name = delay_fields[stage]
        value = float(metrics.get(metric_name) or 0)
        if str(snapshot.get("transport_mode") or "OCEAN") == "AIR":
            severity = "CRITICAL" if value >= 24 else "HIGH" if value >= 12 else "MEDIUM" if value >= 6 else "LOW"
        else:
            severity = "CRITICAL" if value >= 72 else "HIGH" if value >= 48 else "MEDIUM" if value >= 24 else "LOW"
        fingerprint = hashlib.sha256(
            f"SLA_BREACH|{snapshot['shipment_id']}|{stage}".encode("utf-8")
        ).hexdigest()[:32]
        signals.append({
            "signal_fingerprint": fingerprint,
            "shipment_id": snapshot["shipment_id"],
            "dt": metrics["dt"],
            "signal_type": "SLA_BREACH",
            "signal_grain": "SHIPMENT_MILESTONE",
            "signal_dimension": stage,
            "metric_name": metric_name,
            "metric_value": value,
            "threshold_value": 0.0,
            "severity": severity,
            "candidate_status": "ACTIVE" if snapshot["lifecycle_status"] == "OPEN" else "RESOLVED",
            "simulation_provenance": "SIMULATED",
            "computed_at": metrics["computed_at"],
        })

    expected = snapshot.get("expected_total_cost")
    observed = snapshot.get("actual_total_cost")
    if observed is None:
        observed = snapshot.get("accrued_total_cost")
    if expected and observed is not None:
        variance_pct = 100.0 * (float(observed) - float(expected)) / float(expected)
        if variance_pct > cost_threshold_pct:
            fingerprint = hashlib.sha256(
                f"COST_ANOMALY|{snapshot['shipment_id']}|TOTAL_COST".encode("utf-8")
            ).hexdigest()[:32]
            signals.append({
                "signal_fingerprint": fingerprint,
                "shipment_id": snapshot["shipment_id"],
                "dt": metrics["dt"],
                "signal_type": "COST_ANOMALY",
                "signal_grain": "SHIPMENT_COST",
                "signal_dimension": "TOTAL_COST",
                "metric_name": "cost_variance_pct",
                "metric_value": round(variance_pct, 2),
                "threshold_value": float(cost_threshold_pct),
                "severity": "CRITICAL" if variance_pct >= 35 else "HIGH" if variance_pct >= 20 else "MEDIUM",
                "candidate_status": "ACTIVE" if snapshot["lifecycle_status"] == "OPEN" else "RESOLVED",
                "simulation_provenance": "SIMULATED",
                "computed_at": metrics["computed_at"],
            })
    return signals


def _event(shipment: dict[str, Any], event_type: str, event_time: datetime,
           logical_date: date, location: str, segment_type: str = "P2P",
           leg_seq: int = 2) -> dict[str, Any]:
    event_id = hashlib.sha256(
        f"{shipment['shipment_id']}|{event_type}|{event_time.isoformat()}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "event_id": event_id,
        "shipment_id": shipment["shipment_id"],
        "transport_mode": shipment.get("transport_mode", "OCEAN"),
        "segment_type": segment_type,
        "leg_seq": leg_seq,
        "event_type": event_type,
        "event_time": event_time,
        "observed_at": _at_noon(logical_date),
        "processed_at": _at_noon(logical_date),
        "location": location,
        "location_type": (
            shipment.get("origin_location_type", "PORT")
            if segment_type == "ORIGIN" else shipment.get("destination_location_type", "PORT")
        ),
        "logical_run_date": logical_date,
        "scenario_id": shipment.get("journey_exception_type"),
        "simulation_seed": shipment["simulation_seed"],
    }


def advance_shipment(
    source: dict[str, Any], logical_date: date, targets: dict[str, int]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Advance one active shipment and return today's snapshot and new events."""

    transport_mode = str(source.get("transport_mode") or "OCEAN")
    validate_targets(targets, transport_mode)
    if (source.get("terminal_state") or source.get("lifecycle_status") == "CLOSED"
            or source.get("lifecycle_stage") in TERMINAL_STAGES):
        return None, []
    shipment = deepcopy(source)
    shipment.setdefault("transport_mode", transport_mode)
    shipment.setdefault("provider_type", "OCEAN_CARRIER" if shipment.get("carrier") == "MAERSK" else "LOGISTICS_PROVIDER")
    shipment.setdefault("operating_carrier", shipment.get("carrier"))
    shipment.setdefault("origin_location_type", "AIRPORT" if transport_mode == "AIR" else "PORT")
    shipment.setdefault("destination_location_type", "AIRPORT" if transport_mode == "AIR" else "PORT")
    shipment.setdefault("origin_handover_target_at", shipment.get("gate_in_target_at"))
    shipment.setdefault("origin_handover_at", shipment.get("gate_in_at"))
    shipment.setdefault("destination_release_target_at", shipment.get("discharge_target_at"))
    shipment.setdefault("destination_release_at", shipment.get("discharged_at"))
    shipment.setdefault("piece_count", int(shipment.get("container_count") or 0) * 100)
    shipment.setdefault("gross_weight_kg", float(shipment.get("container_count") or 0) * 24000.0)
    shipment.setdefault("volume_cbm", float(shipment.get("container_count") or 0) * 67.7)
    shipment.setdefault("chargeable_weight_kg", shipment["gross_weight_kg"])
    immutable_etd = shipment["etd"]
    immutable_eta = shipment["eta"]
    actual = _actual_milestones(shipment, targets)
    cutoff = datetime.combine(logical_date, time.max, tzinfo=UTC)
    events: list[dict[str, Any]] = []

    if transport_mode == "AIR":
        milestones = (
            ("origin_handover_at", "ORIGIN_RECEIVED", "ORIGIN_HANDOVER", shipment["origin_port"], "ORIGIN", 1),
            ("atd", "FLIGHT_DEPARTED", "IN_TRANSIT", shipment["origin_port"], "P2P", 2),
            ("ata", "FLIGHT_ARRIVED", "ARRIVED_AIRPORT", shipment["destination_port"], "P2P", 2),
            ("destination_release_at", "CARGO_AVAILABLE", "DESTINATION_PROCESSING", shipment["destination_port"], "DESTINATION", 3),
            ("delivered_at", "DELIVERED", "DELIVERED", shipment["destination_port"], "DESTINATION", 3),
        )
    else:
        milestones = (
            ("origin_handover_at", "GATE_IN", "GATE_IN", shipment["origin_port"], "ORIGIN", 1),
            ("atd", "DEPARTED", "IN_TRANSIT", shipment["origin_port"], "P2P", 2),
            ("ata", "ARRIVED", "ARRIVED_PORT", shipment["destination_port"], "P2P", 2),
            ("destination_release_at", "DISCHARGED", "DESTINATION_PROCESSING", shipment["destination_port"], "DESTINATION", 3),
            ("delivered_at", "DELIVERED", "DELIVERED", shipment["destination_port"], "DESTINATION", 3),
        )
    for field, event_type, stage, location, segment_type, leg_seq in milestones:
        if shipment.get(field) is None and actual[field] <= cutoff:
            shipment[field] = actual[field]
            if field == "origin_handover_at" and transport_mode == "OCEAN":
                shipment["gate_in_at"] = actual[field]
            if field == "destination_release_at" and transport_mode == "OCEAN":
                shipment["discharged_at"] = actual[field]
            shipment["lifecycle_stage"] = stage
            events.append(_event(
                shipment, event_type, actual[field], logical_date, location, segment_type, leg_seq
            ))
            if field == "ata":
                release_hours = _target_hours(
                    targets, transport_mode, "ARRIVAL_TO_DESTINATION_RELEASE", "ATA_TO_DISCHARGED"
                )
                shipment["destination_release_target_at"] = actual[field] + timedelta(hours=release_hours)
                if transport_mode == "OCEAN":
                    shipment["discharge_target_at"] = shipment["destination_release_target_at"]
            if field == "destination_release_at":
                delivery_hours = _target_hours(
                    targets, transport_mode, "DESTINATION_RELEASE_TO_DELIVERY", "DISCHARGED_TO_DELIVERED"
                )
                shipment["delivery_target_at"] = actual[field] + timedelta(hours=delivery_hours)

    if shipment["lifecycle_stage"] == "BOOKED" and logical_date > shipment["booking_at"].date():
        shipment["lifecycle_stage"] = "ORIGIN_PROCESSING"
    shipment["terminal_state"] = shipment["lifecycle_stage"] == "DELIVERED"
    shipment["lifecycle_status"] = "CLOSED" if shipment["terminal_state"] else "OPEN"
    shipment["updated_at"] = _at_noon(logical_date)
    shipment["dt"] = logical_date.isoformat()
    if shipment["etd"] != immutable_etd or shipment["eta"] != immutable_eta:
        raise ValueError("ETD and ETA are immutable P2P commitments")
    return shipment, events


def run_day(
    active_shipments: Iterable[dict[str, Any]],
    logical_date: date,
    routes: Iterable[dict[str, Any]],
    targets: dict[str, int],
    seed_version: str = "lifecycle-2026.09-multimodal-v1",
    new_count: int | None = None,
    rate_cards: Iterable[dict[str, Any]] | None = None,
    fx_rates: dict[tuple[str, str], float] | None = None,
) -> dict[str, Any]:
    """Advance active population and add a reproducible normal daily cohort."""

    route_rows = validate_routes(routes)
    if new_count is None:
        new_count = 14 + _stable_int(seed_version, logical_date, "daily-volume", modulo=5)
    if not 0 <= new_count <= 1000:
        raise ValueError("new_count must be between 0 and 1000")

    snapshots: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in active_shipments:
        shipment_id = str(source.get("shipment_id") or "")
        if not shipment_id or shipment_id in seen:
            raise ValueError("Active population contains a missing or duplicate shipment_id")
        seen.add(shipment_id)
        snapshot, new_events = advance_shipment(source, logical_date, targets)
        if snapshot is not None:
            snapshots.append(snapshot)
            events.extend(new_events)

    for sequence in range(1, new_count + 1):
        shipment = create_shipment(
            logical_date, sequence, route_rows, targets, seed_version,
            rate_cards=rate_cards, fx_rates=fx_rates,
        )
        if shipment["shipment_id"] in seen:
            raise ValueError("New shipment ID collides with active population")
        snapshot, new_events = advance_shipment(shipment, logical_date, targets)
        assert snapshot is not None
        snapshots.append(snapshot)
        events.append(_event(
            snapshot, "BOOKING_CONFIRMED", snapshot["booking_at"], logical_date,
            snapshot["origin_port"], "ORIGIN", 1,
        ))
        events.extend(new_events)

    metrics = [calculate_lifecycle_metrics(snapshot, logical_date) for snapshot in snapshots]
    signals = [
        signal
        for snapshot, metric in zip(snapshots, metrics)
        for signal in build_candidate_signals(snapshot, metric)
    ]
    return {
        "status": "success",
        "logical_run_date": logical_date.isoformat(),
        "new_shipments": new_count,
        "active_snapshots": len(snapshots),
        "events_created": len(events),
        "snapshots": snapshots,
        "events": events,
        "metrics": metrics,
        "signals": signals,
    }


def seed_population(
    logical_date: date,
    routes: Iterable[dict[str, Any]],
    targets: dict[str, int],
    population_size: int = 450,
    seed_version: str = "lifecycle-2026.09-multimodal-v1",
    rate_cards: Iterable[dict[str, Any]] | None = None,
    fx_rates: dict[tuple[str, str], float] | None = None,
) -> list[dict[str, Any]]:
    """Create a representative active population across lifecycle stages."""

    if not 1 <= population_size <= 5000:
        raise ValueError("population_size must be between 1 and 5000")
    route_rows = validate_routes(routes)
    population: list[dict[str, Any]] = []
    # Work backwards in daily cohorts. A 60-day bound safely covers the seeded
    # route matrix and destination targets without creating terminal carryover.
    # The seed represents opening inventory before the logical run starts.
    # Today's cohort is created by run_day, so start with yesterday to avoid
    # duplicating deterministic shipment IDs on the initial replay date.
    for age_days in range(1, 62):
        booking_date = logical_date - timedelta(days=age_days)
        cohort_size = 14 + _stable_int(seed_version, booking_date, "seed-volume", modulo=5)
        for sequence in range(1, cohort_size + 1):
            shipment = create_shipment(
                booking_date, sequence, route_rows, targets, seed_version,
                rate_cards=rate_cards, fx_rates=fx_rates,
            )
            snapshot, _ = advance_shipment(shipment, logical_date, targets)
            if snapshot is not None and not snapshot["terminal_state"]:
                population.append(snapshot)
                if len(population) == population_size:
                    stages = {row["lifecycle_stage"] for row in population}
                    if len(stages) < 3:
                        raise ValueError("Seeded population is not representative")
                    return population
    raise ValueError("Configured routes cannot support requested active seed population")


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dry-run/replay entry point; governed AWS persistence is added at deployment."""

    logical_date = date.fromisoformat(event["logical_run_date"])
    active_shipments = event.get("active_shipments", [])
    if event.get("seed_population"):
        active_shipments = seed_population(
            logical_date,
            event["routes"],
            event["targets"],
            int(event.get("population_size", 450)),
            event.get("seed_version", "lifecycle-2026.09-multimodal-v1"),
        )
    result = run_day(
        active_shipments,
        logical_date,
        event["routes"],
        event["targets"],
        event.get("seed_version", "lifecycle-2026.09-multimodal-v1"),
        event.get("new_count"),
    )
    # The controller needs counts, never entity records. Full rows remain in
    # the private persistence adapter or explicit local replay response.
    if not event.get("include_private_rows", False):
        result.pop("snapshots")
        result.pop("events")
        result.pop("metrics")
        result.pop("signals")
    return result
