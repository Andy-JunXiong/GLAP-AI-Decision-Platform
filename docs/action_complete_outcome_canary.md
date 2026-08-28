# Governed COMPLETE-to-Outcome canary

**Status:** `OBSERVED_OUTCOME_FAILED_CLOSED_SOURCE_FIX_LOCALLY_VERIFIED_NOT_DEPLOYED`
**Boundary:** synthetic isolated staging, Australia/Sydney actual calendar

## Purpose

This package governs the smallest path from the already verified `APPROVED`
Action to one delayed simulated Outcome and the existing Learning gate. The
path has now executed through the due-date observation. The Outcome checks and
eligible-count increase from 1 to 2 passed, but the Learning reconciliation
failed closed because at least one unactivated policy proposal exists below
the 20-Outcome threshold. The source-level counting defect is now corrected and
locally verified, but that fix is not deployed and does not alter the failed-
closed staging state. The evidence contains no Action, request, actor, shipment,
Outcome, AWS, or storage identifiers.

The machine-readable source is
[`action_complete_outcome_canary_v1.json`](action_complete_outcome_canary_v1.json).
Validate and render it locally with:

```powershell
python ops/validate_action_complete_outcome_canary.py
python ops/render_action_complete_outcome_canary_plan.py
```

Both commands are local and read-only. The renderer prints only the governed
phase order, authorization gates, current Sydney date, and all-false authority
map. It performs no network call and writes no file.

On the Sydney business date `2026-08-25`, the dedicated staging preflight ran
one aggregate-only Athena `SELECT` and passed all eight checks. It found one
approved candidate, one `EDIT`, one `APPROVE`, zero `REJECT`, zero `COMPLETE`,
one separated-actor check, one assignment match, and zero Outcomes. Protected
identifiers were not printed. This read verified eligibility only; it executed
no Action mutation or lifecycle continuation and grants no later authority.

After the project owner's explicit authorization on `2026-08-25`, a signed-in
named human clicked `Mark complete` in the private Action Board. The agent
navigated and positioned the page but did not click or submit the mutation.
The post-completion aggregate-only reconciliation passed all eight checks: one
completed candidate, one `EDIT`, one `APPROVE`, zero `REJECT`, one named-human
`COMPLETE`, matching assignment, and zero Outcomes. Protected identifiers were
not printed. That authorization is consumed; it grants no lifecycle
continuation or other standing write authority.

After a new explicit project-owner authorization, the agent used the named
GitHub session to trigger one manual `extend-integration-validate` workflow.
Run `32803181376` from commit `291fffc` succeeded for only `2026-08-25` in
`OPERATIONAL` / `ACTUAL_CALENDAR` mode, with one logical date, no seed, and no
future simulation. The trigger assistance did not grant the agent standing
authority.

The aggregate-only pending reconciliation then passed all six checks: one
completed candidate, exactly one Outcome, `PENDING` status, null observed date
and effect, `SIMULATED` provenance, and a due date three days after completion.
Protected identifiers were not printed. The system-computed `2026-08-28` due
date was a future gate relative to the pending-Outcome execution date. It was
not treated as observed evidence until that Sydney date arrived.

After a further explicit project-owner authorization on `2026-08-28`, plan run
`33149532396` passed without lifecycle writes. Exactly one
`extend-integration-validate` run, `33149577300`, then processed only
`2026-08-28` from commit `3316627` in `OPERATIONAL` /
`ACTUAL_CALENDAR` mode, with no seed or future simulation. It passed four
stages and all 41 lifecycle checks. No second date or continuation ran.

The final aggregate-only reconciliation passed the Outcome and temporal gates:
one closed candidate, one latest closed simulated Outcome with an observed
date and effect, observation on or after its due date and by the Sydney cutoff,
and an eligible Outcome increase from 1 to exactly 2. It also confirmed that
2 remains below 20 and that no proposal is activated. The required zero-
proposal check failed, however, because at least one unactivated proposal
exists below the threshold. The reconciler therefore stopped failed closed;
protected identifiers were not printed and no proposal was changed or
activated.

## Governed phase sequence

| Phase | Required evidence or authority |
| --- | --- |
| Read-only preflight | Exactly one selected Action is `APPROVED`; the prior canary retains one `EDIT`, one `APPROVE`, zero `REJECT`, zero `COMPLETE`, and one matching assignment |
| Named-human `COMPLETE` | Separate authorization for an `operator` or `administrator`; actor comes from signed identity claims; retries reuse the same stable request ID |
| Read-only completion reconciliation | One append-only `COMPLETE`, current state `COMPLETED`, assignment unchanged |
| Pending Outcome generation | Separate named-human authorization for an `OPERATIONAL` / `ACTUAL_CALENDAR` lifecycle continuation on the system-derived Sydney date |
| Read-only pending reconciliation | One `PENDING`, `SIMULATED` Outcome with no observed date and no effect |
| Calendar wait | No execution before the system-computed observation due date, three days after completion |
| Observed Outcome generation | Separate named-human actual-calendar continuation on or after the due date and never after the current Sydney date |
| Outcome/Learning reconciliation | One closed simulated Outcome for the Action and an eligible-outcome delta of one; the 20-Outcome proposal gate remains review-only |

## Evidence and authority boundary

Every persisted mutation remains human-owned and append-only. `COMPLETE`, the
pending-Outcome continuation, and the observed-Outcome continuation are three
separate authority decisions; approval of one does not approve the next.
Future simulation cannot satisfy this canary. A pending record is not observed
evidence, and the now-closed simulated Outcome is not real logistics
performance.

The contract grants no AWS write, deployment, production, schedule, policy
activation, or model-promotion authority. Evidence handoff must remain
aggregate-only and must not print protected entity, request, identity, or AWS
identifiers.

The repository includes a dedicated post-`COMPLETE` verifier at
`ops/reconcile_action_complete_staging.ps1`. It passed after the separately
authorized human completion, finding exactly one `COMPLETED` candidate, one
named-human `COMPLETE`, the preserved assignment, and zero Outcomes before the
next lifecycle continuation. Its query is aggregate-only and printed no
protected identifiers.

A second verifier at `ops/reconcile_pending_outcome_staging.ps1` checked the
first lifecycle continuation. It requires exactly one Outcome for
the completed candidate, `PENDING` status, `SIMULATED` provenance, null
observed date and effect, and an observation due date exactly three days after
completion. It passed after run `32803181376`. The later one-time observed-
Outcome continuation authority was separately granted and consumed on
`2026-08-28`.

## Observed Outcome and Learning verifier

The local `ops/check_observed_outcome_due_date.ps1` reads the governed due date
from this contract and derives the current date from the Australia/Sydney
timezone. On `2026-08-25` it returned `BLOCKED` for the `2026-08-28` gate before
any AWS setup or call. On `2026-08-28` the same local gate returned ready.

The aggregate-only `ops/reconcile_observed_outcome_learning_staging.ps1` fails
before any AWS setup when the due date has not been reached. Its authorized
`2026-08-28` run selected only the latest version of each Outcome and passed
the closed simulated result, observed date/effect, calendar window, and frozen
1-to-2 eligible-count checks. Because 2 remains below the 20-Outcome review
threshold, it required zero policy proposals and zero activations. The zero-
activation check passed; the zero-proposal check failed closed.

Local source inspection found a deterministic mismatch capable of explaining
the failure: the lifecycle adapter supplied all closed historical Outcome rows
to a row-count threshold, while the read-side Learning and canary queries de-
duplicated to the latest version per `outcome_id`. The authorized local forward
fix now makes `build_policy_proposal` select exactly one latest cutoff version
per `outcome_id` before applying the closed-state threshold. A latest
`PENDING` version excludes an earlier closed version; a future version or two
conflicting versions for the same ID and date fails closed.

Regression tests prove that 20 historical versions of one logical Outcome do
not trigger a proposal, while 20 distinct latest closed Outcomes still do.
This fixes source behavior but is not runtime confirmation of how the stored
proposal was created. No additional AWS query, deployment, stored-proposal
delete/rewrite, activation, or lifecycle continuation was authorized or run.
The unexpected immutable proposal remains failed-closed audit evidence.
