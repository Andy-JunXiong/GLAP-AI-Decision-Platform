# GLAP Lambda Deployment Workflow

## Source of truth

GitHub is the source of truth for Lambda source code, tests, SQL, and deployment
evidence. Direct AWS CLI development is used to inspect resources and validate
candidate releases, but every deployed change must correspond to a pushed Git
commit.

Do not point production automation at `$LATEST`. The mutable version is only a
build candidate.

## Release channels

| Channel | Purpose | Invocation |
| --- | --- | --- |
| `$LATEST` | Newly uploaded candidate code | Manual only |
| `staging` | Immutable candidate selected for validation | Manual smoke tests |
| `prod` | Approved production version | EventBridge Scheduler |

Current verified mapping:

| Git commit | Lambda version | Alias | Status |
| --- | ---: | --- | --- |
| Pre-reliability release | 1 | none | Rollback point |
| `f983a73` | 2 | `prod` | Verified production release |
| `5be47e7` | 3 | none | OIDC validation artifact; alias promotion was blocked |
| `21f43a4` | 4 | `staging` | Verified OIDC staging release |

Git tag `glap-agent-v2` identifies the merge commit on `main` that contains the
version 2 source, tests, and release documentation.

## Manual CLI release

Use an authenticated AWS CLI profile and explicitly set `us-east-1` for every
command. Never store AWS credentials, account identifiers, bucket names, or
signed download URLs in the repository.

1. Start from a clean, pushed Git commit.
2. Run the local test suite.
3. Package `lambda/glap_ai_agent_orchestrator.py` as `lambda_function.py` in the
   root of the deployment ZIP.
4. Read the current `$LATEST` revision ID.
5. Upload with `update-function-code --revision-id` so a concurrent update cannot
   be overwritten.
6. Wait until `LastUpdateStatus` is `Successful`.
7. Invoke `$LATEST` and inspect the returned payload and CloudWatch tail log.
8. Publish an immutable Lambda version.
9. Move `staging` to that version and run the same smoke test through the alias.
10. Promote by moving `prod` to the tested version.
11. Verify that the Scheduler target still ends in `:prod`.
12. Record the Git commit to Lambda version mapping in this file.

## Promotion and rollback

Promotion changes only the `prod` alias. It does not upload new code:

```powershell
aws lambda update-alias `
  --function-name glap-ai-agent-orchestrator `
  --name prod `
  --function-version <verified-version> `
  --revision-id <current-alias-revision-id> `
  --region us-east-1 `
  --profile <profile>
```

Rollback uses the same operation with the previous verified version. Always read
the current alias revision ID immediately before changing it, and verify the
result with `get-alias` and a qualified invocation.

## Required smoke-test assertions

- Lambda response status is 200.
- `FunctionError` is absent.
- `ExecutedVersion` matches the intended immutable version.
- The response payload reports `status: success`.
- CloudWatch contains no timeout or Athena failure.
- Inserted and skipped counters are plausible for the selected input set.
- The production Scheduler remains enabled and targets the `prod` alias.

## Future automation

When the release process is stable, GitHub Actions should automate the same
sequence through AWS OIDC: test, package, upload candidate, smoke-test, publish,
update `staging`, require approval, and finally update `prod`. Long-lived AWS
access keys must not be stored as GitHub secrets.

## GitHub staging deployment

The manual `Deploy staging` workflow uses GitHub OIDC instead of stored AWS
credentials. The GitHub `staging` Environment is restricted to `main`, and its
AWS role can update candidate code, publish immutable versions, invoke dry-run
smoke tests, and move only the `staging` alias. It cannot update `prod`, modify
the Scheduler, administer IAM, or deploy another Lambda function.

AWS authorizes `UpdateAlias` against the unqualified function ARN, so the
GitHub role does not receive that action. It invokes a separate promoter Lambda
whose code and environment are locked to the `staging` alias. The promoter
validates immutable version numbers and Git commit descriptions and uses the
alias revision ID as a concurrency guard.

Candidate and alias smoke tests pass `{"dry_run": true}`. Dry-run execution reads
the pending anomaly set and builds decision previews without inserting root-
cause or decision records.

The first complete OIDC deployment succeeded on 2026-07-23. GitHub Actions run
`29973354442` published version 4, promoted only `staging`, and completed both
dry-run smoke tests. Production remained on version 2.

## Action assignment staging extension

The repository implementation of Action `EDIT`, owner, due date, and `EDITED`
is not covered by the production orchestrator release channel above. Its
staging rollout remains plan-only and must follow
[`action_assignment_staging_rollout.md`](action_assignment_staging_rollout.md):
additive schema migration, read-only validation, mutation Lambda, Operations
API, private frontend, read-only smoke checks, four-role checks, then a
named-human canary.

The later Decision Truth extension has a separate staging handoff in
[`decision_truth_staging_rollout.md`](decision_truth_staging_rollout.md). Its
additive Action proposal columns were applied by a named human and all six
aggregate checks returned zero on `2026-08-25`. The subsequent workflow plan
run `32853867334` succeeded without deployment. The lifecycle producer remains
an explicit dependency because it creates immutable bindings; an API/frontend-
only release cannot establish end-to-end binding evidence.

The former shared-stack `plan-stack-only` / `deploy-stack-only` path is retired.
Human plan run `32920083879` from `fd6d532` proved that shared dependency
propagation still introduced controller-role and controller-function changes;
the plan uploaded nothing, executed nothing, and changed no resource.

The replacement workflow is
`.github/workflows/refactor-stateful-lifecycle-generator-staging.yml`. It first
offers separately dispatched `plan-refactor`, `inspect-refactor`, and
`execute-refactor` actions to move only `LifecycleGeneratorFunction` into an
independent one-resource stack.
After exclusive ownership is verified, `plan-release` creates and deletes an
unexecuted exact-one-Lambda change set without uploading code, and a separately
authorized `deploy-release` may package and update only that Lambda. The shared
lifecycle workflow no longer exposes Generator-only actions, and its stack
deployer blocks until the refactor has completed. The source design is delivered;
the IAM reconciliation is applied and read-only verified. Human plan run
`32938938361` failed closed because the destination template still contained a
CloudFormation `Parameters` section, which is forbidden while stack refactor
creates a destination stack. No move executed. This repository revision renders
the current deployed configuration into a parameter-free one-resource template
for both refactor and later release planning; source-control and CI maturity are
recorded by Git history. Commit `21d0e3a` passed CI run `32944908271`. Refactor
execution and deployment were pending at that checkpoint. Operations API deployment,
private frontend publication,
temporary-user role verification, and any operational continuation remain
separate human-owned actions.

Human run `32945123509` later created a `CREATE_COMPLETE` / `AVAILABLE` preview
containing CloudFormation's destination-stack `CREATE` metadata action and the
single Generator `MOVE`. The workflow failed after creation because the original
guard counted both as resource moves. Read-only inspection confirmed that the
source stack still owns the Generator and the review-state destination stack has
zero resources. The guard now requires exactly one `CREATE` / `STACK` plus one
expected `MOVE` / `RESOURCE`, rejecting all extras. `inspect-refactor` accepts
the existing exact ID, performs only describe/list validation, and returns
without creating or executing a refactor.

Human inspection attempts `32946252849` and `32946695185` both stopped in the
bounded-input step before AWS credential configuration, so all AWS steps were
skipped. The form now defaults to the read-only `inspect-refactor` action,
trims surrounding ID whitespace, retains the exact UUID requirement, and emits
only the selected action and received character count when validation fails.
It never logs the supplied identifier in an error annotation.

Named-human run `32948002162` completed the one-resource refactor. Read-only
acceptance verified zero source Generator resources and exactly one healthy,
alias-free destination Lambda. `plan-release` run `32951563950` then validated
and deleted the exact-one non-replacing change set without uploading an artifact.
Separately authorized `deploy-release` run `32956001803` uploaded and deployed
only the Generator package from commit `9eb031f`. The destination template is
parameter-free and bound to that artifact; its ZIP SHA-256 matches Lambda
`CodeSha256`, the execution role is unchanged, no active change set remains,
and the shared stack recorded no deployment-window event. No lifecycle date,
schema, Controller, Action, schedule, alias, Pages, or production path ran.

The later `COST_ANOMALY` Decision Brief release followed the same separated
authority boundary from commit `0e5b740`. CI run `32982375432` and the
push-triggered Operations API plan `32982375374` passed. Generator plan
`32982600783` accepted one non-replacing Lambda modification and deleted its
change set without upload or execution; separately authorized Generator deploy
`32982946620` released only that resource. Separately authorized Operations API
deploy `32983721998` completed its staging stack update. The named human then
ran the private frontend plan and apply steps, followed by the read-only staging
verifier and the four-role matrix; all checks passed and all four temporary
users were removed. No protected deployment identifiers were recorded. The
Generator was not invoked, the revised exact-pair Athena validator was not run,
and no Action, lifecycle date, schedule, alias, Pages, or production path ran.

The mutation Lambda has a narrow staging release workflow implemented and
verified through separate protected prepare and execute environments. The
named human configured distinct GitHub OIDC orchestration identities and a
CloudFormation-only service role; neither GitHub identity can update Lambda
directly. The existing stateful lifecycle workflow updates a broader stack and
remains an invalid substitute. This release does not authorise a schema
migration, API/frontend deployment, operational Action mutation, or production
change.

The proposed narrow path is documented in
[`action_mutation_staging_release_rfc.md`](action_mutation_staging_release_rfc.md).
It retains the existing CloudFormation owner, uses the previous stack template,
changes only `ActionMutationArtifactKey`, and rejects execution unless the
change set contains exactly one non-replacing `ActionMutationFunction`
modification. The repository deployer-policy definition currently omits this
function and role. Read-only run `31297032412` successfully assumed the staging
OIDC role and validated the repository, then failed closed on the exact missing
`lambda:GetFunctionConfiguration` capability. The repository owner approved that
single exact-resource read capability for named-human application. The named
repository owner applied it, and read-only run `31298179885` then passed the AWS
inspection while verifying stable stack ownership and Lambda configuration. The
agent did not modify IAM. The later prepare/execute implementation preserves
separate approvals and exact commit, artifact, and one-resource checks.
The first complete release was verified on 2026-08-10 from commit `bde0927`.
Read-only Plan run `31353510147` accepted the stable completed-rollback state
without an AWS write. Prepare run `31359941156` created an available,
unexecuted change set for exactly one non-replacing
`ActionMutationFunction` property modification. After a separate approval,
Execute run `31360187221` completed with stack status `UPDATE_COMPLETE`; the
deployed Lambda code digest matched the prepared artifact and the workflow
reported no production effect.

The recovery path was also exercised rather than inferred. An earlier execute
attempt reached `UPDATE_ROLLBACK_FAILED` after the service role could update the
candidate but could not resolve every template role or read the retained prior
artifact during rollback. A named human added only the required exact-resource
reads and continued rollback without skipping a resource. The stack returned
to `UPDATE_ROLLBACK_COMPLETE`, the prior artifact was restored, and the new
prepare/execute pair then succeeded. The release scripts accept
`UPDATE_ROLLBACK_COMPLETE` only as a reusable preflight state; successful
execution still requires final `UPDATE_COMPLETE`.

AWS permanently associates a supplied service role with the stack for future
operations. The successful one-resource release therefore left its deliberately
narrow Action mutation role as owner of the broader shared lifecycle stack.
Deployment run `32383741062` later exposed that ownership collision: temporal
backfill passed, but the narrow role could neither update the lifecycle
generator and quality gate nor read their artifact prefix, and automatic
rollback stopped at `UPDATE_ROLLBACK_FAILED`.

Broader lifecycle maintenance now has its own CloudFormation-only service role
and supplies it explicitly. The lifecycle deployer preserves the reviewed
Action mutation artifact, inspects its change set, and refuses to execute if
either `ActionMutationFunction` or `ActionMutationRole` would change. The narrow
Prepare/Execute path remains the only routine Action mutation release path.

PR #75 merged the missing-role probe hardening as `1f602c5d`, and post-merge CI
run `32389801911` passed. A named IAM administrator then configured the role,
bounded deployer policies, and protected staging variable. Plan run
`32390302719` passed; separately approved recovery run `32390505373` continued
rollback without skipped resources; plan run `32390677045` passed; and
separately approved deployment run `32390847334` completed the isolated stack
update. Read-only inspection found `UPDATE_COMPLETE` and an active Python 3.14
controller. Diagnostic run `32391364627` passed all 28 checks for the failed
logical date without mutation. The persisted status still requires a separate
named-human `recover-failed-integration-date` approval.

## Public Evaluation Pages gate

The local Pages workflow treats `public-evaluation-snapshot.v1` as a separate
aggregate-only publication input. Changes to the tracked snapshot, exporter,
source validator, public/source schemas, governed five-review summary, rubric,
or frozen review bundle enter the Pages path. Before `_site` is prepared or an
artifact is uploaded, the workflow runs:

```bash
python ops/export_public_evaluation_snapshot.py
```

The command validates the private governed source boundary and then requires
the tracked public JSON to equal the safe projection exactly. A mismatch exits
non-zero and blocks artifact preparation. This gate grants no publication,
AWS, data, model, policy, or Action authority; commit, push, and Pages execution
remain separately human-authorized actions.

The first bounded release of this gate completed from commit `489ef90`: CI run
`32741075346` and Pages run `32741075493` passed. The Pages job successfully
ran the read-only OPS export and the Evaluation validator before artifact
preparation, then deployed the site. Read-only HTTP checks verified the live
v1 snapshot and loader; no AWS write or operational mutation was included.

A post-deployment read-only canary is now implemented locally after
`actions/deploy-pages`. It fetches the published page and v1 JSON with no
credentials, requires them to match the governed local sources, reruns the
Sydney-date and aggregate contract, and verifies all-false authority, the
no-store loader, and the `UNAVAILABLE` fail-closed path. It retries boundedly
for Pages propagation and writes only safe aggregate evidence to the workflow
summary. The project owner separately authorized the bounded release. Commit
`3d9dc34`, CI run `32780350123`, and Pages run `32780350187` passed; the latter
deployed the exact commit and the canary returned all six checks true with the
governed aggregate and all authority fields false.
