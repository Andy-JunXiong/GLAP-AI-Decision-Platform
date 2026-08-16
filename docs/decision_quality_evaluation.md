# Decision Quality Evaluation v1

**Rubric:** `decision-quality-rubric.v1`
**Review submission:** `decision-quality-review.v1`
**Option content:** `decision-option-contract.v3`
**Current status:** public Sites v7 still serves formal v3 plus the separate
non-submitting preview; a validated release candidate makes the Human
Evaluation address the authenticated, submitting 30-package formal v3 entry;
no eligible expert reviews collected

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

The weighted score is normalized to 0--100. A score difference alone is not
sufficient: the v1 interpretation gate requires at least three complete,
independent reviews, at least two non-tie preferences, at least 66.67% non-tie
preference consensus, no declared conflict, and a five-point aggregate score
difference before reporting that review evidence favours an option.

These thresholds are evaluation policy, not statistical proof. They should be
revisited before a larger study and must not be tuned after seeing which option
maps to a GLAP capability.

## Review submission boundary

[`decision_quality_review_v1.schema.json`](decision_quality_review_v1.schema.json)
requires:

- a pseudonymous reviewer reference rather than a name or email;
- the exact review-package digest and rubric version;
- independence, no-conflict, and no-blind-key attestations;
- one complete dimension score set for every blind option;
- one blinded preference (`OPTION_A`, `OPTION_B`, or `TIE`);
- reviewer confidence from 1 to 5.

The local aggregator fails closed on duplicate reviewers, incomplete or
out-of-range scores, package/key mismatches, changed rubric dimensions, or
attestation failures. It stores no identity claim and performs no network or
operational write.

## Objective metrics

Later versions may attach point-in-time objective measures such as decision
latency, evidence coverage, policy violations, tool-call count, hallucination
flags, and cost-estimate error. Each metric needs its own denominator, source,
cutoff, missing-value rule, and evidence class. Missing metrics must remain
missing; they cannot be replaced by an expert score or treated as zero.

## Current evidence boundary

The A303 fixture is controlled synthetic engineering evidence. The frozen v3
Historical Replay bundle is hybrid replay evidence with controlled synthetic
enterprise state. Public Sites v7 serves the formal v3 bundle and a separate
five-case, 15-moment Human Evaluation experience preview. After a separate
human decision, the release candidate now routes
`/pilot/human-evaluation` through the same authenticated formal v3 client as the
root route. It requires all 30 packages, the three eligibility attestations,
server-side save/resume, and immutable final submission. The former preview is
development-only, and its browser-local answers are never migrated into a
`decision-quality-review.v1` submission. The release candidate is validated;
public Sites release and canary remain pending.
Neither preserved v1/v2 draft progress nor unit-test reviews are eligible
expert evidence, so Decision Quality remains
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
