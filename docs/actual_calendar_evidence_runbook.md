# Actual-calendar evidence accumulation runbook

**Scope:** manual, isolated staging only

This runbook accumulates synthetic operational-calendar evidence without a
recurring schedule. It does not turn synthetic logistics data into real-world
performance evidence.

## Per-date procedure

1. Derive the current `Australia/Sydney` date from the system. Never supply a
   future operational date or a scenario ID.
2. Confirm the immediately preceding operational date succeeded or use the
   explicit failed-date recovery path first.
3. Run the stateful lifecycle workflow in `plan` mode for one date with
   `execution_mode=OPERATIONAL`, `replay_days=1`, and `load_initial_seed=false`.
4. After human review, run `extend-integration-validate` for that same single
   date. The controller must pass four stages and 41 checks.
5. Record workflow ID, logical date, temporal scope, check totals, duration,
   and safe query-cost evidence. Do not publish entity records.
6. Refresh the private cockpit and verify the operational cutoff and freshness.

No date is rerun merely to increase counts. A failed date uses the explicit
recovery action and retains its original failure evidence.

## Readiness trigger rules

Re-run the read-only forecast/label workflow only when at least one governed
input changes:

- another closed feature date becomes eligible;
- DHL or KN gains actual-calendar provider coverage;
- a shipment changes from pending to delivered/observed;
- a completeness, drift, or scan-cost status changes.

Backtest evaluation needs at least 14 past rows per mode/provider. The cockpit
advisory forecast needs 28 complete eligible dates. Supervised evaluation stays
blocked until each mode/provider has at least 200 observed labels, 20 positive
and 20 negative classification labels, and 10 distinct cost values where
applicable. These gates permit evaluation only; they do not authorize training,
promotion, scheduling, or production use.
