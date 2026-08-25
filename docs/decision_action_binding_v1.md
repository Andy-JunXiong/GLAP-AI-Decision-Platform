# Decision-to-Action binding v1

**Status:** implemented and locally verified; not deployed or migrated

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
- `COST_ANOMALY` remains unbound because no Cost Decision Brief contract has
  been implemented; its three binding fields remain null.
- `sql/16_decision_action_binding_v1.sql` is an additive, plan-only migration
  for isolated staging. It must be separately reviewed and applied before this
  code can be deployed.
- `sql/17_decision_action_binding_validation.sql` and the local-only renderer
  now provide the exact aggregate post-migration checks and human-owned release
  order. See
  [`decision_truth_staging_rollout.md`](decision_truth_staging_rollout.md).
- The authenticated Action Queue, Action Board, and evidence chain expose the
  binding read-only. They gain no new mutation or approval authority.

Local tests establish schema, persistence, API, cockpit, immutability, and
legacy-null behavior only. No SQL was applied, no AWS resource was changed, no
Action was created or mutated, and no staging, production, or public surface
was deployed.
