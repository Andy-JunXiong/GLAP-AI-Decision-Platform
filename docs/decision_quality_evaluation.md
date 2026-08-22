# Decision Quality Evaluation v1

**Rubric:** `decision-quality-rubric.v1`
**Review submissions:** `decision-quality-review.v1` (absolute-score tooling)
and `decision-quality-comparative-review.v1` (story-mode collection)
**Option content:** `decision-option-contract.v3`
**Current status:** four independent, pseudonymous submissions are reconciled
across the formal Sites v12 and mainland Lambda entries. All four contain one
locked answer for each of the same 30 frozen v3 packages and all required
attestations. The private aggregate has 15 package results favouring
`glap-a303-on` and 15 `REVIEWERS_DO_NOT_AGREE` results. This is controlled
point-in-time Decision Quality evidence, not Business Outcome Effect, real
logistics performance, model promotion, or production readiness. After explicit
publication approval, the live aggregate-only Evaluation & Trust view now shows
the four-review result without private review content.

## Purpose

Capability Attribution shows that a capability changed a recommendation. This
contract defines the separate human-evidence gate for deciding whether one
recommendation is more reasonable using only information available at the
scenario cutoff.

Decision Quality review does not observe or estimate a shipment outcome. It
cannot establish Business Outcome Effect, realised savings, model readiness,
or production readiness.

## Blinded review flow

```text
evaluation manifest + deterministic evaluation report
-> build review package and separate blind key
-> give reviewers only the review package and rubric
-> collect independent pseudonymous submissions
-> validate minimum-reviewer and conflict gates
-> aggregate scores while options remain blinded
-> deblind only the aggregate result
```

The review package excludes variant IDs, capability flags, baseline/challenger
roles, decision IDs, rule traces, and rule-specific rationale. A separate blind
key retains the option-to-variant mapping. Possession of the key and review of
an option are conflicting roles; this process boundary is supported by a
reviewer attestation and must be enforced by the human study owner.

## Frozen Historical Replay handoff v3

The ten-event Historical Replay corpus has a separate, content-addressed v3 freeze at
[`review_freeze_v3.json`](../tests/fixtures/historical_replay/review_freeze_v3.json).
Its machine-readable contract is
[`historical_replay_review_freeze_v3.schema.json`](historical_replay_review_freeze_v3.schema.json).
The freeze binds the exact corpus manifest, ordered scenario membership, every
scenario body, the v1 rubric, and
[`decision_option_contract_v3.json`](decision_option_contract_v3.json) by
SHA-256 digest. Any change fails closed before a package can be built.

Each package now explains the point-in-time story, decision pressure,
difficulties, conditional downstream risks, decision question, and fact
boundary. Each blinded option identifies the problem it addresses, cited
evidence, risk, immediate/short-term/long-term solution paths, expected benefits
with measurement signals, trade-offs, and explicit authority boundaries. Every
benefit is labelled `EXPECTED_NOT_OBSERVED`. This content is generated
deterministically from only cutoff-eligible replay inputs and grants no
execution authority.

[`build_historical_replay_review_bundle.py`](../ops/build_historical_replay_review_bundle.py)
turns the frozen 10-scenario, 30-cutoff corpus into two deterministic outputs:

- one reviewer-safe bundle containing all 30 blinded packages, including the
  no-delta controls;
- one study-owner-only key bundle containing option and evidence mappings.

Post-decision reveal sources are excluded from every review package. The public
bundle contains no A303, baseline/challenger, rule-trace, attribution, or blind-
key identity. The two outputs must be stored and distributed separately.

```bash
python ops/build_historical_replay_review_bundle.py \
  --freeze tests/fixtures/historical_replay/review_freeze_v3.json \
  --corpus-manifest tests/fixtures/historical_replay/corpus_v1.json \
  --decision-option-contract docs/decision_option_contract_v3.json \
  --bundle-output artifacts/historical-replay-review-bundle.json \
  --key-output artifacts/historical-replay-review-key-study-owner-only.json
```

The repository deliberately does not include generated review submissions or
a generated owner key bundle. Building the handoff proves deterministic input
integrity and blinding mechanics only; it does not prove reviewer independence
or produce a Decision Quality result.

### Superseded v1 and v2 collection boundary

The v1 handoff exposed only a recommendation, priority, human-review flag, and
one of two generic rationale sentences. V2 added evidence, risk, bounded steps,
trade-offs, and authority, but user review found that it still lacked a usable
problem story, difficulty and impact chain, targeted solution horizons, and
measurable short- and long-term expected benefits. Collection against both
handoffs is paused. Preserved v1 and v2 drafts remain under their original
bundle identities for audit continuity, but they are ineligible as Decision
Quality evidence and must not be migrated into or aggregated with v3.

## Rubric

The machine-readable rubric is
[`decision_quality_rubric_v1.json`](decision_quality_rubric_v1.json). Each
dimension is scored from 0 to 4:

| Dimension | Weight | Question |
| --- | ---: | --- |
| Evidence grounding | 25% | Is the decision supported by cutoff-eligible evidence without unsupported claims? |
| Risk detection and proportionality | 25% | Does it recognise the material risk and respond proportionately? |
| Policy compliance | 20% | Does it follow the supplied policy and constraints? |
| Actionability | 15% | Is it specific enough for an operator to understand the next bounded step? |
| Authority compliance | 15% | Does it preserve human approval and avoid unauthorised execution or outcome claims? |

For an absolute-score v1 submission, the weighted score is normalized to
0--100. For a comparative story-mode submission, each dimension allocates its
weight to Option A, Option B, or equally to both for a tie; the resulting
weighted comparative preference shares are also normalized to 0--100. These
two submission versions must never be mixed in one aggregate. A difference
alone is not sufficient: the interpretation gate requires at least three complete,
independent reviews, at least two non-tie preferences, at least 66.67% non-tie
preference consensus, no declared conflict, and a five-point aggregate score
difference before reporting that review evidence favours an option.

These thresholds are evaluation policy, not statistical proof. They should be
revisited before a larger study and must not be tuned after seeing which option
maps to a GLAP capability.

## Review submission boundary

[`decision_quality_review_v1.schema.json`](decision_quality_review_v1.schema.json)
defines the original independent 0--4 score submission.
[`decision_quality_comparative_review_v1.schema.json`](decision_quality_comparative_review_v1.schema.json)
defines the corrected story-mode submission and requires:

- a pseudonymous reviewer reference rather than a name or email;
- the exact review-package digest and rubric version;
- independence, no-conflict, and no-blind-key attestations;
- one A/B/Tie comparison for every frozen rubric dimension;
- one blinded preference (`OPTION_A`, `OPTION_B`, or `TIE`);
- reviewer confidence from 1 to 5.

The private formal Sites export is separately bound by
[`formal_story_review_export_v1.schema.json`](formal_story_review_export_v1.schema.json).
V1 intentionally has no submission-level status field: finality requires a
timezone-aware `submitted_at`, all three attestations, and exactly 30
`ANSWER_LOCKED` answers. The reconciler enforces the Schema's exact field sets,
so adding or removing fields requires a new export version rather than being
silently accepted.

The local aggregator accepts either complete absolute-score reviews or complete
comparative reviews, but fails closed if the two versions are mixed. It also
fails on duplicate reviewers, incomplete or out-of-range values, package/key
mismatches, changed rubric dimensions, or attestation failures. It stores no
identity claim and performs no network or operational write.

## Objective metrics

Later versions may attach point-in-time objective measures such as decision
latency, evidence coverage, policy violations, tool-call count, hallucination
flags, and cost-estimate error. Each metric needs its own denominator, source,
cutoff, missing-value rule, and evidence class. Missing metrics must remain
missing; they cannot be replaced by an expert score or treated as zero.

## Current evidence boundary

The A303 fixture is controlled synthetic engineering evidence. The frozen v3
Historical Replay bundle is hybrid replay evidence with controlled synthetic
enterprise state. Public Sites v9 is paused after user inspection found its
technical story copy and duplicate-looking identical A/B controls unusable;
Ming received that link before the rejection and began one three-moment case;
that story-v1 draft is preserved but ineligible. Public Sites v12 presents
ten plain-language, three-moment stories. Distinct
source plans remain anonymous A/B choices, while true identical controls appear
once as a shared plan requiring explicit confirmation. It stores comparative
judgments under isolated collection `human-evaluation-story.v2`, aligned with
`decision-quality-comparative-review.v1`; preview-local answers, questionnaire
drafts, and story-v1 records are never migrated. Sites v12 passed a
non-submitting production canary before Dylan was notified. The live database
contains two complete story-v2 submissions. Ming's and Dong's
sessions are locked and submitted with 30 committed answers and all three
attestations each. The earlier story-v1 draft still contains only three
ineligible answers and was not migrated. All six additional-account canaries,
including the seventh hosted account released on 2026-08-20, created no
session, attestation, answer, save, or submission. Unit tests exercise
packaging and scoring mechanics with in-memory test reviews; those tests are
not expert evidence and are never written to the scenario corpus.

The deployed and health-verified collection `glap-ten-story-review.v1` is a
separate mainland-access fallback for the human-created Lambda Function URL.
It reuses all ten frozen stories and 30 source package identifiers, and records
the same five comparative judgments, overall preference, confidence, optional
notes, and final attestations. Every moment is immutable and time-ordered.
On 2026-08-22 the study owner approved combining the content-equivalent entry
surfaces. Read-only source inspection found two complete mainland submissions.
The compatibility/import check passed exact frozen-bundle identity, all 30
review IDs and package digests, the five rubric dimensions, locked-answer and
final-submission state, required attestations, and distinct pseudonymous
reviewer references. The two mainland submissions and two Sites submissions
therefore form four eligible reviews per package. No live database was changed.
The mainland design and human-owned update procedure are documented in
[`three_case_review_entry.md`](three_case_review_entry.md).

## Cross-entry reconciliation

[`reconcile_review_collections.py`](../ops/reconcile_review_collections.py)
normalizes both exports to `decision-quality-comparative-review.v1`, fails
closed on any version, field-shape, compatibility, or integrity mismatch, and
optionally deblinds
only the aggregate with the study-owner key. Its output is private because it
retains pseudonymous review records; `artifacts/` is excluded from Git.

The 2026-08-22 aggregate contains four reviewers, 30 packages, and 120 locked
review records. Fifteen packages meet every interpretation gate and all favour
`glap-a303-on`. Fourteen identical-option controls are unanimous ties. The
remaining non-identical package, Cyclone Gabrielle T1, splits 2:2 with zero
score delta and remains `REVIEWERS_DO_NOT_AGREE`. No adjudication was inferred.

```bash
python ops/reconcile_review_collections.py \
  --formal-export artifacts/formal-review-export.json \
  --mainland-export artifacts/mainland-review-export.json \
  --key-bundle artifacts/review-key.json \
  --output artifacts/combined-review-evidence.json
```

Use the tooling only after first producing an evaluation report:

```bash
python ops/evaluate_decision_capabilities.py \
  tests/fixtures/evaluation/a303_high_risk_route_v1.json \
  --output artifacts/a303-evaluation-report.json

python ops/evaluate_decision_quality.py build-package \
  --manifest tests/fixtures/evaluation/a303_high_risk_route_v1.json \
  --report artifacts/a303-evaluation-report.json \
  --package-output artifacts/a303-review-package.json \
  --key-output artifacts/a303-blind-key.json
```

The blind key must not be distributed to reviewers. No repository review
submission is provided because doing so would manufacture human evidence.

## Parallel Decision Quality and Outcome robustness

Decision Quality answers whether reviewers regard one recommendation as more
reasonable from the then-visible evidence. It is not an admission gate for the
local A303 Outcome simulator and is not a substitute for an Outcome. All 16
verified A303-attributed decision changes enter the synthetic robustness run,
including the package with a 2:2 human split; all 14 unchanged packages enter
as exact-zero controls.

The corrected path applies the frozen
[`a303-outcome-simulator.v1`](a303_outcome_simulator_v1.json), sensitivity
protocol, and capability gate and emits `SIMULATED_COUNTERFACTUAL` evidence.
The controls pass, but the rule result is `NOT_ROBUST`: only 2 of 16 base cases
favour A303-on and the full-grid non-negative rate is 39.81%. The earlier
human-selected 15-package run is preserved as `EXPLORATORY_CONDITIONAL` and is
not eligible for the capability gate. Neither result is observed business
performance, real logistics evidence, or production/model readiness evidence. See
[`evaluation_architecture.md`](evaluation_architecture.md) and
[`historical_replay_lab.md`](historical_replay_lab.md).

The future calibration interface keeps a second separation: historical factual
reveals may calibrate the baseline that actually occurred, while A303 treatment
effects require independently validated prospective controlled pairs. No such
pairs currently exist. In addition, the current synthetic capability gate is
`NOT_ROBUST`, so a human-governed A303 redesign or stop decision comes before
prospective calibration.

After the complete robustness failure and two failed post-hoc guardrail
candidates, the human project owner selected retirement option 1 on
`2026-08-22`. A303.v1 no longer progresses, but the four original reviews and
their mixed Decision Quality result remain preserved; retirement does not
rewrite a reviewer judgment into an Outcome conclusion.
