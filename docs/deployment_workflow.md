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
