# Action assignment staging rollout

**Status:** plan-only; blocked pending a reviewed narrow mutation-Lambda release path

This package prepares the repository implementation of Action `EDIT`, owner,
due date, and `EDITED` review state for private staging. It does not authorize
or execute Athena DDL, Lambda/API deployment, frontend publication, user
creation, or an operational Action mutation.

## Preflight and release order

1. Re-run the repository validator and all local quality gates.
2. Record the current staging audit-table and Action-view definitions privately.
3. A named human reviews and applies the additive
   `sql/15_action_assignment_v1.sql` migration.
4. Run the read-only `sql/16_action_assignment_validation.sql`; all five checks
   must return zero.
5. Release the Action mutation Lambda. This is currently blocked: the existing
   lifecycle workflow updates the whole stateful stack, so a narrow sanctioned
   release path must be reviewed before continuing. The proposed previous-
   template, one-resource change-set design is documented in
   [`action_mutation_staging_release_rfc.md`](action_mutation_staging_release_rfc.md).
   Its manual read-only plan stage is implemented, but no AWS write phase is
   approved or implemented.
6. Run the existing Operations API workflow in `plan`, then separately approve
   its `deploy` action.
7. Run the existing internal frontend publisher in plan mode, then separately
   approve publication to the private staging origin.
8. Run `verify_operations_staging.ps1 -RequireActionAssignment` and
   `verify_operations_roles_staging.ps1 -Apply -RequireActionAssignment`.
9. Two named signed-in humans perform the canary: an operator records `EDIT`
   and a separate approver approves or rejects it. Retry the same request ID and
   confirm no duplicate audit event.

The agent may prepare and validate these artifacts but may not perform steps
3, 5-7, or 9. Temporary role-test users in step 8 also require explicit human
approval because that verifier writes to Cognito before cleaning them up.

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
