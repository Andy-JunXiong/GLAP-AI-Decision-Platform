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
four-role gates passed. No real `EDIT` event, Action canary, production
mutation, alias movement, schedule activation, Pages publication, or
policy/model promotion occurred today.

## Next authorised decision

The only remaining Action assignment rollout step is the two-human canary. A
named signed-in operator must record `EDIT` and retry the same request ID; a
different named signed-in approver must then approve or reject it. The agent
cannot perform either human decision.
