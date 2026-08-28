"""Authenticated internal Operations API adapter for GLAP staging.

API Gateway's JWT authorizer validates the token. This adapter maps trusted
group claims to explicit permissions, exposes a bounded Action queue, and
forwards mutations with an actor derived from the authenticated identity.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


DATABASE = os.getenv("ATHENA_SOURCE_DATABASE", "simulated_iceberg_m")
WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
OUTPUT = os.getenv("ATHENA_OUTPUT", "")
ACTION_VIEW = os.getenv("LIFECYCLE_ACTION_CURRENT_VIEW", "vw_lifecycle_action_current_staging_v1")
ACTION_AUDIT_TABLE = os.getenv(
    "LIFECYCLE_ACTION_AUDIT_TABLE", "fact_lifecycle_action_audit_staging_v1"
)
ACTION_TABLE = os.getenv("LIFECYCLE_ACTION_TABLE", "fact_lifecycle_action_staging_v1")
ALERT_TABLE = os.getenv("LIFECYCLE_ALERT_TABLE", "fact_lifecycle_alert_staging_v1")
OUTCOME_TABLE = os.getenv("LIFECYCLE_OUTCOME_TABLE", "fact_lifecycle_outcome_staging_v1")
POLICY_PROPOSAL_TABLE = os.getenv(
    "POLICY_PROPOSAL_TABLE", "fact_policy_proposal_staging_v1"
)
MINIMUM_POLICY_OUTCOMES = int(os.getenv("MINIMUM_POLICY_OUTCOMES", "20"))
FORECAST_SOURCE_TABLE = os.getenv(
    "FORECAST_SOURCE_TABLE", "vw_multimodal_forecast_feature_daily_v1"
)
LABEL_READINESS_SOURCE_VIEW = os.getenv(
    "LABEL_READINESS_SOURCE_VIEW", "vw_multimodal_outcome_label_v1"
)
MINIMUM_LABEL_OBSERVED = int(os.getenv("MINIMUM_LABEL_OBSERVED", "200"))
MINIMUM_LABEL_CLASS = int(os.getenv("MINIMUM_LABEL_CLASS", "20"))
MINIMUM_LABEL_COST_DISTINCT = int(os.getenv("MINIMUM_LABEL_COST_DISTINCT", "10"))
NETWORK_SOURCE_VIEW = os.getenv(
    "NETWORK_SOURCE_VIEW", "vw_multimodal_shipment_daily_v1"
)
MUTATION_FUNCTION = os.getenv("ACTION_MUTATION_FUNCTION", "")
PIPELINE_STATUS_S3_URI = os.getenv("PIPELINE_STATUS_S3_URI", "")
PIPELINE_STAGE_ORDER = (
    "generation",
    "raw_to_iceberg",
    "input_validation",
    "decision_pipeline",
    "decision_flywheel",
    "output_validation",
)
PIPELINE_QUALITY_STAGES = {"input_validation", "output_validation"}
PIPELINE_QUALITY_CHECKS = {
    "missing_dates",
    "empty_inputs",
    "duplicate_business_keys",
    "abnormal_volume_change",
    "stale_stage_outputs",
}
COST_SOURCE_CONTRACT_VERSION = "stateful-cost-variance.v1"
COST_METRIC_NAME = "cost_variance_pct"
SAFE_FAILURE_CATEGORIES = {
    "dependency_failure",
    "invalid_response",
    "quality_contract_invalid",
    "quality_gate_failed",
    "unexpected_failure",
}
SAFE_STAGE_STATUS = {"blocked", "running", "succeeded", "failed", "not_invoked"}
PIPELINE_RUNBOOK_URL = (
    "https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/"
    "blob/main/docs/runbooks/pipeline_reliability.md"
)
ROLE_PERMISSIONS = {
    "viewer": {
        "risks:read", "actions:read", "outcomes:read", "health:read", "forecasts:read",
        "network:read", "learning:read", "labels:read",
    },
    "operator": {
        "risks:read", "actions:read", "actions:edit", "actions:complete", "outcomes:read", "health:read",
        "forecasts:read", "network:read", "shipments:read", "learning:read", "labels:read",
    },
    "approver": {
        "risks:read", "actions:read", "actions:approve", "actions:reject", "outcomes:read",
        "health:read", "forecasts:read", "network:read", "shipments:read", "learning:read",
        "labels:read",
    },
    "administrator": {
        "risks:read", "actions:read", "actions:edit", "actions:approve", "actions:reject", "actions:complete",
        "outcomes:read", "health:read", "forecasts:read", "network:read", "shipments:read",
        "learning:read", "labels:read",
    },
}
OPERATION_PERMISSION = {
    "EDIT": "actions:edit",
    "APPROVE": "actions:approve",
    "REJECT": "actions:reject",
    "COMPLETE": "actions:complete",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
APPROVED_OUTCOME_COHORT_CONTRACT_VERSION = "outcome-cohort-threshold-contract.v1"
APPROVED_OUTCOME_COHORT_OBSERVATION_FLOOR = 20
APPROVED_OUTCOME_COHORT_RESULT_STATE_FLOOR = 2
SAFE_PROVIDER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,31}$")
SAFE_LANE = re.compile(r"^[A-Z0-9]{2,8}-[A-Z0-9]{2,8}$")
LOGGER = logging.getLogger(__name__)
SLA_DELAY_METRICS = {
    "ORIGIN_GATE_IN": "gate_in_delay_hours",
    "ORIGIN_HANDOVER": "origin_delay_hours",
    "P2P_DEPARTURE": "departure_delay_hours",
    "P2P_ARRIVAL": "arrival_delay_hours",
    "DESTINATION_DISCHARGE": "discharge_delay_hours",
    "DESTINATION_RELEASE": "destination_release_delay_hours",
    "FINAL_DELIVERY": "delivery_delay_hours",
}
SLA_URGENCY = {
    "CRITICAL": "IMMEDIATE_REVIEW",
    "HIGH": "REVIEW_WITHIN_4_HOURS",
    "MEDIUM": "REVIEW_SAME_DAY",
    "LOW": "MONITOR",
}


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Unsafe Athena identifier")
    return value


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


def _safe_aws_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    if not isinstance(response, dict):
        return "none"
    error = response.get("Error") or {}
    code = str(error.get("Code") or "none")
    return code if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code) else "invalid"


def _mutation_failure_response(payload: dict[str, Any], request_id: Any) -> dict[str, Any] | None:
    error_type = str(payload.get("errorType") or "")
    message = str(payload.get("errorMessage") or "")
    if error_type == "ActionConflictError" or message.startswith(
        ("Invalid Action transition:", "request_id is already bound")
    ):
        return _response(409, {"error": "conflict", "request_id": request_id})
    if error_type == "ValueError" and message.startswith("Action was not found"):
        return _response(404, {"error": "not_found", "request_id": request_id})
    if error_type == "ValueError":
        return _response(400, {"error": "invalid_request", "request_id": request_id})
    return None


def _record_failure_metric(client: Any | None = None) -> bool:
    try:
        if client is None:
            import boto3

            client = boto3.client("cloudwatch")
        client.put_metric_data(
            Namespace="GLAP/OperationsApi",
            MetricData=[{"MetricName": "ServiceUnavailable", "Value": 1, "Unit": "Count"}],
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "operations_failure_metric_failed exception=%s aws_error=%s",
            type(exc).__name__,
            _safe_aws_error_code(exc),
        )
        return False


def _claim_groups(raw_groups: Any) -> list[str]:
    if isinstance(raw_groups, list):
        return [str(group) for group in raw_groups]
    text = str(raw_groups or "").strip()
    if text.startswith("["):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                return [str(group) for group in decoded]
        except json.JSONDecodeError:
            pass
    return [part.strip("[]\"'") for part in re.split(r"[ ,]+", text) if part.strip("[]\"'")]


def _identity(event: dict[str, Any]) -> tuple[str, str, set[str]]:
    jwt = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {})
    claims = jwt.get("claims") or {}
    subject = str(claims.get("sub") or "").strip()
    actor = str(
        claims.get("name")
        or claims.get("email")
        or claims.get("username")
        or claims.get("cognito:username")
        or ""
    ).strip()
    raw_groups = claims.get("cognito:groups") or claims.get("groups") or ""
    groups = _claim_groups(raw_groups)
    roles = {str(group).lower() for group in groups if str(group).lower() in ROLE_PERMISSIONS}
    if not subject or not actor or not roles:
        raise PermissionError("Authenticated named identity with an Operations role is required")
    permissions = set().union(*(ROLE_PERMISSIONS[role] for role in roles))
    return subject, actor, permissions


def build_action_queue_query(limit: int, status: str | None) -> str:
    where = "WHERE temporal_scope_id = 'OPERATIONAL'"
    if status:
        if status not in {"PROPOSED", "EDITED", "APPROVED", "REJECTED", "COMPLETED"}:
            raise ValueError("Unsupported Action status filter")
        where += f" AND status = '{status}'"
    return f"""SELECT action_id, alert_fingerprint, shipment_id, action_type,
alert_type, alert_severity, status, approval_required, approved_by,
approved_at, completed_at, decision_brief_version, selected_alternative,
selection_rationale, action_owner, action_due_date, created_date
FROM {_identifier(DATABASE)}.{_identifier(ACTION_VIEW)}
{where}
ORDER BY created_date DESC, action_id
LIMIT {limit}"""


def build_action_evidence_query(action_id: str, as_of_date: str) -> str:
    """Read one bounded Action, its immutable audit trail, and latest Outcome."""

    if not SAFE_ID.fullmatch(action_id):
        raise ValueError("Invalid Action identifier")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    return f"""WITH ranked_actions AS (
    SELECT action_id, alert_fingerprint, shipment_id, action_type,
           alert_type, alert_severity, status, approval_required,
           approved_by, approved_at, completed_at, decision_brief_version,
           selected_alternative, selection_rationale, created_date,
           row_number() OVER (
               PARTITION BY action_id
               ORDER BY as_of_date DESC, created_date DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(ACTION_TABLE)}
    WHERE action_id = '{action_id}'
      AND temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND created_date <= DATE '{as_of_date}'
), immutable_action AS (
    SELECT * FROM ranked_actions WHERE row_rank = 1
), ranked_audit_events AS (
    SELECT event_id, event_type, previous_status, new_status, actor,
           reason, occurred_at, approved_by, approved_at, completed_at,
           action_owner, action_due_date,
           row_number() OVER (
               PARTITION BY action_id
               ORDER BY occurred_at DESC,
                        CASE event_type WHEN 'COMPLETE' THEN 4 WHEN 'REJECT' THEN 3
                             WHEN 'APPROVE' THEN 2 WHEN 'EDIT' THEN 1 ELSE 0 END DESC,
                        event_id DESC
           ) AS event_rank,
           action_id
    FROM {_identifier(DATABASE)}.{_identifier(ACTION_AUDIT_TABLE)}
    WHERE action_id = '{action_id}'
      AND temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND created_date <= DATE '{as_of_date}'
), audit_events AS (
    SELECT * FROM ranked_audit_events
), latest_audit_event AS (
    SELECT * FROM ranked_audit_events WHERE event_rank = 1
), current_action AS (
    SELECT a.action_id, a.alert_fingerprint, a.shipment_id, a.action_type,
           a.alert_type, a.alert_severity,
           coalesce(e.new_status, a.status) AS status,
           a.approval_required,
           coalesce(e.approved_by, a.approved_by) AS approved_by,
           coalesce(e.approved_at, a.approved_at) AS approved_at,
           coalesce(e.completed_at, a.completed_at) AS completed_at,
           a.decision_brief_version, a.selected_alternative,
           a.selection_rationale,
           e.action_owner, e.action_due_date, a.created_date
    FROM immutable_action a
    LEFT JOIN latest_audit_event e ON a.action_id = e.action_id
), ranked_outcomes AS (
    SELECT outcome_id, action_id, observation_due_date, status,
           observed_date, effect_pct, outcome_version, as_of_date,
           row_number() OVER (
               PARTITION BY action_id
               ORDER BY try_cast(dt AS date) DESC, as_of_date DESC,
                        outcome_version DESC, outcome_id DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(OUTCOME_TABLE)}
    WHERE action_id = '{action_id}'
      AND temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND try_cast(dt AS date) <= DATE '{as_of_date}'
      AND (
          (status = 'PENDING' AND observed_date IS NULL AND effect_pct IS NULL)
          OR (status IN ('SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE')
              AND observed_date <= DATE '{as_of_date}')
      )
), current_outcome AS (
    SELECT * FROM ranked_outcomes WHERE row_rank = 1
)
SELECT a.action_id, a.alert_fingerprint, a.shipment_id, a.action_type,
       a.alert_type, a.alert_severity, a.status AS action_status,
       CAST(a.approval_required AS varchar) AS approval_required,
       a.approved_by, CAST(a.approved_at AS varchar) AS approved_at,
       CAST(a.completed_at AS varchar) AS completed_at,
       a.decision_brief_version, a.selected_alternative,
       a.selection_rationale,
       a.action_owner, CAST(a.action_due_date AS varchar) AS action_due_date,
       CAST(a.created_date AS varchar) AS action_created_date,
       e.event_id, e.event_type, e.previous_status, e.new_status, e.actor,
       e.reason, CAST(e.occurred_at AS varchar) AS occurred_at,
       e.action_owner AS event_action_owner,
       CAST(e.action_due_date AS varchar) AS event_action_due_date,
       o.outcome_id, CAST(o.observation_due_date AS varchar) AS observation_due_date,
       o.status AS outcome_status, CAST(o.observed_date AS varchar) AS observed_date,
       CAST(o.effect_pct AS varchar) AS effect_pct, o.outcome_version,
       CAST(o.as_of_date AS varchar) AS outcome_as_of_date,
       CASE WHEN o.status = 'PENDING' THEN 'NOT_OBSERVED'
            WHEN o.status IS NOT NULL THEN 'OBSERVED_ACTUAL_CALENDAR'
            ELSE NULL END AS evidence_status
FROM current_action a
LEFT JOIN audit_events e ON a.action_id = e.action_id
LEFT JOIN current_outcome o ON a.action_id = o.action_id
ORDER BY e.occurred_at, e.event_id
LIMIT 100"""


def build_action_evidence_contract(
    rows: list[dict[str, str | None]], as_of_date: str
) -> dict[str, Any] | None:
    """Shape a joined Athena result into one reviewable Action evidence chain."""

    if not rows:
        return None
    first = rows[0]
    action_id = first.get("action_id")
    if not action_id:
        return None

    action = {
        "action_id": action_id,
        "alert_fingerprint": first.get("alert_fingerprint"),
        "shipment_id": first.get("shipment_id"),
        "action_type": first.get("action_type"),
        "alert_type": first.get("alert_type"),
        "alert_severity": first.get("alert_severity"),
        "status": first.get("action_status"),
        "approval_required": first.get("approval_required"),
        "approved_by": first.get("approved_by"),
        "approved_at": first.get("approved_at"),
        "completed_at": first.get("completed_at"),
        "decision_brief_version": first.get("decision_brief_version"),
        "selected_alternative": first.get("selected_alternative"),
        "selection_rationale": first.get("selection_rationale"),
        "action_owner": first.get("action_owner"),
        "action_due_date": first.get("action_due_date"),
        "created_date": first.get("action_created_date"),
    }
    events = []
    seen_events: set[str] = set()
    for row in rows:
        event_id = row.get("event_id")
        if not event_id or event_id in seen_events:
            continue
        seen_events.add(event_id)
        events.append({
            "event_id": event_id,
            "event_type": row.get("event_type"),
            "previous_status": row.get("previous_status"),
            "new_status": row.get("new_status"),
            "actor": row.get("actor"),
            "reason": row.get("reason"),
            "occurred_at": row.get("occurred_at"),
            "action_owner": row.get("event_action_owner"),
            "action_due_date": row.get("event_action_due_date"),
        })

    outcome = None
    if first.get("outcome_id"):
        outcome = {
            "outcome_id": first.get("outcome_id"),
            "action_id": action_id,
            "observation_due_date": first.get("observation_due_date"),
            "outcome_status": first.get("outcome_status"),
            "observed_date": first.get("observed_date"),
            "effect_pct": first.get("effect_pct"),
            "outcome_version": first.get("outcome_version"),
            "as_of_date": first.get("outcome_as_of_date"),
            "evidence_status": first.get("evidence_status"),
        }

    if action["status"] == "REJECTED":
        chain_status = "ACTION_REJECTED"
    elif outcome is None:
        chain_status = (
            "ACTION_COMPLETED_AWAITING_OUTCOME"
            if action["status"] == "COMPLETED" else "ACTION_OPEN"
        )
    elif outcome["outcome_status"] == "PENDING":
        chain_status = "OUTCOME_PENDING"
    else:
        chain_status = "OUTCOME_OBSERVED"

    return {
        "schema_version": "operations-api.v1",
        "as_of_date": as_of_date,
        "source": {
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_EVIDENCE",
        },
        "chain_status": chain_status,
        "action": action,
        "events": events,
        "outcome": outcome,
        "governance": {
            "proposal_immutable": True,
            "decision_binding_immutable": True,
            "audit_append_only": True,
            "outcome_is_simulated": True,
            "real_logistics_performance": False,
        },
    }


def build_risk_hotspots_query(limit: int, status: str | None, as_of_date: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    status_filter = ""
    if status:
        if status not in {"OPEN", "RESOLVED"}:
            raise ValueError("Unsupported Risk status filter")
        status_filter = f" AND status = '{status}'"
    return f"""WITH ranked_alerts AS (
    SELECT alert_fingerprint, shipment_id, alert_type, alert_grain,
           alert_dimension, severity, status, first_detected_date,
           last_detected_date, resolved_date, metric_name, metric_value,
           threshold_value, as_of_date,
           row_number() OVER (
               PARTITION BY alert_fingerprint
               ORDER BY try_cast(dt AS date) DESC, updated_at DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(ALERT_TABLE)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND try_cast(dt AS date) <= DATE '{as_of_date}'
)
SELECT alert_fingerprint, shipment_id, alert_type, alert_grain,
       alert_dimension, severity, status, first_detected_date,
       last_detected_date, resolved_date, metric_name, metric_value,
       threshold_value, as_of_date
FROM ranked_alerts
WHERE row_rank = 1{status_filter}
ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
         WHEN 'MEDIUM' THEN 3 ELSE 4 END,
         last_detected_date DESC, alert_fingerprint
LIMIT {limit}"""


def build_sla_breach_decision_brief(
    alert: dict[str, str | None], as_of_date: str
) -> dict[str, Any] | None:
    """Build one deterministic SLA-breach brief without inventing effect value."""

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid Decision Brief cutoff date")
    if alert.get("alert_type") != "SLA_BREACH":
        return None
    if alert.get("status") != "OPEN" or alert.get("alert_grain") != "SHIPMENT_MILESTONE":
        return None
    dimension = str(alert.get("alert_dimension") or "")
    metric_name = str(alert.get("metric_name") or "")
    if SLA_DELAY_METRICS.get(dimension) != metric_name:
        raise ValueError("SLA_BREACH metric and milestone do not match")
    severity = str(alert.get("severity") or "")
    if severity not in SLA_URGENCY:
        raise ValueError("Unsupported SLA_BREACH severity")
    try:
        metric_value = float(str(alert.get("metric_value")))
        threshold_value = float(str(alert.get("threshold_value")))
    except (TypeError, ValueError) as exc:
        raise ValueError("SLA_BREACH values must be numeric") from exc
    if (
        not math.isfinite(metric_value)
        or not math.isfinite(threshold_value)
        or metric_value < 0
        or threshold_value < 0
        or metric_value <= threshold_value
    ):
        raise ValueError("SLA_BREACH must exceed a non-negative threshold")
    breach_margin = round(metric_value - threshold_value, 2)
    return {
        "schema_version": "decision-brief.v1",
        "decision_type": "SLA_BREACH",
        "as_of_date": as_of_date,
        "source": {
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_ALERT",
        },
        "risk": {
            "severity": severity,
            "milestone": dimension,
            "evidence_class": "OBSERVED_INPUT",
        },
        "exposure": {
            "metric_name": metric_name,
            "delay_hours": metric_value,
            "threshold_hours": threshold_value,
            "breach_margin_hours": breach_margin,
            "affected_shipments": 1,
            "monetary_value": None,
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "urgency": {
            "status": SLA_URGENCY[severity],
            "basis": f"{severity} SLA breach at {dimension}",
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "recommendation": {
            "action_type": "EXPEDITE_MILESTONE",
            "rationale": (
                f"Review an expedite intervention for {dimension}; the governed "
                f"delay is {breach_margin:g} hours above threshold."
            ),
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "alternatives": [
            {
                "action_type": "EXPEDITE_MILESTONE",
                "label": "Expedite the affected milestone",
                "recommended": True,
            },
            {
                "action_type": "MONITOR_NEXT_MILESTONE",
                "label": "Monitor the next milestone before intervening",
                "recommended": False,
            },
            {
                "action_type": "NO_ACTION",
                "label": "Take no action and retain the current delay exposure",
                "recommended": False,
            },
        ],
        "no_action_exposure": {
            "status": "DERIVED",
            "delay_hours_at_risk": metric_value,
            "breach_margin_hours": breach_margin,
            "monetary_value": None,
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "benefit_estimate": {
            "status": "NOT_ESTIMATED",
            "estimate_evidence_class": "NOT_ESTIMATED",
            "assumption_set_version": None,
        },
        "governance": {
            "human_review_required": True,
            "execution_authorized": False,
            "outcome_observed": False,
            "financial_value_estimated": False,
            "deterministic_rule": True,
        },
    }


def build_cost_anomaly_decision_brief(
    alert: dict[str, str | None], as_of_date: str
) -> dict[str, Any] | None:
    """Build one deterministic cost-review brief without inventing value."""

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid Decision Brief cutoff date")
    if alert.get("alert_type") != "COST_ANOMALY":
        return None
    if (
        alert.get("status") != "OPEN"
        or alert.get("alert_grain") != "SHIPMENT_COST"
        or alert.get("alert_dimension") != "TOTAL_COST"
        or alert.get("metric_name") != COST_METRIC_NAME
    ):
        return None
    severity = str(alert.get("severity") or "")
    if severity not in SLA_URGENCY:
        raise ValueError("Unsupported COST_ANOMALY severity")
    try:
        metric_value = float(str(alert.get("metric_value")))
        threshold_value = float(str(alert.get("threshold_value")))
    except (TypeError, ValueError) as exc:
        raise ValueError("COST_ANOMALY values must be numeric") from exc
    if (
        not math.isfinite(metric_value)
        or not math.isfinite(threshold_value)
        or metric_value < 0
        or threshold_value < 0
        or metric_value <= threshold_value
    ):
        raise ValueError("COST_ANOMALY must exceed a non-negative threshold")
    breach_margin = round(metric_value - threshold_value, 2)
    rationale = (
        f"Review the governed cost basis under {COST_SOURCE_CONTRACT_VERSION}; "
        f"total cost variance is {breach_margin:g} percentage points above threshold."
    )
    return {
        "schema_version": "decision-brief.v1",
        "decision_type": "COST_ANOMALY",
        "as_of_date": as_of_date,
        "source": {
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_ALERT",
            "source_contract_version": COST_SOURCE_CONTRACT_VERSION,
            "rate_card_version": None,
            "rate_card_version_status": "UNAVAILABLE_IN_ALERT_CONTRACT",
        },
        "risk": {
            "severity": severity,
            "cost_scope": "TOTAL_COST",
            "evidence_class": "OBSERVED_INPUT",
        },
        "exposure": {
            "metric_name": COST_METRIC_NAME,
            "variance_pct": metric_value,
            "threshold_pct": threshold_value,
            "breach_margin_pct": breach_margin,
            "affected_shipments": 1,
            "monetary_value": None,
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "urgency": {
            "status": SLA_URGENCY[severity],
            "basis": f"{severity} total-cost variance anomaly",
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "recommendation": {
            "action_type": "REVIEW_COST",
            "rationale": rationale,
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "alternatives": [
            {
                "action_type": "REVIEW_COST",
                "label": "Review the governed cost basis and charge lines",
                "recommended": True,
            },
            {
                "action_type": "MONITOR_COST",
                "label": "Monitor the next cost snapshot before reviewing",
                "recommended": False,
            },
            {
                "action_type": "NO_ACTION",
                "label": "Take no action and retain the current variance exposure",
                "recommended": False,
            },
        ],
        "no_action_exposure": {
            "status": "DERIVED",
            "variance_pct_at_risk": metric_value,
            "breach_margin_pct": breach_margin,
            "monetary_value": None,
            "evidence_class": "DERIVED_EXPOSURE",
        },
        "benefit_estimate": {
            "status": "NOT_ESTIMATED",
            "estimate_evidence_class": "NOT_ESTIMATED",
            "assumption_set_version": None,
        },
        "governance": {
            "human_review_required": True,
            "execution_authorized": False,
            "outcome_observed": False,
            "financial_value_estimated": False,
            "deterministic_rule": True,
        },
    }


def build_decision_brief_v1(
    alert: dict[str, str | None], as_of_date: str
) -> dict[str, Any] | None:
    """Dispatch only the two implemented deterministic v1 contracts."""

    if alert.get("alert_type") == "SLA_BREACH":
        return build_sla_breach_decision_brief(alert, as_of_date)
    if alert.get("alert_type") == "COST_ANOMALY":
        return build_cost_anomaly_decision_brief(alert, as_of_date)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid Decision Brief cutoff date")
    return None


def build_risk_response(
    rows: list[dict[str, str | None]], as_of_date: str
) -> dict[str, Any]:
    """Attach a Decision Brief only where the implemented v1 contract applies."""

    items = []
    for row in rows:
        item: dict[str, Any] = dict(row)
        item["decision_brief"] = build_decision_brief_v1(row, as_of_date)
        items.append(item)
    return {
        "schema_version": "operations-api.v1",
        "as_of_date": as_of_date,
        "items": items,
        "next_token": None,
    }


def build_outcome_review_query(limit: int, status: str | None, as_of_date: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    valid_statuses = {"PENDING", "SUCCESSFUL", "PARTIALLY_SUCCESSFUL", "FAILED", "INCONCLUSIVE"}
    status_filter = ""
    if status:
        if status not in valid_statuses:
            raise ValueError("Unsupported Outcome status filter")
        status_filter = f" AND outcome_status = '{status}'"
    return f"""WITH ranked_outcomes AS (
    SELECT outcome_id, action_id, alert_fingerprint, shipment_id,
           observation_due_date, status AS outcome_status, observed_date,
           effect_pct, outcome_version, as_of_date,
           row_number() OVER (
               PARTITION BY outcome_id
               ORDER BY try_cast(dt AS date) DESC, as_of_date DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(OUTCOME_TABLE)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND try_cast(dt AS date) <= DATE '{as_of_date}'
      AND (
          (status = 'PENDING' AND observed_date IS NULL)
          OR (status IN ('SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE')
              AND observed_date <= DATE '{as_of_date}')
      )
), current_outcomes AS (
    SELECT * FROM ranked_outcomes WHERE row_rank = 1
)
SELECT o.outcome_id, o.action_id, o.alert_fingerprint, o.shipment_id,
       o.observation_due_date, o.outcome_status, o.observed_date,
       o.effect_pct, o.outcome_version, o.as_of_date,
       CASE WHEN o.outcome_status = 'PENDING' THEN 'NOT_OBSERVED'
            ELSE 'OBSERVED_ACTUAL_CALENDAR' END AS evidence_status,
       a.action_type, a.alert_type, a.alert_severity, a.status AS action_status,
       a.decision_brief_version, a.selected_alternative
FROM current_outcomes o
LEFT JOIN {_identifier(DATABASE)}.{_identifier(ACTION_VIEW)} a
  ON o.action_id = a.action_id
 AND a.temporal_scope_id = 'OPERATIONAL'
 AND a.execution_mode = 'OPERATIONAL'
 AND a.time_basis = 'ACTUAL_CALENDAR'
 AND a.as_of_date <= DATE '{as_of_date}'
 AND a.created_date <= DATE '{as_of_date}'
WHERE 1 = 1{status_filter}
ORDER BY CASE o.outcome_status WHEN 'PENDING' THEN 1 ELSE 2 END,
         o.observation_due_date, o.outcome_id
LIMIT {limit}"""


def build_outcome_cohort_query(as_of_date: str) -> str:
    """Aggregate observed synthetic effects by immutable Decision contract."""

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    return f"""WITH ranked_outcomes AS (
    SELECT outcome_id, action_id, status AS outcome_status, observed_date,
           effect_pct, as_of_date,
           row_number() OVER (
               PARTITION BY outcome_id
               ORDER BY try_cast(dt AS date) DESC, as_of_date DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(OUTCOME_TABLE)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND try_cast(dt AS date) <= DATE '{as_of_date}'
      AND observed_date IS NOT NULL
      AND observed_date <= DATE '{as_of_date}'
      AND status IN ('SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE')
      AND try_cast(effect_pct AS double) IS NOT NULL
), current_outcomes AS (
    SELECT * FROM ranked_outcomes WHERE row_rank = 1
), eligible_actions AS (
    SELECT action_id, decision_brief_version, selected_alternative
    FROM {_identifier(DATABASE)}.{_identifier(ACTION_VIEW)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND created_date <= DATE '{as_of_date}'
      AND nullif(trim(decision_brief_version), '') IS NOT NULL
      AND nullif(trim(selected_alternative), '') IS NOT NULL
)
SELECT a.decision_brief_version, a.selected_alternative,
       count(*) AS observed_outcome_count,
       count_if(o.outcome_status = 'SUCCESSFUL') AS successful_count,
       count_if(o.outcome_status = 'PARTIALLY_SUCCESSFUL') AS partially_successful_count,
       count_if(o.outcome_status = 'FAILED') AS failed_count,
       count_if(o.outcome_status = 'INCONCLUSIVE') AS inconclusive_count,
       round(min(try_cast(o.effect_pct AS double)), 2) AS minimum_effect_pct,
       round(avg(try_cast(o.effect_pct AS double)), 2) AS average_effect_pct,
       round(max(try_cast(o.effect_pct AS double)), 2) AS maximum_effect_pct
FROM current_outcomes o
JOIN eligible_actions a ON o.action_id = a.action_id
GROUP BY a.decision_brief_version, a.selected_alternative
ORDER BY a.decision_brief_version, a.selected_alternative"""


def _finite_float_value(row: dict[str, str | None], field: str) -> float:
    value = row.get(field)
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Outcome cohort field {field} is invalid") from exc
    if not math.isfinite(parsed):
        raise RuntimeError(f"Outcome cohort field {field} is not finite")
    return parsed


def build_outcome_cohort_contract(
    rows: list[dict[str, str | None]],
    as_of_date: str,
    approved_minimum_observed: int | None = None,
    approved_minimum_result_states: int | None = None,
    approved_threshold_contract_version: str | None = None,
) -> dict[str, Any]:
    """Shape descriptive synthetic cohorts without implying causal effect."""

    threshold_parts = (
        approved_minimum_observed,
        approved_minimum_result_states,
        approved_threshold_contract_version,
    )
    thresholds_configured = all(value is not None for value in threshold_parts)
    if any(value is not None for value in threshold_parts) and not thresholds_configured:
        raise RuntimeError("Outcome cohort sufficiency configuration is incomplete")
    if thresholds_configured:
        if (
            isinstance(approved_minimum_observed, bool)
            or isinstance(approved_minimum_result_states, bool)
            or not isinstance(approved_minimum_observed, int)
            or not isinstance(approved_minimum_result_states, int)
            or approved_minimum_observed < 1
            or not 1 <= approved_minimum_result_states <= 4
            or not SAFE_ID.fullmatch(str(approved_threshold_contract_version))
        ):
            raise RuntimeError("Outcome cohort sufficiency configuration is invalid")

    cohorts = []
    for row in rows:
        brief_version = str(row.get("decision_brief_version") or "").strip()
        alternative = str(row.get("selected_alternative") or "").strip()
        if not brief_version or not alternative:
            raise RuntimeError("Outcome cohort contains an unbound Decision source")
        observed = _count_value(row, "observed_outcome_count")
        statuses = {
            "successful": _count_value(row, "successful_count"),
            "partially_successful": _count_value(
                row, "partially_successful_count"
            ),
            "failed": _count_value(row, "failed_count"),
            "inconclusive": _count_value(row, "inconclusive_count"),
        }
        if observed < 1 or sum(statuses.values()) != observed:
            raise RuntimeError("Outcome cohort status counts do not reconcile")
        minimum = round(_finite_float_value(row, "minimum_effect_pct"), 2)
        average = round(_finite_float_value(row, "average_effect_pct"), 2)
        maximum = round(_finite_float_value(row, "maximum_effect_pct"), 2)
        minimum = 0.0 if minimum == 0 else minimum
        average = 0.0 if average == 0 else average
        maximum = 0.0 if maximum == 0 else maximum
        if not minimum <= average <= maximum:
            raise RuntimeError("Outcome cohort effect distribution is invalid")
        distinct_result_states = sum(count > 0 for count in statuses.values())
        sample_gate_met = (
            observed >= approved_minimum_observed
            if thresholds_configured else None
        )
        result_coverage_gate_met = (
            distinct_result_states >= approved_minimum_result_states
            if thresholds_configured else None
        )
        additional_observed_outcomes = (
            max(approved_minimum_observed - observed, 0)
            if thresholds_configured else None
        )
        additional_distinct_result_states = (
            max(approved_minimum_result_states - distinct_result_states, 0)
            if thresholds_configured else None
        )
        comparison_eligible = bool(
            thresholds_configured and sample_gate_met and result_coverage_gate_met
        )
        cohorts.append({
            "decision_brief_version": brief_version,
            "selected_alternative": alternative,
            "observed_outcome_count": observed,
            "status_counts": statuses,
            "effect_pct": {
                "minimum": minimum,
                "average": average,
                "maximum": maximum,
            },
            "evidence_sufficiency": {
                "status": (
                    "SUFFICIENT_FOR_DESCRIPTIVE_COMPARISON"
                    if comparison_eligible
                    else "INSUFFICIENT_EVIDENCE"
                    if thresholds_configured
                    else "PENDING_HUMAN_APPROVAL"
                ),
                "distinct_result_states": distinct_result_states,
                "sample_gate_met": sample_gate_met,
                "result_coverage_gate_met": result_coverage_gate_met,
                "comparison_eligible": comparison_eligible,
            },
            "evidence_gap": {
                "schema_version": "outcome-cohort-evidence-gap.v1",
                "status": (
                    "TARGET_MET"
                    if comparison_eligible
                    else "GAP_REMAINS"
                    if thresholds_configured
                    else "PENDING_HUMAN_APPROVAL"
                ),
                "target_contract_version": (
                    approved_threshold_contract_version
                    if thresholds_configured else None
                ),
                "additional_observed_outcomes": additional_observed_outcomes,
                "additional_distinct_result_states": (
                    additional_distinct_result_states
                ),
                "calculation_only": True,
                "outcome_collection_recommended": False,
                "outcome_creation_authorized": False,
                "lifecycle_continuation_authorized": False,
            },
        })
    eligible_comparison_cohorts = []
    for cohort in cohorts:
        if not cohort["evidence_sufficiency"]["comparison_eligible"]:
            continue
        observed_count = cohort["observed_outcome_count"]
        comparison_cohort = {
            "decision_brief_version": cohort["decision_brief_version"],
            "selected_alternative": cohort["selected_alternative"],
            "observed_outcome_count": observed_count,
            "status_percentages": {
                status: round(count / observed_count * 100, 2)
                for status, count in cohort["status_counts"].items()
            },
            "effect_pct": cohort["effect_pct"],
            "provenance": {
                "schema_version": "outcome-cohort-comparison-provenance.v1",
                "decision_binding": {
                    "binding_source": "IMMUTABLE_ACTION_PROPOSAL",
                    "decision_brief_version": cohort["decision_brief_version"],
                    "selected_alternative": cohort["selected_alternative"],
                },
                "evidence_contract": {
                    "cohort_summary_schema_version": "outcome-cohort-summary.v1",
                    "threshold_contract_version": (
                        approved_threshold_contract_version
                    ),
                    "as_of_date": as_of_date,
                    "execution_mode": "OPERATIONAL",
                    "time_basis": "ACTUAL_CALENDAR",
                    "evidence_class": (
                        "SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT"
                    ),
                    "observed_only": True,
                    "pending_excluded": True,
                    "unbound_actions_excluded": True,
                    "future_simulations_excluded": True,
                },
                "privacy": {
                    "action_identifiers_exposed": False,
                    "outcome_identifiers_exposed": False,
                    "shipment_identifiers_exposed": False,
                },
                "read_only": True,
            },
        }
        fingerprint_payload = {
            **comparison_cohort,
            "status_percentages": {
                key: f"{value:.2f}"
                for key, value in comparison_cohort["status_percentages"].items()
            },
            "effect_pct": {
                key: f"{value:.2f}"
                for key, value in comparison_cohort["effect_pct"].items()
            },
        }
        canonical_comparison = json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        comparison_cohort["integrity"] = {
            "schema_version": "outcome-cohort-comparison-fingerprint.v1",
            "algorithm": "SHA-256",
            "canonicalization": (
                "JSON_SORT_KEYS_COMPACT_UTF8_ASCII_DECIMAL_2_STRINGS"
            ),
            "digest": hashlib.sha256(canonical_comparison).hexdigest(),
            "covered_fields": [
                "decision_brief_version",
                "selected_alternative",
                "observed_outcome_count",
                "status_percentages",
                "effect_pct",
                "provenance",
            ],
            "verification_scope": "RESPONSE_CONTENT_INTEGRITY_ONLY",
            "digital_signature": False,
            "source_authenticity_attested": False,
            "business_validity_attested": False,
        }
        eligible_comparison_cohorts.append(comparison_cohort)
    comparison_available = len(eligible_comparison_cohorts) >= 2
    return {
        "schema_version": "outcome-cohort-summary.v1",
        "as_of_date": as_of_date,
        "status": "AVAILABLE" if cohorts else "NO_ELIGIBLE_BOUND_OUTCOMES",
        "source": {
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT",
        },
        "eligibility": {
            "observed_only": True,
            "pending_excluded": True,
            "unbound_actions_excluded": True,
            "future_simulations_excluded": True,
        },
        "cohorts": cohorts,
        "evidence_sufficiency_gate": {
            "schema_version": "outcome-cohort-evidence-sufficiency.v1",
            "configuration_status": (
                "HUMAN_APPROVED_CONTRACT"
                if thresholds_configured else "PENDING_HUMAN_APPROVAL"
            ),
            "threshold_contract_version": (
                approved_threshold_contract_version
                if thresholds_configured else None
            ),
            "thresholds": {
                "minimum_observed_outcomes": (
                    approved_minimum_observed if thresholds_configured else None
                ),
                "minimum_distinct_result_states": (
                    approved_minimum_result_states
                    if thresholds_configured else None
                ),
            },
            "comparison_scope": "DESCRIPTIVE_SYNTHETIC_ONLY",
            "any_comparison_eligible": any(
                cohort["evidence_sufficiency"]["comparison_eligible"]
                for cohort in cohorts
            ),
        },
        "descriptive_comparison_view": {
            "schema_version": "outcome-cohort-descriptive-comparison.v1",
            "status": (
                "AVAILABLE"
                if comparison_available
                else "INSUFFICIENT_ELIGIBLE_COHORTS"
            ),
            "required_eligible_cohort_count": 2,
            "eligible_cohort_count": len(eligible_comparison_cohorts),
            "excluded_cohort_count": (
                len(cohorts) - len(eligible_comparison_cohorts)
            ),
            "cohorts": (
                eligible_comparison_cohorts if comparison_available else []
            ),
            "comparison_scope": "DESCRIPTIVE_SYNTHETIC_ONLY",
            "governance": {
                "ranking_produced": False,
                "preferred_alternative_selected": False,
                "causal_superiority_estimated": False,
                "statistical_significance_estimated": False,
                "action_recommended": False,
            },
        },
        "governance": {
            "descriptive_summary_only": True,
            "causal_effect_estimate": False,
            "financial_value_estimated": False,
            "real_logistics_performance": False,
            "model_readiness": False,
            "policy_activation_authorized": False,
            "human_threshold_approval_required": True,
            "automatic_threshold_selection": False,
        },
    }


def build_outcome_review_response(
    items: list[dict[str, str | None]],
    cohort_rows: list[dict[str, str | None]],
    as_of_date: str,
) -> dict[str, Any]:
    return {
        "schema_version": "operations-api.v1",
        "as_of_date": as_of_date,
        "items": items,
        "cohort_summary": build_outcome_cohort_contract(
            cohort_rows,
            as_of_date,
            approved_minimum_observed=APPROVED_OUTCOME_COHORT_OBSERVATION_FLOOR,
            approved_minimum_result_states=APPROVED_OUTCOME_COHORT_RESULT_STATE_FLOOR,
            approved_threshold_contract_version=(
                APPROVED_OUTCOME_COHORT_CONTRACT_VERSION
            ),
        ),
        "next_token": None,
    }


def build_learning_evidence_query(as_of_date: str) -> str:
    """Aggregate eligible Outcomes and attach the latest governed proposal."""

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    return f"""WITH ranked_outcomes AS (
    SELECT outcome_id, status, observed_date,
           row_number() OVER (
               PARTITION BY outcome_id
               ORDER BY try_cast(dt AS date) DESC, as_of_date DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(OUTCOME_TABLE)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND try_cast(dt AS date) <= DATE '{as_of_date}'
      AND observed_date IS NOT NULL
      AND observed_date <= DATE '{as_of_date}'
      AND status IN ('SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE')
), eligible_outcomes AS (
    SELECT * FROM ranked_outcomes WHERE row_rank = 1
), outcome_summary AS (
    SELECT count(*) AS eligible_outcome_count,
           count_if(status = 'SUCCESSFUL') AS successful_count,
           count_if(status = 'PARTIALLY_SUCCESSFUL') AS partially_successful_count,
           count_if(status = 'FAILED') AS failed_count,
           count_if(status = 'INCONCLUSIVE') AS inconclusive_count,
           CASE WHEN count(*) = 0 THEN NULL ELSE round(
               100.0 * count_if(status IN ('SUCCESSFUL', 'PARTIALLY_SUCCESSFUL')) / count(*), 2
           ) END AS success_rate_pct
    FROM eligible_outcomes
), ranked_proposals AS (
    SELECT proposal_id, source_policy_version, status AS proposal_status,
           observed_outcome_count, success_rate_pct AS proposal_success_rate_pct,
           proposed_change, simulation_config_change, effective_date,
           approved_by, approved_policy_version, rollback_policy_version,
           provenance, created_date,
           row_number() OVER (
               ORDER BY created_date DESC, as_of_date DESC, proposal_id DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(POLICY_PROPOSAL_TABLE)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND created_date <= DATE '{as_of_date}'
)
SELECT summary.eligible_outcome_count, summary.successful_count,
       summary.partially_successful_count, summary.failed_count,
       summary.inconclusive_count, summary.success_rate_pct,
       proposal.proposal_id, proposal.source_policy_version,
       proposal.proposal_status, proposal.observed_outcome_count,
       proposal.proposal_success_rate_pct, proposal.proposed_change,
       proposal.simulation_config_change, proposal.effective_date,
       proposal.approved_by, proposal.approved_policy_version,
       proposal.rollback_policy_version, proposal.provenance,
       proposal.created_date
FROM outcome_summary summary
LEFT JOIN ranked_proposals proposal ON proposal.row_rank = 1"""


def _count_value(row: dict[str, str | None], field: str) -> int:
    value = row.get(field)
    return int(str(value)) if value not in (None, "") else 0


def build_learning_evidence_contract(
    rows: list[dict[str, str | None]],
    as_of_date: str,
    minimum_observed: int = MINIMUM_POLICY_OUTCOMES,
) -> dict[str, Any]:
    """Shape the Outcome learning gate without granting policy authority."""

    if minimum_observed < 1:
        raise ValueError("Minimum observed Outcome count must be positive")
    row = rows[0] if rows else {}
    eligible = _count_value(row, "eligible_outcome_count")
    successful = _count_value(row, "successful_count")
    partial = _count_value(row, "partially_successful_count")
    failed = _count_value(row, "failed_count")
    inconclusive = _count_value(row, "inconclusive_count")
    proposal = None
    if row.get("proposal_id"):
        proposal = {
            "proposal_id": row.get("proposal_id"),
            "source_policy_version": row.get("source_policy_version"),
            "status": row.get("proposal_status"),
            "observed_outcome_count": _count_value(row, "observed_outcome_count"),
            "success_rate_pct": (
                float(str(row["proposal_success_rate_pct"]))
                if row.get("proposal_success_rate_pct") not in (None, "") else None
            ),
            "proposed_change": row.get("proposed_change"),
            "simulation_config_change": str(
                row.get("simulation_config_change") or "false"
            ).lower() == "true",
            "effective_date": row.get("effective_date"),
            "approved_by": row.get("approved_by"),
            "approved_policy_version": row.get("approved_policy_version"),
            "rollback_policy_version": row.get("rollback_policy_version"),
            "provenance": row.get("provenance"),
            "created_date": row.get("created_date"),
        }

    gate_met = eligible >= minimum_observed
    if proposal:
        status = "POLICY_PROPOSAL_RECORDED"
    elif gate_met:
        status = "ELIGIBLE_AWAITING_PROPOSAL"
    else:
        status = "INSUFFICIENT_ELIGIBLE_OUTCOMES"
    return {
        "schema_version": "operations-api.v1",
        "as_of_date": as_of_date,
        "status": status,
        "source": {
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_LEARNING_EVIDENCE",
        },
        "gate": {
            "minimum_observed_outcomes": minimum_observed,
            "eligible_observed_outcomes": eligible,
            "remaining_outcomes": max(0, minimum_observed - eligible),
            "gate_met": gate_met,
        },
        "outcome_summary": {
            "successful": successful,
            "partially_successful": partial,
            "failed": failed,
            "inconclusive": inconclusive,
            "success_rate_pct": (
                float(str(row["success_rate_pct"]))
                if row.get("success_rate_pct") not in (None, "") else None
            ),
        },
        "proposal": proposal,
        "governance": {
            "eligibility_scope": "SYNTHETIC_POLICY_REVIEW_ONLY",
            "review_required": True,
            "automatic_activation": False,
            "deterministic_rules_replaced": False,
            "outcomes_are_simulated": True,
            "real_logistics_performance": False,
            "model_readiness": False,
            "production_readiness": False,
        },
    }


def build_label_readiness_query(as_of_date: str) -> str:
    """Aggregate provider label coverage without returning shipment identifiers."""

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    return f"""SELECT transport_mode, provider_code,
       max(label_observed_through_date) AS source_latest_date,
       count(*) AS cohort_shipments,
       count_if(outcome_status = 'PENDING') AS pending_label_count,
       count_if(outcome_status = 'OBSERVED') AS observed_label_count,
       count_if(outcome_status = 'OBSERVED' AND sla_breach_label = true)
           AS sla_positive_count,
       count_if(outcome_status = 'OBSERVED' AND sla_breach_label = false)
           AS sla_negative_count,
       count_if(outcome_status = 'OBSERVED' AND delivery_late_label = true)
           AS delay_positive_count,
       count_if(outcome_status = 'OBSERVED' AND delivery_late_label = false)
           AS delay_negative_count,
       count_if(outcome_status = 'OBSERVED' AND cost_variance_pct_label IS NOT NULL)
           AS cost_label_count,
       count(DISTINCT CASE WHEN outcome_status = 'OBSERVED'
             THEN cost_variance_pct_label END) AS cost_variance_distinct_count
FROM {_identifier(DATABASE)}.{_identifier(LABEL_READINESS_SOURCE_VIEW)}
WHERE temporal_scope_id = 'OPERATIONAL'
  AND execution_mode = 'OPERATIONAL'
  AND time_basis = 'ACTUAL_CALENDAR'
  AND as_of_date <= DATE '{as_of_date}'
  AND booking_cohort_date <= DATE '{as_of_date}'
  AND label_observed_through_date <= DATE '{as_of_date}'
  AND outcome_status IN ('PENDING', 'OBSERVED')
GROUP BY transport_mode, provider_code
ORDER BY transport_mode, provider_code"""


def _label_binary_target(
    observed: int,
    positive: int,
    negative: int,
    minimum_observed: int,
    minimum_class: int,
) -> dict[str, Any]:
    blockers = []
    if observed < minimum_observed:
        blockers.append("MIN_OBSERVED_LABELS")
    if positive < minimum_class:
        blockers.append("MIN_POSITIVE_LABELS")
    if negative < minimum_class:
        blockers.append("MIN_NEGATIVE_LABELS")
    return {
        "evaluation_eligible": not blockers,
        "positive_count": positive,
        "negative_count": negative,
        "remaining_observed": max(0, minimum_observed - observed),
        "remaining_positive": max(0, minimum_class - positive),
        "remaining_negative": max(0, minimum_class - negative),
        "blockers": blockers,
    }


def build_label_readiness_contract(
    rows: list[dict[str, str | None]],
    as_of_date: str,
    minimum_observed: int = MINIMUM_LABEL_OBSERVED,
    minimum_class: int = MINIMUM_LABEL_CLASS,
    minimum_cost_distinct: int = MINIMUM_LABEL_COST_DISTINCT,
) -> dict[str, Any]:
    """Shape a read-only label gate; it never grants training or promotion authority."""

    cutoff = date.fromisoformat(as_of_date)
    if minimum_observed < 1 or minimum_class < 1 or minimum_cost_distinct < 2:
        raise ValueError("Label-readiness thresholds are outside the governed range")

    groups = []
    seen_groups: set[tuple[str, str]] = set()
    observed_total = 0
    pending_total = 0
    eligible_targets = 0
    for row in rows:
        mode = str(row.get("transport_mode") or "").upper()
        provider = str(row.get("provider_code") or "").upper()
        if mode not in {"AIR", "OCEAN"} or not SAFE_PROVIDER.fullmatch(provider):
            raise RuntimeError("Label-readiness provider group is invalid")
        group_key = (mode, provider)
        if group_key in seen_groups:
            raise RuntimeError("Duplicate label-readiness provider group")
        seen_groups.add(group_key)
        try:
            source_latest = date.fromisoformat(str(row.get("source_latest_date") or ""))
            counts = {
                field: int(str(row.get(field) or "0"))
                for field in (
                    "cohort_shipments", "pending_label_count", "observed_label_count",
                    "sla_positive_count", "sla_negative_count", "delay_positive_count",
                    "delay_negative_count", "cost_label_count",
                    "cost_variance_distinct_count",
                )
            }
        except ValueError as error:
            raise RuntimeError("Label-readiness aggregate is invalid") from error
        if source_latest > cutoff or any(value < 0 for value in counts.values()):
            raise RuntimeError("Label-readiness aggregate exceeds its governed cutoff")
        observed = counts["observed_label_count"]
        pending = counts["pending_label_count"]
        if pending + observed != counts["cohort_shipments"]:
            raise RuntimeError("Label-readiness cohort does not reconcile")
        if counts["sla_positive_count"] + counts["sla_negative_count"] != observed:
            raise RuntimeError("SLA labels do not reconcile to observed Outcomes")
        if counts["delay_positive_count"] + counts["delay_negative_count"] != observed:
            raise RuntimeError("Delay labels do not reconcile to observed Outcomes")
        if counts["cost_label_count"] != observed:
            raise RuntimeError("Cost labels do not reconcile to observed Outcomes")

        sla = _label_binary_target(
            observed, counts["sla_positive_count"], counts["sla_negative_count"],
            minimum_observed, minimum_class,
        )
        delay = _label_binary_target(
            observed, counts["delay_positive_count"], counts["delay_negative_count"],
            minimum_observed, minimum_class,
        )
        cost_blockers = []
        if counts["cost_label_count"] < minimum_observed:
            cost_blockers.append("MIN_OBSERVED_LABELS")
        if counts["cost_variance_distinct_count"] < minimum_cost_distinct:
            cost_blockers.append("MIN_DISTINCT_COST_LABELS")
        cost = {
            "evaluation_eligible": not cost_blockers,
            "label_count": counts["cost_label_count"],
            "distinct_value_count": counts["cost_variance_distinct_count"],
            "remaining_observed": max(0, minimum_observed - counts["cost_label_count"]),
            "remaining_distinct_values": max(
                0, minimum_cost_distinct - counts["cost_variance_distinct_count"]
            ),
            "blockers": cost_blockers,
        }
        targets = {"sla_breach": sla, "delay_risk": delay, "cost_variance": cost}
        group_eligible = sum(bool(target["evaluation_eligible"]) for target in targets.values())
        eligible_targets += group_eligible
        observed_total += observed
        pending_total += pending
        groups.append({
            "transport_mode": mode,
            "provider_code": provider,
            "source_latest_date": source_latest.isoformat(),
            "status": (
                "ready" if group_eligible == len(targets)
                else "partially_ready" if group_eligible else "blocked_insufficient_observed_labels"
            ),
            "cohort_shipments": counts["cohort_shipments"],
            "observed_label_count": observed,
            "pending_label_count": pending,
            "observed_rate_pct": round(100.0 * observed / counts["cohort_shipments"], 2)
            if counts["cohort_shipments"] else None,
            "targets": targets,
        })

    groups.sort(key=lambda item: (str(item["transport_mode"]), str(item["provider_code"])))
    total_targets = len(groups) * 3
    ready_groups = sum(group["status"] == "ready" for group in groups)
    if total_targets and eligible_targets == total_targets:
        status = "ready"
    elif eligible_targets:
        status = "partially_ready"
    else:
        status = "blocked_insufficient_observed_labels"
    return {
        "schema_version": "operations-api.v1",
        "label_contract_version": "multimodal_outcome_label_v1",
        "readiness_policy_version": "supervised_label_readiness_v1",
        "as_of_date": as_of_date,
        "status": status,
        "source": {
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_LABEL_EVIDENCE",
        },
        "thresholds": {
            "minimum_observed_per_provider": minimum_observed,
            "minimum_positive_and_negative_per_binary_target": minimum_class,
            "minimum_distinct_cost_variance_values": minimum_cost_distinct,
        },
        "coverage": {
            "provider_groups": len(groups),
            "ready_provider_groups": ready_groups,
            "eligible_targets": eligible_targets,
            "total_targets": total_targets,
            "observed_labels": observed_total,
            "pending_labels": pending_total,
        },
        "groups": groups,
        "governance": {
            "decision_use": "SUPERVISED_EVALUATION_GATE_ONLY",
            "pending_labels_excluded": True,
            "future_simulations_included": False,
            "entity_identifiers_included": False,
            "model_training_authorized": False,
            "model_promotion_authorized": False,
            "production_readiness": False,
        },
    }


def build_forecast_series_query(as_of_date: str, history_days: int = 90) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    if not 35 <= history_days <= 90:
        raise ValueError("Forecast history must be between 35 and 90 days")
    return f"""WITH params AS (
    SELECT DATE '{as_of_date}' AS as_of_date
), calendar AS (
    SELECT CAST(day AS date) AS feature_date
    FROM params
    CROSS JOIN UNNEST(
        sequence(date_add('day', -{history_days - 1}, as_of_date), as_of_date, INTERVAL '1' DAY)
    ) AS dates(day)
), operational AS (
    SELECT source.feature_date,
           sum(source.new_booking_count) AS shipment_count
    FROM {_identifier(DATABASE)}.{_identifier(FORECAST_SOURCE_TABLE)} AS source
    CROSS JOIN params
    WHERE source.temporal_scope_id = 'OPERATIONAL'
      AND source.execution_mode = 'OPERATIONAL'
      AND source.time_basis = 'ACTUAL_CALENDAR'
      AND source.as_of_date <= params.as_of_date
      AND source.feature_date <= params.as_of_date
      AND source.feature_date >= date_add('day', -{history_days - 1}, params.as_of_date)
    GROUP BY source.feature_date
)
SELECT CAST(calendar.feature_date AS varchar) AS feature_date,
       CAST(coalesce(operational.shipment_count, 0) AS varchar) AS shipment_count,
       IF(operational.feature_date IS NULL, '0', '1') AS eligible_date
FROM calendar
LEFT JOIN operational ON calendar.feature_date = operational.feature_date
ORDER BY calendar.feature_date"""


def _network_filters(
    as_of_date: str, mode: str | None, provider: str | None, lane: str | None
) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    filters = [
        "temporal_scope_id = 'OPERATIONAL'",
        "execution_mode = 'OPERATIONAL'",
        "time_basis = 'ACTUAL_CALENDAR'",
        f"as_of_date <= DATE '{as_of_date}'",
        f"metric_date <= DATE '{as_of_date}'",
    ]
    if mode:
        mode = mode.upper()
        if mode not in {"AIR", "OCEAN"}:
            raise ValueError("Unsupported transport mode filter")
        filters.append(f"transport_mode = '{mode}'")
    if provider:
        provider = provider.upper()
        if not SAFE_PROVIDER.fullmatch(provider):
            raise ValueError("Invalid provider filter")
        filters.append(f"carrier = '{provider}'")
    if lane:
        lane = lane.upper()
        if not SAFE_LANE.fullmatch(lane):
            raise ValueError("Invalid lane filter")
        filters.append(f"market_lane = '{lane}'")
    return " AND\n      ".join(filters)


def build_network_summary_query(
    as_of_date: str, mode: str | None = None, provider: str | None = None,
    lane: str | None = None,
) -> str:
    filters = _network_filters(as_of_date, mode, provider, lane)
    return f"""WITH ranked_shipments AS (
    SELECT metric_date, shipment_id, transport_mode, carrier AS provider_code,
           market_lane, lifecycle_status, sla_breach_flag,
           planned_p2p_hours, actual_p2p_hours,
           row_number() OVER (
               PARTITION BY shipment_id ORDER BY metric_date DESC, as_of_date DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(NETWORK_SOURCE_VIEW)}
    WHERE {filters}
)
SELECT transport_mode, provider_code, market_lane,
       count(*) AS shipment_count,
       count_if(lifecycle_status = 'OPEN') AS active_shipment_count,
       count_if(sla_breach_flag) AS sla_breach_count,
       round(100.0 * count_if(sla_breach_flag) / nullif(count(*), 0), 2)
           AS sla_breach_rate_pct,
       round(avg(planned_p2p_hours), 2) AS avg_planned_p2p_hours,
       round(avg(actual_p2p_hours), 2) AS avg_actual_p2p_hours
FROM ranked_shipments
WHERE row_rank = 1
GROUP BY transport_mode, provider_code, market_lane
ORDER BY sla_breach_count DESC, active_shipment_count DESC,
         transport_mode, provider_code, market_lane
LIMIT 100"""


def build_shipment_drilldown_query(
    limit: int, as_of_date: str, mode: str | None = None,
    provider: str | None = None, lane: str | None = None,
    status: str | None = None, after: str | None = None,
) -> str:
    filters = _network_filters(as_of_date, mode, provider, lane)
    if status:
        status = status.upper()
        if status not in {"OPEN", "CLOSED"}:
            raise ValueError("Unsupported shipment status filter")
    if after and not SAFE_ID.fullmatch(after):
        raise ValueError("Invalid shipment page token")
    status_filter = f" AND lifecycle_status = '{status}'" if status else ""
    after_filter = f" AND shipment_id > '{after}'" if after else ""
    return f"""WITH ranked_shipments AS (
    SELECT metric_date, shipment_id, transport_mode, carrier AS provider_code,
           market_lane, service_level, lifecycle_stage, lifecycle_status,
           sla_breach_flag, planned_p2p_hours, actual_p2p_hours,
           row_number() OVER (
               PARTITION BY shipment_id ORDER BY metric_date DESC, as_of_date DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(NETWORK_SOURCE_VIEW)}
    WHERE {filters}
)
SELECT CAST(metric_date AS varchar) AS metric_date, shipment_id, transport_mode,
       provider_code, market_lane, service_level, lifecycle_stage,
       lifecycle_status, CAST(sla_breach_flag AS varchar) AS sla_breach_flag,
       CAST(planned_p2p_hours AS varchar) AS planned_p2p_hours,
       CAST(actual_p2p_hours AS varchar) AS actual_p2p_hours
FROM ranked_shipments
WHERE row_rank = 1{status_filter}{after_filter}
ORDER BY shipment_id
LIMIT {limit + 1}"""


def _encode_page_token(shipment_id: str) -> str:
    return base64.urlsafe_b64encode(shipment_id.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_page_token(token: str | None) -> str | None:
    if not token:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,180}", token):
        raise ValueError("Invalid shipment page token")
    try:
        value = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid shipment page token") from exc
    if not SAFE_ID.fullmatch(value):
        raise ValueError("Invalid shipment page token")
    return value


def _parse_rows(response: dict[str, Any]) -> list[dict[str, str | None]]:
    result = response.get("ResultSet", {})
    rows = result.get("Rows", [])
    columns = result.get("ResultSetMetadata", {}).get("ColumnInfo", [])
    headers = [str(column.get("Name")) for column in columns]
    parsed = []
    for row in rows[1:]:
        values = [cell.get("VarCharValue") for cell in row.get("Data", [])]
        values.extend([None] * (len(headers) - len(values)))
        parsed.append(dict(zip(headers, values)))
    return parsed


def _query_rows(client: Any, query: str) -> list[dict[str, str | None]]:
    query_id = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": OUTPUT},
        WorkGroup=WORKGROUP,
    )["QueryExecutionId"]
    deadline = time.monotonic() + 30
    while True:
        state = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return _parse_rows(client.get_query_results(QueryExecutionId=query_id, MaxResults=102))
        if state in {"FAILED", "CANCELLED"}:
            raise RuntimeError("Operations query failed")
        if time.monotonic() >= deadline:
            client.stop_query_execution(QueryExecutionId=query_id)
            raise TimeoutError("Operations query timed out")
        time.sleep(0.25)


def _query_outcome_rows_parallel(
    item_client: Any,
    cohort_client: Any,
    item_query: str,
    cohort_query: str,
) -> tuple[list[dict[str, str | None]], list[dict[str, str | None]]]:
    """Run the two independent Outcome reads concurrently and fail as one unit."""

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="outcome-read") as pool:
        item_future = pool.submit(_query_rows, item_client, item_query)
        cohort_future = pool.submit(_query_rows, cohort_client, cohort_query)
        try:
            return item_future.result(), cohort_future.result()
        except Exception:
            item_future.cancel()
            cohort_future.cancel()
            raise


def _sydney_date() -> str:
    return datetime.now(ZoneInfo("Australia/Sydney")).date().isoformat()


def _ols(values: list[float]) -> tuple[float, float]:
    count = len(values)
    x_values = list(range(count))
    sum_x = sum(x_values)
    sum_y = sum(values)
    sum_xx = sum(value * value for value in x_values)
    sum_xy = sum(x * y for x, y in zip(x_values, values))
    denominator = count * sum_xx - sum_x * sum_x
    if not denominator:
        return 0.0, fmean(values)
    slope = (count * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / count
    return slope, intercept


def _forecast_point(values: list[float]) -> tuple[float, float]:
    slope, intercept = _ols(values)
    point = max(0.0, intercept + slope * len(values))
    fitted_errors = [
        value - (intercept + slope * index) for index, value in enumerate(values)
    ]
    sigma = math.sqrt(fmean(error * error for error in fitted_errors))
    return point, sigma


def build_forecast_contract(rows: list[dict[str, str | None]], as_of_date: str) -> dict[str, Any]:
    cutoff = date.fromisoformat(as_of_date)
    series = []
    seen_dates = set()
    for row in rows:
        try:
            feature_date = date.fromisoformat(str(row.get("feature_date") or ""))
            shipment_count = int(str(row.get("shipment_count") or ""))
        except ValueError:
            continue
        if feature_date > cutoff or feature_date in seen_dates or shipment_count < 0:
            continue
        seen_dates.add(feature_date)
        series.append({
            "date": feature_date,
            "shipments": shipment_count,
            "eligible": str(row.get("eligible_date") or "0") == "1",
        })
    series.sort(key=lambda item: item["date"])

    training = series[-28:]
    training_ready = len(training) == 28 and all(item["eligible"] for item in training)
    scenario_id = f"internal-advisory-forecast-{as_of_date}"
    points = []
    if training_ready:
        values = [float(item["shipments"]) for item in training]
        slope, intercept = _ols(values)
        residuals = [value - (intercept + slope * index) for index, value in enumerate(values)]
        sigma = math.sqrt(fmean(error * error for error in residuals))
        interval = max(1, round(1.96 * sigma))
        for horizon in range(1, 8):
            point = max(0, round(intercept + slope * (len(values) - 1 + horizon)))
            points.append({
                "date": (cutoff + timedelta(days=horizon)).isoformat(),
                "predicted_shipments": point,
                "lower_bound": max(0, point - interval),
                "upper_bound": point + interval,
                "evidence_status": "ADVISORY_FORECAST_NOT_OBSERVED",
            })

    predictions = []
    for index in range(28, len(series)):
        prior = series[index - 28:index]
        target = series[index]
        if not target["eligible"] or not all(item["eligible"] for item in prior):
            continue
        point, sigma = _forecast_point([float(item["shipments"]) for item in prior])
        interval = 1.96 * sigma
        predictions.append({
            "date": target["date"],
            "actual": float(target["shipments"]),
            "predicted": point,
            "lower": max(0.0, point - interval),
            "upper": point + interval,
        })
    predictions = predictions[-14:]
    metrics = None
    if len(predictions) >= 7:
        errors = [item["predicted"] - item["actual"] for item in predictions]
        nonzero = [item for item in predictions if item["actual"]]
        metrics = {
            "forecast_count": len(predictions),
            "mae": round(fmean(abs(error) for error in errors), 2),
            "rmse": round(math.sqrt(fmean(error * error for error in errors)), 2),
            "bias": round(fmean(errors), 2),
            "mape_pct": round(
                100 * fmean(abs(item["predicted"] - item["actual"]) / item["actual"] for item in nonzero),
                2,
            ) if nonzero else None,
            "interval_coverage_pct": round(
                100 * fmean(item["lower"] <= item["actual"] <= item["upper"] for item in predictions),
                2,
            ),
        }

    forecast_status = "ready" if len(points) == 7 else "insufficient_operational_history"
    accuracy_status = "engineering_evidence" if metrics else "insufficient_operational_history"
    return {
        "schema_version": "operations-api.v1",
        "as_of_date": as_of_date,
        "source": {
            "execution_mode": "OPERATIONAL",
            "time_basis": "ACTUAL_CALENDAR",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE",
            "feature_contract_version": "shipment_volume_daily_v1",
        },
        "forecast": {
            "status": forecast_status,
            "execution_mode": "FUTURE_SIMULATION",
            "time_basis": "MODEL_PROJECTION",
            "scenario_id": scenario_id,
            "method": "ordinary_least_squares_28d",
            "model_version": "booking_volume_ols_v1",
            "horizon_days": 7,
            "training_start": training[0]["date"].isoformat() if training_ready else None,
            "training_end": training[-1]["date"].isoformat() if training_ready else None,
            "points": points,
            "decision_use": "ADVISORY_ONLY",
            "production_effect": False,
        },
        "accuracy": {
            "status": accuracy_status,
            "evaluation_policy": "ROLLING_28_DAY_ONE_STEP_AHEAD_NO_FUTURE_DATA",
            "evidence_class": "SYNTHETIC_ENGINEERING_BACKTEST",
            "metrics": metrics,
            "model_promotion_status": "BLOCKED",
        },
        "coverage": {
            "window_days": len(series),
            "eligible_dates": sum(item["eligible"] for item in series),
            "latest_eligible_date": (
                max((item["date"] for item in series if item["eligible"]), default=None).isoformat()
                if any(item["eligible"] for item in series) else None
            ),
            "minimum_training_dates": 28,
            "minimum_accuracy_forecasts": 7,
        },
        "history": [
            {
                "date": item["date"].isoformat(),
                "shipments": item["shipments"],
                "evidence_status": "SYNTHETIC_OPERATIONAL_CALENDAR",
            }
            for item in series[-14:] if item["eligible"]
        ],
        "disclosure": (
            "Staging-only advisory forecast over synthetic operational-calendar data; "
            "not real-world performance, an operational target, or model-promotion evidence."
        ),
    }


def _safe_timestamp(value: Any) -> str | None:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _safe_failure(value: Any) -> str | None:
    failure = str(value or "") or None
    if failure and failure not in SAFE_FAILURE_CATEGORIES:
        return "unexpected_failure"
    return failure


def sanitize_pipeline_health(run: dict[str, Any], sydney_date: str) -> dict[str, Any]:
    """Return the internal stage-level view without infrastructure identifiers."""

    cutoff = date.fromisoformat(sydney_date)
    try:
        logical_date = date.fromisoformat(str(run.get("logical_run_date") or ""))
    except ValueError:
        logical_date = None

    execution_mode = str(run.get("execution_mode") or "OPERATIONAL").upper()
    time_basis = str(run.get("time_basis") or "ACTUAL_CALENDAR").upper()
    operational = (
        execution_mode == "OPERATIONAL"
        and time_basis == "ACTUAL_CALENDAR"
        and not run.get("scenario_id")
    )

    safe_stages = []
    for index, expected_name in enumerate(PIPELINE_STAGE_ORDER):
        raw_stages = run.get("stages")
        raw = raw_stages[index] if isinstance(raw_stages, list) and index < len(raw_stages) else {}
        raw = raw if isinstance(raw, dict) and raw.get("name") == expected_name else {}
        stage_status = str(raw.get("status") or "blocked").lower()
        if stage_status not in SAFE_STAGE_STATUS:
            stage_status = "blocked"
        checks = []
        for check in raw.get("quality_checks") or []:
            if not isinstance(check, dict):
                continue
            name = str(check.get("name") or "")
            status = str(check.get("status") or "").lower()
            if name in PIPELINE_QUALITY_CHECKS and status in {"passed", "failed"}:
                checks.append({"name": name, "status": status})
        safe_stages.append({
            "name": expected_name,
            "status": stage_status,
            "started_at": _safe_timestamp(raw.get("started_at")),
            "completed_at": _safe_timestamp(raw.get("completed_at")),
            "duration_ms": int(raw["duration_ms"])
            if isinstance(raw.get("duration_ms"), (int, float)) and raw["duration_ms"] >= 0
            else None,
            "failure_category": _safe_failure(raw.get("failure_category")),
            "quality_checks": checks,
        })

    contract_complete = all(
        stage["name"] == expected and stage["status"] == "succeeded"
        for stage, expected in zip(safe_stages, PIPELINE_STAGE_ORDER)
    )
    quality_complete = all(
        {check["name"] for check in stage["quality_checks"]} == PIPELINE_QUALITY_CHECKS
        and all(check["status"] == "passed" for check in stage["quality_checks"])
        for stage in safe_stages if stage["name"] in PIPELINE_QUALITY_STAGES
    )
    raw_status = str(run.get("status") or "unknown").lower()
    future_invalid = logical_date is not None and logical_date > cutoff
    verified_success = (
        operational and not future_invalid and raw_status in {"success", "succeeded"}
        and contract_complete and quality_complete
    )
    if not operational or future_invalid or logical_date is None:
        status = "unverified"
        freshness = "future_invalid" if future_invalid else "unverified"
    elif raw_status == "failed":
        status, freshness = "failed", "current" if logical_date == cutoff else "stale"
    elif raw_status == "running":
        status, freshness = "running", "current" if logical_date == cutoff else "stale"
    elif verified_success and logical_date == cutoff:
        status, freshness = "current", "current"
    elif verified_success:
        status, freshness = "stale", "stale"
    else:
        status, freshness = "unverified", "unverified"

    return {
        "schema_version": "operations-api.v1",
        "status": status,
        "freshness_status": freshness,
        "as_of_date": sydney_date,
        "logical_run_date": logical_date.isoformat() if logical_date and not future_invalid else None,
        "started_at": _safe_timestamp(run.get("started_at")),
        "completed_at": _safe_timestamp(run.get("completed_at")),
        "failed_stage": run.get("failed_stage")
        if run.get("failed_stage") in PIPELINE_STAGE_ORDER else None,
        "failure_category": _safe_failure(run.get("failure_category")),
        "stages": safe_stages,
        "stage_count": len(safe_stages),
        "stages_succeeded": sum(stage["status"] == "succeeded" for stage in safe_stages),
        "quality_checks_succeeded": sum(
            check["status"] == "passed" for stage in safe_stages for check in stage["quality_checks"]
        ),
        "quality_checks_total": len(PIPELINE_QUALITY_CHECKS) * len(PIPELINE_QUALITY_STAGES),
        "runbook_url": PIPELINE_RUNBOOK_URL,
    }


def _read_pipeline_health(client: Any, uri: str, sydney_date: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise RuntimeError("Pipeline status is not configured")
    response = client.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
    raw = json.loads(response["Body"].read())
    if not isinstance(raw, dict):
        raise RuntimeError("Pipeline status is invalid")
    return sanitize_pipeline_health(raw, sydney_date)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request_id = event.get("requestContext", {}).get("requestId")
    try:
        subject, actor, permissions = _identity(event)
        method = str(event.get("requestContext", {}).get("http", {}).get("method") or "")
        path = str(event.get("rawPath") or "")
        if method == "GET" and path == "/v1/network":
            if "network:read" not in permissions:
                raise PermissionError("Role cannot read network summaries")
            import boto3
            params = event.get("queryStringParameters") or {}
            cutoff = _sydney_date()
            rows = _query_rows(
                boto3.client("athena"),
                build_network_summary_query(
                    cutoff, params.get("mode"), params.get("provider"), params.get("lane")
                ),
            )
            return _response(200, {
                "schema_version": "operations-api.v1",
                "as_of_date": cutoff,
                "source": {
                    "execution_mode": "OPERATIONAL",
                    "time_basis": "ACTUAL_CALENDAR",
                    "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE",
                },
                "entity_access": "shipments:read" in permissions,
                "items": rows,
                "next_token": None,
            })

        if method == "GET" and path == "/v1/shipments":
            if "shipments:read" not in permissions:
                raise PermissionError("Role cannot read shipment entities")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            after = _decode_page_token(params.get("next_token"))
            cutoff = _sydney_date()
            rows = _query_rows(
                boto3.client("athena"),
                build_shipment_drilldown_query(
                    limit, cutoff, params.get("mode"), params.get("provider"),
                    params.get("lane"), params.get("status"), after,
                ),
            )
            has_more = len(rows) > limit
            items = rows[:limit]
            next_token = _encode_page_token(str(items[-1]["shipment_id"])) if has_more else None
            return _response(200, {
                "schema_version": "operations-api.v1",
                "as_of_date": cutoff,
                "source": {
                    "execution_mode": "OPERATIONAL",
                    "time_basis": "ACTUAL_CALENDAR",
                    "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE",
                },
                "items": items,
                "next_token": next_token,
            })

        if method == "GET" and path == "/v1/forecasts":
            if "forecasts:read" not in permissions:
                raise PermissionError("Role cannot read Forecasts")
            import boto3
            cutoff = _sydney_date()
            rows = _query_rows(boto3.client("athena"), build_forecast_series_query(cutoff))
            return _response(200, build_forecast_contract(rows, cutoff))

        if method == "GET" and path == "/v1/label-readiness":
            if "labels:read" not in permissions:
                raise PermissionError("Role cannot read label readiness")
            import boto3
            cutoff = _sydney_date()
            rows = _query_rows(
                boto3.client("athena"), build_label_readiness_query(cutoff)
            )
            return _response(200, build_label_readiness_contract(rows, cutoff))

        if method == "GET" and path == "/v1/pipeline-health":
            if "health:read" not in permissions:
                raise PermissionError("Role cannot read Pipeline Health")
            import boto3
            return _response(
                200,
                _read_pipeline_health(boto3.client("s3"), PIPELINE_STATUS_S3_URI, _sydney_date()),
            )

        if method == "GET" and path == "/v1/risks":
            if "risks:read" not in permissions:
                raise PermissionError("Role cannot read Risks")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            cutoff = _sydney_date()
            rows = _query_rows(
                boto3.client("athena"),
                build_risk_hotspots_query(limit, params.get("status"), cutoff),
            )
            return _response(200, build_risk_response(rows, cutoff))

        if method == "GET" and path == "/v1/outcomes":
            if "outcomes:read" not in permissions:
                raise PermissionError("Role cannot read Outcomes")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            cutoff = _sydney_date()
            rows, cohort_rows = _query_outcome_rows_parallel(
                boto3.client("athena"),
                boto3.client("athena"),
                build_outcome_review_query(limit, params.get("status"), cutoff),
                build_outcome_cohort_query(cutoff),
            )
            return _response(
                200, build_outcome_review_response(rows, cohort_rows, cutoff)
            )

        if method == "GET" and path == "/v1/learning":
            if "learning:read" not in permissions or "outcomes:read" not in permissions:
                raise PermissionError("Role cannot read Learning evidence")
            import boto3
            cutoff = _sydney_date()
            rows = _query_rows(
                boto3.client("athena"), build_learning_evidence_query(cutoff)
            )
            return _response(200, build_learning_evidence_contract(rows, cutoff))

        if method == "GET" and path == "/v1/actions":
            if "actions:read" not in permissions:
                raise PermissionError("Role cannot read Actions")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            rows = _query_rows(boto3.client("athena"), build_action_queue_query(limit, params.get("status")))
            return _response(200, {"schema_version": "operations-api.v1", "items": rows, "next_token": None})

        evidence_match = re.fullmatch(r"/v1/actions/([^/]+)/evidence", path)
        if method == "GET" and evidence_match:
            if "actions:read" not in permissions or "outcomes:read" not in permissions:
                raise PermissionError("Role cannot read Action evidence")
            action_id = evidence_match.group(1)
            cutoff = _sydney_date()
            import boto3
            rows = _query_rows(
                boto3.client("athena"),
                build_action_evidence_query(action_id, cutoff),
            )
            contract = build_action_evidence_contract(rows, cutoff)
            if contract is None:
                return _response(404, {"error": "not_found", "request_id": request_id})
            return _response(200, contract)

        match = re.fullmatch(r"/v1/actions/([^/]+)/events", path)
        if method == "POST" and match:
            action_id = match.group(1)
            if not SAFE_ID.fullmatch(action_id):
                raise ValueError("Invalid Action identifier")
            body = json.loads(event.get("body") or "{}")
            operation = str(body.get("operation") or "").upper()
            required = OPERATION_PERMISSION.get(operation)
            if not required or required not in permissions:
                raise PermissionError("Role cannot perform this Action operation")
            import boto3
            mutation_event = {
                "action_id": action_id,
                "operation": operation,
                "request_id": str(body.get("request_id") or ""),
                "reason": str(body.get("reason") or ""),
                "action_owner": str(body.get("action_owner") or ""),
                "action_due_date": str(body.get("action_due_date") or ""),
                "actor": actor,
                "actor_subject": subject,
                "logical_run_date": _sydney_date(),
                "execution_mode": "OPERATIONAL",
                "time_basis": "ACTUAL_CALENDAR",
            }
            result = boto3.client("lambda").invoke(
                FunctionName=MUTATION_FUNCTION,
                InvocationType="RequestResponse",
                Payload=json.dumps(mutation_event).encode("utf-8"),
            )
            payload = json.loads(result["Payload"].read())
            if result.get("FunctionError"):
                mapped = _mutation_failure_response(payload, request_id)
                if mapped:
                    return mapped
                raise RuntimeError("Action mutation was rejected")
            return _response(200, {"schema_version": "operations-api.v1", "action": payload})
        return _response(404, {"error": "not_found", "request_id": request_id})
    except PermissionError as exc:
        return _response(403, {"error": "forbidden", "message": str(exc), "request_id": request_id})
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": "invalid_request", "message": str(exc), "request_id": request_id})
    except Exception as exc:
        _record_failure_metric()
        LOGGER.error(
            "operations_api_failure exception=%s aws_error=%s request_id_present=%s",
            type(exc).__name__,
            _safe_aws_error_code(exc),
            bool(request_id),
        )
        return _response(503, {"error": "service_unavailable", "request_id": request_id})
