# Outcome cohort comparison envelope runtime validator v1

**Implementation status:** implemented and locally verified

**Deployment status:** not deployed

This private-cockpit boundary validates the top-level descriptive comparison
response before React or the per-cohort fingerprint verifier can iterate it.
It closes the structural gap between an untrusted JSON response and the typed
client contract.

## Accepted envelope

The validator accepts an exposed comparison view only when all of these are
true:

- schema is exactly `outcome-cohort-descriptive-comparison.v1`;
- status is `AVAILABLE` or `INSUFFICIENT_ELIGIBLE_COHORTS`;
- the required eligible-cohort count is exactly two;
- eligible and excluded counts are non-negative safe integers whose sum equals
  the parent summary cohort count;
- the comparison scope remains `DESCRIPTIVE_SYNTHETIC_ONLY`;
- `cohorts` is an array and every member has non-empty Decision Brief and
  selected-alternative keys plus a non-negative safe observed count;
- all five governance flags remain exactly false.

For `AVAILABLE`, at least two eligible cohorts must exist and the array length
must equal the eligible count. For `INSUFFICIENT_ELIGIBLE_COHORTS`, the eligible
count must be below two and the array must be empty.

An older API response may omit the whole cohort summary or comparison view.
That remains a supported partial-data state. A present but malformed summary or
comparison envelope throws one fixed safe error, so the existing Operations
error state withholds the complete Outcome view.

## Relationship to fingerprint verification

This validator establishes only that the container is safe to iterate and that
its status, counts, and governance shape reconcile. It does not validate the
covered metrics or provenance inside a cohort. The existing browser fingerprint
verifier remains responsible for each cohort and continues to hide those fields
until its digest matches.

## Trust and authority boundary

The validator is a local structural consistency check. It does not authenticate
the server or source, prove business validity, estimate causality or value,
rank alternatives, recommend or mutate an Action, or authorize Outcome,
Learning, model, policy, deployment, or production work.

It adds no endpoint, request, retry, telemetry, persistence, browser storage,
identifier exposure, key, secret, certificate, table, migration, infrastructure
change, AWS call, public export, or external write. Staging use remains
separately human-authorized deployment work.
