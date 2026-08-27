# SLA_BREACH runtime evidence reconciler v1

**Status:** corrected full reconciliation passed against `2026-08-27` staging

This read-only, aggregate-only reconciler prepares the runtime producer check
for the deployed `SLA_BREACH` Decision Brief. It validates only naturally
generated operational actual-calendar proposals. It does not invoke the
Generator and does not create, backfill, edit, approve, reject, or complete an
Action.

## Runtime result — 2026-08-27

The separately authorized staging query found one or more naturally generated
SLA proposals. Five checks passed: every inspected proposal had exactly one
eligible source Alert, remained an immutable unreviewed proposal, matched the
current-view binding projection, and preserved the pre-release SLA legacy-null
boundary; candidate existence also passed. Two checks failed: not every
proposal satisfied the exact Decision binding, and the invalid-binding count
was non-zero. The aggregate result does not identify which binding subcondition
failed, so no root cause is established and no runtime SLA binding evidence is
accepted.

The query printed no protected identifier and performed no lifecycle, Action,
API, deployment, identity, schedule, alias, Pages, policy, model, or production
mutation. A more granular aggregate diagnostic and every future Athena query
remain separately authorized work.

## Binding diagnostic result — 2026-08-27

The same script now has an optional `-BindingDiagnostic` mode. It preserves all
seven full reconciliation checks and adds five aggregate booleans that isolate:

- `decision-brief.v1` version;
- `EXPEDITE_MILESTONE` Action type;
- `EXPEDITE_MILESTONE` selected alternative;
- exact milestone-bound rationale shape;
- calculated breach value inside the rationale.

The separately authorized diagnostic query preserved the earlier seven
results. Among the five added components, `decision-brief.v1`, the
`EXPEDITE_MILESTONE` Action type, and the `EXPEDITE_MILESTONE` selected
alternative passed. Exact milestone-bound rationale shape and calculated breach
value failed. The gate therefore failed closed again.

The deployed commit's versioned source uses the same rationale template as the
current repository. Aggregate evidence still cannot distinguish a persisted
rationale-text difference from a verifier-expression difference, so no root
cause or runtime binding evidence is accepted. The mode printed no counts or
entity identifiers, cannot replace the full reconciliation gate, and cannot
mutate or repair a binding. Every future query requires new separate human
authorization because it creates another protected Athena result object.

## Prepared rationale diagnostic

The same script now has an optional `-RationaleDiagnostic` mode. It retains the
full seven checks and the five binding components, then adds five rationale-
only booleans that do not depend on regex parsing:

- rationale is present and non-empty;
- the exact Alert-milestone prefix is present;
- the exact governed suffix is present;
- the remaining token is a finite non-negative number;
- that token equals the rounded Alert breach margin.

The separately authorized first execution attempt failed before Athena returned
any boolean row. Safe read-only metadata classified the non-retryable failure as
`ENDS_WITH_EXPRESSION`; it produced no rationale diagnosis. After the suffix
check was locally corrected to a regex-independent `length` plus `substr`
comparison, the separately authorized retry returned all five rationale-only
booleans true. The legacy regex shape and value checks remained false.

The combined evidence validates the persisted rationale and isolates the
failure to verifier-expression drift. The legacy regex uses `[A-Z_]+`, while
the governed milestone set includes digit-bearing `P2P_DEPARTURE` and
`P2P_ARRIVAL`. The local full-gate verifier is now corrected: rationale shape
requires presence, the exact source-derived prefix, the governed suffix, and a
finite non-negative numeric token; rationale value reuses the independent
numeric-equality check. The reconciler contains no rationale regex. This change
was locally verified and then separately authorized for a corrected full
reconciliation.

## Corrected full reconciliation result — 2026-08-27

The corrected full reconciliation returned all seven aggregate booleans true:
a naturally generated proposal existed; every proposal had exactly one eligible
same-date source Alert and the exact Decision binding; the inspected cohort had
no invalid binding; every Action remained an immutable unreviewed proposal; the
current view preserved every binding; and pre-release SLA Actions remained
legacy-null. This establishes synthetic staging runtime evidence for the
natural SLA Decision binding. It does not establish approval, execution,
Outcome, value, causality, real logistics performance, model readiness, policy
readiness, or production readiness.

The mode printed no counts, text, or entity identifiers and could not mutate or
repair a proposal. It does not replace the full gate. Every future execution
requires new separate human authorization.

## Pass contract

The reconciler fails closed unless all of these conditions hold:

- At least one naturally generated SLA proposal exists on or after the bounded
  release date and no later than the current Australia/Sydney business date.
- Every proposal is `OPERATIONAL` / `ACTUAL_CALENDAR`, has no scenario ID, and
  traces to exactly one same-date open `SLA_BREACH` Alert.
- The Alert uses `SHIPMENT_MILESTONE` grain and exactly one of the seven governed
  milestone/delay-metric pairs.
- Delay and threshold are finite and non-negative, and delay strictly exceeds
  the threshold.
- Every immutable Action uses `decision-brief.v1` /
  `EXPEDITE_MILESTONE`; its rationale preserves both the exact milestone and the
  calculated hours above threshold.
- Each source Action remains an unreviewed `PROPOSED` row requiring approval;
  the current view preserves the same immutable Decision binding.
- Pre-release SLA Actions remain legacy-null rather than being backfilled.

Duplicate or missing source Alerts fail the exact-one-source gate. Future
simulation cannot satisfy the gate. Output contains only named boolean checks
and never prints an Action, Alert, shipment, actor, request, AWS, or storage
identifier.

## Execution and authority boundary

Running `ops/reconcile_sla_breach_runtime_staging.ps1` starts one read-only
Athena `SELECT`. Athena writes its query-result object to the already configured
protected results location, so every run is an external AWS operation requiring
separate human authorization. The script itself issues no lifecycle invocation,
table mutation, API mutation, workflow dispatch, deployment, identity change,
schedule, alias, Pages publication, policy action, model action, or production
action.

A passing result would establish only synthetic staging engineering evidence
that the deployed producer preserved the SLA Decision binding on a naturally
eligible proposal. It would not establish human approval, execution, realised
value, causal effect, real logistics performance, model readiness, policy
readiness, or production readiness.
