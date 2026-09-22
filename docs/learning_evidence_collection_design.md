# Learning evidence collection preparation v1

Sydney checkpoint: `2026-09-22`.
Status: `IMPLEMENTED_OFFLINE_PREPARATION_NO_EXECUTOR`.

The local module `ops/prepare_learning_evidence_collection.py` prepares pinned
staging data queries and validates supplied query/page receipts. It has no AWS
client, credential lookup, execution option, file writer, workflow or IAM change.
No live query or data collection was performed. All logistics inputs remain
synthetic; local validation does not establish runtime evidence or authority.

## Implemented behavior

- Default invocation prints only a fixed redacted plan; it does not read stdin.
- `render_queries` returns two private SELECT strings in memory, for the fixed
  staging Outcome and policy-proposal tables. Each uses one supplied Iceberg
  snapshot ID and all comparator-required columns, cast to VARCHAR for explicit
  type conversion. There is no table override, DDL, DML, query limit or date-gap
  continuation. The sole filter is `temporal_scope_id = 'OPERATIONAL'`.
- Future/inconsistent dates or temporal labels inside that scope are retained
  for rejection by the comparator; SQL must not silently filter them away.
- `assemble_snapshot` checks exact query bindings, successful engine-v3 execution
  assertions, no result reuse, distinct query IDs, ordered page-token chains,
  column order/types, first-page header, row widths, nulls, typed finite values,
  and complete pagination. It constructs a private comparator-shaped snapshot
  only after both tables and the existing row validator succeed.
- The CLI exposes only aggregate plan/validation reports. Private SQL, database,
  snapshot IDs, query IDs, page tokens, digests and rows are never printed.
  Unknown arguments, including `--execute`, fail with a fixed safe reason code.

These are checks on supplied assertions, not independent authentication of AWS
responses. `complete=true` on the private candidate means the supplied page
chain is complete for the declared SELECT. It does not mean the snapshot IDs
were verified, that there was an atomic cross-table read, or that a run was
exclusive. The tool never fills `generator_path_completed` or `exclusive_window`
for the comparator and never clears its runtime-unverified evidence boundary.

## Local interfaces

```powershell
py -3.13 ops/prepare_learning_evidence_collection.py
py -3.13 -m unittest discover -s tests -p test_learning_evidence_collection.py -v
```

`--validate-pages` reads one private JSON packet from stdin and returns an
aggregate report. Exit 0 means the supplied pages passed local checks; exit 2
means `UNVERIFIED`. Neither grants collection or operational authority.

The packet has exactly `schema_version=learning-evidence-result-pages.v1`,
`config`, `captured_at`, `release`, and `queries`. `release` uses the fixed
source and digest contract in the [offline comparator](learning_cardinality_post_release_validation_plan.md).
`captured_at` must be offset-aware, no later than the system clock, and fall on
the declared logical Sydney date. Callers cannot supply today's date override.

`config` has exactly:

| Field | Local constraint |
| --- | --- |
| `schema_version` | `learning-evidence-collection-plan.v1` |
| `phase` | `BEFORE` or `AFTER`; a label, not proof of collection order |
| `logical_date` | ISO date on or before system-derived Sydney today |
| `database` | One identifier, at most 128 characters; external staging binding remains required |
| `outcome_snapshot_id`, `proposal_snapshot_id` | Non-zero positive decimal strings within signed bigint range; private and not externally verified here |

`queries` has exactly `outcomes` and `proposals`. Each contains:

- `execution`: exactly `query_id`, `query`, `state=SUCCEEDED`,
  `engine_version=Athena engine version 3`, and boolean `result_reused=false`.
  The SQL must match the fixed planner byte for byte. These are projected
  receipts for a future adapter, not a claim that supplied JSON came from AWS.
- `pages`: an ordered array of `{query_id, request_token, response}` receipts.
  The first request token is null. Every subsequent token matches the preceding
  response's `NextToken`. Repeated tokens, missing final pages and extra pages
  after completion fail closed. Each response carries the Athena `ResultSet`
  shape, with optional `NextToken`, `ResponseMetadata` and zero `UpdateCount`.
  The first row of the first page is the exact header. Nullable cells are empty
  objects, not empty strings. Integers, doubles and booleans are explicitly
  decoded; all resulting rows pass the comparator's full schema validation.

The bounded limits are 16 MiB per CLI packet, 32 pages per query, 1,000 rows
per page and 10,000 data rows per table. Exceeding a limit rejects the packet;
no truncation, aggregate substitution or automatic widening is permitted.
The two-query count is **data queries per phase**, not a total AWS call budget:
the bounded metadata reader is locally implemented but unexecuted, and integrated
row-query fences and complete provenance acquisition remain unavailable.

## Remaining collection design gates

1. Establish independent business purpose, a named human owner and one exact
   date scope. Do not fill the gap since August or manufacture Learning rows.
2. Bind private database/workgroup/result location to the intended isolated
   staging resources. Fix the protected result location, retention, encryption,
   access scope, query budget, timeout and cancellation procedure before any
   execution proposal. No IAM or configuration change is supplied by this tool.
3. Acquire the two snapshot IDs through a separately reviewed metadata path.
   Check table identity, lineage, snapshot commit times, schema and availability.
   Expired/missing snapshots must stop, never fall back to current unpinned data.
4. Establish a quiet collection window and account for all intervening writers.
   Iceberg snapshots are per table; a pair of IDs does not establish an atomic
   transaction across Outcome and proposal tables. If concurrent writes or
   incomplete provenance prevent attribution, leave the comparison unverified.
5. Bind the actual generator invocation, source/artifact/configuration and
   logical date to the intended workflow window. The existing adapter returns
   aggregate `policy_proposal_rows_created` and `dry_run` fields; source presence
   of those fields is not a verified invocation trace. Do not infer execution
   from zero new proposals, a successful unrelated workflow, or matching hashes.
6. Only after local adapter validation and separate authorization, capture all
   pages in protected memory, finish the baseline before the authorized run,
   and capture after-state afterward. The comparator requires the four times
   to be ordered on the same Sydney date. Cross-midnight work is out of scope.
7. Pass exact rows to the comparator; retain only bounded aggregate evidence in
   repository reports. Private persistence, result cleanup and cancellation
   each need an explicit reviewed scope. No automatic delete or retry is added.

The [provenance/continuity receipt validator](learning_evidence_provenance_contract.md)
is now implemented locally for supplied snapshot lineages, collection fences
and invocation receipts. It checks relationships only; live acquisition and
authentication for gates 3-5 remain unresolved. The
[private Generator execution-receipt producer](generator_execution_receipt.md)
and Controller correlation are implemented locally but undeployed. The
[private reader/correlation adapter](generator_receipt_reader.md) is implemented
but unexecuted: it reads bounded logs and existing query metadata only. The
[release-binding validator](generator_release_binding.md) now checks local
Git/ZIP bytes and supplied receipt/configuration consistency. Artifact and
configuration acquisition and private reader composition are now implemented
locally but unexecuted. The [snapshot/writer attribution design](snapshot_writer_attribution_design.md)
defines proposed metadata-only scope and the missing query/commit/writer links;
its [offline metadata normalizer](snapshot_metadata_normalizer.md) is now locally
implemented, together with the [bounded metadata reader](snapshot_metadata_reader.md),
without live collection. The [offline source-bound query-target projection](generator_query_targets.md)
now checks supplied SQL and full release records; private receipt/target composition
before SQL discard is next recommended. Generated
counts still need snapshot/key reconciliation, and the fixed legacy source pin
remains incompatible with the new receipt-producing source until separately
reviewed migration. The pin is unchanged.
An executor remains unavailable in this module. Existing failed-closed Learning evidence and the immutable proposal
remain intact; no policy progression or production readiness follows from this
preparation.

## Technical basis

Athena engine v3 supports per-table snapshot-ID queries with `FOR VERSION AS OF`.
This fixes the version read from that table, not a cross-table transaction.
See [AWS version-travel documentation](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg-time-travel-and-version-travel-queries.html).

Athena returns continuation tokens for truncated result pages, and reading query
results also requires access to the S3 result location. See
[AWS GetQueryResults](https://docs.aws.amazon.com/athena/latest/APIReference/API_GetQueryResults.html).
The supplied execution receipt must indicate no reused result, following
[AWS ResultReuseInformation](https://docs.aws.amazon.com/athena/latest/APIReference/API_ResultReuseInformation.html).
Running an Athena SELECT creates protected result artifacts; data-read semantics
do not make query execution part of the earlier control-plane-only approval.

References: [governed loop](governed_closed_loop.md),
[temporal truthfulness](temporal_truthfulness.md),
[original canary](action_complete_outcome_canary.md).
