# Learning cardinality offline evidence comparison v1

Status: `IMPLEMENTED_LOCAL_ONLY_RUNTIME_UNVERIFIED`, Sydney `2026-09-22`.
The offline comparator is executable locally. It grants no AWS query, lifecycle continuation, deployment,
proposal mutation, policy activation, or production authority.

## Established evidence

The isolated Generator artifact and configuration passed 16 independent checks
against `a10678b`. Local regression tests cover repeated historical versions,
20 distinct latest closed Outcomes, latest pending exclusion, and future or
same-date conflicting versions. These do not establish post-release business
behavior. The last observed eligible count is 2/20, not a fresh count, and at
least one unexpected unactivated proposal remains immutable audit evidence.

## Why the previous canary cannot serve as a generic repair test

`ops/reconcile_observed_outcome_learning_staging.ps1` preserves the original
single-candidate, baseline-1, increase-by-1, below-20 and zero-proposal checks.
Its failed zero-proposal result must remain intact. A forward fix does not
remove an existing proposal. Re-running this script or changing its baseline
cannot distinguish a historical anomaly from a newly generated proposal.
Do not weaken its checks or delete historical evidence to obtain a pass.

Despite its read-only business SQL, this script starts an Athena query, which
creates an S3 result object, and can stop a timed-out query. The earlier
control-plane read authorization does not cover those actions.

## Implemented local capability

`ops/compare_learning_cardinality_evidence.py` compares supplied before/after
evidence entirely in memory and emits only aggregate results. It makes no AWS
call and writes no file. The [collection preparation module](learning_evidence_collection_design.md)
now plans pinned queries and validates supplied pages offline. Live collection
and external verification of the supplied assertions remain unimplemented. The comparator reports three dimensions:

| Dimension | Local comparison | Claim boundary |
| --- | --- | --- |
| Release identity | Supplied bindings agree on the fixed source commit and artifact/configuration digests | Consistency only; neither freshness nor authenticity is established |
| New behavior | Latest logical Outcome counts and exact new proposal set across the supplied window | Below 20 eligible Outcomes, no new proposal; supplied path assertions do not prove execution |
| Historical anomaly | Exact preservation of previously observed proposal content and zero activation | An unchanged old anomaly remains unresolved and cannot become a global PASS |

Net proposal counts alone are insufficient: insertion and removal could cancel
out. This comparator uses exact identity/content comparison in memory. A future
collector needs separately approved private evidence acquisition and storage. Public/repository
results must contain only bounded counts, booleans and approved provenance.
Do not retain entity identifiers, raw rows or private digests in repository
reports. If exact continuity cannot be established, return unverified.

## Preconditions for a later runtime observation

1. A named human supplies an independently justified staging operational task
   and exact date scope. Dates must be on or before the then-current Sydney
   date. Do not auto-fill the gap since 28 August, seed Outcomes, or advance
   dates merely to manufacture Learning evidence.
2. Review and validate the separately implemented collection method against the
   local comparator contract.
   Bind before/after observations to the same temporal scope and source version;
   reject conflicting versions, incomplete evidence, concurrent unrelated writes,
   configuration drift, or ambiguous proposal provenance.
3. Obtain explicit bounded authority for each external action: protected
   baseline collection (including Athena result creation if used), operational
   continuation, and post-run reconciliation. Define artifact retention and any
   cancellation/cleanup separately. No authority carries over from this plan.
4. Capture a fresh baseline; do not use the historical 2/20 as today's measured
   count. If the run no longer exercises the below-20 case, stop this validation
   rather than redefining the threshold or authorizing policy progression.
5. After the independently justified run, verify generator-path execution and
   compare exact evidence. Report behavior evidence separately from the existing
   failed-closed historical result. No retry, additional dates, proposal rewrite,
   or policy activation follows a failure without a new human decision.

## Current disposition

The comparator is implemented and locally tested. No runtime collection command
is ready: business purpose, date scope, acquisition authority and a trusted
collection method remain missing. Pinned-query planning and supplied-page decoding are now implemented locally.
The [provenance/continuity receipt validator](learning_evidence_provenance_contract.md)
now composes supplied page, snapshot and invocation evidence offline. Live
provenance remains unverified. The
[Generator execution-receipt producer](generator_execution_receipt.md) and
private Controller linkage are now implemented locally and undeployed. The
[private reader/correlation adapter](generator_receipt_reader.md) is implemented
but unexecuted; its bounded reads do not execute the pinned SELECT collection.
The [release-binding validator](generator_release_binding.md) is implemented
locally without authenticating a release; artifact/configuration acquisition
planning is next. Generated counts require independent
key/snapshot reconciliation, and a
future release needs a reviewed source binding without silently changing the
comparator's fixed source pin.
Production readiness, model readiness and policy progression remain unchanged.

References: [governed loop](governed_closed_loop.md),
[original canary](action_complete_outcome_canary.md),
[temporal rules](temporal_truthfulness.md).

## Input contract and use

The CLI reads a single UTF-8 JSON object from standard input, up to 8 MiB. It
accepts no path or output option. Pass protected evidence through a private
local input channel; do not paste raw evidence into tracked files or logs.
No real staging export was collected or consumed during implementation.

The top-level object has exactly these fields:

| Field | Value |
| --- | --- |
| `schema_version` | `learning-cardinality-comparison-input.v1` |
| `input_kind` | `SYNTHETIC_FIXTURE` or `SUPPLIED_STAGING_EXPORT`; neither grants authenticity |
| `before`, `after` | Snapshot objects described below |
| `run` | Supplied execution assertions described below |

Each snapshot has exactly `captured_at`, `cutoff_date`, `complete`, `release`,
`outcomes`, and `proposals`. `complete` must be the boolean true, not a string
or number. Both row arrays are limited to 10,000 rows. Snapshots must have the
same cutoff. Each Outcome row contains exactly all `OUTCOME_COLUMNS`; each
proposal contains exactly all `POLICY_PROPOSAL_COLUMNS` from the persistence
adapter. The regression suite checks those column sets without importing AWS.
This is an exact full-row comparison, not a digest of a selected projection.
JSON nulls must remain null; identifiers and version strings must be non-empty.
No credentials or infrastructure locators belong in these row objects.

`run` has exactly `started_at`, `finished_at`, `logical_date`, `release`,
`generator_path_completed`, and `exclusive_window`. The final two fields must
be boolean true. They are supplied assertions, not trusted attestations.
`release` in all three objects has exactly `source_commit`, `artifact_sha256`,
and `configuration_sha256`. The commit is fixed to
`a10678bc324f62731a021b33d9919f39fcba7731`; digest strings are lower-case 64-digit
SHA-256 hex values, compared only in memory. All three bindings must agree.
A future collector must define the configuration canonicalization and establish
all bindings externally; arbitrary matching digests are not proof of a release.

Timestamps need explicit UTC offsets. The strict ordering is before capture,
run start, run finish, after capture, then no later than the system clock.
All four must fall on the same Sydney date, equal to the logical date and both
cutoffs. Sydney today is system-derived; callers cannot override it. Rows must
be operational, actual-calendar, scenario-null and within the cutoff. Closed
Outcomes must have a finite effect and an observed date between the due date
and row version date. Pending Outcomes must have null observed date/effect;
a future due date alone is permitted as a pending calendar gate.

Latest selection occurs before closed-state counting. Conflicting versions of
any Outcome/date fail closed regardless of input order; identical repeats are
collapsed. Earlier Outcome versions must remain unchanged in the after history.
Duplicate proposal IDs fail closed. Approved status or any approval/effective
field is treated as activation. The minimum is fixed at 20 and cannot be supplied
or lowered. If either snapshot reaches 20, this below-threshold comparison is
out of scope; it does not authorize a new proposal or promotion.

## Output contract

The report schema is `learning-cardinality-comparison-report.v1`, with fixed
`evidence_class=OFFLINE_INPUT_CONSISTENCY_ONLY`. It returns fixed reason codes,
bounded counts, a historical-proposal state, and all-false authority. Input
identifiers, raw rows, digests, timestamps and error text are never echoed.
`runtime_verified`, `historical_anomaly_resolved`, and `real_world_evidence`
remain false for every result, including supplied staging exports.

| Status | Exit code | Meaning |
| --- | --- | --- |
| `CONSISTENT_WITH_BELOW_THRESHOLD_RULE` | 0 | Complete supplied assertions agree with the bounded rule; not a runtime PASS |
| `VIOLATION_IN_SUPPLIED_EVIDENCE` | 1 | New below-threshold proposal, missing/changed history, or activation appears in otherwise valid inputs |
| `UNVERIFIED` | 2 | Invalid, incomplete, ambiguous, future, unbound or out-of-scope inputs |

An unchanged historical proposal yields `PRESERVED_REVIEW_STILL_REQUIRED`; it
cannot disappear from the conclusion or be declared resolved by this tool.
Malformed evidence is validated before business comparison, so an `UNVERIFIED`
report does not certify the absence of a violation.

Run local regression fixtures with:

```powershell
py -3.13 -m unittest discover -s tests -p test_learning_cardinality_comparison.py -v
```

Run the CLI only with a separately acquired private stdin stream:

```text
python ops/compare_learning_cardinality_evidence.py < private-input.json
```

The last line uses shell input-redirection notation; the referenced input is
not supplied or created by this feature. It does not authorize collection.
