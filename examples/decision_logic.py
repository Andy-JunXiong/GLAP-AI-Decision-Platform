"""Sanitized representative decision logic derived from the GLAP architecture."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnomalyRecord:
    entity_key: str
    metric_name: str
    metric_value: float
    baseline_value: float
    z_score: float
    shipment_count: int


def build_decision(record: AnomalyRecord) -> dict:
    gap = record.metric_value - record.baseline_value

    if record.metric_name == "avg_leg_duration_days" and record.z_score >= 2.5:
        root_cause = "Likely carrier transit delay or port congestion"
        action = "Investigate carrier transit delay and review impacted shipments"
        priority = "HIGH"
    elif record.metric_name == "breach_rate" and record.z_score >= 2.0:
        root_cause = "Service-level reliability degradation on this lane"
        action = "Escalate SLA issue with carrier and monitor exception queue"
        priority = "HIGH"
    else:
        root_cause = "Localized operational deviation"
        action = "Continue monitoring and re-check next scheduled run"
        priority = "MEDIUM"

    return {
        "entity_key": record.entity_key,
        "metric_name": record.metric_name,
        "recommended_action": action,
        "decision_reason": (
            f"{record.metric_name} is {gap:.2f} above baseline with "
            f"z_score={record.z_score:.2f} across {record.shipment_count} shipments"
        ),
        "root_cause": root_cause,
        "action_priority": priority,
        "requires_human_review": priority == "HIGH",
    }


if __name__ == "__main__":
    sample = AnomalyRecord(
        entity_key="DEHAM->AUSYD / MAERSK",
        metric_name="avg_leg_duration_days",
        metric_value=35.4,
        baseline_value=27.8,
        z_score=2.91,
        shipment_count=18,
    )
    print(build_decision(sample))
