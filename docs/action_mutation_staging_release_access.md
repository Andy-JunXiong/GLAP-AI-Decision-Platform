# Action mutation staging release access review

**Status:** proposal only; no IAM, GitHub Environment, or AWS release change

This review package defines the minimum access needed by the already implemented
Action mutation prepare and execute jobs. It is deliberately not an executable
IAM policy and contains no account ID, ARN, bucket name, token, or protected
URL. A named human must resolve the exact deployed resource identifiers from
the existing staging stack and review the resulting IAM documents before
applying anything.

## Required separation

| Phase | Protected environment | Variable | Purpose |
| --- | --- | --- | --- |
| Prepare | `action-mutation-staging-prepare` | `AWS_ACTION_MUTATION_PREPARE_ROLE_ARN` | Upload one commit-addressed artifact and create an unexecuted change set |
| Execute | `action-mutation-staging-execute` | `AWS_ACTION_MUTATION_EXECUTE_ROLE_ARN` | Revalidate and execute that exact one-resource change set |

Both environments also receive `ACTION_MUTATION_CF_EXECUTION_ROLE_ARN`. This
identifies a dedicated service role trusted only by CloudFormation. Only that
service role receives the underlying `lambda:UpdateFunctionCode` permission;
neither GitHub OIDC identity may call the Lambda update API directly.

Both environments must be restricted to `main` and require reviewers. The
execute approval must be a new decision made after the prepare output has been
reviewed; approving prepare must not implicitly approve execute. Self-approval
should remain disabled where the repository plan supports it.

## Resource boundaries

- CloudFormation access is limited to the existing
  `glap-stateful-lifecycle-staging` stack.
- Lambda access is limited to the physical function resolved from the stack's
  `ActionMutationFunction` logical resource and must equal
  `glap-lifecycle-action-mutation-staging`.
- Artifact access is limited to the existing `ArtifactBucket` stack parameter
  and `action-mutation/<commit>/` key prefix.
- No role may update IAM, another Lambda, an alias, a schedule, production, or
  another CloudFormation stack.
- The prepare identity may pass only the dedicated execution role and only to
  CloudFormation. GitHub must not be able to assume that role directly.
- The workflow still rejects any change set other than one non-replacing
  `ActionMutationFunction` property modification.

## Named-human checklist

1. Inspect the current stack and resolve its exact stack ARN, artifact bucket,
   and mutation Lambda ARN without recording them in the repository.
2. Translate the machine-readable action lists into two GitHub orchestration
   policies and one CloudFormation execution policy. Do not add wildcards
   beyond the unavoidable commit-addressed S3 object suffix.
3. Confirm only the CloudFormation service role can update the exact Lambda;
   neither GitHub role may receive `lambda:UpdateFunctionCode`.
4. Configure the two GitHub Environments, branch restrictions, reviewers, OIDC
   trust subjects, and environment-scoped role variables.
5. Run the existing read-only plan again. Do not run `prepare` until its AWS
   writes receive a separate explicit approval.
6. After prepare, inspect the recorded commit, digest, previous artifact and
   exact change set. Obtain another explicit approval before execute.

The canonical machine-readable proposal is
[`action_mutation_staging_release_access_proposal.json`](action_mutation_staging_release_access_proposal.json).
