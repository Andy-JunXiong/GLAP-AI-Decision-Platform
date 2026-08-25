# Private cockpit comparison fingerprint verifier v1

**Implementation status:** implemented and locally verified
**Deployment status:** not deployed

This browser-only verifier recomputes each displayed eligible Outcome cohort's
`outcome-cohort-comparison-fingerprint.v1` digest before the private cockpit
reveals any covered comparison metric or provenance field.

## Verification contract

The verifier requires the exact v1 metadata, covered-field order, SHA-256
algorithm, canonicalization identifier, and
`RESPONSE_CONTENT_INTEGRITY_ONLY` scope. Digital-signature,
source-authenticity, and business-validity fields must all remain false.

It then:

1. requires a positive safe-integer observed count;
2. rejects non-finite or greater-than-two-decimal percentage values;
3. normalizes signed zero and formats every percentage as a two-decimal string;
4. rejects non-ASCII canonical strings or unsupported JSON values;
5. sorts object keys recursively and emits compact UTF-8 JSON;
6. recomputes SHA-256 with browser Web Crypto; and
7. compares the lowercase hexadecimal result with the server digest.

The repository test uses a server-generated known digest. The unchanged
fixture verifies, while a changed effect percentage and an expanded
digital-signature claim both fail closed.

## Cockpit behavior

Comparison metrics and provenance remain hidden while verification is pending.
They appear only after `VERIFIED`. A missing integrity object or Web Crypto,
malformed values, metadata drift, authority-flag drift, canonicalization
failure, and digest mismatch all resolve to `MISMATCH`; the card withholds
covered content and asks the operator to refresh Outcome Review.

Each result now also carries one bounded, non-sensitive reason code for local
operator troubleshooting. No raw error or covered evidence is returned; see
[`outcome_cohort_comparison_diagnostics_v1.md`](outcome_cohort_comparison_diagnostics_v1.md).
Transient local failures may be retried once against the same loaded response
under
[`outcome_cohort_comparison_retry_v1.md`](outcome_cohort_comparison_retry_v1.md).

## Trust and authority boundary

Successful browser recomputation establishes response-content consistency
only. Because the digest is unsigned, a party able to alter both content and
digest can still recompute it. `VERIFIED` therefore proves neither server or
source authenticity nor business validity, causality, statistical
significance, realised value, preferred-alternative quality, Action
recommendation, model/policy readiness, deployment approval, or production
readiness.

The verifier uses the already-loaded authenticated response and browser-local
Web Crypto. It adds no API request, route, entity identifier, key, secret,
certificate, telemetry, persistence, mutation, table, environment value,
CloudFormation change, schedule, AWS call, public export, or external write.
Staging activation remains separately human-authorized deployment work.
