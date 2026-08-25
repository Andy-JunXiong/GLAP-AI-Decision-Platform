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

## Row identity and query isolation

Every lifecycle snapshot, event, cost, metric, and signal row carries the same
five-field temporal identity:

- `temporal_scope_id`: `OPERATIONAL` or `SIMULATION:<scenario_id>`;
- `execution_mode` and `time_basis`;
- the system-derived `as_of_date`; and
- `execution_scenario_id`, which is null for operational rows.

`temporal_scope_id` is part of every Iceberg MERGE key and prior-snapshot
lookup. Lifecycle continuation selects the latest earlier populated snapshot
inside that same scope; it never bridges an operational/simulation boundary or
invents a row for a missing calendar date. As a result, the same shipment and
logical date may exist in multiple explicit scenarios without overwriting or
continuing one another. Quality validation also selects one scope and rejects
internally inconsistent temporal labels. Absence of any earlier same-scope
baseline remains a fail-closed condition.

Default compatibility, OPS, forecast-feature, and outcome-label views expose
only `OPERATIONAL` / `ACTUAL_CALENDAR` rows. Their explicitly named
`*_context*` counterparts retain all scopes for governed scenario work and
must always be queried with one `temporal_scope_id`.

An operational-baseline cutoff is not itself proof that source rows exist
through that date. Late recovery rows retain the Sydney `as_of_date` on which
they became available and must not be backdated into an earlier point-in-time
baseline. A connected public baseline may claim a cutoff only when its
`source_max_metric_date` equals `baseline_as_of_date`; otherwise validation and
publication fail closed. Public UI surfaces must show both values whenever the
contract is unavailable or being diagnosed.

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
- The authenticated provider label-readiness surface derives that Sydney cutoff
  on the server and reads only the aggregate operational label view. Pending
  labels are coverage-only, future simulations and entity identifiers are
  excluded, and a threshold result grants neither training nor promotion
  authority.
- Closed staging Action Outcomes with `OPERATIONAL` / `ACTUAL_CALENDAR` labels
  may count only toward the synthetic, review-only policy-proposal gate. Meeting
  that gate is not factual treatment-effect evidence, model readiness,
  production readiness, or authority to activate a policy.

## Historical evaluation replay

`HYBRID_HISTORICAL_REPLAY` is a local evaluation evidence class, not a third
lifecycle execution mode. Every replay cutoff must be on or before the current
Sydney date. Public historical facts retain event, publication, conservative
availability, retrieval, and revision metadata; controlled enterprise state is
labelled synthetic and kept separate.

An official source with a signed or declared exact timestamp may use
`EXACT_TIMESTAMP`, in which case publication and availability must be
identical. Date-only sources remain subject to conservative next-day
availability. Corpus authors cannot shift either timestamp class to make
evidence visible earlier.

A historical scenario's declared severity is derived from the strongest fact
actually visible by its final decision cutoff. Reveal-only outcomes and
hypothetical worst cases cannot be used to inflate the decision-time severity
or manufacture a capability delta.

The public Evaluation snapshot carries its own `evaluation_as_of_date`. That
date must parse as a calendar date and be on or before the current Sydney
business date. It dates the aggregate evaluation record; it does not turn
historical replay or controlled enterprise state into operational evidence.
The public page must fail closed to `UNAVAILABLE` when the date is missing,
invalid, or future-dated, and must not reuse a previously embedded Evaluation
result as a fallback.

Multi-scenario replay membership is frozen in a selection manifest before
aggregation. Every member still passes its own cutoff, source-revision, and
reveal-isolation checks. Corpus totals cannot convert hybrid replay into
operational evidence or hide a scenario-level temporal failure.

Historical replay artifacts never enter operational default views, OPS
exports, label readiness, policy/model promotion evidence, or production
tables. Post-cutoff factual reveals remain isolated from decision inputs. They
can score what actually happened, but cannot establish the counterfactual
business effect of an action that was not taken.

## Synthetic Outcome robustness and calibration

A303 synthetic robustness uses `HYBRID_HISTORICAL_REPLAY` decision inputs and
`SIMULATED_COUNTERFACTUAL` outcomes. It must evaluate the complete attributed
set and frozen negative controls independently of human preference. A synthetic
robustness result, whether favourable or unfavourable, is engineering evidence
only and never becomes actual-calendar Outcome, realised savings, or production
performance. The current Simulator v1 result is `NOT_ROBUST`.

Any guardrail designed after inspecting that result is post-hoc development
evidence. Replaying it on the same dated corpus cannot become independent or
confirmatory evidence, even though the historical cutoffs themselves are
valid. A new design requires a new frozen holdout; repeated threshold tuning on
the current corpus is evaluation leakage.

The `2026-08-22` human retirement decision closes A303.v1 progression without
changing the time or evidence class of any prior record. Historical review,
exploratory, robustness, and candidate artifacts remain preserved under their
original classifications; retirement does not turn them into operational or
measured evidence.

Outcome calibration uses the current Sydney clock derived by the evaluator.
Every eligible record must use `ACTUAL_CALENDAR`, have timezone-aware observed
and source-availability timestamps on or before that clock, be frozen, and
carry an independent validation attestation. `FUTURE_SIMULATION`, generated
staging Outcomes, and `SIMULATED_COUNTERFACTUAL` records are ineligible.

An `OBSERVED_FACTUAL` record may calibrate only the baseline level actually
observed. It cannot be paired with an invented A303 result. Calibrating the
A303 treatment effect requires independently governed
`PROSPECTIVE_CONTROLLED` pairs. Test fixtures prove contract behavior only and
never count toward the minimum evidence gate, readiness, policy activation, or
model promotion.

## Existing September--October 2026 runs

Runs already executed through `2026-10-05` are retained for auditability. As of
`2026-08-06`, they are future-dated synthetic scenario evidence. They show that
the isolated staging code paths and quality gates worked against generated
scenario data; they must not be used as real historical performance or observed
label evidence. On the first later operational run, a legacy untagged future
status is archived under the `legacy-pre-boundary-2026` scenario before the
operational pointer is replaced. Operational evidence can accumulate only as
calendar dates actually arrive and governed runs complete.

The one-time `sql/12_temporal_scope_backfill.sql` migration permanently marks
pre-existing rows after `2026-08-06` as
`SIMULATION:legacy-pre-boundary-2026`. The migration is plan-only unless
`ops/backfill_temporal_scope.ps1 -Apply` is explicitly approved. This permanent
row label prevents old September or October scenario rows from becoming
operational merely because the calendar later reaches those dates. The fixed
`2026-08-06` value is a classification cutoff, not a permanent ceiling on later
actual-calendar operations. On a safe re-run, verification derives the current
Sydney business date from the system and accepts an `OPERATIONAL` row only when
its logical date is on or before both its stored `as_of_date` and the current
Sydney date. The default operational view is checked against the same dynamic
boundary. This preserves the legacy labels while allowing governed operational
history to accumulate as calendar dates arrive.
