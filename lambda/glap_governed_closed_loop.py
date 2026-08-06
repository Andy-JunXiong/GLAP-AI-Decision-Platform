"""Deterministic, human-gated exception-to-outcome loop for GLAP staging.

The functions in this module are pure and storage agnostic.  They turn the
stateful lifecycle signal candidates into auditable alerts, actions, delayed
synthetic outcomes, learning evidence, and policy proposals.  Nothing here
activates a policy: activation always requires an explicit human approval.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
from typing import Any, Iterable


UTC = timezone.utc
OUTCOME_STATES = {"SUCCESSFUL", "PARTIALLY_SUCCESSFUL", "FAILED", "INCONCLUSIVE"}


def _stable_int(*parts: object, modulo: int) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % modulo


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:32]


def reconcile_alerts(
    candidates: Iterable[dict[str, Any]],
    previous_alerts: Iterable[dict[str, Any]],
    logical_date: date,
) -> list[dict[str, Any]]:
    """Carry alert identity across dates and explicitly close disappeared alerts."""

    previous = {str(row["alert_fingerprint"]): dict(row) for row in previous_alerts}
    current = {str(row["signal_fingerprint"]): dict(row) for row in candidates}
    reconciled: list[dict[str, Any]] = []
    observed_at = datetime.combine(logical_date, datetime.min.time(), tzinfo=UTC)
    for fingerprint, candidate in sorted(current.items()):
        prior = previous.get(fingerprint)
        first_detected = prior.get("first_detected_date") if prior else logical_date.isoformat()
        reconciled.append({
            "alert_fingerprint": fingerprint,
            "shipment_id": candidate["shipment_id"],
            "alert_type": candidate["signal_type"],
            "alert_grain": candidate["signal_grain"],
            "alert_dimension": candidate["signal_dimension"],
            "severity": candidate["severity"],
            "status": "OPEN",
            "first_detected_date": first_detected,
            "last_detected_date": logical_date.isoformat(),
            "resolved_date": None,
            "metric_name": candidate["metric_name"],
            "metric_value": candidate["metric_value"],
            "threshold_value": candidate["threshold_value"],
            "provenance": "SIMULATED",
            "updated_at": observed_at,
        })
    for fingerprint, prior in sorted(previous.items()):
        if fingerprint in current or prior.get("status") == "RESOLVED":
            continue
        closed = dict(prior)
        closed.update({"status": "RESOLVED", "resolved_date": logical_date.isoformat(), "updated_at": observed_at})
        reconciled.append(closed)
    return reconciled


def propose_actions(alerts: Iterable[dict[str, Any]], policy_version: str) -> list[dict[str, Any]]:
    """Create one stable, human-review-required action for every open alert."""

    actions = []
    for alert in alerts:
        if alert.get("status") != "OPEN":
            continue
        action_type = "EXPEDITE_MILESTONE" if alert["alert_type"] == "SLA_BREACH" else "REVIEW_COST"
        action_id = _fingerprint("ACTION", alert["alert_fingerprint"], policy_version)
        actions.append({
            "action_id": action_id,
            "alert_fingerprint": alert["alert_fingerprint"],
            "shipment_id": alert["shipment_id"],
            "action_type": action_type,
            "policy_version": policy_version,
            "status": "PROPOSED",
            "approval_required": True,
            "approved_by": None,
            "approved_at": None,
            "completed_at": None,
            "provenance": "SIMULATED",
        })
    return actions


def record_action_approval(action: dict[str, Any], actor: str, approved_at: datetime) -> dict[str, Any]:
    """Record explicit human approval; a system actor is not accepted."""

    if not actor.strip() or actor.strip().lower() in {"system", "automation", "model"}:
        raise ValueError("A named human reviewer is required")
    if action.get("status") != "PROPOSED":
        raise ValueError("Only a proposed action can be approved")
    approved = dict(action)
    approved.update({"status": "APPROVED", "approved_by": actor.strip(), "approved_at": approved_at})
    return approved


def complete_action(action: dict[str, Any], completed_at: datetime) -> dict[str, Any]:
    if action.get("status") != "APPROVED" or not action.get("approved_by"):
        raise ValueError("An action must be human-approved before completion")
    completed = dict(action)
    completed.update({"status": "COMPLETED", "completed_at": completed_at})
    return completed


def observe_outcome(
    action: dict[str, Any],
    alert: dict[str, Any],
    as_of_date: date,
    observation_lag_days: int = 3,
    context: dict[str, Any] | None = None,
    outcome_version: str = "outcome-v1",
) -> dict[str, Any]:
    """Return a pending or reproducibly observed context-dependent outcome."""

    if action.get("status") != "COMPLETED" or not isinstance(action.get("completed_at"), datetime):
        raise ValueError("Only a completed action can produce an outcome")
    if observation_lag_days < 1:
        raise ValueError("Outcome observation lag must be at least one day")
    due_date = action["completed_at"].date() + timedelta(days=observation_lag_days)
    outcome_id = _fingerprint("OUTCOME", action["action_id"], outcome_version)
    base = {
        "outcome_id": outcome_id,
        "action_id": action["action_id"],
        "alert_fingerprint": alert["alert_fingerprint"],
        "shipment_id": action["shipment_id"],
        "observation_due_date": due_date.isoformat(),
        "outcome_version": outcome_version,
        "provenance": "SIMULATED",
    }
    if as_of_date < due_date:
        return {**base, "status": "PENDING", "observed_date": None, "effect_pct": None}
    context = context or {}
    score = _stable_int(
        outcome_version, action["action_id"], action["action_type"], alert["alert_type"],
        alert["severity"], context.get("shipment_stage"), context.get("carrier"),
        context.get("execution_delay_hours", 0), context.get("active_disruption", False), modulo=100,
    )
    delay_penalty = min(25, int(context.get("execution_delay_hours", 0)) // 4)
    disruption_penalty = 20 if context.get("active_disruption") else 0
    adjusted = score - delay_penalty - disruption_penalty
    status = "SUCCESSFUL" if adjusted >= 55 else "PARTIALLY_SUCCESSFUL" if adjusted >= 25 else "FAILED" if adjusted >= 0 else "INCONCLUSIVE"
    effect_pct = {"SUCCESSFUL": 20.0, "PARTIALLY_SUCCESSFUL": 8.0, "FAILED": -5.0, "INCONCLUSIVE": 0.0}[status]
    return {**base, "status": status, "observed_date": as_of_date.isoformat(), "effect_pct": effect_pct}


def build_policy_proposal(
    outcomes: Iterable[dict[str, Any]],
    current_policy_version: str,
    as_of_date: date,
    minimum_observed: int = 20,
) -> dict[str, Any] | None:
    """Create reviewable learning evidence; never activate the proposal."""

    observed = [row for row in outcomes if row.get("status") in OUTCOME_STATES]
    if len(observed) < minimum_observed:
        return None
    success = sum(row["status"] in {"SUCCESSFUL", "PARTIALLY_SUCCESSFUL"} for row in observed)
    rate = round(100.0 * success / len(observed), 2)
    proposal_id = _fingerprint("POLICY_PROPOSAL", current_policy_version, as_of_date, len(observed), rate)
    return {
        "proposal_id": proposal_id,
        "source_policy_version": current_policy_version,
        "status": "PENDING_HUMAN_REVIEW",
        "observed_outcome_count": len(observed),
        "success_rate_pct": rate,
        "proposed_change": "REVIEW_ACTION_RANKING_THRESHOLDS",
        "simulation_config_change": False,
        "effective_date": None,
        "approved_by": None,
        "rollback_policy_version": current_policy_version,
        "provenance": "SIMULATED_LEARNING_EVIDENCE",
    }


def approve_policy_proposal(
    proposal: dict[str, Any], reviewer: str, approved_version: str, effective_date: date
) -> dict[str, Any]:
    if proposal.get("status") != "PENDING_HUMAN_REVIEW":
        raise ValueError("Only a pending policy proposal can be approved")
    if not reviewer.strip() or reviewer.strip().lower() in {"system", "automation", "model"}:
        raise ValueError("A named human reviewer is required")
    approved = dict(proposal)
    approved.update({
        "status": "APPROVED", "approved_by": reviewer.strip(),
        "approved_policy_version": approved_version, "effective_date": effective_date.isoformat(),
    })
    return approved


def eligible_operational_outcomes(
    outcomes: Iterable[dict[str, Any]], as_of_date: date
) -> list[dict[str, Any]]:
    """Exclude future simulations, pending labels, and post-cutoff observations."""

    eligible = []
    for row in outcomes:
        observed_date = row.get("observed_date")
        if row.get("execution_mode") != "OPERATIONAL" or row.get("time_basis") != "ACTUAL_CALENDAR":
            continue
        if row.get("status") not in OUTCOME_STATES or not observed_date:
            continue
        if date.fromisoformat(str(observed_date)) <= as_of_date:
            eligible.append(dict(row))
    return eligible
