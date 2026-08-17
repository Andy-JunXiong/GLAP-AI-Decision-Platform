# Decision Quality Evaluation v1

**Rubric:** `decision-quality-rubric.v1`
**Review submissions:** `decision-quality-review.v1` (absolute-score tooling)
and `decision-quality-comparative-review.v1` (story-mode collection)
**Option content:** `decision-option-contract.v3`
**Current status:** public Sites v11 is the canary-verified story-v2 formal
entry across ten cases and 30 cutoffs. One invited reviewer completed a
server-saved 30-package submission with all three attestations on 2026-08-17;
the superseded story-v1 draft remains isolated and ineligible. The governed
three-review minimum is not met, so Decision Quality remains `NOT_EVALUATED`.
The multi-reviewer account extension is deployed with separate hosted secrets
and pseudonymous persistence scopes; Dylan's second account passed a zero-write
login/isolation canary and its credentials were delivered privately.

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
that story-v1 draft is preserved but ineligible. Public Sites v10 now presents
ten plain-language, three-moment stories. Distinct
source plans remain anonymous A/B choices, while true identical controls appear
once as a shared plan requiring explicit confirmation. It stores comparative
judgments under isolated collection `human-evaluation-story.v2`, aligned with
`decision-quality-comparative-review.v1`; preview-local answers, questionnaire
drafts, and story-v1 records are never migrated. Sites v11 passed a
non-submitting production canary before Dylan was notified. The live
database now contains one complete story-v2 submission: all 30 package digests
are present, all answers are final and committed, and the three reviewer
attestations are recorded. The earlier story-v1 draft still contains only three
ineligible answers and was not migrated. Dylan's account canary created no
session, attestation, answer, save, or submission. One submission is
insufficient for
the declared three-review interpretation gate, so Decision Quality remains
`NOT_EVALUATED`. Unit tests exercise packaging and scoring
mechanics with in-memory test reviews; those tests are not expert evidence and
are never written to the scenario corpus.

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
