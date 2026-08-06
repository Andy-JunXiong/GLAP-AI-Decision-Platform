# Development handoff -- 6 August 2026

## Outcome

The isolated AWS staging lifecycle was technically exercised through
`2026-10-05`, but those September--October rows are future-dated synthetic
scenario evidence relative to `2026-08-06`. The expanded private rolling
scenario backtest exercised all three mode/provider code paths. Its selected
recent-level benchmarks are not evidence of real forecast performance, and
supervised outcome models remain blocked.

No production alias, recurring lifecycle or forecast schedule, current-v2
write, public entity-level publication, or automatic policy change was added.

## Repository changes

PRs `#14` through `#19` were merged:

- `#14` bounded a lifecycle extension to at most 12 dates and 50 minutes;
- `#15` added explicit same-day recovery for persisted dependency failures;
- `#16` corrected plan rendering without changing apply behavior;
- `#17` added insert-only Q4 2026 synthetic rate and FX configuration;
- `#18` preserved actual Air milestone ordering after an origin delay and
  allowed configured quality-gate failures into the guarded recovery path;
- `#19` allowed deterministic non-key matched-row updates only during explicit
  failed-date recovery. Normal daily writes remain insert-only.

The final repository suite contains 121 passing tests. CI passed on Python 3.13
and 3.14 for the two recovery fixes.

## AWS future-scenario execution evidence

Every run below used generated staging data beyond the actual Sydney business
date. The records are retained as proof of pipeline, recovery, and quality-gate
behavior only; they are not real history or observed operational outcomes.

| Purpose | Workflow run | Result |
| --- | --- | --- |
| Deploy Q4 synthetic configuration | `31055604564` | Succeeded; three insert-only configuration statements |
| Recover `2026-10-01` | `31055665942` | Succeeded; four stages and 32 checks passed |
| Detect `2026-10-02` quality failure | `31055943259` | Failed closed at lifecycle validation |
| Confirm invalid milestone order | `31056178106` | Read-only validation found `invalid_milestone_order=1` |
| Deploy Air milestone fix | `31057017116` | Succeeded |
| Demonstrate stale same-key row | `31057104595` | Failed closed; insert-only MERGE retained the prior row |
| Reconfirm stale row | `31057299415` | Read-only validation again found one invalid ordering |
| Deploy recovery-only matched update | `31057566716` | Succeeded |
| Repair `2026-10-02` | `31057648407` | Succeeded; four stages and 32 checks passed |
| Extend `2026-10-03`--`2026-10-05` | `31057844351` | Succeeded; each date passed all 32 checks |
| Final private backtest | `31058326815` | Succeeded; evidence artifact uploaded privately |

The failed runs are retained as useful fail-closed evidence. No later date was
started until its predecessor had passed.

## Scenario backtest evidence

The final synthetic-scenario report uses feature contract
`multimodal_forecast_feature_daily_v1`, model bundle
`booking_volume_baselines_v1`, and rolling one-step-ahead evaluation with no
look-ahead within the generated scenario sequence.

| Mode/provider | Complete feature days | Held-out forecasts | Selected model | MAE | RMSE | Bias | MAPE | Interval coverage |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Air / DHL | 34 | 20 | `recent_level` | 0.5500 | 0.8660 | 0.0500 | 20.0000% | 90.0000% |
| Ocean / KN | 34 | 20 | `recent_level` | 0.8000 | 1.0954 | -0.1000 | 12.7619% | 100.0000% |
| Ocean / Maersk | 63 | 49 | `recent_level` | 1.3469 | 1.8844 | 0.1633 | 15.1084% | 95.9184% |

Every scenario group has 100% generated-calendar completeness and zero missing
scenario dates. These metrics do not establish real-world accuracy. The Athena
feature query scanned 316,183 bytes against a 104,857,600-byte budget.

## Supervised-label boundary

The scenario report returned `blocked_insufficient_observed_labels`, but its
future-dated synthetic outcomes are not operational observations and cannot
advance real supervised-label readiness:

| Mode/provider | Cohort | Observed | Pending | Observed rate |
| --- | ---: | ---: | ---: | ---: |
| Air / DHL | 97 | 85 | 12 | 87.6289% |
| Ocean / KN | 222 | 2 | 220 | 0.9009% |
| Ocean / Maersk | 682 | 423 | 259 | 62.0235% |

The policy requires at least 200 observed labels per provider, at least 20
positive and 20 negative examples for each binary target, and at least 10
distinct cost-variance values. DHL and KN do not meet the provider minimum;
positive SLA/delay examples remain rare; every provider currently has only one
distinct cost-variance value. Pending labels remain excluded from training.

## Next work

1. Accumulate operational outcomes only as Sydney calendar dates arrive,
   without changing the governed thresholds.
2. Add real-calendar cost-variation evidence before reconsidering a supervised
   cost-variance target; scenario variation may test mechanics only.
3. Re-run operational label readiness first; train or compare a supervised
   candidate only after every provider/target gate passes on eligible data.
4. Keep the current simple forecast private and advisory. Any recurring
   schedule, production alias, public entity-level output, or policy consumer
   requires a separate explicit approval.

The repository now enforces the separate `OPERATIONAL` and
`FUTURE_SIMULATION` paths described in the
[`temporal truthfulness contract`](temporal_truthfulness.md).
It also defines row-level temporal scopes across all five lifecycle fact
tables, scenario-aware MERGE keys and validation views, operational-only
default analytics, and an explicit one-time legacy-row backfill. Apply that
backfill only as part of the approved schema/view deployment; it changes the
shared staging Iceberg tables but does not publish or schedule the pipeline.
