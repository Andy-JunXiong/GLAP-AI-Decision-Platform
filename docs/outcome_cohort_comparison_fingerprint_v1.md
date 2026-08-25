# Comparison contract integrity fingerprint v1

**Implementation status:** implemented and locally verified
**Deployment status:** not deployed

This read-only contract gives every displayed eligible Outcome cohort a
deterministic SHA-256 fingerprint covering its descriptive comparison values
and aggregate-only provenance. A verifier can recompute the digest to detect a
content or contract mismatch.

## Canonical fingerprint contract

`outcome-cohort-comparison-fingerprint.v1` covers exactly:

- Decision Brief version and selected alternative;
- observed Outcome count;
- four result-state percentages;
- descriptive minimum, average, and maximum effect percentages;
- the complete `outcome-cohort-comparison-provenance.v1` object.

Before serialization, percentage values are normalized to fixed two-decimal
ASCII strings; signed zero is normalized to `0.00`. This matches the two-decimal
aggregate contract and prevents Python and browser number serializers from
producing different bytes for the same displayed value. The server then
serializes the normalized fields as JSON with sorted keys, compact separators,
ASCII escaping, and UTF-8 encoding before computing the lowercase hexadecimal
SHA-256 digest. The integrity object itself is excluded from its own digest.
Identical normalized inputs therefore produce the same 64-character digest,
while a change to any covered displayed value produces a different digest.

The private cockpit now recomputes the digest before revealing any covered
comparison values. It displays verified content, the algorithm, verification
scope, and full digest only after a match; otherwise the card fails closed. See
[`outcome_cohort_comparison_verifier_v1.md`](outcome_cohort_comparison_verifier_v1.md).

## Trust and authority boundary

The fingerprint supports `RESPONSE_CONTENT_INTEGRITY_ONLY`. It is not a digital
signature, MAC, timestamp authority, source-authenticity attestation, or proof
that the underlying business evidence is correct. A party able to alter both
content and digest can recompute it, so independent authenticity would require
a separately designed and approved signing boundary.

The contract keeps `digital_signature`, `source_authenticity_attested`, and
`business_validity_attested` false. A matching digest does not establish
causality, statistical significance, realised value, real logistics
performance, a preferred alternative, Action recommendation, Learning/model
readiness, policy authority, deployment approval, or production readiness.

This feature uses only the standard-library hash implementation inside the
existing response builder. It adds no query, route, key, secret, certificate,
table, environment value, CloudFormation change, mutation, schedule, AWS call,
public export, or external write. Staging activation still requires separate
migration and deployment authority.
