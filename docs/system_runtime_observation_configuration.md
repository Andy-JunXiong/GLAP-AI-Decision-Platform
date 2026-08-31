# System Runtime Observation: Human Configuration Checklist

## Status and authority

This is a human-operated review checklist for the protected
`system-observation-read` GitHub Environment and its AWS OIDC role. It is not
an infrastructure template, an IAM change, standing execution authority, or
authorization to run `execute`. The agent may validate repository contracts but
may not create the Environment, grant AWS permissions, populate secrets, or
dispatch `execute`.

Keep every account number, resource identifier, role ARN, queue URL, topic ARN,
and private resource name outside the repository. Record only bounded evidence
such as a workflow run ID, commit SHA, pass/fail result, and artifact count.

## 1. Preconditions

- The dependency and workflow commit is present on `main`, and source CI is
  green.
- The configuration-free `plan` action passes for the same commit. It must not
  request OIDC, read secrets, create an AWS client, or retain an artifact.
- A named human owns the Environment and AWS changes. Repository approval to
  edit this checklist does not grant infrastructure or execution authority.
- The reviewer has confirmed the repository's current GitHub OIDC subject
  format. Repositories using immutable subject claims include owner and
  repository IDs; do not assume the older name-only format.

## 2. GitHub Environment

Create the Environment manually with the exact name
`system-observation-read`, then configure these controls:

1. Require at least one named reviewer and, where available, prevent
   self-review.
2. Limit deployment branches and tags to the intended protected `main` ref.
3. Do not configure an environment URL, deployment action, schedule, or bypass.
4. Store all private values as Environment secrets, not repository variables,
   workflow literals, artifacts, issues, or logs.
5. Confirm that the Environment contains exactly the secret names below before
   considering an `execute` request. Never copy their values into evidence.

| Secret name | Protected value and validation |
| --- | --- |
| `SYSTEM_OBSERVATION_ROLE_ARN` | Exact read-only OIDC role locator; never a user or long-lived access key. |
| `SYSTEM_STORAGE_BUCKET` | One storage bucket name used only by the bounded bucket control-plane check. |
| `SYSTEM_GLUE_DATABASE` | One Glue database name. |
| `SYSTEM_ATHENA_WORKGROUP` | One enabled Athena workgroup; query execution remains forbidden. |
| `SYSTEM_PRODUCTION_FUNCTION_NAME` | One production Lambda function whose immutable `prod` alias is inspected. |
| `SYSTEM_PRODUCTION_SCHEDULE_NAME` | One production Scheduler schedule inspected for the fixed reliability boundary. |
| `SYSTEM_DLQ_URL` | One dead-letter queue URL inspected for retention and encryption attributes. |
| `SYSTEM_ALARM_NAMES_JSON` | JSON array of unique non-empty alarm names; maximum 100 entries. |
| `SYSTEM_ALERT_TOPIC_ARN` | One alert topic locator inspected without publishing. |
| `SYSTEM_STAGING_FUNCTION_NAMES_JSON` | JSON array of unique staging Lambda function names. |
| `SYSTEM_STAGING_ROLE_NAMES_JSON` | JSON array of unique staging role names whose inline policies are inspected. |
| `SYSTEM_STAGING_SCHEDULE_PREFIX` | One staging schedule prefix; the collector requires the matching schedule set to be empty. |
| `SYSTEM_STAGING_TABLE_NAMES_JSON` | JSON array of the only staging tables allowed in inspected role write scopes. |
| `SYSTEM_STAGING_S3_WRITE_PREFIXES_JSON` | JSON array of the only protected staging object-resource prefixes allowed in inspected role write scopes. |

Every JSON secret must decode to a non-empty array of unique, non-empty
strings. The workflow maps these secrets to the collector's `GLAP_SYSTEM_*`
environment fields only inside the protected `execute` job.

## 3. OIDC trust review

The human IAM reviewer must verify all of the following before attaching a
permission policy:

- The provider issuer is GitHub's token service and the audience condition is
  exactly `sts.amazonaws.com` for the official credentials action.
- The subject condition is an exact equality match for this repository and the
  `system-observation-read` Environment. Use the repository's actual current
  name-based or immutable-ID subject format. Do not use `StringLike`, a
  wildcard repository, wildcard environment, organization-wide subject, branch
  fallback, or pull-request subject.
- The trust policy grants only web-identity assumption to the one reviewed
  role. It must not trust an AWS account principal or provide a second
  assumption path.
- The role session is short-lived, has no long-lived access key, and has no
  additional attached or inline policy that expands the reviewed read set. Any
  permissions boundary must be independently reviewed as part of the effective
  permission calculation.
- The GitHub Environment protection rules are active before the role is made
  assumable.

If the repository's subject format cannot be established without requesting a
token, stop. Subject-claim inspection and any resulting trust change are
separate human-owned security actions; do not weaken the condition to make an
assumption succeed.

## 4. Permission-policy review

The collector can issue only the API calls below. The role's effective policy
must contain the corresponding read actions and no unrelated action. Resource
scope must be narrowed to the exact protected values where the AWS service
supports resource-level authorization. `s3:HeadBucket` is an API operation;
AWS authorizes it with `s3:ListBucket` on the exact bucket.

| Collector API call | IAM action to review | Resource boundary |
| --- | --- | --- |
| `s3:HeadBucket` | `s3:ListBucket` | Exact storage bucket only. |
| `glue:GetDatabase` | `glue:GetDatabase` | Exact catalog/database resources required by Glue authorization. |
| `athena:GetWorkGroup` | `athena:GetWorkGroup` | Exact workgroup only. |
| `lambda:GetAlias` | `lambda:GetAlias` | Exact production function and `prod` alias. |
| `lambda:ListAliases` | `lambda:ListAliases` | Exact configured staging functions. |
| `scheduler:GetSchedule` | `scheduler:GetSchedule` | Exact production schedule only. |
| `scheduler:ListSchedules` | `scheduler:ListSchedules` | Smallest service-supported scope; runtime results remain prefix-bounded. |
| `sqs:GetQueueAttributes` | `sqs:GetQueueAttributes` | Exact dead-letter queue only. |
| `cloudwatch:DescribeAlarms` | `cloudwatch:DescribeAlarms` | Configured alarm set or smallest service-supported scope. |
| `sns:GetTopicAttributes` | `sns:GetTopicAttributes` | Exact alert topic only. |
| `iam:ListAttachedRolePolicies` | `iam:ListAttachedRolePolicies` | Exact configured staging roles. |
| `iam:ListRolePolicies` | `iam:ListRolePolicies` | Exact configured staging roles. |
| `iam:GetRolePolicy` | `iam:GetRolePolicy` | Exact configured staging roles and inline policies. |

Reject the policy if its effective permissions include any of the following:

- `Action: "*"`, service wildcards, `NotAction`, AWS managed policies, or an
  unrelated attached/inline policy;
- Athena query execution, S3 object reads or writes, Lambda invocation or alias
  mutation, Scheduler mutation, EventBridge mutation, IAM mutation, secrets
  access, deployment, publication, or artifact upload;
- production analytics table access, a production data write, or staging write
  scope outside the configured table and object-prefix allowlists.

The human reviewer should validate the finished policy with IAM Access Analyzer
and simulate the required actions against the intended resources. Do not commit
the policy, simulator inputs, role locator, resource locators, or raw results to
this repository.

## 5. Pre-execution review gate

All boxes must be satisfied for the same commit:

- [ ] Source CI is green and the project drift audit passes.
- [ ] A fresh configuration-free `plan` run passes with zero artifacts.
- [ ] Environment reviewers and protected-branch restrictions are active.
- [ ] All 14 Environment secret names exist; no value has been logged or
      copied into the repository.
- [ ] OIDC audience and the repository's actual Environment subject are exact;
      no wildcard trust is present.
- [ ] Effective permissions match the reviewed action set and resource scopes;
      no write, query, invoke, deploy, publish, or mutation permission exists.
- [ ] A named human has reviewed IAM Access Analyzer and policy-simulation
      results outside the repository.
- [ ] The intended run has a new, explicit human authorization for `execute`.

Configuration completion alone does not satisfy the final box.

## 6. Expected protected run

After separate authorization, a named human selects `execute` in the manual
workflow. Required Environment approval occurs before the job starts. Once the
job is admitted, its steps must proceed in this order:

1. repository contract tests;
2. pinned dependency installation and Boto3 import check;
3. short-lived OIDC authentication using the approved Environment trust;
4. exact confirmation `AWS_CONTROL_PLANE_READS`;
5. one aggregate observation and candidate in runner temporary storage;
6. validation followed by unconditional deletion, with zero uploaded artifacts.

Stop on any missing secret, trust mismatch, access denial, unexpected resource,
policy drift, retained artifact, or validation failure. Do not broaden a policy
or replace an exact subject with a wildcard to make the run pass. Candidate
promotion, Sites publication, AWS mutation, and any recurring schedule remain
separate decisions and are not authorized by this checklist.

## Authoritative external references

- [GitHub: Configuring OIDC in AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [GitHub: OpenID Connect reference](https://docs.github.com/en/actions/reference/security/oidc)
- [AWS: Required permissions for S3 API operations](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html)
- [AWS: Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference.html)
