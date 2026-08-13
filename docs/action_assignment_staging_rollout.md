# Action assignment staging rollout

**Status:** canary partially complete; response fix release, stable retry, and
separate approver decision pending

This package governs the repository implementation of Action `EDIT`, owner,
due date, and `EDITED` review state for private staging. The Action mutation
Lambda package was released through the governed staging path on 2026-08-10.
The additive schema migration was separately reviewed and applied by a named
human on 2026-08-13. The Operations API and private frontend were then released
through their separately approved plan-first paths. This document does not
authorize another deployment, persistent user creation, or an operational
Action mutation. One separately authorised named-human canary `EDIT` has since
been recorded; it does not create standing authority for another mutation.

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
    separately approved mutation-Lambda Prepare/Execute path. Implementation
    commit `763a817` is pushed to `main`, passes 240 local tests, and is not
    deployed. Prepare must target the later clean, pushed `main` commit that
    contains both `763a817` and this synchronized evidence, not the earlier
    stale-document snapshot. Do not use the whole lifecycle stack or a direct
    Lambda update.
11. After the fix is deployed and the prior operator token has expired, the
    same named operator retries the original request ID and confirms the audit
    row count remains one. A different named approver may then approve or reject
    the `EDITED` Action.

Steps 3-8 and the first write in step 9 are complete. The operator session used
during diagnosis was globally signed out, and the identity was independently
confirmed as operator-only. Steps 10-11 remain blocked on separate release and
human authority. No retry, approver decision, production mutation, Pages
publication, or schedule activation occurred.

The agent may prepare and validate these artifacts but may not perform steps
3, 6-7, 9, or 11, or any future release write. Temporary role-test users in step 8
also require explicit human approval because that verifier writes to Cognito
before cleaning them up.

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
