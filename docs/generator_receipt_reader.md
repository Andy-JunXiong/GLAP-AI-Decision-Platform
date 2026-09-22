# Private Generator receipt reader v1

Implemented and tested locally on 2026-09-22 Sydney time. No live read,
deployment or lifecycle continuation has been performed by this reader.
The [receipt producer and Controller extension](generator_execution_receipt.md)
remain undeployed, so the previously verified Generator release must not be
described as supplying this new receipt format.

## What it does

`ops/read_generator_execution_receipt.py` reads a bounded private log window,
requires exactly one target Generator receipt and its two Controller link
records, and compares every referenced query with Athena execution metadata.
It checks query IDs, exact SQL-byte hashes, database/workgroup, success,
non-reuse and query timing. It issues no SQL and reads no result rows.

This is a callable reader with a plan-first CLI, rather than another component
requiring user-supplied page exports. It uses the existing AWS SDK credential
chain when explicitly run; no credential setup, new role or permission is
implemented. Missing access produces a fixed failure code, not an access grant.

## Exact scope and bounds

| Item | Contract |
| --- | --- |
| Calls | Only `logs:FilterLogEvents` and `athena:GetQueryExecution` |
| Log targets | The two fixed isolated staging Generator/Controller function groups; no discovery or arbitrary group argument |
| Region/database | Fixed existing region and lifecycle source database; workgroup must match the private supplied expectation |
| Target | One supplied UUID invocation ID, expected function version and three receipt digests |
| Window | Offset-aware, positive, at most two hours, entirely on the supplied Sydney logical date and ending no later than now |
| Calendar | Actual-calendar only; no future scenario, cross-day run or backdated execution is accepted by this v1 reader |
| Log pagination | At most 20 pages, 200 returned events and 2 MiB of message bytes per group, including repeated delivery |
| Query metadata | At most 256 reads, drawn exclusively from the validated target receipt |
| Retry/polling | No application retry or wait; CLI SDK uses one total attempt, 5-second connect and 10-second read timeout |
| Output/retention | CLI prints aggregates and fixed reason codes only; raw logs/SQL are transient in process memory; no file/artifact upload or cleanup operation |

The metadata API returns the submitted SQL, which may contain private synthetic
entity values. It is hashed in memory and omitted from both the public summary
and the callable private bundle. Log streams, storage locations and raw errors
are also omitted. Existing AWS logging/retention settings are not changed.

## Input and invocation

With no arguments, the CLI returns only a redacted `LOCAL_PLAN_ONLY` call
inventory and limits, without importing the AWS SDK or resolving credentials:

```powershell
py -3.13 ops/read_generator_execution_receipt.py
```

The sole executing option is `--read`, with private JSON supplied on stdin.
This document is not authorization to execute it. There is no query, invoke,
deploy, output-file or retry option. Input must have exactly these fields:

- `schema_version=generator-receipt-reader-config.v1`, `region`;
- `logical_date`, `invocation_id`, `function_version`;
- `window_start`, `window_end`, `database`, `workgroup`;
- `source_bundle_sha256`, `settings_sha256`, `request_parameters_sha256`.

The three expected digests are independently supplied expectations, not values
copied from the received log. Equality does not establish who supplied them or
bind them to a Git commit, deployment ZIP or complete Lambda configuration.
This version intentionally does not alter any existing offline source pin.

## Correlation and failure handling

The Generator filter selects the receipt schema and target invocation. Once
the receipt passes strict validation, the Controller filter selects its schema
and exact link ID. All pages must finish before correlation succeeds. Empty
intermediate pages are followed; absent final tokens terminate pagination.
Repeated/cyclic tokens, limit exhaustion and inaccessible records return
`UNVERIFIED` without guessing or retrying.

Exact duplicate delivery of the same service event is deduplicated. Conflicting
content under one event ID, two distinct target receipt events, missing link
records, different Controller streams, malformed JSON, duplicate object keys,
inconsistent counters or event ordering all prevent a conclusion. Plain JSON
and the exact standard four-field Lambda application-log envelope are accepted;
other formats fail closed. A wrapper's invocation ID must agree where present.

Only complete non-dry successful receipts with all nine reads and matching
acknowledged writes advance to query metadata checks. Reuse must explicitly
be false in both the receipt and Athena response. SQL hashes, query identity,
scope and successful status must match. Service submission/completion times
must fit the recorded query window at millisecond precision. Unknown metadata
or clock disagreement remains unverified; no timestamp is invented.

`read_and_correlate` returns a private in-memory bundle containing the validated
receipt and bounded query bindings. It must not be printed or persisted to
public status. `collect_receipts` and the CLI return only:

- `RECEIPT_QUERY_RECORDS_CONSISTENT` (exit 0): returned records agree;
- `UNVERIFIED` (exit 2): missing, ambiguous, failed or conflicting evidence.

The default plan exits 0 without any read. All reports keep runtime verification,
receipt authentication, release binding, snapshot lineage, net-new-row proof,
real-world evidence and operational authority false. API response consistency
does not prove log authorship, exclusive execution or correct business results.
There is no automatic adapter into the Learning comparator: generated counts
cannot be substituted for independently reconciled net-new keys.

## Remaining work

The [release-binding validator](generator_release_binding.md) is now implemented
locally. This reader's private bundle supplies the invocation and query side;
the validator compares four Git blobs with ZIP bytes and matches receipt hashes
against supplied configuration/request evidence. It rejects legacy source and
changed or unbracketed configuration records, but authenticates no release or
human review. Next is a release-evidence acquisition handoff for the exact
artifact/configuration read scope and pre/post-run capture timing.

Snapshot/writer attribution and before/after row acquisition remain separate
gaps. No AWS API in this reader establishes which Iceberg snapshot a query
committed. The fixed-source offline validators remain unchanged. Any future
producer release, collection or independently justified lifecycle continuation
needs its own existing human-authority scope; no run should be manufactured
merely to supply a receipt, and the historical 2/20 result is preserved.

## Technical basis and verification

Pagination follows the documented empty-page and token behavior of
[CloudWatch FilterLogEvents](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_FilterLogEvents.html).
Per-query comparison uses the SQL, scope, status, timestamps and reuse fields
returned by [Athena GetQueryExecution](https://docs.aws.amazon.com/athena/latest/APIReference/API_GetQueryExecution.html).
The optional log wrapper follows the standard fields described in
[Lambda log formats](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs-logformat.html).
These references describe APIs, not evidence that this reader has run on AWS.

Tests generate receipts through the real producer with mocked execution,
validate the real Controller summary, and then exercise the reader against
synthetic service responses. They include successful correlation, pagination,
duplicate/conflicting records, scope/time/digest drift, partial or missing
receipts, SQL/metadata mismatch, privacy, sanitized failures and both CLI modes.

```powershell
py -3.13 -m unittest discover -s tests -p test_generator_receipt_reader.py -v
```
