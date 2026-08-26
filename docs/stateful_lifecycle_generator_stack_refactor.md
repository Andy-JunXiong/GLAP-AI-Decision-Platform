# Stateful lifecycle Generator stack refactor

## Current maturity

The repository contains a source-delivered design, a parameter-free destination
template, and fail-closed tooling for this refactor.
Commit `961b32f` is on `main`;
implementation CI run `32929610077` and documentation-sync commit `05477e5` CI
run `32929755239` passed on Python 3.13 and 3.14. The named IAM administrator
later applied and directly verified the bounded refactor permissions. Human
plan run `32938938361` failed closed because CloudFormation does not allow a
`Parameters` section when the refactor creates the destination stack. Its
execution remained unavailable and no resource moved. This repository revision
contains the parameter-free correction; source-control and CI maturity are
recorded by Git history. Commit `21d0e3a` passed CI run `32944908271`. Stack
refactor, deployment, and runtime verification remain pending. Every AWS write
below remains a separate named-human decision.

Human run `32945123509` then created an available preview with exactly one
destination-stack `CREATE` metadata action and one `LifecycleGeneratorFunction`
`MOVE`. The workflow failed after creation because the original guard counted
both actions as resource moves. Read-only checks found the Generator still in
the source stack and zero destination resources. This repository revision fixes
that guard and adds a non-executing `inspect-refactor` recovery path for the
existing preview. A local read-only invocation against the retained AWS preview
passed the corrected exact-action gate and executed nothing. Execution remains
pending and separately human-owned.

Human workflow attempts `32946252849` and `32946695185` then failed only at
bounded form-input validation before AWS credentials; all AWS steps were
skipped. The form now defaults to read-only inspection, trims surrounding ID
whitespace, and emits only the selected action plus received character count on
failure. The successful local read-only inspection is retained; another plan or
inspection retry is not required before a separate human execution decision.

## Why the split is required

Human-dispatched plan run `32920083879` from commit `fd6d532` proved that using
the deployed shared-stack template and every previous parameter except
`GeneratorArtifactKey` still produced three non-replacing changes:
`LifecycleGeneratorFunction`, `IntegrationControllerRole`, and
`IntegrationControllerFunction`. The generator ARN dependency in the controller
role propagated a shared-stack update even though the intended release was only
generator code. The change set was not executed and no stack resource changed.

The durable boundary is ownership, not a larger allow-list:

| Stack | Ownership after refactor |
| --- | --- |
| `glap-stateful-lifecycle-generator-staging` | Exactly one `AWS::Lambda::Function`: `LifecycleGeneratorFunction` |
| `glap-stateful-lifecycle-staging` | Generator execution role, alarm, controller, quality gate, Action mutation resources, and their support policies |

The shared alarm and controller policy refer to the fixed generator function
name/ARN instead of a CloudFormation resource reference. The function keeps its
existing physical name and execution-role ARN; the refactor changes
CloudFormation ownership, not runtime configuration.

The destination template is parameter-free because CloudFormation stack
refactor cannot add parameters while creating a destination stack. Planning
renders the current deployed function name, role, artifact, Athena output,
workgroup, and source database directly into that one-resource template. Later
code plans render the same template from the current Lambda configuration and
change only the new artifact key; they do not depend on destination-stack
parameters.

## Human-owned migration sequence

Use `.github/workflows/refactor-stateful-lifecycle-generator-staging.yml`. Its
concurrency group is shared with the lifecycle workflow, so these operations
cannot overlap.

1. A named IAM administrator reviews and, if approved, applies the updated
   `ops/configure_stateful_lifecycle_deployer.ps1` policy. The new permissions
   are limited to the shared and generator staging stack ARN patterns and the
   CloudFormation stack-refactor actions. This remains a human-owned operation;
   the bounded policy is currently applied and read-only verified.
2. A named human dispatches `plan-refactor`. This calls
   `CreateStackRefactor`, which is an external AWS write that creates only a
   reviewable refactor preview. It does not execute the move. The script accepts
   exactly one `CREATE` / `STACK` metadata action plus one `MOVE` / `RESOURCE`
   action for `LifecycleGeneratorFunction`, rejects all extras, and prints the
   safe refactor ID.
3. If planning created a valid preview but the workflow stopped afterward,
   dispatch `inspect-refactor` with that exact ID. It performs only read-only
   describe/list validation and does not create or execute another preview.
4. The human reviews the completed plan and its exact one-resource action. A
   separate dispatch of `execute-refactor` must supply that exact ID. Do not
   execute if the preview contains any other logical resource.
5. Execution verifies that the destination stack owns exactly one Lambda with
   the expected physical name and that the shared stack no longer owns
   `LifecycleGeneratorFunction`. No lifecycle date, schema, seed, controller,
   Action, schedule, alias, or production path is invoked.
6. For later code releases, dispatch `plan-release`. It creates, validates, and
   deletes an unexecuted change set without packaging or uploading a new ZIP.
   The plan must contain exactly one non-replacing Lambda modification.
7. Only after reviewing that plan may a named human separately dispatch
   `deploy-release`. That path packages and uploads only the Generator code and
   executes only the exact one-resource change set.

The old `plan-stack-only` and `deploy-stack-only` actions are removed from the
shared lifecycle workflow. The shared deployer packages no Generator code and
fails closed until exclusive one-resource destination ownership is verified.

## Failure and rollback boundary

If refactor planning, validation, execution, or post-move ownership checks fail,
stop and inspect the CloudFormation refactor status; do not run a shared-stack
deployment as a repair. A successful move may be reversed only through a new,
separately reviewed stack refactor. Deleting either stack is not an authorized
rollback. Production aliases, schedules, tables, and public Pages remain out of
scope.
