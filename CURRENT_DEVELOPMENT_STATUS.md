# GLAP Current Development Status

**Sydney as-of date:** `2026-08-16`

This document states what is true now, what is waiting for validation, and what
should be implemented next. It is updated at each formal closeout and contains
only the current week, recent seven-day context, and active carry-over.

Long-term direction lives in [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md).
Authority and execution rules live in [`AGENTS.md`](AGENTS.md). Historical
records live under [`docs/archive/status/`](docs/archive/status/README.md).

## Current product reality

| Capability | Current state | Evidence boundary |
| --- | --- | --- |
| Success-gated production pipeline | `IMPLEMENTED_VERIFIED` | Scheduled synthetic production track; aggregate public status only |
| Stateful multimodal lifecycle | `IMPLEMENTED_STAGING` | Manual isolated staging; no production alias or schedule |
| Authenticated Operations loop | `IMPLEMENTED_STAGING` | Private staging with signed identity and RBAC |
| Action assignment canary | `PARTIAL` | Operator `EDIT` recorded; response fix release, stable retry, and separate approver decision remain |
| Governed Action and Outcome | `IMPLEMENTED_STAGING` | Synthetic actual-calendar staging evidence |
| Forecast backtest framework | `IMPLEMENTED_STAGING` | Private advisory evaluation; label maturity remains blocked |
| Evaluation Architecture | `IMPLEMENTED_VERIFIED` | Local read-only engineering evaluation only |
| Historical Replay corpus | `IMPLEMENTED_VERIFIED` | Ten-event AIR/OCEAN/RAIL/ROAD hybrid corpus; structural gates met, independent-review gate not met |
| Decision Quality review handoff | `PUBLIC_RELEASED_PENDING_EXPERT_REVIEW` | public Sites v7 serves the formal story-complete v3 flow plus a separate non-submitting Human Evaluation preview; v1/v2 drafts are ineligible; no independent expert result |
| Production readiness | `PARTIAL` | Plan-only controls; no production authorization |

All logistics records, exposures, outcomes, and replay enterprise state remain
synthetic. Only inspected AWS runtime, delivery, and reliability facts may be
described as operational evidence.

## Active slice — Human Evaluation decision-story preview

**Status:** `PUBLIC_PREVIEW_PENDING_REVIEWER_FEEDBACK`

**Goal**

Test whether a logistics reviewer can enter a point-in-time event, understand
what is currently known, and debate two executable choices without learning the
Evaluation Harness schema. Present five selected Historical Replay cases as 15
sequential decision moments while preserving the frozen reviewer-safe source
mapping and keeping the formal v3 submission flow unchanged.

**Non-goals**

- changing the frozen corpus, scenarios, or rubric;
- changing the formal v3 review API, D1 session, submission, or attestation flow;
- fabricating or automatically generating expert reviews;
- evaluating Business Outcome Effect;
- calling AWS, deploying, scheduling, or mutating an operational Action;
- adding External Evidence, Decision Memory, or an Investigation Agent variant.

**Objects / schema**

- `decision-option-contract.v3`;
- `historical-replay-review-freeze.v3`;
- the frozen reviewer-safe v3 30-package bundle;
- the separate study-owner-only blind-key bundle;
- bundle-scoped review sessions that retain but isolate v1/v2 drafts;
- a browser-only Human Evaluation presentation projection over 15 exact frozen
  package positions, with seven expected identical pairs allowlisted;
- `decision-quality-review.v1` submissions created only by independent humans.

**Files / modules**

- deterministic v3 story, solution, expected-benefit, and reviewer-safe package generator;
- bilingual reviewer site with complete option sections;
- public `/pilot/human-evaluation` experience preview with five operational
  stories, sequential reveal, read-only past judgments, and browser-local state;
- D1 migration from user-only sessions to `(user_id, bundle_id)` sessions;
- owner-only blind keys retained outside reviewer access;
- the public review site behind a dedicated reviewer account, with no ChatGPT
  account dependency.

**Business rules**

- scenario, rubric, and v3 option-contract digests must remain unchanged;
- reviewers receive packages and rubric, never blind keys;
- v1/v2 draft answers remain stored but are never loaded into or counted toward v3;
- repository-generated test objects are never counted as expert evidence;
- preview answers never call `/api/review`, create a formal submission, or count
  as Decision Quality evidence;
- unrevealed moments expose no future title, date, result label, colour cue,
  progress text, or tooltip;
- after later evidence appears, earlier preview judgments remain read-only;
- every accepted submission must satisfy independence, conflict, digest, and
  completeness gates;
- no operational mutation authority exists.

**Automated validation**

- fail-closed package, rubric, option-contract, submission, and blind-key
  digest validation;
- citations may reference only evidence and facts visible in the same cutoff;
- every package has a cutoff-safe story, difficulties, conditional impact
  pathways, and decision question;
- every option has three solution horizons, expected benefits with measurement
  signals, trade-offs, uncertainty, and a proposal-only authority boundary;
- duplicate-reviewer and attestation checks;
- de-identified aggregation only after the minimum-review gate is met.
- exact source-position and identical-pair allowlist checks across all 15
  preview moments;
- DOM-level future-information exclusion and sequential-unlock checks.

**Manual validation**

- the earlier public Sites v6 canary verified dedicated-account login,
  bilingual switching, and the formal v3 30-package bundle identity;
- public Sites v7 now exposes the separate non-submitting preview after
  explicit approval, and the invited reviewer received its direct link;
- the hosted database contains a distinct v3 `DRAFT` session at Case 1 and
  zero review-answer rows; v1/v2 drafts remain under their own bundle IDs;
- answer save/resume remains for the independent reviewer because the agent
  did not make the reviewer's personal attestations or submit a score;
- have the human study owner verify conflicts and key separation;
- keep reviewer identity details out of repository artifacts.

**Definition of done**

- v3 generation, citation integrity, story, solution, benefit, schema, site
  build, and bundle-isolation gates pass;
- public Sites v7 serves the unchanged formal v3 flow and the separate
  browser-only preview after explicit release approval;
- all five preview cases and 15 moments map to the frozen reviewer-safe source,
  with strict future locking and no formal API call;
- the hosted canary confirms dedicated-account login and the v3 bundle while
  a fresh v3 `DRAFT` remains at Case 1 and v1/v2 drafts stay preserved under
  different bundle identities;
- Decision Quality remains `NOT_EVALUATED` until eligible v3 reviews are later
  collected and aggregated.

**Stop conditions**

- a frozen v3 digest changes;
- reviewer identity or independence cannot be verified;
- a reviewer has blind-key access or a conflict of interest;
- reviewer access would expose the owner-only blind key or merge v1/v2 answers
  into v3;
- the change would require AWS or operational mutation authority.

**Next slice after completion**

Collect reviewer feedback on whether the five preview cases support realistic
operational debate. Any integration of this presentation into formal review
submission requires a separate human-approved change; only then resume eligible
v3 collection and later corpus-level result integration.

## Pending validation

- Release the Action response-serialization fix only through separately
  authorized narrow Prepare and Execute phases.
- Retry the original Action request ID after that release and confirm the audit
  event remains idempotent.
- Have a different named approver approve or reject the edited staging Action.
- Collect the invited reviewer's usability feedback on the non-submitting
  preview without treating browser-local judgments as formal evidence.
- Have the independent reviewer verify formal v3 save/resume and complete only
  personally true attestations if formal collection resumes.
- Collect genuinely independent Decision Quality reviews only from the v3
  scenario, rubric, and option-contract freeze.

`pending validation` means implementation exists but the required human,
runtime, or external evidence has not been completed. It is not equivalent to
done.

## Incomplete or blocked

- Historical Replay: ten scenarios meet the declared structural gate; the
  independent-review gate remains unmet.
- Decision Quality: v1/v2 collection is paused and preserved drafts are
  ineligible; public Sites v7 serves formal v3 plus a separate browser-only
  preview, but no eligible independent expert reviews exist.
- Business Outcome Effect: no counterfactual business result is established.
- Provider/model readiness: eligible actual-calendar DHL/KN history and closed
  labels remain insufficient.
- Supervised learning: blocked by governed observed-label thresholds.
- AWS cost and maintenance controls: designed but require separate human
  infrastructure approval.
- Production aliases, schedules, policy activation, and model promotion remain
  human-owned and unauthorized.

## Recently completed — current seven-day window

- Evaluation Architecture separated System Correctness, Capability
  Attribution, Decision Quality, and Business Outcome Effect.
- Decision Quality rubric, blind package, review schema, and fail-closed local
  aggregation mechanics were implemented without creating expert evidence.
- Historical Replay expanded to ten frozen events, 30 cutoffs,
  AIR/OCEAN/RAIL/ROAD, HIGH/MEDIUM, sixteen attributed changes, and fourteen
  no-delta controls. The latest additions cover Europe, North Africa, Oceania,
  Southeast Asia, and South America across tunnel failure, vessel grounding,
  extreme weather, port congestion, and flood-damaged highways. Every recovery
  fact remains reveal-only.
- Historical Replay review inputs are now frozen by manifest, scenario, and
  rubric digests. The deterministic handoff covers all 30 cutoffs, excludes
  post-decision reveals and capability identity, and retains the blind keys for
  a human study owner only. No independent review has been created.
- Decision Quality v2 adds a frozen option-content contract. Every option now
  includes visible-evidence citations, explicit risk and exposure reasoning,
  three bounded action steps, a review trigger, trade-offs, uncertainty, and a
  proposal-only authority boundary. The reviewer site is bilingual and keeps
  v1 sessions isolated by bundle ID.
- Sites v5 was released publicly after explicit human approval. A hosted canary
  verified dedicated-account login, fresh v2 session creation, full option
  content, and refresh/resume behavior. The migrated database retained separate
  v1 and v2 draft sessions and contained zero review answers after the canary.
- The invited reviewer was notified that v2 collection is ready and should
  restart from Case 1 using the existing corrected dedicated credentials. This
  notification creates no expert evidence and does not change Decision Quality
  from `NOT_EVALUATED`.
- User review found that v2 still presented rule mechanics rather than a usable
  decision story and solution. V3 now adds a cutoff-safe story, decision
  pressure, difficulties, conditional downstream risks, a targeted problem
  response, 0–24 hour / 2–7 day / 30–90 day solution paths, and short- and
  long-term expected benefits with measurement signals. V1/v2 remain
  preserved but ineligible. Sites v6 initially released v3 publicly after
  explicit human approval; the invited reviewer was told to restart from Case 1.
- Human Evaluation now presents five selected cases and 15 sequential moments
  as operational stories with current facts, executable anonymous choices,
  four comparison judgments, and confidence scoring. Future result semantics
  remain absent until sequential unlock, earlier judgments become read-only,
  and seven expected identical pairs remain source-faithful through an explicit
  allowlist. Sites v7 exposes this as a separate browser-only preview; it never
  calls the formal review API or creates expert evidence. The invited reviewer
  received the direct preview link after explicit release approval.
- Documentation Architecture v1 separated rules, direction, current truth, and
  historical evidence and added a fail-closed drift check against legacy mixed
  authority. Local post-migration validation is complete.

## Validation ledger

### Codex-run validation

- Repository-wide validation after the v3 story-complete handoff: 295 Python
  tests passed, including story, solution-horizon, expected-benefit,
  point-in-time citation, and blinding checks.
- Reviewer site validation passed lint, production build, and 21 tests across
  the formal v3 flow and the Human Evaluation preview. The v3 bundle contains
  30 packages and keeps fourteen identical
  controls, and remains absent from unauthenticated client assets. The public
  v6 canary verified dedicated-account login, Chinese/English switching, and
  the v3 bundle marker. A database read confirmed a distinct v3 `DRAFT` at
  Case 1 and zero answer rows; no personal reviewer attestation or score was
  created by the agent.
- Preview-specific validation covers five cases, 15 exact source mappings,
  seven allowlisted identical pairs, DOM-level future-information exclusion,
  strict sequential unlock, read-only past judgments, browser-local persistence,
  and absence of formal review API calls. The public Sites v7 deployment
  succeeded; no preview answer was submitted by the agent.
- Deterministic corpus replay passed with ten scenarios, 30 cutoffs, sixteen
  attributed changes, fourteen no-delta controls, all structural gates met,
  and `NOT_MET` status because independent reviews are absent.
- Project drift audit: 16 checks passed with zero drift.
- Relative-link validation passed for 64 links across nine changed Markdown
  files.

### User-reported validation

- The user explicitly approved Sites v5 publication, restoration of public
  access, and the reviewer restart notification.
- The user then rejected v2 as too vague and specified that each case must
  include a story, difficulties, downstream impacts, targeted solutions, and
  short- and long-term expected benefits.
- The user explicitly approved public Sites v6. The hosted login and bilingual
  canary passed, and the reviewer restart notification was sent after success.
- The user explicitly approved public Sites v7 for the non-submitting Human
  Evaluation preview and approved sending the direct link to the invited
  reviewer. Both external writes completed successfully.

### Pending validation

- Independent human review and product/runtime items remain listed above.

### Incomplete

- All independent blinded reviews still remain before the declared benchmark
  gate can be met.

## Next Up

1. Collect the invited reviewer's feedback on whether the five preview cases
   produce realistic operational A/B debate; preview answers remain non-evidence.
2. Make a separate human decision on whether to integrate the approved
   presentation into the formal v3 submission flow without changing frozen
   inputs, blind identities, or reviewer attestations.
3. If formal collection resumes, accept only integrity-valid v3 reviews;
   preserved v1/v2 drafts remain ineligible and isolated.
4. Keep Decision Quality and benchmark eligibility `NOT_EVALUATED` / `NOT_MET`
   until at least three eligible reviews per variant pass governed checks.

## Current-week history

Detailed session evidence is recorded in
[`docs/archive/status/daily-logs/2026-08.md`](docs/archive/status/daily-logs/2026-08.md).
Completed capability history is summarized in
[`docs/archive/status/CHANGELOG.md`](docs/archive/status/CHANGELOG.md).
