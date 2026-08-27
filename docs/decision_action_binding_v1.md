# Decision-to-Action binding v1

**Status:** staging schema, producer, and private readers deployed and verified;
`2026-08-27` Cost reconciliation failed closed with zero natural candidates;
SLA reconciliation found natural candidates but failed closed on exact binding

This contract makes a newly generated governed Action prove which implemented
Decision Brief recommendation produced its immutable proposal. It does not add
an Action-creation endpoint, allow the cockpit to write proposals directly, or
change the existing named-human approval path.

## Immutable proposal binding

For a valid open `SLA_BREACH` that satisfies `decision-brief.v1`, the lifecycle
generator writes these fields once on the Action proposal:

```json
{
  "decision_brief_version": "decision-brief.v1",
  "selected_alternative": "EXPEDITE_MILESTONE",
  "selection_rationale": "Review an expedite intervention for <milestone>; the governed delay is <hours> hours above threshold."
}
```

The selected alternative is the deterministic rule's proposal, not a claim of
human approval or execution. The Action remains `PROPOSED` with
`approval_required = true`. Its stable ID and existing retry-safe merge key are
unchanged.

The generator applies the same fail-closed eligibility boundary as the brief:
shipment-milestone grain, an exact milestone/delay-metric pair, a supported
severity, finite non-negative values, and an actual threshold breach. It will
not stamp a `decision-brief.v1` binding onto an invalid SLA proposal.

For a valid open `COST_ANOMALY`, the deployed extension reuses the same immutable
fields:

```json
{
  "decision_brief_version": "decision-brief.v1",
  "selected_alternative": "REVIEW_COST",
  "selection_rationale": "Review the governed cost basis under stateful-cost-variance.v1; total cost variance is <margin> percentage points above threshold."
}
```

The Cost boundary requires exact shipment-cost grain, total-cost dimension,
`cost_variance_pct` metric, supported severity, finite non-negative values, and
a strict threshold breach. It does not infer the unavailable rate-card version.

## Human review binding

A human decision cannot truthfully exist when the system first creates a
proposal. Therefore human rationale is not prewritten into the Action row.
The existing named-human `EDIT`, `APPROVE`, or `REJECT` event stores the actor,
decision, and reason in the append-only audit table. The evidence chain shows
the immutable system proposal next to those chronological human judgments.

This division preserves both sides of the contract:

```text
Alert + deterministic Decision Brief
  -> immutable Action proposal binding
  -> named-human append-only review reason
  -> approval-gated execution and delayed synthetic Outcome
```

## Compatibility and rollout boundary

- Existing Actions are not backfilled. Missing binding fields mean `legacy
  proposal — binding unavailable`, not an inferred Decision Brief.
- Existing and pre-release `COST_ANOMALY` Actions remain unbound and are never
  backfilled. Only a future newly generated eligible Cost proposal may receive
  the exact `decision-brief.v1` / `REVIEW_COST` binding.
- `sql/16_decision_action_binding_v1.sql` is an additive migration for isolated
  staging. A named human applied it on `2026-08-25`; the following aggregate
  validator returned all six checks with zero failures.
- `sql/17_decision_action_binding_validation.sql` and the local-only renderer
  now provide the exact aggregate post-migration checks and human-owned release
  order. See
  [`decision_truth_staging_rollout.md`](decision_truth_staging_rollout.md).
- The authenticated Action Queue, Action Board, and evidence chain expose the
  binding read-only. They gain no new mutation or approval authority.

Local tests establish persistence, API, cockpit, immutability, legacy-null, and
independent one-resource Generator release behavior. The staging schema is
applied and the earlier SLA-only validator passed. The revised source-delivered validator
allows only the exact SLA and Cost pairs and has not run in staging.
Named-human refactor run `32948002162` moved only the Generator into its
independent stack. For the Cost extension, commit `0e5b740` passed CI
`32982375432`; plan run `32982600783` validated one non-replacing Generator
change without upload or execution; deploy run `32982946620` released only
that resource. Operations API plan/deploy runs `32982375374` and `32983721998`
succeeded, the named human published the matching private cockpit, and the
read-only and four-role verifiers passed with all four temporary users removed.
The exact-pair validator revision has not run in staging. Bounded plan run
`33020601008` and separately authorized continuation run `33020683956` advanced
only `2026-08-27`; the Generator ran and all 41 checks passed. The workflow did
not expose aggregate proposal or binding counts. The subsequent aggregate query
found zero natural Cost proposals, zero invalid bindings, and zero pre-release
backfilled Cost bindings. With no candidate, exact runtime binding correctness
is not established. No human Action judgment, production surface, or public
surface changed.

The local runtime-evidence reconciler now prepares the next read-only gate. It
requires one or more naturally generated actual-calendar Cost proposals,
validates their exact source Alert and immutable binding, compares the binding
with the current view, and fails if any pre-release Cost Action was backfilled.
Its separately authorized `2026-08-27` run found zero natural candidates and
failed closed; it cannot invoke the Generator or mutate an Action. See
[`cost_anomaly_runtime_evidence_v1.md`](cost_anomaly_runtime_evidence_v1.md).

The separate SLA runtime reconciler is also aggregate-only and fail-closed. It
requires exactly one eligible same-date source Alert, one of the seven governed
milestone/metric pairs, the exact `decision-brief.v1` /
`EXPEDITE_MILESTONE` binding and calculated breach-hours rationale, an
immutable unreviewed proposal, a matching current-view projection, and no
invented binding on pre-release SLA Actions. Its separately authorized
`2026-08-27` query found natural proposals and passed the source, immutable-
state, current-view, and legacy-null checks. At least one proposal failed the
exact binding and the invalid-binding count was non-zero, so no runtime binding
evidence or root cause is accepted. Every future query is a separately
authorized external operation. See
[`sla_breach_runtime_evidence_v1.md`](sla_breach_runtime_evidence_v1.md).

The separately authorized `-BindingDiagnostic` run preserved the seven full-
gate booleans and added five aggregate-only binding components. Brief version,
Action type, and selected alternative passed; exact milestone-bound rationale
shape and calculated rationale value failed. Versioned deployed source matches
the expected template, but aggregate evidence cannot distinguish persisted-
text from verifier-expression drift. It exposed no identifiers, repaired
nothing, and established no root cause.

The optional `-RationaleDiagnostic` mode retains every earlier check and adds
five regex-independent booleans for presence, exact milestone prefix, governed
suffix, finite non-negative numeric token, and numeric equality. Its first
separately authorized execution failed before results on
`ENDS_WITH_EXPRESSION`; after a local `length` plus `substr` correction, the
separately authorized retry returned all five rationale-only booleans true
while the legacy regex checks remained false. This validates the persisted
rationale and isolates verifier-expression drift: `[A-Z_]+` excludes digits in
governed `P2P_*` milestones. The local full-gate verifier now reuses the
compositional rationale checks and contains no rationale regex. The separately
authorized corrected full reconciliation returned all seven aggregate booleans
true, establishing synthetic staging runtime evidence for the natural SLA
Decision binding. It exposes no text or identifiers and cannot repair a
proposal; no Action was mutated.
