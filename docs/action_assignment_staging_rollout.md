# Action assignment staging rollout

**Status:** application rollout verified; named-human Action canary pending

This package prepares the repository implementation of Action `EDIT`, owner,
due date, and `EDITED` review state for private staging. The Action mutation
Lambda package was released through the governed staging path on 2026-08-10.
The additive schema migration was separately reviewed and applied by a named
human on 2026-08-13. The Operations API and private frontend were then released
through their separately approved plan-first paths. This document does not
authorize another deployment, persistent user creation, or an operational
Action mutation.

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
   confirm no duplicate audit event.

Steps 3-8 are complete. The deployed private API and frontend now expose the
assignment contract. No real Action mutation or canary occurred. Step 9 retains
its separate two-human boundary.

The agent may prepare and validate these artifacts but may not perform steps
3, 6-7, or 9, or any future release write. Temporary role-test users in step 8
also require explicit human approval because that verifier writes to Cognito
before cleaning them up.

## Rollback decision

Before package rollback, use aggregate-only read queries to count `EDIT` audit
events and current `EDITED` Actions.

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
