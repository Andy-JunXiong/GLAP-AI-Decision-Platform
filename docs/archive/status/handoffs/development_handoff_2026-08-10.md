# Development handoff -- 10 August 2026

## Completed today

The narrow Action mutation Lambda release path is now configured and verified
in isolated staging. Two protected GitHub environments enforce separate human
decisions for Prepare and Execute. Distinct GitHub OIDC identities orchestrate
those phases, while a CloudFormation-only service role owns the exact Lambda
update capability. Neither GitHub identity can update Lambda directly.

Workflow hardening landed in commits `7df651f`, `8605868`, and `bde0927`:

- validate the exact checked-out commit rather than the workflow commit;
- bind the reviewed CloudFormation execution role in immutable change-set
  metadata and verify the stack role after execution;
- accept `UPDATE_ROLLBACK_COMPLETE` as a completed preflight state while still
  requiring final `UPDATE_COMPLETE` after execution.

CI run `31353483375` and read-only Plan run `31353510147` passed for
`bde0927`. Local verification passed 237 unit tests, all 15 drift checks, the
Action mutation release validator, PowerShell parsing, template presence, and
diff checks.

## Release and recovery evidence

The first approved execution revealed that the CloudFormation service role had
enough access for the candidate update but not for rollback. CloudFormation
could not resolve every exact IAM role referenced by the template or read the
retained prior mutation artifact. The stack reached
`UPDATE_ROLLBACK_FAILED`.

A named human added only the exact template-role and prior-artifact reads, then
continued rollback without skipping any resource. CloudFormation restored the
previous artifact and finished at `UPDATE_ROLLBACK_COMPLETE`; the Lambda was
active and its update status was successful.

Prepare run `31359941156` created the replacement reviewed change set for
commit `bde0927`. It contained exactly one `Modify` operation for
`ActionMutationFunction`, with `Replacement=False` and property-only scope.
The change set remained unexecuted until a separate Execute approval.

Execute run `31360187221` completed successfully. Independent read-only AWS
inspection verified:

- stack status `UPDATE_COMPLETE`;
- the dedicated CloudFormation service role remained attached;
- the stack parameter referenced the reviewed content-addressed artifact;
- the mutation Lambda was `Active` with `LastUpdateStatus=Successful`;
- the Lambda code digest exactly matched the prepared artifact digest;
- no rollback followed the successful update;
- the workflow reported no production effect.

## Current boundary

The updated Action mutation Lambda code is deployed in isolated staging, but
the additive Action assignment schema migration remains plan-only. The
Operations API and private frontend therefore still expose the existing
three-operation contract. No named-human `EDIT` canary was executed today.

This work does not move a production alias, enable a schedule, modify
production data, activate a policy, promote a model, publish entity-level data,
or establish real logistics performance evidence.

## Next authorised decision

The next logical milestone is the separately governed Action assignment rollout:

1. obtain explicit approval for the additive staging schema migration;
2. run fail-closed post-migration validation;
3. release the Operations API and private frontend through their own
   plan-first paths;
4. run read-only runtime and four-role verification;
5. have two named signed-in humans perform the `EDIT` and approve/reject canary.

None of those steps is authorised by this handoff alone.
