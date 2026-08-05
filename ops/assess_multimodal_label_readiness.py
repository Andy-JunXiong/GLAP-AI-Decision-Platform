"""Assess whether observed multimodal outcomes are sufficient for supervised models."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path


LABEL_CONTRACT_VERSION = "multimodal_outcome_label_v1"
READINESS_POLICY_VERSION = "supervised_label_readiness_v1"
REQUIRED_COLUMNS = {
    "transport_mode",
    "provider_code",
    "source_latest_date",
    "cohort_shipments",
    "pending_label_count",
    "observed_label_count",
    "sla_positive_count",
    "sla_negative_count",
    "delay_positive_count",
    "delay_negative_count",
    "cost_label_count",
    "cost_variance_distinct_count",
}


@dataclass(frozen=True)
class LabelSummary:
    transport_mode: str
    provider_code: str
    source_latest_date: date
    cohort_shipments: int
    pending_label_count: int
    observed_label_count: int
    sla_positive_count: int
    sla_negative_count: int
    delay_positive_count: int
    delay_negative_count: int
    cost_label_count: int
    cost_variance_distinct_count: int


def load_summaries(path: Path, *, expected_cutoff_date: date) -> list[LabelSummary]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    columns = set(reader.fieldnames or ())
    if not rows or not REQUIRED_COLUMNS.issubset(columns):
        raise ValueError(f"input must contain columns: {', '.join(sorted(REQUIRED_COLUMNS))}")

    integer_fields = sorted(REQUIRED_COLUMNS - {
        "transport_mode", "provider_code", "source_latest_date"
    })
    summaries = []
    for row in rows:
        summary = LabelSummary(
            transport_mode=row["transport_mode"].strip().upper(),
            provider_code=row["provider_code"].strip().upper(),
            source_latest_date=date.fromisoformat(row["source_latest_date"]),
            **{field: int(row[field]) for field in integer_fields},
        )
        if not summary.transport_mode or not summary.provider_code:
            raise ValueError("transport_mode and provider_code cannot be blank")
        if summary.source_latest_date != expected_cutoff_date:
            raise ValueError("expected cutoff must equal the latest available label date")
        if any(getattr(summary, field) < 0 for field in integer_fields):
            raise ValueError("label counts cannot be negative")
        if summary.pending_label_count + summary.observed_label_count != summary.cohort_shipments:
            raise ValueError("pending and observed labels must reconcile to the cohort")
        if summary.sla_positive_count + summary.sla_negative_count != summary.observed_label_count:
            raise ValueError("SLA labels must include observed outcomes only")
        if summary.delay_positive_count + summary.delay_negative_count != summary.observed_label_count:
            raise ValueError("delay labels must include observed outcomes only")
        if summary.cost_label_count != summary.observed_label_count:
            raise ValueError("cost labels must include observed outcomes only")
        summaries.append(summary)

    keys = [(row.transport_mode, row.provider_code) for row in summaries]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate mode/provider label summary")
    return sorted(summaries, key=lambda row: (row.transport_mode, row.provider_code))


def _binary_target(
    *, observed: int, positive: int, negative: int, min_observed: int, min_class: int
) -> dict[str, object]:
    blockers = []
    if observed < min_observed:
        blockers.append("MIN_OBSERVED_LABELS")
    if positive < min_class:
        blockers.append("MIN_POSITIVE_LABELS")
    if negative < min_class:
        blockers.append("MIN_NEGATIVE_LABELS")
    return {
        "training_permitted": not blockers,
        "positive_count": positive,
        "negative_count": negative,
        "blockers": blockers,
    }


def build_report(
    summaries: list[LabelSummary],
    *,
    cutoff_date: date,
    min_observed: int = 200,
    min_class: int = 20,
    min_cost_distinct: int = 10,
) -> dict[str, object]:
    if min_observed < 1 or min_class < 1 or min_cost_distinct < 2:
        raise ValueError("readiness thresholds are outside the governed range")
    groups = []
    permitted_targets = 0
    total_targets = 0
    for row in summaries:
        sla = _binary_target(
            observed=row.observed_label_count,
            positive=row.sla_positive_count,
            negative=row.sla_negative_count,
            min_observed=min_observed,
            min_class=min_class,
        )
        delay = _binary_target(
            observed=row.observed_label_count,
            positive=row.delay_positive_count,
            negative=row.delay_negative_count,
            min_observed=min_observed,
            min_class=min_class,
        )
        cost_blockers = []
        if row.cost_label_count < min_observed:
            cost_blockers.append("MIN_OBSERVED_LABELS")
        if row.cost_variance_distinct_count < min_cost_distinct:
            cost_blockers.append("MIN_DISTINCT_COST_LABELS")
        cost = {
            "training_permitted": not cost_blockers,
            "label_count": row.cost_label_count,
            "distinct_value_count": row.cost_variance_distinct_count,
            "blockers": cost_blockers,
        }
        targets = {"sla_breach": sla, "delay_risk": delay, "cost_variance": cost}
        permitted_targets += sum(target["training_permitted"] for target in targets.values())
        total_targets += len(targets)
        groups.append(
            {
                "transport_mode": row.transport_mode,
                "provider_code": row.provider_code,
                "cohort_shipments": row.cohort_shipments,
                "observed_label_count": row.observed_label_count,
                "pending_label_count": row.pending_label_count,
                "observed_rate_pct": round(
                    100 * row.observed_label_count / row.cohort_shipments, 4
                ) if row.cohort_shipments else None,
                "targets": targets,
            }
        )
    if total_targets and permitted_targets == total_targets:
        status = "ready"
    elif permitted_targets:
        status = "partially_ready"
    else:
        status = "blocked_insufficient_observed_labels"
    return {
        "label_contract_version": LABEL_CONTRACT_VERSION,
        "readiness_policy_version": READINESS_POLICY_VERSION,
        "status": status,
        "cutoff_date": cutoff_date.isoformat(),
        "pending_label_policy": "EXCLUDE_FROM_ALL_TRAINING",
        "thresholds": {
            "minimum_observed_per_provider": min_observed,
            "minimum_positive_and_negative_per_binary_target": min_class,
            "minimum_distinct_cost_variance_values": min_cost_distinct,
        },
        "groups": groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--cutoff-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-observed", type=int, default=200)
    parser.add_argument("--minimum-class", type=int, default=20)
    parser.add_argument("--minimum-cost-distinct", type=int, default=10)
    args = parser.parse_args()
    report = build_report(
        load_summaries(args.input_csv, expected_cutoff_date=args.cutoff_date),
        cutoff_date=args.cutoff_date,
        min_observed=args.minimum_observed,
        min_class=args.minimum_class,
        min_cost_distinct=args.minimum_cost_distinct,
    )
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
