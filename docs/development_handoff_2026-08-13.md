# Development handoff -- 13 August 2026

## Completed today

The additive Action assignment schema is now applied and verified in isolated
staging. Before the change, a named human saved the deployed audit-table and
Action-view definitions privately. The human then ran the two reviewed
statements from `sql/15_action_assignment_v1.sql` against
`simulated_iceberg_m` in `us-east-1`; both Athena executions completed
successfully.

Read-only post-migration query
`858a5024-1e08-487b-8dd4-b01a0302acca` returned all five required checks with
zero failures. Glue inspection confirmed `action_owner:string` and
`action_due_date:date` on both the Action audit table and current-state view.

A dedicated local schema-plan script now renders the reviewed migration and
validation SQL without exposing an AWS execution path. Local verification
passed 239 Python tests and all 15 project-drift checks.

Operations API plan run `31680467442` and separately approved deploy run
`31680885483` succeeded for commit `fb7a3a6`. The API stack finished at
`UPDATE_COMPLETE`, its Lambda was active/successful, and the selected artifact
matched that commit. A separately approved private Amplify deployment reported
`SUCCEED` at `2026-08-13T18:18:15.521000+10:00`; Public Pages and production
were not targeted.

The assignment-specific runtime verifier passed every identity, API, static
asset, CORS, alarm, and log gate. The separately approved four-role run passed
all allow/deny checks using an unguessable missing Action ID, so it appended no
real audit event. An initial externally timed-out run left four temporary users;
they were identified exactly, removed, and reconciled to zero before a
successful 205-second rerun. That rerun also removed its four users, and an
independent final check confirmed zero temporary role-check users.

The named-human canary then recorded one valid staging `EDIT`. The audit table
contained exactly one event for one request ID and one Action, and the current
view resolved that Action to `EDITED` with valid assignment fields. The browser
received HTTP 503 after the successful write because the mutation Lambda tried
to return a Python `date` object. Safe logs classified this as a Lambda response
marshal failure; both Lambdas remained active and successfully configured.

Commit `763a817` converts response dates to ISO strings and adds a Lambda-level
JSON serialization regression test. It is pushed to `main`, passed 240 Python
tests and all 15 drift checks locally, and is not deployed. The operator session
used during diagnosis was globally signed out, and read-only reconciliation
confirmed that identity now belongs only to the `operator` group. No token or
private identifier is retained in repository evidence.

## AWS profile visibility finding

The existing user-level `codex-readonly` profile was present and valid. The
initial missing-profile result came from the repository sandbox being unable to
see the Windows user's `.aws` directory. Inspection in the normal Windows user
environment found both `default` and `codex-readonly`; STS confirmed the
read-only session for account `381491905860`. No credentials were copied into
the repository.

## Current boundary

The staging schema, Action mutation Lambda, Operations API, and private
frontend now support `EDIT`, named owner, due date, and `EDITED`. Runtime and
four-role gates passed. The operator half of the Action canary wrote one real
staging `EDIT` and left the Action at `EDITED`; the response-fix release, stable
request-ID retry, and separate approver decision remain incomplete. No
production mutation, alias movement, schedule activation, Pages publication,
or policy/model promotion occurred today.

## Next authorised decision

The next decision is whether to commit and push this synchronized evidence,
wait for CI, and approve a narrow mutation-Lambda response-fix Prepare run for
that exact new `main` commit, which contains implementation commit `763a817`.
After reviewing its exact one-resource change set, Execute requires separate
approval. After deployment and token-expiry containment, the same named
operator must retry the original request ID; a different named approver must
then approve or reject the `EDITED` Action. The agent cannot perform the
release or either human decision.
