"""Shared fail-closed quality contracts for GLAP pipeline stages."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re


PIPELINE_CHECK_NAMES = frozenset(
    {
        "missing_dates",
        "empty_inputs",
        "duplicate_business_keys",
        "abnormal_volume_change",
        "stale_stage_outputs",
    }
)

LIFECYCLE_CHECK_NAMES = frozenset(
    {
        "duplicate_snapshot_key",
        "invalid_milestone_order",
        "p2p_commitment_mutated",
        "actual_milestone_mutated",
        "invalid_terminal_state",
        "unknown_route_version",
        "unknown_rate_version",
        "cost_detail_does_not_reconcile",
        "duplicate_metric_key",
        "metric_snapshot_mismatch",
        "invalid_metric_contract",
        "duplicate_signal_key",
        "invalid_signal_contract",
        "duplicate_alert_key",
        "invalid_alert_contract",
        "invalid_action_contract",
        "duplicate_outcome_key",
        "invalid_outcome_contract",
        "invalid_policy_proposal_contract",
        "duplicate_route_config",
        "ambiguous_rate_card",
        "invalid_rate_tier",
        "invalid_transport_contract",
        "missing_provider_coverage",
        "air_booking_share_out_of_range",
        "invalid_temporal_provenance",
    }
)

MULTIMODAL_ANALYTICS_CHECK_NAMES = frozenset(
    {
        "duplicate_analytics_shipment_key",
        "mode_rollup_does_not_reconcile",
        "provider_rollup_does_not_reconcile",
        "invalid_mode_unit_contract",
        "invalid_sla_rate_contract",
        "air_decision_missing_ocean_reference",
        "duplicate_forecast_feature_key",
        "invalid_outcome_label_contract",
    }
)

QUALITY_CONTRACTS = {
    "pipeline_v1": PIPELINE_CHECK_NAMES,
    "lifecycle_v1": LIFECYCLE_CHECK_NAMES,
    "lifecycle_compat_v2": PIPELINE_CHECK_NAMES,
    "multimodal_analytics_v1": MULTIMODAL_ANALYTICS_CHECK_NAMES,
}


def _validation_template() -> str:
    packaged = Path(__file__).with_name("lifecycle_validation.sql")
    repository = Path(__file__).resolve().parents[1] / "sql" / "06_stateful_lifecycle_validation.sql"
    for path in (packaged, repository):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise RuntimeError("Lifecycle validation SQL is missing from the deployment package")


def render_lifecycle_validation_queries(
    logical_run_date: str,
    source_database: str,
    template: str | None = None,
    temporal_scope_id: str = "OPERATIONAL",
) -> tuple[str, ...]:
    parsed = date.fromisoformat(logical_run_date)
    if parsed.isoformat() != logical_run_date:
        raise ValueError("logical_run_date must use YYYY-MM-DD")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", source_database):
        raise ValueError("source_database must be a safe Athena identifier")
    if not re.fullmatch(r"(?:OPERATIONAL|SIMULATION:[A-Za-z0-9][A-Za-z0-9._-]{2,63})", temporal_scope_id):
        raise ValueError("temporal_scope_id must be a safe operational or simulation scope")
    rendered = (template if template is not None else _validation_template()).replace(
        "{{SOURCE_DATABASE}}", source_database
    ).replace("{{LOGICAL_RUN_DATE}}", logical_run_date).replace(
        "{{TEMPORAL_SCOPE_ID}}", temporal_scope_id
    )
    if re.search(r"\{\{[^}]+\}\}", rendered):
        raise ValueError("Lifecycle validation SQL has unresolved template tokens")
    rendered = re.sub(r"^\s*--.*$", "", rendered, flags=re.MULTILINE)
    statements = tuple(statement.strip() for statement in rendered.split(";") if statement.strip())
    if len(statements) != 2:
        raise ValueError("Lifecycle validation contract must contain exactly two statements")
    return statements


def _analytics_validation_template() -> str:
    packaged = Path(__file__).with_name("multimodal_ops_validation.sql")
    repository = Path(__file__).resolve().parents[1] / "sql" / "10_multimodal_ops_validation.sql"
    for path in (packaged, repository):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise RuntimeError("Multimodal analytics validation SQL is missing from the deployment package")


def render_multimodal_analytics_validation_query(
    logical_run_date: str,
    source_database: str,
    template: str | None = None,
    temporal_scope_id: str = "OPERATIONAL",
) -> str:
    parsed = date.fromisoformat(logical_run_date)
    if parsed.isoformat() != logical_run_date:
        raise ValueError("logical_run_date must use YYYY-MM-DD")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", source_database):
        raise ValueError("source_database must be a safe Athena identifier")
    if not re.fullmatch(r"(?:OPERATIONAL|SIMULATION:[A-Za-z0-9][A-Za-z0-9._-]{2,63})", temporal_scope_id):
        raise ValueError("temporal_scope_id must be a safe operational or simulation scope")
    rendered = (template if template is not None else _analytics_validation_template()).replace(
        "{{SOURCE_DATABASE}}", source_database
    ).replace("{{LOGICAL_RUN_DATE}}", logical_run_date).replace(
        "{{TEMPORAL_SCOPE_ID}}", temporal_scope_id
    )
    if re.search(r"\{\{[^}]+\}\}", rendered):
        raise ValueError("Multimodal analytics validation SQL has unresolved template tokens")
    rendered = re.sub(r"^\s*--.*$", "", rendered, flags=re.MULTILINE)
    statements = tuple(statement.strip() for statement in rendered.split(";") if statement.strip())
    if len(statements) != 1:
        raise ValueError("Multimodal analytics validation contract must contain exactly one statement")
    return statements[0]
