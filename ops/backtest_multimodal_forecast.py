"""Time-ordered booking-volume backtests for the multimodal feature contract.

The module intentionally uses only the Python standard library so it can run in
CI or after an Athena CSV export without creating a second analytics runtime.
Every prediction is one-step-ahead and is fitted only on rows strictly before
the prediction date.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import date
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Iterable, Sequence


FEATURE_CONTRACT_VERSION = "multimodal_forecast_feature_daily_v1"
MODEL_VERSION = "booking_volume_baselines_v1"
MODEL_NAMES = ("recent_level", "moving_average_7d", "weekday_seasonal", "ols_trend")
MIN_SELECTION_FORECASTS = 7
CONTRACT_COLUMNS = {
    "feature_cutoff_date",
    "feature_contract_version",
    "leakage_policy",
}


@dataclass(frozen=True)
class Observation:
    feature_date: date
    transport_mode: str
    provider_code: str
    new_booking_count: float


@dataclass(frozen=True)
class Prediction:
    feature_date: date
    transport_mode: str
    provider_code: str
    model: str
    actual: float
    predicted: float
    lower_bound: float
    upper_bound: float
    training_start: date
    training_end: date
    training_rows: int


def load_observations(path: Path, *, require_contract: bool = False) -> list[Observation]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    required = {"feature_date", "transport_mode", "provider_code", "new_booking_count"}
    columns = set(reader.fieldnames or ())
    if not rows or not required.issubset(columns):
        raise ValueError(f"input must contain columns: {', '.join(sorted(required))}")
    if require_contract and not CONTRACT_COLUMNS.issubset(columns):
        raise ValueError(
            f"contract input must contain columns: {', '.join(sorted(CONTRACT_COLUMNS))}"
        )
    if require_contract:
        for row in rows:
            if row["feature_contract_version"] != FEATURE_CONTRACT_VERSION:
                raise ValueError("unexpected feature_contract_version")
            if row["leakage_policy"] != "NO_FUTURE_DATA":
                raise ValueError("unexpected leakage_policy")
            if row["feature_cutoff_date"] != row["feature_date"]:
                raise ValueError("feature cutoff must equal the closed feature date")
    observations = [
        Observation(
            feature_date=date.fromisoformat(row["feature_date"]),
            transport_mode=row["transport_mode"].strip().upper(),
            provider_code=row["provider_code"].strip().upper(),
            new_booking_count=float(row["new_booking_count"]),
        )
        for row in rows
    ]
    if any(not item.transport_mode or not item.provider_code for item in observations):
        raise ValueError("transport_mode and provider_code cannot be blank")
    if any(
        not math.isfinite(item.new_booking_count) or item.new_booking_count < 0
        for item in observations
    ):
        raise ValueError("new_booking_count must be finite and non-negative")
    keys = [(item.transport_mode, item.provider_code, item.feature_date) for item in observations]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate mode/provider/date feature key")
    return sorted(observations, key=lambda item: (item.transport_mode, item.provider_code, item.feature_date))


def _ols(values: Sequence[float]) -> float:
    x_mean = (len(values) - 1) / 2
    y_mean = fmean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    slope = (
        sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
        / denominator
        if denominator
        else 0.0
    )
    return y_mean + slope * (len(values) - x_mean)


def _model_history(
    model: str, history: Sequence[Observation], target: Observation
) -> Sequence[Observation]:
    if model == "recent_level":
        return history[-1:]
    if model == "moving_average_7d":
        return history[-7:]
    if model == "weekday_seasonal":
        weekday_rows = [
            item for item in history if item.feature_date.weekday() == target.feature_date.weekday()
        ]
        return weekday_rows[-4:] if weekday_rows else history[-7:]
    if model == "ols_trend":
        return history[-28:]
    raise ValueError(f"unknown model: {model}")


def _point_forecast(model: str, history: Sequence[Observation], target: Observation) -> float:
    model_history = _model_history(model, history, target)
    values = [item.new_booking_count for item in model_history]
    if model in ("recent_level", "moving_average_7d", "weekday_seasonal"):
        return fmean(values)
    if model == "ols_trend":
        return _ols(values)
    raise ValueError(f"unknown model: {model}")


def rolling_backtest(
    observations: Iterable[Observation], *, minimum_history: int = 14
) -> list[Prediction]:
    if minimum_history < 2:
        raise ValueError("minimum_history must be at least 2")
    groups: dict[tuple[str, str], list[Observation]] = {}
    for observation in observations:
        groups.setdefault((observation.transport_mode, observation.provider_code), []).append(observation)

    predictions: list[Prediction] = []
    for (mode, provider), group in sorted(groups.items()):
        group.sort(key=lambda item: item.feature_date)
        for target_index in range(minimum_history, len(group)):
            target = group[target_index]
            history = group[:target_index]
            if history[-1].feature_date >= target.feature_date:
                raise ValueError("training rows must be strictly earlier than the target date")
            for model in MODEL_NAMES:
                model_history = _model_history(model, history, target)
                point = max(0.0, _point_forecast(model, history, target))
                fitted_errors = []
                for index in range(2, len(history)):
                    fitted = max(0.0, _point_forecast(model, history[:index], history[index]))
                    fitted_errors.append(history[index].new_booking_count - fitted)
                sigma = math.sqrt(fmean([error * error for error in fitted_errors])) if fitted_errors else 0.0
                predictions.append(
                    Prediction(
                        feature_date=target.feature_date,
                        transport_mode=mode,
                        provider_code=provider,
                        model=model,
                        actual=target.new_booking_count,
                        predicted=point,
                        lower_bound=max(0.0, point - 1.96 * sigma),
                        upper_bound=point + 1.96 * sigma,
                        training_start=model_history[0].feature_date,
                        training_end=model_history[-1].feature_date,
                        training_rows=len(model_history),
                    )
                )
    return predictions


def summarize(predictions: Iterable[Prediction]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[Prediction]] = {}
    for prediction in predictions:
        groups.setdefault(
            (prediction.transport_mode, prediction.provider_code, prediction.model), []
        ).append(prediction)
    results = []
    for (mode, provider, model), rows in sorted(groups.items()):
        errors = [row.predicted - row.actual for row in rows]
        nonzero = [row for row in rows if row.actual != 0]
        actual_average = fmean(row.actual for row in rows)
        mae = fmean(abs(error) for error in errors)
        results.append(
            {
                "transport_mode": mode,
                "provider_code": provider,
                "model": model,
                "forecast_count": len(rows),
                "mae": round(mae, 4),
                "normalized_mae_pct": (
                    round(100 * mae / actual_average, 4) if actual_average else None
                ),
                "rmse": round(math.sqrt(fmean(error * error for error in errors)), 4),
                "bias": round(fmean(errors), 4),
                "mape_pct": (
                    round(100 * fmean(abs(row.predicted - row.actual) / row.actual for row in nonzero), 4)
                    if nonzero
                    else None
                ),
                "mape_defined_count": len(nonzero),
                "interval_coverage_pct": round(
                    100 * fmean(row.lower_bound <= row.actual <= row.upper_bound for row in rows), 4
                ),
            }
        )
    return results


def coverage(observations: Iterable[Observation], minimum_history: int) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[Observation]] = {}
    for observation in observations:
        groups.setdefault((observation.transport_mode, observation.provider_code), []).append(observation)
    results = []
    for (mode, provider), rows in sorted(groups.items()):
        rows.sort(key=lambda item: item.feature_date)
        calendar_days = (rows[-1].feature_date - rows[0].feature_date).days + 1
        recent = [row.new_booking_count for row in rows[-7:]]
        prior = [row.new_booking_count for row in rows[-14:-7]]
        prior_average = fmean(prior) if prior else None
        drift_pct = (
            100 * (fmean(recent) / prior_average - 1)
            if prior_average not in (None, 0.0) and len(recent) == 7 and len(prior) == 7
            else None
        )
        results.append(
            {
                "transport_mode": mode,
                "provider_code": provider,
                "observed_rows": len(rows),
                "first_feature_date": rows[0].feature_date.isoformat(),
                "last_feature_date": rows[-1].feature_date.isoformat(),
                "calendar_completeness_pct": round(100 * len(rows) / calendar_days, 4),
                "missing_calendar_days": calendar_days - len(rows),
                "booking_count_recent_vs_prior_7d_pct": (
                    round(drift_pct, 4) if drift_pct is not None else None
                ),
                "eligible_for_evaluation": len(rows) > minimum_history,
            }
        )
    return results


def recommend(predictions: Iterable[Prediction]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[Prediction]] = {}
    for prediction in predictions:
        groups.setdefault((prediction.transport_mode, prediction.provider_code), []).append(prediction)
    recommendations = []
    for (mode, provider), rows in sorted(groups.items()):
        model_rows = {
            model: [row for row in rows if row.model == model] for model in MODEL_NAMES
        }
        benchmark = model_rows["recent_level"]
        benchmark_mae = fmean(abs(row.predicted - row.actual) for row in benchmark)
        benchmark_rmse = math.sqrt(
            fmean((row.predicted - row.actual) ** 2 for row in benchmark)
        )
        eligible = []
        for model in MODEL_NAMES[1:]:
            candidates = model_rows[model]
            mae = fmean(abs(row.predicted - row.actual) for row in candidates)
            rmse = math.sqrt(fmean((row.predicted - row.actual) ** 2 for row in candidates))
            wins = sum(
                abs(candidate.predicted - candidate.actual)
                < abs(reference.predicted - reference.actual)
                for candidate, reference in zip(candidates, benchmark)
            )
            win_rate = wins / len(candidates)
            if (
                len(candidates) >= MIN_SELECTION_FORECASTS
                and mae < benchmark_mae
                and rmse < benchmark_rmse
                and win_rate >= 0.60
            ):
                eligible.append((mae, model, win_rate))
        if eligible:
            _, selected, win_rate = min(eligible)
            reason = "LOWER_MAE_RMSE_AND_AT_LEAST_60_PCT_POINT_WINS"
        else:
            selected, win_rate = "recent_level", None
            reason = (
                "INSUFFICIENT_SELECTION_WINDOWS_RETAIN_SIMPLE_BENCHMARK"
                if len(benchmark) < MIN_SELECTION_FORECASTS
                else "RETAIN_SIMPLE_BENCHMARK"
            )
        recommendations.append(
            {
                "transport_mode": mode,
                "provider_code": provider,
                "selected_model": selected,
                "selection_reason": reason,
                "challenger_win_rate_pct": round(100 * win_rate, 4) if win_rate else None,
            }
        )
    return recommendations


def build_report(observations: list[Observation], minimum_history: int = 14) -> dict[str, object]:
    predictions = rolling_backtest(observations, minimum_history=minimum_history)
    group_coverage = coverage(observations, minimum_history)
    eligible_groups = sum(item["eligible_for_evaluation"] for item in group_coverage)
    if eligible_groups == len(group_coverage) and eligible_groups:
        status = "ready"
    elif eligible_groups:
        status = "partial_history"
    else:
        status = "insufficient_history"
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "model_version": MODEL_VERSION,
        "status": status,
        "evaluation_policy": "ROLLING_ONE_STEP_AHEAD_NO_FUTURE_DATA",
        "selection_policy": "RECENT_LEVEL_UNLESS_LOWER_MAE_RMSE_AND_60_PCT_POINT_WINS",
        "minimum_selection_forecasts": MIN_SELECTION_FORECASTS,
        "minimum_history_rows": minimum_history,
        "coverage": group_coverage,
        "metrics": summarize(predictions),
        "recommendations": recommend(predictions),
        "predictions": [
            {**asdict(row), "feature_date": row.feature_date.isoformat(),
             "training_start": row.training_start.isoformat(), "training_end": row.training_end.isoformat()}
            for row in predictions
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-history", type=int, default=14)
    parser.add_argument("--require-contract", action="store_true")
    args = parser.parse_args()
    report = build_report(
        load_observations(args.input_csv, require_contract=args.require_contract),
        args.minimum_history,
    )
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
