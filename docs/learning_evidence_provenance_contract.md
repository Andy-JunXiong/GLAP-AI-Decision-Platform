# Learning evidence provenance receipt contract v1

Sydney checkpoint: `2026-09-22`.
Status: `IMPLEMENTED_OFFLINE_RECEIPT_VALIDATOR_RUNTIME_UNVERIFIED`.

`ops/validate_learning_evidence_provenance.py` joins the existing supplied-page
validator and full-row comparator with a bounded receipt relationship check.
It verifies only internal consistency of supplied evidence. It has no AWS
client, authentication verifier, executor, credential lookup or file output.
No deployed code, infrastructure or operational state changed in this slice.

## What is checked

- Exactly one successful non-dry invocation of the fixed isolated Generator is
  declared, with a source-bound release, logical date and ordered timestamps.
- Four distinct query IDs connect the two tables' before/after page packets to
  their collection windows. Both phases share the database, release and date.
- Each table retains its identity and schema. The selected heads are observed
  unchanged at opening and closing of each collection window. Both tables'
  opening observations precede either query; both closing observations follow
  both queries. Baseline capture precedes the run and after collection follows it.
- The supplied complete history begins at the before snapshot and ends at the
  after snapshot. Parent links cannot gap, branch or cycle. Every intermediate
  commit retains the table/schema, belongs to the declared invocation and falls
  inside its interval. Snapshot IDs cannot be reused to return different rows.
- Supplied Generator creation counts equal exact new proposal IDs and new
  `(outcome_id, dt)` keys. The original comparator still applies the fixed
  below-20 scope, history preservation and activation gates.

All query/fence times and both captures must be on the logical Sydney date.
The system clock provides today's boundary. Old queries cannot be relabelled
with a newer capture timestamp. Historical baseline commits may predate the day.
No assumption is made that matching endpoint heads prove no unseen rollback:
the complete history declaration is required, but remains unauthenticated.

## Input contract

One stdin JSON object, at most 32 MiB, has exactly:

| Field | Contract |
| --- | --- |
| `schema_version` | `learning-evidence-provenance-input.v1` |
| `input_kind` | `SYNTHETIC_FIXTURE` or `SUPPLIED_STAGING_EXPORT`; neither authenticates receipts |
| `before`, `after` | Existing [result-page packets](learning_evidence_collection_design.md); correct phase labels required |
| `run` | Exact invocation receipt below |
| `tables` | Exactly `outcomes` and `proposals`, each containing one table receipt |

The `run` fields are exactly:

- `run_id`, `invocation_id`, `function_name`;
- `logical_date`, `release`, `started_at`, `finished_at`, `status`, `dry_run`;
- `write_statements`, `outcome_rows_created`, `policy_proposal_rows_created`.
- `execution_mode`, `time_basis`, `scenario_id`, `as_of_date`.

Function identity is fixed to the isolated staging Generator. The run must
declare `SUCCEEDED`, boolean `dry_run=false`, at least one write statement and
non-negative integer counts no greater than the comparator's row bound. The
release uses the comparator's fixed `a10678b` source and matching private
artifact/configuration digests. The run-to-invocation association is supplied,
not independently proven; a future acquiring adapter must establish it.
Invocation scope must be `OPERATIONAL` / `ACTUAL_CALENDAR`, scenario-null, with
`as_of_date` equal to the single logical date. Newly inserted Outcome versions
and proposals must carry that date and as-of boundary; backdated new rows fail.

Each table receipt has exactly:

- `database`, `table`, `table_uuid_before`, `table_uuid_after`;
- `schema_sha256_before`, `schema_sha256_after`, `history_complete`;
- `snapshots`, `before`, `after`.

Database/table values must match the collection packets and fixed table names.
The two tables need distinct UUIDs; each UUID and schema digest is stable across
the window. `history_complete` must be boolean true. `snapshots` contains the
baseline plus all commits in the declared window, ordered as a single lineage,
with at most 100 entries. Do not provide only a filtered ancestor path that
hides other writers or discarded branches. Missing/expired history is unverified.

Each snapshot node has exactly `snapshot_id`, `parent_snapshot_id`,
`committed_at`, `writer_invocation_id`, `table_uuid`, and `schema_sha256`.
The baseline parent may be null or a predecessor outside the supplied window.
All later parents must equal the previous node, and every later writer must
equal the run's invocation. The baseline writer may be null. Numeric IDs are
positive bigint strings; private IDs and SHA-256 digests are never echoed.

The `before` and `after` table windows each have exactly `opened_at`,
`closed_at`, `head_at_open`, `head_at_close`, `query_started_at`,
`query_finished_at`, and `query_id`. Opening, query, closing and capture
ordering is validated, including shared coverage across both tables.

These are **projected receipt fields**, not a claim that Iceberg metadata
natively supplies an invocation ID, complete writer history or these fences.
The acquiring adapter must derive and substantiate the relationships. A missing
relationship must not be filled from a user-entered boolean or guessed timestamp.

## Composition and output

Only after receipt checks pass does the module construct a private comparator
candidate in memory. Its path/window flags signify consistency of the supplied
receipts for this offline calculation. Both outer and nested reports retain
`runtime_verified=false`. No input identifier, digest, SQL or timestamp is echoed.

| Status | Exit | Meaning |
| --- | --- | --- |
| `RECEIPTS_AND_COMPARISON_CONSISTENT` | 0 | The supplied receipt relationships and below-threshold data comparison agree |
| `RECEIPTS_CONSISTENT_COMPARISON_VIOLATION` | 1 | Receipt relationships agree, but the data comparison detects a violation |
| `UNVERIFIED` | 2 | Missing, conflicting, out-of-scope or unbound inputs prevent the combined conclusion |

Reports contain only fixed reason codes, bounded counts and the existing
aggregate comparison. AWS authentication, snapshot verification, actual
cross-table consistency, exclusive execution, Generator path verification,
historical anomaly resolution, real-world evidence and all operational authority
remain false for every result. A caller can fabricate a coherent packet; local
consistency does not turn it into trusted AWS evidence.

```powershell
py -3.13 -m unittest discover -s tests -p test_learning_evidence_provenance.py -v
```

The CLI accepts only private stdin. There are no execution or output-path flags.
Invalid arguments and malformed input return fixed aggregate errors.

## Source-grounded acquisition gap and next work

The deployed source inspected before this slice uses query IDs internally
without retaining them as a receipt with Generator counters. Existing runtime
logs were not inspected here. Generic successful workflow status therefore
cannot fill this contract.

The [private execution-receipt producer](generator_execution_receipt.md) and
Controller correlation are now implemented locally and undeployed.
They record runtime context identity, query IDs and statement hashes, generated
counts, acknowledged MERGEs and completion state in private logs/responses.
Public status remains aggregate-only; legacy absence is explicitly unavailable.
Generated counts are not net-new keys, source-manifest hashes are not release
commit/ZIP identities, and a structurally complete receipt is not authenticated.

The [private reader/correlation adapter](generator_receipt_reader.md) is now
implemented with bounded log/query-metadata reads and has not run against AWS.
It returns a private receipt/query bundle or an aggregate-only summary; it does
not build this validator's run input from generated counters. Snapshot/writer
acquisition, log authenticity and net-new-key reconciliation remain unresolved.
The [release-binding validator](generator_release_binding.md) now compares
Git/ZIP bytes, receipt hashes and supplied configuration records locally; this
does not authenticate release acceptance or runtime continuity. The
[artifact/configuration acquisition handoff](generator_release_evidence_acquisition_handoff.md)
now has a bounded two-phase reader, implemented and locally tested but not
executed against AWS. It does not supply this validator's snapshot/writer inputs.
The [private composition flow](generator_evidence_collection.md) now joins that
reader to receipt acquisition locally; no live collection or snapshot attribution
has occurred. The [snapshot/writer attribution design](snapshot_writer_attribution_design.md)
now maps these projected fields to obtainable metadata and unresolved proof.
Snapshot creation timestamps cannot simply become commit timestamps, and writer
IDs or complete-history flags must not be guessed. The [offline metadata normalizer](snapshot_metadata_normalizer.md)
is now locally implemented with those explicit gaps; it does not construct this
validator's provenance input. The [bounded metadata reader](snapshot_metadata_reader.md)
is also locally implemented and unexecuted. The [offline source-bound query-target projection](generator_query_targets.md)
now checks supplied SQL and release evidence without closing the query-to-commit
gate. Private receipt/target composition before SQL discard is next recommended.
This validator's pinned source
commit stays unchanged, and a missing historical pre-run record cannot be
recreated by a later read.

The pinned legacy source and new receipt producer are currently incompatible
across validators: the release-binding validator requires a producer absent from
the old pin. This is an explicit integration blocker, not permission to relabel
new release evidence or silently change the source contract.

No new lifecycle run is justified merely by implementing this validator. AWS
execution, deployment and operational continuation retain their separate
human-owned authority boundaries.
