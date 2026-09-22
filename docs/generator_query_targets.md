# Offline source-bound query target projection v1

Implemented and locally tested on 2026-09-23, Australia/Sydney. No live query
metadata, AWS collection, SQL execution, release, source-pin migration or business
operation is performed. This supplies the local query-to-table projection in the
[snapshot/writer attribution design](snapshot_writer_attribution_design.md).

## Inputs and use

`python ops/project_generator_query_targets.py` prints `LOCAL_PLAN_ONLY` without
reading stdin, Git or credentials. `--project` reads a private JSON packet from
stdin and prints only aggregate results. Other arguments fail closed. There is
no AWS SDK, network, query executor, artifact writer or supplied-source execution.
The optional `source_reader` callable is for trusted local composition/tests;
the default uses the release validator's bounded local Git blob reader.

The exact `generator-query-target-input.v1` packet contains:

- `schema_version`;
- `release_binding`: the complete existing [release-binding input](generator_release_binding.md),
  including independently supplied source/artifact/configuration expectations,
  private receipt/query bundle, ZIP and before/after configuration observations;
- `write_statements`: exactly one `{query_id, sql}` record for every acknowledged
  `WRITE_MERGE` query, with no read queries, duplicates, extra writes or guessed
  target/snapshot fields.

The current [receipt reader](generator_receipt_reader.md) discards raw SQL and
does not yet supply this packet. This module consumes separately supplied SQL;
it does not reacquire SQL, infer missing text from hashes or turn an aggregate
composition report into a private release record. A live capture integration
remains a separate local feature and its eventual use needs separate authority.

| Resource | Bound |
| --- | --- |
| CLI input | 24 MiB |
| Nested release input | Existing 4 MiB limit and bounded Git/ZIP validation |
| SQL text | 512 KiB/query, 16 MiB combined |
| Queries | Existing 256-query receipt ceiling; supplied SQL covers writes only |
| MERGE batch | 1–100 literal rows, exact source column count |
| Target inventory | Nine fixed staging families; other seven are accounted for |

## Source and full-statement checks

First compose the existing release validator: exact committed Git/ZIP bytes,
four-file receipt digest, independent expectations, scoped unchanged configuration,
request digest and bounded actual-calendar receipt/query timing must agree.
Read source files once; do not substitute the current worktree for the requested
commit. Local source injection in tests is explicitly synthetic evidence.

An additional reviewed adapter SHA-256 fixes the supported source recipe. Only
this recipe check normalizes CRLF to LF; release byte equality does not. Even a
comment change requires explicit recipe review. Static Python AST inspection
extracts the nine table defaults, columns, key columns and retry-update policy
from these checked bytes. No packaged or supplied Python is imported or executed.
The recipe digest is not a new Learning source pin or a release-authentication claim.

Match every SQL text's exact UTF-8 SHA-256 to the same query ID in the validated
receipt and bound-query records. Recognize the whole generated MERGE: database,
target, alias, VALUES literals, columns, key join, allowed matched-update clause
and complete insert clause. Reject comments/extra statements outside literals,
expressions, unsupported quoting, altered joins, unknown targets, malformed or
non-finite literals, missing columns and unexpected trailing content. Quoted
strings may contain SQL-like text, escaped apostrophes, Unicode or newlines as
data. Typed dates/timestamps receive syntax checks; numeric literals must match
the producer's canonical rendering. This is a narrow recognizer, not a general
SQL parser or proof of row-level business/temporal correctness.

Retry updates must match the already bound `retry_failed_run` request. Actions
and policy proposals remain insert-only even in retry mode. Table order and
intermediate 100-row batch boundaries must match the checked source, but targets
are recognized from SQL rather than inferred from query position. Input statement
list order is irrelevant; query IDs supply the joins. No-op writes and zero-write
receipts are allowed without manufacturing snapshot changes or new rows.

## Outputs and evidence limits

`project_private` returns an in-memory `generator-query-target-private.v1`
projection with source commit/bundle digest, invocation/date, and each query's
ID, exact SQL hash, database/table, family, batch size and matched-update flag.
It omits SQL, literal values, snapshot IDs, commit times and writer assertions.
Batch size counts submitted VALUES rows only; it is never an inserted-key count.
This private callable raises on incomplete input; callers must not log its input
or private result. The safe `project` wrapper and CLI discard the private result
and return only `write_queries`, `outcomes_queries`, `proposals_queries` and
`other_queries`, plus fixed statuses and gap codes.

`SOURCE_QUERY_TARGETS_CONSISTENT_WITH_GAPS` (exit 0) means local supplied records
and source shapes agree. `UNVERIFIED` (exit 2) has no partial counts or raw error.
Runtime, release authentication, writer attribution, complete history, snapshot
lineage, net-new rows, real-world evidence and all authority flags remain false.
An SQL target is not a table UUID or a committed snapshot binding. The other seven
families are classified without claiming their snapshots were inspected. All
logistics values remain synthetic. Missing historical captures are not recreated.

The fixed legacy Learning source remains incompatible with the receipt-producing
adapter. Its pin is unchanged; passing this projection does not resolve that gate.
The metadata reader's cached-object/history limitations also remain unchanged.

## Verification and next recommendation

Synthetic tests use SQL emitted by the existing generator and matching release/
receipt fixtures, then exercise nine-family coverage, retry/insert-only behavior,
batching, quoted payloads, altered SQL and hashes, missing/duplicate statements,
source/ZIP/config drift, limits, dates, private output and CLI redaction. The drift
gate also checks the reviewed recipe, offline call/import boundary and false claims.

The next recommended local feature is private composition with the receipt
reader: project each transient SQL before it is discarded, and bind the collected
set to the same release expectations and receipt at finish. This would supply the
offline projection without separately prepared SQL inputs. It must preserve the
existing read inventory, limits, aggregate output and distinct old/new schemas;
query-to-commit proof, live-read authority and source migration remain separate.
