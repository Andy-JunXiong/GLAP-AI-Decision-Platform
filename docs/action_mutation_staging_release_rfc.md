# RFC: narrow Action mutation Lambda staging release

**Status:** one read permission approved; awaiting named-human IAM application

## Approved decision

On 9 August 2026, the user approved implementing only the plan stage of a
staging release path that retains the existing CloudFormation-owned
`ActionMutationFunction`, does not directly update Lambda code, and does not
replay the broader stateful lifecycle deployment.

The manual plan workflow and local packaging/inspection script are repository
implementation evidence. This approval does not authorise an IAM or
CloudFormation change, artifact upload, change-set creation or execution,
schema migration, frontend/API deployment, or operational Action mutation.

## Current ownership and blocker

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

## Proposed design

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

### Phase 3: execute

A separate human approval must re-read the change set, confirm it is unchanged,
and execute it with a revision/concurrency guard. Wait for stack completion and
verify that only the mutation Lambda code digest changed. The function must
remain staging-only, unaliased, unscheduled, and connected only to the private
Operations API.

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

1. A named human must apply the approved `lambda:GetFunctionConfiguration`
   permission to the staging OIDC role for the exact physical Lambda resolved
   from `ActionMutationFunction`, then rerun the read-only plan. Agent-side IAM
   application remains prohibited.
2. Separately authorise implementation of prepare/execute workflow phases and
   their protected environment approvals.
3. Separately authorise schema migration, change-set preparation/execution, API
   and frontend deployment, role-test user creation, and named-human canary.

The machine-readable boundary is
[`action_mutation_staging_release_contract.json`](action_mutation_staging_release_contract.json).
