# Stateful lifecycle Generator stack refactor

## Current maturity

The repository contains locally verified, source-delivered design and
fail-closed tooling for this refactor. Main CI, IAM application, stack refactor,
deployment, and runtime verification remain pending. Every AWS write below
remains a separate named-human decision.

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

## Human-owned migration sequence

Use `.github/workflows/refactor-stateful-lifecycle-generator-staging.yml`. Its
concurrency group is shared with the lifecycle workflow, so these operations
cannot overlap.

1. A named IAM administrator reviews and, if approved, applies the updated
   `ops/configure_stateful_lifecycle_deployer.ps1` policy. The new permissions
   are limited to the shared and generator staging stack ARN patterns and the
   CloudFormation stack-refactor actions. This repository change does not apply
   that policy.
2. A named human dispatches `plan-refactor`. This calls
   `CreateStackRefactor`, which is an external AWS write that creates only a
   reviewable refactor preview. It does not execute the move. The script accepts
   only one `MOVE` / `RESOURCE` action for `LifecycleGeneratorFunction` and
   prints the safe refactor ID.
3. The human reviews the completed plan and its exact one-resource action. A
   separate dispatch of `execute-refactor` must supply that exact ID. Do not
   execute if the preview contains any other logical resource.
4. Execution verifies that the destination stack owns exactly one Lambda with
   the expected physical name and that the shared stack no longer owns
   `LifecycleGeneratorFunction`. No lifecycle date, schema, seed, controller,
   Action, schedule, alias, or production path is invoked.
5. For later code releases, dispatch `plan-release`. It creates, validates, and
   deletes an unexecuted change set without packaging or uploading a new ZIP.
   The plan must contain exactly one non-replacing Lambda modification.
6. Only after reviewing that plan may a named human separately dispatch
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
