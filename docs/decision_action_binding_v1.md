# Decision-to-Action binding v1

**Status:** staging schema and producer deployed; producer not invoked; readers not deployed

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
applied and validated. Named-human refactor run `32948002162` moved only the
Generator into its independent stack; plan run `32951563950` validated the
exact-one non-replacing release without upload; separately authorized deploy
run `32956001803` deployed the Generator from commit `9eb031f`. Read-only
acceptance verified the one-resource parameter-free template, matching
artifact/Lambda SHA-256, preserved execution role, zero aliases, and no
shared-stack deployment-window event. The Generator was not invoked, so no
bound runtime Action was observed. No Action was created or mutated, and no
staging reader, production, or public surface was deployed.
