# Bounded local comparison fingerprint re-verification v1

**Implementation status:** implemented and locally verified
**Deployment status:** not deployed

This private cockpit control lets an operator rerun fingerprint verification
against the same already-loaded comparison cohort only when the local failure
is plausibly transient.

## Retry eligibility contract

Exactly two reason codes are retryable:

- `CRYPTO_UNAVAILABLE`;
- `VERIFICATION_ERROR`.

`MISSING_INTEGRITY`, `CONTRACT_METADATA_MISMATCH`, `NON_CANONICAL_CONTENT`, and
`DIGEST_MISMATCH` are structural failures and never expose the retry control.
`MATCH` is already verified and is not retryable.

The helper requires `status=MISMATCH` in addition to a retryable reason. The
cockpit checks that helper again inside the click handler, so hiding or
synthetically invoking a button cannot bypass eligibility.

## Attempt and response boundary

Each cohort receives at most one local retry for the currently loaded
comparison response. The attempt count is React memory only. Starting a retry
removes the prior result, returns the card to the pending/hidden state, and
runs the same verifier against the same cohort object. A result is applied only
if the original comparison-view object is still current.

Refreshing Outcome Review may load a new response object and resets the local
attempt boundary. The retry control itself never calls refresh, `fetch`, the
Operations API, or any other network surface.

## Trust and authority boundary

Retry does not weaken verification: content remains withheld until a new
`MATCH`, and every new mismatch retains its diagnostic boundary. A retry is not
an approval, authenticity check, incident classification, business-validity
test, causal/statistical result, preferred-alternative selection, Action
recommendation, or Learning/model/policy/deployment/production decision.

This feature adds no API request, route, telemetry, persistence, browser
storage, identifier exposure, key, secret, certificate, mutation, table,
environment value, CloudFormation change, schedule, AWS call, public export,
or external write. Staging activation remains separately human-authorized
deployment work.
