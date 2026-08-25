# Decision Truth private staging rollout

**Status:** plan-only handoff; no deployment or migration authorized

This is the minimum human execution handoff for moving the locally verified
`SLA_BREACH` Decision Truth chain into isolated private staging. It adds no new
governance layer and creates no standing deployment or operational authority.

## Local preflight

Render the exact migration and aggregate validation locally:

```powershell
.\ops\plan_decision_truth_staging_rollout.ps1 -ShowSql
```

The renderer accepts only a safe Athena database identifier, requires exactly
two migration statements and one validation statement, rejects destructive
migration operations, rejects every write operation in validation, and never
opens an AWS session. Its output is a plan, not evidence that staging changed.

## Human-owned release order

Each numbered write is a separate human authority decision. Finishing one does
not authorize the next.

1. A named staging data administrator reviews and applies only
   `sql/16_decision_action_binding_v1.sql` to the isolated staging database.
   Existing Action rows remain null; no backfill is allowed.
2. The administrator runs only the read-only
   `sql/17_decision_action_binding_validation.sql`. All six aggregate
   `failure_count` values must be zero. Stop on any nonzero or missing result.
3. A named staging release owner reviews and deploys the current isolated
   lifecycle producer through the existing manual stateful-lifecycle workflow.
   This producer step is required because the immutable binding is written
   when a new Action proposal is generated; deploying only readers cannot
   create truthful bindings.
4. A named staging release owner runs the existing Operations API workflow in
   `plan`, reviews it, and separately dispatches `action=deploy` if approved.
5. A named staging release owner first runs
   `ops/deploy_internal_operations_frontend.ps1` without `-Apply`, then
   separately decides whether to rerun it with `-Apply` for the private origin.
   Public Pages is not a target.
6. Run the read-only staging contract verifier. Four-role verification remains
   a separately approved human operation because it creates and then removes
   temporary Cognito users.

The agent may prepare, validate, and explain this handoff. It may not perform
steps 1, 3, 4, 5, or the write-capable role-verification step.

## Runtime evidence boundary

Schema and reader checks do not prove that a bound Action exists. Existing
Actions intentionally remain legacy-null. End-to-end runtime proof requires a
later, separately authorized `OPERATIONAL` / `ACTUAL_CALENDAR` lifecycle
continuation that naturally generates an eligible new `SLA_BREACH` proposal.
Do not create, backfill, or mutate an Action merely to satisfy the test.

The runtime verifier may then report only aggregate counts showing that:

- the new Action has either all three binding fields or none;
- any `decision-brief.v1` binding is `SLA_BREACH` /
  `EXPEDITE_MILESTONE`;
- every `COST_ANOMALY` Action remains unbound;
- the current view matches the immutable proposal row.

This remains synthetic staging engineering evidence. It proves no execution,
Outcome quality, causality, realised value, real logistics performance, model
readiness, policy authority, or production readiness.

## Rollback boundary

The additive columns are retained. Never drop them, rewrite existing proposal
rows, or delete audit/Outcome evidence.

- Before any bound Action exists, a human release owner may restore the prior
  lifecycle producer, API, or private frontend packages and rerun read-only
  verification.
- After a bound Action exists, package rollback must not deploy code that
  cannot preserve or read the binding. Disable new proposal generation if
  necessary, forward-fix, and retain all immutable proposal and audit evidence.

Rollback never changes production, moves a production alias, creates a
schedule, publishes Pages, activates a policy/model, or authorizes an
operational Action mutation.
