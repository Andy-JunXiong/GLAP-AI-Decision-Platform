# Comparison fingerprint verification diagnostics v1

**Implementation status:** implemented and locally verified
**Deployment status:** not deployed

This private cockpit contract explains a fingerprint verification result with
exactly one bounded reason code while preserving the verifier's fail-closed
display gate.

## Reason-code contract

The verifier returns `status` plus one of:

- `MATCH` — the only code paired with `status=VERIFIED`;
- `MISSING_INTEGRITY` — the response omitted the required integrity object;
- `CONTRACT_METADATA_MISMATCH` — version, algorithm, canonicalization,
  covered-field order, digest shape, scope, or trust flags differ from v1;
- `CRYPTO_UNAVAILABLE` — browser Web Crypto is unavailable;
- `NON_CANONICAL_CONTENT` — a covered value fails the safe-integer,
  two-decimal, ASCII, or supported-JSON rules;
- `DIGEST_MISMATCH` — canonical recomputation completed but did not match;
- `VERIFICATION_ERROR` — browser hashing could not complete safely.

No raw exception, stack trace, canonical payload, covered metric, provenance
value, or computed digest is included in a diagnostic result. Every
non-`MATCH` reason retains `status=MISMATCH` and cannot reveal covered evidence.

## Cockpit behavior

The cockpit displays only the reason code and a fixed operator-safe explanation
for a mismatch. The corresponding comparison metrics and provenance remain
withheld. Pending verification still has no diagnostic code and keeps the same
content hidden.

The reason code is local troubleshooting context, not a security incident
classification or authenticity result. It is not sent to a server, stored, or
used to rank cohorts, select an alternative, recommend an Action, or change a
governed record.

Only `CRYPTO_UNAVAILABLE` and `VERIFICATION_ERROR` permit the bounded local
retry defined in
[`outcome_cohort_comparison_retry_v1.md`](outcome_cohort_comparison_retry_v1.md).
All structural reason codes remain non-retryable.

## Trust and authority boundary

`MATCH` remains unsigned response-content consistency only. No reason code
proves or disproves source authenticity, business validity, causality,
statistical significance, realised value, real logistics performance,
Learning/model readiness, policy authority, deployment approval, or production
readiness.

Diagnostics reuse the existing browser verification result and add no API
request, route, telemetry, persistence, identifier exposure, key, secret,
certificate, mutation, table, environment value, CloudFormation change,
schedule, AWS call, public export, or external write. Staging activation remains
separately human-authorized deployment work.
