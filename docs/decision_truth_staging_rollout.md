# Decision Truth private staging rollout

**Status:** existing SLA schema, independent one-resource stack, authenticated
Operations API, and private cockpit deployed and verified; COST_ANOMALY v1
producer/readers released and RBAC verified; Generator not invoked

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
   Existing Action rows remain null; no backfill is allowed. Completed by the
   named human on `2026-08-25`.
2. The administrator runs only the read-only
   `sql/17_decision_action_binding_validation.sql`. All six aggregate
   `failure_count` values must be zero. Stop on any nonzero or missing result.
   Completed on `2026-08-25`; all six checks returned zero.
3. A named staging release owner reviews and deploys the current isolated
   lifecycle producer through the independent Generator workflow. After the
   source is validated, committed, and pushed, a named IAM administrator first
   reviews and separately applies the required staging-only refactor
   permissions. Then dispatch `plan-refactor`, review its exact one-resource
   move, and make a separate decision whether to run `execute-refactor` with the
   exact reviewed ID. After exclusive ownership is verified, dispatch
   `plan-release`; only a later separate decision may run `deploy-release`.
   This producer step is required because the immutable binding is written
   when a new Action proposal is generated; deploying only readers cannot
   create truthful bindings. Refactor planning accepts exactly one
   `LifecycleGeneratorFunction` `MOVE`. Release planning creates and deletes an
   unexecuted change set and accepts exactly one non-replacing Lambda
   modification; it uploads no artifact. Neither path applies schema or invokes
   a lifecycle date. See the
   [Generator stack refactor runbook](stateful_lifecycle_generator_stack_refactor.md).
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

## Verified staging progress

The named human applied the two additive statements and ran the aggregate-only
validator on `2026-08-25`. The Athena result completed with exactly six rows;
all six checks returned zero. This establishes the three Action-table columns,
the three current-view columns, no partial or invalid v1 binding, no Cost
binding under the then-deployed SLA-only producer, and table/view agreement at
that query time. It does not prove a new bound Action exists. The repository
validator now accepts only the exact `SLA_BREACH` / `EXPEDITE_MILESTONE` and
`COST_ANOMALY` / `REVIEW_COST` v1 pairs; that validator revision has not run in
staging.

Manual workflow run `32853867334` from commit `978beb8` then completed with
`action=plan`, `execution_mode=OPERATIONAL`, an empty scenario ID, and
`time_basis=ACTUAL_CALENDAR`. It created no artifact and performed no stack
deployment, schema write, seed, replay, lifecycle invocation, or continuation.
Commit `59a9eaa` delivered the repository-local `deploy-stack-only` candidate
and its separate `plan-stack-only` prerequisite. Run `32901614061` completed
the original render-only `plan-stack-only` path. Human-dispatched deploy run
`32905914076` reached the exact change-set gate, uploaded the inactive
commit-addressed generator artifact, and failed closed because the change set
was not exactly one non-replacing generator modification. The change set was
deleted before execution; no stack resource, schema, lifecycle date, alias,
schedule, Action, or production path changed. The locally corrected plan now
creates, sanitizes, validates, and deletes an unexecuted temporary change set so
the mismatch can be diagnosed before any later deployment decision. Commit
`f9bbad2` delivered that correction and CI run `32907780599` passed. Human
diagnostic plan runs `32908262838` and `32917959958` then consistently reported
three non-replacing changes: `LifecycleGeneratorFunction`,
`IntegrationControllerFunction`, and `IntegrationControllerRole`. Both failed
closed and cleaned up without artifact upload, change-set execution, or stack
resource change. Commit `fd6d532` then delivered the deployed-template and
previous-parameter baseline. Human plan run `32920083879` still returned the
same three changes, proving the remaining cause was shared-stack dependency
propagation rather than parameter drift. It also uploaded nothing, executed no
change set, and changed no resource. The replacement is an independent
one-resource Generator stack with five separately dispatched refactor/release
actions. The bounded IAM update, refactor, plan-first release, deployment, and
read-only artifact/runtime-config verification are complete through runs
`32948002162`, `32951563950`, and `32956001803`. The Generator has not been
invoked, so no bound runtime Action has been observed.

Operations API plan run `32972934184` then completed from commit `a3fe692` with
the deploy step explicitly skipped. Separately authorized run `32973297196`
deployed the authenticated staging API successfully. The first matching private
frontend attempt failed during local Next.js type checking before archive
creation or any Amplify deployment. The verification-result type now binds
`VERIFIED` to `MATCH` and `MISMATCH` to non-match diagnostic codes; frontend
lint, the internal production build, and all five frontend tests passed locally.
Fix commit `2627da6` then passed ordinary CI run `32975380386`, and the named
human published the corrected private cockpit without printing its protected
origin or deployment identifiers.

The read-only staging verifier passed every configured frontend, API, CORS,
alarm, logging, and redaction check. The separately human-run four-role verifier
passed its reader, role-bound mutation, response-contract, temporal,
governance, and redaction checks, then removed all four temporary users. It did
not mutate a real Action. Runtime reads remained bounded: Action evidence was
`ACTION_OPEN` with zero audit events and no Outcome; Learning remained
`INSUFFICIENT_ELIGIBLE_OUTCOMES` at 1/20 with no proposal; label readiness had
one insufficient provider group, no ready group, and zero of three eligible
targets. The Generator was not invoked, so no bound runtime Action, eligible
Decision comparison cohort, or browser fingerprint exercise is claimed.

Commit `0e5b740` then delivered the Cost extension and passed CI run
`32982375432`. Push-triggered Operations API plan `32982375374` succeeded with
the deploy step skipped. Generator plan `32982600783` accepted one
non-replacing `LifecycleGeneratorFunction` modification and deleted the change
set without upload or execution; separately authorized deploy `32982946620`
released only that independent Generator. Separately authorized Operations API
deploy `32983721998` completed its staging stack update. The named human then
ran the private frontend plan and apply steps; the production build and private
Amplify release succeeded without printing protected origin or deployment
identifiers. The read-only verifier passed again for all configured surfaces,
and the separately authorized four-role matrix passed all reader, denial,
contract, temporal, governance, and redaction checks before removing all four
temporary users. The revised exact-pair Athena validator has not run in
staging. No lifecycle continuation, bound Cost proposal, real Action mutation,
schedule, alias, Pages, or production change occurred.

## Runtime evidence boundary

Schema and reader checks do not prove that a bound Action exists. Existing
Actions intentionally remain legacy-null. Existing `COST_ANOMALY` Actions
remain unbound and are never backfilled. The producer/API/cockpit releases are
complete, but end-to-end runtime proof still requires a separately authorized
`OPERATIONAL` / `ACTUAL_CALENDAR` lifecycle continuation that naturally
generates an eligible new `SLA_BREACH` or `COST_ANOMALY` proposal.
Do not create, backfill, or mutate an Action merely to satisfy the test.

The runtime verifier may then report only aggregate counts showing that:

- the new Action has either all three binding fields or none;
- any SLA `decision-brief.v1` binding is `SLA_BREACH` /
  `EXPEDITE_MILESTONE`;
- every newly bound `COST_ANOMALY` Action is `decision-brief.v1` /
  `REVIEW_COST`, while pre-release Cost Actions may remain legacy-null;
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
