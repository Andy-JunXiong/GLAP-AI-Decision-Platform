# RFC: narrow Action mutation Lambda staging release

**Status:** staging release and rollback recovery verified on 2026-08-10

Commit `3b4dd78` published the initial implementation to `main`; subsequent
hardening commits `7df651f`, `8605868`, and `bde0927` corrected immutable
checkout validation, CloudFormation execution-role evidence, and completed
rollback-state handling. The two protected environments and three separated
roles were configured by named humans without publishing protected values.
Plan, Prepare, Execute, failed rollback recovery, and a successful retry have
now all been exercised in staging.

## Approved decision

On 9 August 2026, the user approved implementing only the plan stage of a
staging release path that retains the existing CloudFormation-owned
`ActionMutationFunction`, does not directly update Lambda code, and does not
replay the broader stateful lifecycle deployment.

The manual plan workflow and local packaging/inspection script are repository
implementation evidence. On 9 August 2026, the user subsequently authorised
repository implementation of the prepare/execute phases, without authorising
their AWS execution. This approval does not authorise an IAM or
CloudFormation change, artifact upload, change-set creation or execution,
schema migration, frontend/API deployment, or operational Action mutation.

## Current ownership and verified release

`ActionMutationFunction` belongs to the existing
`glap-stateful-lifecycle-staging` CloudFormation stack. Its code is selected by
the `ActionMutationArtifactKey` parameter. The Operations API invokes this
unaliased staging function by its exact name.

The existing lifecycle deployment packages four Lambdas and submits the whole
repository template and every stack parameter. That is too broad for this
release. The repository deployer-policy script also omits the Action mutation
function and execution role from its managed-resource lists.

GitHub Actions run `31297032412` inspected the boundary on 9 August 2026 from
commit `35e2d46`. OIDC role assumption, repository validation, 228 unit tests,
and all 15 drift checks passed. The plan then failed closed because the staging
role lacks `lambda:GetFunctionConfiguration` for the CloudFormation-owned
`ActionMutationFunction`. The run reported no artifact upload, change set,
Lambda update, IAM/CloudFormation modification, or production effect.

The exact missing capability is recorded in
[`action_mutation_staging_read_permission_proposal.json`](action_mutation_staging_read_permission_proposal.json).
That artifact is deliberately not an executable IAM policy, contains no account
ID or ARN, and permits no wildcard. On 9 August 2026, the repository owner
approved that exact read capability for named-human application. The approval
does not permit the agent to modify IAM and does not approve any release write.

The named repository owner then applied the exact-resource permission. GitHub
Actions run `31298179885` on commit `ed475f3` passed 231 unit tests, all 15 drift
checks, OIDC assumption, local two-file packaging, and the bounded AWS
inspection. It verified stable CloudFormation ownership and Lambda
configuration. Artifact upload, change-set creation or execution, Lambda code
update, IAM/CloudFormation modification, operational Action mutation, and
production effect were all absent. This closed the original read-permission
blocker. Release writes still required separate human decisions and did not
become implicit authority.

On 2026-08-10, CI run `31353483375` and read-only Plan run `31353510147`
passed for `bde0927`. The first approved execution exposed two additional
rollback-only gaps: the CloudFormation service role could not resolve every
exact template role or read the retained previous mutation artifact. The stack
reached `UPDATE_ROLLBACK_FAILED`. A named human added only the exact missing
reads and continued rollback without skipping any resource. The stack returned
to `UPDATE_ROLLBACK_COMPLETE`, and the previous artifact was restored.

Prepare run `31359941156` then created a new available, unexecuted change set
containing exactly one non-replacing `ActionMutationFunction` property change.
After a separate Execute approval, run `31360187221` completed with stack
status `UPDATE_COMPLETE`. The active Lambda code digest matched the reviewed
content-addressed artifact and the workflow reported no production effect.

## Approved and verified design

Keep the resource in its current stack and use a CloudFormation update change
set with the stack's previous template. Preserve every previous parameter except
`ActionMutationArtifactKey`, which receives one immutable, commit-addressed
artifact key.

Before execution, a validator must require exactly one resource change:

| Field | Required value |
| --- | --- |
| Action | `Modify` |
| Logical resource | `ActionMutationFunction` |
| Resource type | `AWS::Lambda::Function` |
| Replacement | `False` |
| Scope | properties only |

Any additional resource, IAM change, configuration change, replacement,
unknown change detail, missing previous parameter, or stack/template drift
must delete the unexecuted change set and stop.

### Phase 1: read-only plan

Implemented by `.github/workflows/plan-action-mutation-staging.yml` and
`ops/plan_action_mutation_staging_release.ps1`. It is manual-only and uses the
existing staging OIDC session solely for the listed read operations.

- require a clean, pushed commit on `main` and passing CI;
- validate the rollout and release contracts;
- package only `glap_action_mutation.py` and `glap_temporal_boundary.py` locally;
- record the local artifact digest;
- read the current stack status, previous artifact parameter, Lambda
  configuration, and current `CodeSha256` without printing protected values;
- confirm the additive schema migration is still unapplied or, after approval,
  that all post-migration checks return zero;
- report the repository policy gap and stop if actual deployment authority has
  not been separately reviewed.

This phase writes nothing to AWS.

### Phase 2: prepare change set

After explicit human approval, upload only the mutation artifact to a unique
commit-addressed key and create an unexecuted update change set using the
previous stack template. Reuse every previous parameter except the mutation
artifact key. Validate the exact one-resource contract above and retain the
previous artifact parameter and code digest for rollback.

Artifact upload and change-set creation are AWS writes. They are not authorised
by this RFC alone.

The repository implementation is
`.github/workflows/release-action-mutation-staging.yml` with
`ops/prepare_action_mutation_staging_release.ps1`. It uses the protected
`action-mutation-staging-prepare` environment, requires an exact commit already
on `main`, uploads to a commit-and-digest-addressed key, creates an unexecuted
change set with the previous template, and deletes that change set if the exact
one-resource guard fails.

### Phase 3: execute

A separate human approval must re-read the change set, confirm it is unchanged,
and execute it with a revision/concurrency guard. Wait for stack completion and
verify that only the mutation Lambda code digest changed. The function must
remain staging-only, unaliased, unscheduled, and connected only to the private
Operations API.

The execute job uses a separate protected
`action-mutation-staging-execute` environment and
`ops/execute_action_mutation_staging_release.ps1`. It revalidates the commit,
change-set identity and state, exact resource change, artifact path and object
metadata before execution. The workflow has now been run successfully. Its two
GitHub OIDC role variables and dedicated CloudFormation execution-role variable
remain protected, environment-scoped configuration. Only the CloudFormation
service role holds the exact Lambda code-update permission; GitHub cannot call
that API directly.

The exact review-only action and resource selectors are recorded in
[`action_mutation_staging_release_access_proposal.json`](action_mutation_staging_release_access_proposal.json),
with the named-human configuration checklist in
[`action_mutation_staging_release_access.md`](action_mutation_staging_release_access.md).
Neither file is an executable IAM policy or an AWS-write approval.

### Phase 4: verify and canary

Continue with the existing Action assignment rollout: deploy the Operations API
and private frontend through their separate plan-first paths, run read-only
runtime verification, run the isolated four-role verifier, and then use two
named signed-in humans for the `EDIT` and approve/reject canary. The agent may
not execute the canary.

## Rejected alternatives

- Direct `lambda update-function-code` is rejected because it bypasses the
  resource owner and creates CloudFormation drift.
- Re-running the current stateful lifecycle deploy is rejected because it
  packages and can update unrelated functions, roles, alarms, configuration,
  and stack parameters.
- Moving the existing Lambda into a new stack is rejected because import or
  replacement changes ownership and has a larger failure surface.

## Rollback

Rollback uses the same previous-template, one-resource change-set guard and the
recorded previous artifact parameter. It never directly updates Lambda, drops
schema columns, deletes audit events, or changes production.

Package rollback is allowed only if aggregate read-only checks show zero `EDIT`
events and zero current `EDITED` Actions. Otherwise disable new edit entry and
forward-fix while preserving the reader and audit contract.

## Human decisions still required

1. Keep each future Prepare and Execute as separate approvals; the successful
   2026-08-10 release does not pre-authorise another deployment.
2. Separately authorise schema migration, API and frontend deployment,
   role-test user creation, and the named-human Action assignment canary.
3. Production alias movement, scheduling, policy activation, and model
   promotion remain separate human decisions.

The machine-readable boundary is
[`action_mutation_staging_release_contract.json`](action_mutation_staging_release_contract.json).
