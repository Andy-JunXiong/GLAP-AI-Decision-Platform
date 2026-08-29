# Governed exception-to-outcome contract

**Business-date boundary:** Australia/Sydney
**Implementation status:** private AWS staging persistence deployed and verified on 2026-08-06;
Action assignment application chain verified in staging through distinct
operator EDIT and approver APPROVE identities; stable retry verified; read-only
Action–Outcome and Outcome–Learning reviews deployed and runtime-verified in
private staging on 2026-08-23

The governed closed loop connects lifecycle evidence without allowing synthetic
learning to change either the generator or an effective policy automatically:

```text
Lifecycle snapshot
-> stable SLA_BREACH / COST_ANOMALY candidate
-> cross-day alert (OPEN / RESOLVED)
-> human-approved action
-> delayed simulated outcome
-> learning evidence
-> PENDING_HUMAN_REVIEW policy proposal
-> separately approved policy version with rollback target
```

## Alert contract

An alert keeps the candidate's stable fingerprint, shipment grain and explicit
dimension. The first and last detection dates survive daily reconciliation. A
missing candidate resolves an open alert; it does not delete its history.

`SLA_BREACH` is emitted per shipment milestone. `COST_ANOMALY` is emitted per
shipment total-cost comparison. Public use is aggregate-only and every row is
labelled simulated.

Before Action review, the authenticated Risk surface derives
`decision-brief.v1` for a valid current open `SLA_BREACH`; the deployed extension
now does the same for `COST_ANOMALY`. SLA preserves the deterministic
`EXPEDITE_MILESTONE` rule. Cost deterministically selects `REVIEW_COST`, binds
the exact `stateful-cost-variance.v1` calculation source, and explicitly marks
the rate-card version unavailable rather than inferring it. Both distinguish
observed Alert inputs from derived exposure, include monitor and no-action
alternatives, and keep expected benefit `NOT_ESTIMATED`. Reading either brief
creates no mutation. The SLA and Cost surfaces are deployed and reader/RBAC
verified, but no newly bound Cost proposal has been observed. See [`decision_brief_v1.md`](decision_brief_v1.md)
and [`cost_anomaly_decision_brief_v1.md`](cost_anomaly_decision_brief_v1.md).

The local SLA runtime-evidence reconciler prepares the corresponding producer
proof. Its aggregate-only query requires exactly one eligible same-date source
Alert, one of seven governed milestone/metric pairs, the exact
`decision-brief.v1` / `EXPEDITE_MILESTONE` binding and calculated rationale,
an immutable unreviewed proposal, a matching current-view projection, and
unchanged legacy-null pre-release SLA Actions. Its separately authorized
`2026-08-27` staging query found natural proposals and passed the source,
immutable-state, current-view, and legacy-null checks, but at least one proposal
failed the exact binding and the invalid-binding count was non-zero. The gate
failed closed and established neither root cause nor runtime binding evidence.
Any future Athena query remains a separately authorized external AWS operation;
the reconciler invokes no lifecycle date and performs no Action mutation. See
[`sla_breach_runtime_evidence_v1.md`](sla_breach_runtime_evidence_v1.md).

Its separately authorized binding-diagnostic run kept the full gate and added
five identifier-free booleans. Version, Action type, and selected alternative
passed; rationale shape and rationale value failed. Versioned deployed source
matches the expected template, but aggregate evidence cannot distinguish
persisted-text from verifier-expression drift. It mutated or repaired nothing,
established no root cause, and every future query requires separate authority.

The optional regex-independent rationale diagnostic retains the full and
binding gates, then adds five identifier-free booleans for rationale presence,
milestone prefix, governed suffix, numeric token, and numeric equality. Its
first separately authorized execution failed before results on
`ENDS_WITH_EXPRESSION`; after a local `length` plus `substr` correction, the
separately authorized retry returned all five rationale-only booleans true
while the legacy regex checks remained false. This validates the persisted
rationale and isolates verifier drift: `[A-Z_]+` excludes digits in governed
`P2P_*` milestones. The local full-gate verifier now reuses the compositional
rationale checks and contains no rationale regex. The separately authorized
corrected full reconciliation returned all seven aggregate booleans true,
establishing synthetic staging runtime evidence for the natural SLA Decision
binding. It cannot mutate or repair an Action, and no human judgment occurred.

The local Cost runtime-evidence reconciler prepares the remaining producer
proof without manufacturing it. Its aggregate-only query requires a naturally
generated operational actual-calendar proposal, the exact eligible Alert and
`decision-brief.v1` / `REVIEW_COST` / `stateful-cost-variance.v1` binding, an
immutable unreviewed proposal state, a matching current-view projection, and
unchanged legacy-null pre-release Cost Actions. Its separately authorized
`2026-08-27` staging query found zero natural Cost proposals: the candidate gate
failed while the other six aggregate checks passed. No runtime binding evidence
was established. Any future Athena rerun remains a separately authorized
external AWS operation; the reconciler invokes no lifecycle date and performs
no Action mutation. See
[`cost_anomaly_runtime_evidence_v1.md`](cost_anomaly_runtime_evidence_v1.md).

Every newly generated eligible SLA Action preserves `decision_brief_version`,
the deterministically selected `EXPEDITE_MILESTONE` alternative, and the exact
proposal rationale on its immutable row. The deployed Cost extension reuses that
binding with `REVIEW_COST` and a source-versioned rationale. Invalid inputs
fail closed; legacy and pre-release Cost Actions receive no invented binding.
Human review reasons remain chronological append-only audit events. A named human applied
the additive staging migration and all six aggregate checks returned zero on
`2026-08-25`. The independent producer, SLA readers, and Cost readers are
deployed and reader/RBAC verified. Bounded actual-calendar continuation run
`33020683956` invoked the Generator on `2026-08-27` and passed all 41 checks,
and the subsequent aggregate Cost query found zero natural proposals. The gate
failed closed, so no runtime Cost binding is established. See
[`decision_action_binding_v1.md`](decision_action_binding_v1.md).

## Action and outcome contract

Every proposed action requires a named human reviewer. System, automation and
model actors cannot approve it. Only an approved and completed action may
produce an outcome.

The proposed Action row is immutable. A private, manual-only mutation function
appends every `EDIT`, `APPROVE`, `REJECT`, or `COMPLETE` event to an Iceberg audit table.
Valid transitions are fail closed, and stable request IDs make retries
idempotent. A view overlays the latest audit event to expose current Action
state without erasing its history.

Decision-to-Action binding does not change that state machine. The system's
selected alternative is a proposal requiring human review, not approval or
execution. A named human's actual judgment is evidenced only by the signed
audit actor and reason on `EDIT`, `APPROVE`, or `REJECT`.

The repository now also exposes that relationship as one authenticated,
read-only evidence chain: immutable proposal, chronological audit events,
current Action state, and the latest cutoff-eligible Outcome. The chain uses
only operational actual-calendar rows through the current Sydney date. It
labels pending Outcomes as not observed and all closed-loop effects as
synthetic; it creates no mutation, approval, real-performance, or production
claim. After separate named-human authorization, the endpoint and cockpit
timeline were deployed to private staging and passed both the staging and
four-role runtime verifiers. This release created no Action mutation.

The repository-local Outcome Review now projects the same immutable proposal
provenance beside every cutoff-eligible Outcome. It follows the existing
`action_id` at read time to expose nullable `decision_brief_version` and
`selected_alternative`; it does not duplicate those fields into Outcome
history. Legacy and unimplemented Decision types remain explicitly unbound.
This makes synthetic evaluation groupable by proposal contract without
claiming approval, execution, causality, realised value, or real logistics
performance. The extension is deployed, reader/RBAC verified, and returned no
eligible bound cohort at its runtime checkpoint; see
[`outcome_review_decision_provenance_v1.md`](outcome_review_decision_provenance_v1.md).

A repository-local aggregate readiness audit now connects the runtime-verified
natural SLA Decision binding to that deployed provenance reader. It validates
the exact Decision pair, named-human completion chain, latest Outcome
cardinality, and cutoff-valid pending or closed evidence, then returns one of
seven bounded workflow states. Expected absence remains a waiting state;
contract drift fails closed. The separately authorized `2026-08-27` audit
returned `WAITING_HUMAN_REVIEW`: the exact-bound proposal exists, but no named-
human completion or Outcome exists, and every drift check remained valid. It
exposed no counts or identifiers, performed no mutation, and cannot replace
human Action judgment.
See [`sla_outcome_provenance_readiness_v1.md`](sla_outcome_provenance_readiness_v1.md).

Outcome Review now also consumes that provenance through a versioned cohort
summary. A separate read-only aggregate groups only latest-version observed,
numeric, bound synthetic Outcomes by Decision Brief version and selected
alternative. It returns reconciled sample/status counts and descriptive effect
ranges without depending on the bounded entity list. Pending, unbound, and
future-simulation rows are excluded. The summary creates no counterfactual,
causal, realised-value, real-performance, Learning, model, policy, or
production claim; see
[`decision_contract_outcome_cohort_v1.md`](decision_contract_outcome_cohort_v1.md).
The API latency correction starts this aggregate and the unchanged bounded
Outcome-list query together with exactly two workers and independent Athena
clients. Both remain mandatory for one response, and either failure fails the
response closed. Commit `66eeb52` was delivered to the private staging stack by
separately authorized workflow run `33220634162`; the run passed contract tests
and stack deployment but performed no endpoint or latency recheck at that
checkpoint. It adds no cache, query omission, mutation, permission,
causal-performance, schedule, production, or Pages claim.
A later separately authorized bounded read observation returned 20/20 2xx
responses under the frozen workload, while overall p95 4,996 ms still failed
the unchanged gate. The three `outcomes_pending` samples had p95 2,913 ms. That
small sample is descriptive only; it does not establish causality, production
performance, or authority to rerun or optimize.

The cohort response now includes a separate evidence-sufficiency gate whose
business configuration is now bound to the project-owner-approved
`outcome-cohort-threshold-contract.v1`: 20 observed Outcomes and two represented
result states per cohort. Each cohort receives explicit pass/fail gate results;
only a cohort passing both may report descriptive comparison eligibility. The
mechanism cannot select thresholds, change Learning, or expand any causal,
value, model, policy, deployment, or production claim; see
[`outcome_cohort_evidence_sufficiency_v1.md`](outcome_cohort_evidence_sufficiency_v1.md).

The same response now explains the exact non-negative evidence gap to those
20/2 targets for every cohort. The gap is arithmetic only: it cannot recommend
Outcome creation, lifecycle continuation, or a desired result-state mix, and
it cannot expand causal, value, Learning, model, policy, deployment, or
production authority. See
[`outcome_cohort_evidence_gap_v1.md`](outcome_cohort_evidence_gap_v1.md).

An eligible-cohort comparison view fails closed until at least two cohorts pass
the approved gate. It then places their descriptive status mixes and effect
ranges side by side without ranking, selecting a preferred alternative,
estimating causal or statistical superiority, or recommending an Action. See
[`outcome_cohort_descriptive_comparison_v1.md`](outcome_cohort_descriptive_comparison_v1.md).

Each displayed comparison cohort now carries aggregate-only provenance for its
immutable Decision binding, Sydney cutoff, evidence basis, aggregation schema,
and approved threshold contract. Action, Outcome, and shipment identifiers
remain unexposed, so traceability adds no entity drill-through or mutation
authority. See
[`outcome_cohort_comparison_provenance_v1.md`](outcome_cohort_comparison_provenance_v1.md).

A deterministic SHA-256 fingerprint now covers each displayed comparison
aggregate and its provenance. It detects covered-content mismatch when
recomputed, but it is unsigned and establishes neither source authenticity nor
business validity. See
[`outcome_cohort_comparison_fingerprint_v1.md`](outcome_cohort_comparison_fingerprint_v1.md).
Its canonical form uses fixed two-decimal percentage strings before sorted,
compact JSON encoding, avoiding server/browser numeric-serialization drift.
The private cockpit now recomputes that digest locally and withholds the
covered aggregate and provenance until verification succeeds. Failure or
unavailable browser cryptography fails closed without a new request or write;
see
[`outcome_cohort_comparison_verifier_v1.md`](outcome_cohort_comparison_verifier_v1.md).
Mismatch results now include one bounded local diagnostic code. The code helps
the operator distinguish a missing contract, contract drift, unavailable
cryptography, non-canonical content, digest mismatch, or safe verification
failure without exposing covered evidence, persisting a result, or sending
telemetry; see
[`outcome_cohort_comparison_diagnostics_v1.md`](outcome_cohort_comparison_diagnostics_v1.md).
The cockpit offers one local-only retry for the two transient browser reason
codes and none for structural mismatch codes. The same loaded response is
rechecked, content stays hidden, and no network, telemetry, persistence, or
mutation path is introduced; see
[`outcome_cohort_comparison_retry_v1.md`](outcome_cohort_comparison_retry_v1.md).

The client now validates the complete comparison envelope before React or the
per-cohort verifier can iterate it. Schema drift, inconsistent eligible and
excluded counts, an invalid status/array combination, or any true governance
flag fails the Outcome load closed. A wholly omitted comparison remains the
existing partial-data state. This local structural prerequisite adds no new
request or authority; see
[`outcome_cohort_comparison_envelope_validator_v1.md`](outcome_cohort_comparison_envelope_validator_v1.md).

The repository extension uses `PROPOSED -> EDITED` to record a named owner and
due date without approving the Action. `EDITED` then requires a separate
approver to approve or reject it. Assignment is carried forward into later
audit events, while the source proposal remains unchanged. The additive staging
schema migration was applied by a named human on 2026-08-13 and passed all five
read-only checks with zero failures. The migration itself executed no Action
mutation. The named-human canary completed on 2026-08-23. The response fix was
released through the protected narrow path, the same operator replayed the
original request ID with HTTP 200 and no duplicate audit row, and a different
named approver selected `APPROVE`. Reconciliation found one `EDIT`, one
`APPROVE`, zero `REJECT`, zero `COMPLETE`, two distinct named actors, one
current `APPROVED` row, and an unchanged assignment. This authorizes neither
`COMPLETE` nor Outcome creation.

The next canary package is prepared locally. Its versioned contract freezes
eight ordered gates: read-only verification of
the existing `APPROVED` source state; a separately authorized named-human
`COMPLETE`; read-only completion reconciliation; a separately authorized
actual-calendar continuation that creates one pending Outcome; read-only
pending reconciliation; the three-day calendar wait; a separately authorized
actual-calendar continuation on or after the due date; and read-only
Outcome/Learning reconciliation. Each write phase is a separate authority
decision. Future simulation cannot satisfy the canary, and the redacted local
plan prints no entity, request, identity, or AWS identifiers. See
[`action_complete_outcome_canary.md`](action_complete_outcome_canary.md).
The dedicated aggregate-only staging preflight subsequently passed all eight
checks on `2026-08-25`: exactly one approved candidate, one `EDIT`, one
`APPROVE`, zero `REJECT`, zero `COMPLETE`, preserved role separation, one
assignment match, and zero Outcomes. It printed no protected identifiers and
executed no mutation or lifecycle continuation.
After explicit project-owner authorization on `2026-08-25`, a signed-in named
human selected `Mark complete` in the private Action Board. The agent only
positioned the page and did not click or submit the mutation. The subsequent
aggregate-only reconciliation passed all eight checks: one `COMPLETED`
candidate, one `EDIT`, one `APPROVE`, zero `REJECT`, exactly one named-human
`COMPLETE`, the preserved assignment, and zero Outcomes. It printed no
protected identifiers. This supersedes the earlier `APPROVED` source state;
the one-time completion authority is consumed and creates no standing
authority.
After a new explicit project-owner authorization, the agent used the named
GitHub session to trigger manual workflow run `32803181376` from commit
`291fffc`. It succeeded for only `2026-08-25` in `OPERATIONAL` /
`ACTUAL_CALENDAR` mode, with one date, no seed, and no future simulation. The
pending-Outcome reconciliation then passed all six checks: one completed
candidate, one `PENDING` / `SIMULATED` Outcome, null observed date and effect,
and a due date three days after completion. It printed no protected
identifiers. The consumed authority creates no standing authority.
The system-computed due date was `2026-08-28`. Relative to the pending run it
was a future calendar gate, not observed evidence. On that Sydney date, plan
run `33149532396` passed and separately authorized continuation run
`33149577300` processed only that one date from commit `3316627`, with no seed
or future simulation, and passed all 41 lifecycle checks.

A local Australia/Sydney due-date verifier returned `BLOCKED` on `2026-08-25`
before any AWS setup or call and returned ready on `2026-08-28`. The companion
aggregate-only reconciler then passed the latest closed simulated Outcome,
governed calendar window, and eligible-count increase from 1 to 2. It confirmed
that 2 is below 20 and that no proposal is activated, but failed closed because
at least one unactivated policy proposal exists below the threshold. No second
continuation, proposal mutation, or activation followed.

Outcomes remain `PENDING` until their observation lag expires. Once due, the
result is reproducible from stable entity/version identifiers and depends on
action type, alert type and severity, shipment stage, carrier, execution delay,
and active-disruption context. Result states are `SUCCESSFUL`,
`PARTIALLY_SUCCESSFUL`, `FAILED`, and `INCONCLUSIVE`; all are `SIMULATED`.

## Learning and calendar gate

Learning may create a `PENDING_HUMAN_REVIEW` policy proposal after the configured
minimum observed-outcome count. A proposal cannot modify simulation
configuration, has no effective date before approval, and retains the current
policy version as its rollback target.

The authenticated Learning Review now exposes this gate as a read-only
contract. It de-duplicates closed Outcomes, applies the Sydney cutoff and the
`OPERATIONAL` / `ACTUAL_CALENDAR` eligibility rules, reports progress toward the
20-Outcome minimum, and attaches only the latest eligible stored proposal. It
cannot approve or activate that proposal, cannot replace deterministic safety
rules, and labels all summarized effects as synthetic rather than real
logistics performance. Passing this synthetic policy-review threshold is not
model readiness or production readiness. The implementation is deployed in
private staging. Its earlier explicit reader gates passed at `1/20` with no
proposal. After the authorized due observation, the latest-version eligible
count is `2/20`; the canary failed closed because at least one unactivated
proposal is already present below that threshold.

Source inspection identified a counting mismatch capable of explaining this
state: the lifecycle adapter supplied all closed historical Outcome rows to the
proposal builder, which thresholded by row count, while the Learning reader and
canary reconciled only the latest version per `outcome_id`. The separately
authorized local forward fix now selects one latest cutoff version per logical
Outcome before thresholding. It excludes earlier closed history when the latest
version is pending and fails closed on future or same-date conflicting versions.
Regression tests preserve both sides of the threshold: 20 versions of one
Outcome do not trigger, while 20 distinct Outcomes do. Commit `a10678b` passed
CI run `33154815653`; plan run `33155014510` completed the independent
one-resource guard without upload or execution, and separately authorized
deploy run `33157729317` released only the isolated Generator. The release
summary reports no lifecycle, schema, Controller, schedule, alias, or production
effect. The deployed digest and post-release behavior are not independently
reconciled, so this remains no runtime confirmation of stored-proposal
provenance. The stored proposal remains immutable and unactivated.

Learning maturity is therefore reported on four independent dimensions rather
than compressed into one optimistic lifecycle label:

- `implementation_status = IMPLEMENTED_VERIFIED`;
- `operational_status = DORMANT`;
- `evidence_status = INSUFFICIENT_ELIGIBLE_OUTCOMES`;
- `progression_status = EVIDENCE_GATED`.

The contract and staging mechanics are implemented, but Learning is not an
active evidence-producing product loop under the current synthetic-data pace.
The already-started due-date canary reached its one authorized observation and
then stopped failed closed. Advancing mechanically from 2/20 to 20/20 is not
the roadmap.

Operational model-readiness inputs must satisfy every condition below:

- `execution_mode = OPERATIONAL`;
- `time_basis = ACTUAL_CALENDAR`;
- outcome state is closed rather than pending;
- `observed_date` is on or before the Sydney as-of date.

`FUTURE_SIMULATION` outcomes are useful for workflow testing only. They never
count as observed labels, operational backtest evidence, or promotion evidence.

## Deployment evidence and boundary

[`glap_governed_closed_loop.py`](../lambda/glap_governed_closed_loop.py) remains
a pure, deterministic domain layer. The existing private lifecycle adapter now
persists its state to four isolated Iceberg staging tables using
scenario-aware, retry-safe keys.

The `2026-08-06` actual-calendar staging run produced 15 Alert rows and 15
proposed Action rows. A repeat run produced zero new Actions. Athena
reconciliation found 15/15 distinct Alert keys, 15/15 distinct Action keys,
zero future-simulation rows, and no Outcomes or policy proposals before their
human-completion and observation gates. All six original closed-loop quality
checks passed.

The controlled Action-mutation verification appended exactly two events,
`APPROVE` then `COMPLETE`, for one operational-calendar engineering Action.
Replaying the approval returned the original event. The current-state view
reports `COMPLETED`, and the same-date generator continuation created one
`PENDING` Outcome whose observation is due on `2026-08-09`. It has no observed
date and is not actual outcome evidence as of `2026-08-06`.

On the Sydney business date `2026-08-09`, an authenticated `viewer` refreshed
private Outcome Review and verified that the dated record had matured without
rewriting its historical Action or execution evidence. The response contained
zero pending Outcomes and one observed `SUCCESSFUL` Outcome with
`observed_date=2026-08-09`, `time_basis=ACTUAL_CALENDAR`, and a 20.0% simulated
effect. This is one eligible synthetic staging record; it is not real logistics
performance, sufficient label maturity, model readiness, production readiness,
or authority to activate a policy.

The same-date broader readiness run kept the governed Action Outcome separate
from the multimodal shipment-label contract. Its operational, actual-calendar
cohort contained 67 pending Maersk shipment labels and zero observed shipment
labels, so every supervised target remained
`blocked_insufficient_observed_labels`. This is expected: an Action Outcome
records a delayed simulated intervention effect, while a shipment label becomes
observed only after delivery. The pending labels were excluded from training,
and no future-simulation scope contributed to the result.

The expanded 28-check lifecycle gate passed the duplicate-request and invalid
audit-transition checks, while retaining one pre-existing failure:
`missing_provider_coverage`. The actual-calendar baseline for this date contains
only Maersk Ocean; future DHL/KN simulation rows were not used to manufacture
operational coverage.

On 17 August, read-only diagnosis confirmed that the persisted `2026-08-09`
controller status still failed only that check. The deployed recovery
controller now compares the booking cohort with providers whose active route
configuration is effective on the logical date, rather than requiring the later
three-provider roadmap on every earlier date. This does not rewrite the
historical failure, add provider rows, or establish provider/model readiness.

On 23 August, separately authorized recovery run `32634293552` passed that
28-check lifecycle gate, then failed closed at compatibility input validation:
the current volume was 17 and the exact prior-calendar-day volume was zero.
The repository follow-up makes lifecycle continuation, prior-alert reconciliation,
immutable-state validation, and volume comparison select the latest earlier
populated date in the same temporal scope. It does not relax the threshold,
fabricate a missing date, clear the failed status, or authorize deployment or
another recovery attempt.

This deployment does not enable a recurring schedule, create a production
alias, expose entity records publicly, complete an Action automatically, or
activate a policy.
