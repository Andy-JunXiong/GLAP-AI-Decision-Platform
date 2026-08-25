# Governed COMPLETE-to-Outcome canary

**Status:** `OBSERVED_OUTCOME_RECONCILER_IMPLEMENTED_WAITING_DUE_DATE`
**Boundary:** synthetic isolated staging, Australia/Sydney actual calendar

## Purpose

This package prepares the smallest governed path from the already verified
`APPROVED` Action to one delayed simulated Outcome and the existing Learning
gate. The governed path has now executed through creation and reconciliation
of one pending Outcome; observation remains calendar-gated and separately
unauthorized. The plan contains no Action, request, actor, shipment, Outcome,
AWS, or storage identifiers.

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
date is a future gate relative to the execution date, not observed evidence.

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
evidence, and a closed simulated Outcome is not real logistics performance.

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
completion. It passed after run `32803181376`. No observed-Outcome continuation
is authorized, and the calendar gate prohibits it before `2026-08-28`.

## Observed Outcome and Learning verifier

The local `ops/check_observed_outcome_due_date.ps1` reads the governed due date
from this contract and derives the current date from the Australia/Sydney
timezone. On `2026-08-25` it returned `BLOCKED` for the `2026-08-28` gate before
any AWS setup or call and reported that no external write occurred.

The prepared aggregate-only
`ops/reconcile_observed_outcome_learning_staging.ps1` also fails before any AWS
setup when the due date has not been reached. Once separately authorized on or
after the due date, it will select only the latest version of each Outcome and
require exactly one closed simulated result for the canary Action, a non-null
observed date and effect, observation on or after the due date and by the
current Sydney cutoff, and an eligible Learning count increase from the frozen
baseline of 1 to exactly 2. Because 2 remains below the 20-Outcome review
threshold, it also requires zero policy proposals and zero activations. The
reconciler has not run against AWS and makes no observed-result claim today.
