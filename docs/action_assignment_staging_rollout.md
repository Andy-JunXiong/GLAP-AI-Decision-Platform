# Action assignment staging rollout

**Status:** assignment, approval, Evidence refresh, named-human Action
completion, and pending simulated Outcome runtime-verified; observation waits
for the separately governed due-date continuation

This package governs the repository implementation of Action `EDIT`, owner,
due date, and `EDITED` review state for private staging. The Action mutation
Lambda package was released through the governed staging path on 2026-08-10.
The additive schema migration was separately reviewed and applied by a named
human on 2026-08-13. The Operations API and private frontend were then released
through their separately approved plan-first paths. This document does not
authorize another deployment, persistent user creation, or an operational
Action mutation. The separately authorised named-human canary now covers the
operator `EDIT`, stable request-ID retry, different-person `APPROVE`, and the
later separately authorized named-human `COMPLETE`. A later separately
authorized actual-calendar continuation created one pending simulated Outcome.
Neither consumed authority creates standing authority; observation remains a
separate decision.

## Preflight and release order

1. Re-run the repository validator and all local quality gates.
2. Render and review the deterministic local schema plan, then record the
   current staging audit-table and Action-view definitions privately. The plan
   script has no AWS execution path:

   ```powershell
   .\ops\plan_action_assignment_schema.ps1 -ShowSql
   ```

   A missing AWS session does not weaken this boundary; it means the deployed
   definitions cannot yet be recorded and the migration must not proceed.
3. A named human reviews and applies the additive
   `sql/15_action_assignment_v1.sql` migration. Completed on 2026-08-13 against
   `simulated_iceberg_m` only.
4. Run the read-only `sql/16_action_assignment_validation.sql`; all five checks
   must return zero. Completed on 2026-08-13: query
   `858a5024-1e08-487b-8dd4-b01a0302acca` returned five checks and zero total
   failures; both assignment columns were present on the audit table and view.
5. Release the Action mutation Lambda. The existing lifecycle workflow updates
   the whole stateful stack and remains prohibited. The reviewed previous-
   template, one-resource change-set design is documented in
   [`action_mutation_staging_release_rfc.md`](action_mutation_staging_release_rfc.md).
   This step completed on 2026-08-10 through separately approved Prepare run
   `31359941156` and Execute run `31360187221`. The stack finished at
   `UPDATE_COMPLETE`, and the active Lambda digest matched the reviewed
   artifact. This does not pre-authorise another release.
6. Run the existing Operations API workflow in `plan`, then separately approve
   its `deploy` action. Plan run `31680467442` and deploy run `31680885483`
   succeeded for commit `fb7a3a6`; the stack finished at `UPDATE_COMPLETE` and
   selected the commit-addressed artifact.
7. Run the existing internal frontend publisher in plan mode, then separately
   approve publication to the private staging origin. Completed on 2026-08-13;
   the latest private Amplify job reported `SUCCEED`. Public Pages and
   production were not targeted.
8. Run `verify_operations_staging.ps1 -RequireActionAssignment` and
   `verify_operations_roles_staging.ps1 -Apply -RequireActionAssignment`.
   Completed on 2026-08-13. All runtime gates and role checks passed. Four
   temporary users were removed, and independent reconciliation found zero
   remaining role-check users. An initial externally timed-out run was also
   reconciled and its four temporary users were removed before the successful
   rerun.
9. Two named signed-in humans perform the canary: an operator records `EDIT`
   and a separate approver approves or rejects it. Retry the same request ID and
   confirm no duplicate audit event. The operator phase started on 2026-08-13:
   one valid `EDIT` event was appended and the current Action resolved to
   `EDITED`. The API returned 503 only after the write because the mutation
   response contained a Python `date` that Lambda could not JSON-serialize.
   Read-only reconciliation found one event, one Action, one request ID, valid
   assignment fields, and one row for that request ID.
10. Release the response-only serialization fix through the same narrow,
    separately approved mutation-Lambda Prepare/Execute path. Completed on
    2026-08-23. Prepare run `32623784739` and Execute run `32624244648`
    selected pushed commit `08b21e3`, changed only the non-replacing Action
    mutation Lambda, and finished with the stack at `UPDATE_COMPLETE`. Direct
    read-only inspection found the Python 3.14 Lambda active with its last
    update successful. Production effect remained false. The whole lifecycle
    stack and direct Lambda update path were not used.
11. After the fix is deployed and the prior operator token has expired, the
    same named operator retries the original request ID and confirms the audit
    row count remains one. A different named approver may then approve or reject
    the `EDITED` Action. Completed on 2026-08-23 under two separately confirmed
    named-human identities. The stable retry returned HTTP 200 with
    `idempotent_replay=true`; reconciliation retained one request-ID row, one
    current `EDITED` row, matching assignment, and zero approval events. The
    different named approver then selected `APPROVE`. Final reconciliation
    returned one `EDIT`, one `APPROVE`, zero `REJECT`, zero `COMPLETE`, two
    distinct named actors, one current `APPROVED` row, and one assignment
    match.
12. Publish the post-mutation Evidence-chain refresh correction only through
    the separately governed private-frontend path, then run the read-only
    staging verifier with all Action assignment, Action evidence, and Learning
    evidence gates enabled. Completed on 2026-08-23: a named human published
    the clean frontend tree at commit `adfd2a5`, and every reported verifier
    check passed. No Action mutation was performed, so this verifies the
    deployed bundle and governance controls but not the refresh interaction end
    to end. On `2026-08-24`, a separately authorized named operator opened an
    eligible `PROPOSED` Action's Evidence chain, submitted one `EDIT`, and
    reported that the Board changed to `EDITED` while the already expanded
    chain automatically displayed the new event. The bounded aggregate-only
    reconciler then confirmed exactly one matching `EDIT`, one Action, one
    request ID, one named actor, a valid assignment, one current `EDITED` row,
    and one matching current assignment. It printed no protected identifiers:

    ```powershell
    .\ops\reconcile_action_evidence_refresh_staging.ps1 `
      -Profile codex-readonly `
      -ObservationDate 2026-08-24
    ```

Steps 3-12 and the later refresh interaction reconciliation are complete. The
original operator identity was independently
confirmed as operator-only, and the decision used a different named approver.
On `2026-08-25`, the project owner explicitly authorized the next bounded
canary step. A signed-in named human used the private Action Board to submit
one `COMPLETE`; the agent did not click or submit it. Aggregate-only read-only
reconciliation then found one current `COMPLETED` candidate, one `EDIT`, one
`APPROVE`, zero `REJECT`, exactly one named-human `COMPLETE`, a matching
assignment, and zero Outcomes before continuation. Protected identifiers were
not printed. A later explicit project-owner authorization allowed the agent to
trigger manual workflow run `32803181376` through the named GitHub session.
The run extended only `2026-08-25` in `OPERATIONAL` / `ACTUAL_CALENDAR` mode;
the aggregate-only pending reconciler passed 6/6 with one unobserved
`PENDING` / `SIMULATED` Outcome and the three-day due-date rule. The consumed
authority grants no observation, production, Pages, deployment, schedule,
alias, policy, or model authority.

The agent may prepare and validate these artifacts but may not perform steps
3, 6-7, 9, 11-12, or any future release write. Temporary role-test users in
step 8 also require explicit human approval because that verifier writes to
Cognito before cleaning them up.

## Rollback decision

Before package rollback, use aggregate-only read queries to count `EDIT` audit
events and current `EDITED` Actions.

The 2026-08-13 reconciliation found nonzero `EDIT`/`EDITED` evidence, so the
zero-event package rollback path is no longer available for this rollout.

- If both counts are zero, previous application packages may be restored while
  retaining the additive columns and migration evidence. Re-run the old role
  matrix and read-only staging verifier.
- If either count is nonzero, do not deploy mutation code that cannot understand
  `EDITED`, drop columns, delete events, or rewrite status. Disable new `EDIT`
  entry in the private UI/API while retaining the new reader/mutation contract,
  then forward-fix and reconcile the affected Actions with named humans.

Rollback never changes production, publishes to Pages, activates a schedule,
or erases audit history.

## Smoke-test evidence

Retain only bounded evidence: commit SHA, workflow/run IDs, schema check totals,
role/status matrix, request-ID replay result, and safe timestamps. Never record
tokens, passwords, raw claims, shipment details, ARNs, S3 paths, or query text
in public artifacts.

The machine-readable source is
[`action_assignment_rollout_contract.json`](action_assignment_rollout_contract.json).
