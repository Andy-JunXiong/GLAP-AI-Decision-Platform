# Decision Quality Evaluation v1

**Rubric:** `decision-quality-rubric.v1`
**Review submission:** `decision-quality-review.v1`
**Current status:** implemented locally; no expert reviews collected

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

The A303 fixture is controlled synthetic engineering evidence. The repository
contains no submitted expert reviews, so its Decision Quality layer remains
`NOT_EVALUATED`. Unit tests exercise scoring mechanics with in-memory test
reviews; those tests are not expert evidence and are never written to the
scenario corpus.

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
