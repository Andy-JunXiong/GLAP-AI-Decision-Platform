# Temporal Truthfulness Contract

**Business timezone:** `Australia/Sydney`

**Modes:** `OPERATIONAL` and `FUTURE_SIMULATION`

## Boundary

An operational logical date or analysis cutoff must be on or before the current
Sydney business date. The application derives that date itself; callers cannot
override `as_of_date` or claim a different `time_basis`.

`OPERATIONAL` means the date belongs to the actual calendar. It may feed normal
status, OPS snapshots, default backtests, and readiness decisions. It cannot
carry a scenario ID and fails before any pipeline stage runs when its logical
date is in the future.

`FUTURE_SIMULATION` is an explicitly labelled, staging-only scenario. It
requires a safe scenario ID and an environment flag. Controller status is kept
under `simulations/<scenario_id>/latest.json` instead of the operational
`latest.json`; reports also record the execution mode, scenario ID, Sydney
as-of date, and `FUTURE_SIMULATION` time basis.

## Evidence rules

- Future simulations may test lifecycle transitions, quality gates, recovery,
  and backtest mechanics.
- Their generated outcomes are synthetic scenario outcomes, not observations
  that occurred in the real calendar.
- Scenario accuracy numbers do not prove real forecast performance, label
  maturity, supervised-model readiness, or production readiness.
- OPS verification refuses to report `current` from a future-simulation status.
- Operational backtest and label-readiness defaults end at the current Sydney
  date. A later cutoff requires the explicit future-simulation mode and remains
  scenario evidence.

## Existing September--October 2026 runs

Runs already executed through `2026-10-05` are retained for auditability. As of
`2026-08-06`, they are future-dated synthetic scenario evidence. They show that
the isolated staging code paths and quality gates worked against generated
scenario data; they must not be used as real historical performance or observed
label evidence. On the first later operational run, a legacy untagged future
status is archived under the `legacy-pre-boundary-2026` scenario before the
operational pointer is replaced. Operational evidence can accumulate only as
calendar dates actually arrive and governed runs complete.
