# Snapshot and writer attribution acquisition design v1

Prepared 2026-09-23, Australia/Sydney.
Status: `METADATA_READER_IMPLEMENTED_LIVE_ACQUISITION_PENDING`.
The machine-readable companion is [the design contract](snapshot_writer_attribution_design.json).
The [bounded metadata reader](snapshot_metadata_reader.md) is implemented locally;
no live collection, query executor, writer attestation, permission change or
runtime observation is added. Learning remains at its last failed-closed 2/20
observation; the unexpected immutable proposal remains unchanged.

## Decision

Use three separate evidence steps: normalize acquired table metadata, reconcile
complete pinned before/after rows, and substantiate writer ownership. Do not
turn query success or coincident timestamps into attribution. The current
[private composition](generator_evidence_collection.md) establishes local
release/receipt consistency only; it cannot populate all fields required by the
[provenance validator](learning_evidence_provenance_contract.md).

The [offline metadata normalizer](snapshot_metadata_normalizer.md) is now
implemented and locally tested with explicit unavailable fields. Live metadata acquisition, a writer-proof mechanism
and any source-pin migration remain separate work. A normalizer must not produce
a provenance-ready packet simply because its input JSON is internally coherent.

## Source findings and missing relationships

The adapter batches MERGEs in groups of at most 100 generated rows across nine
table families. `WRITE_MERGE` does not identify the target table in the receipt.
The receipt reader hashes the submitted SQL but drops it from the private bundle;
that bundle contains no table target or committed snapshot ID. The composition
returns only an aggregate report and closes its private state. It is therefore
not an existing machine-readable snapshot-attribution input.

| Required relationship | Available evidence | Missing evidence / design rule |
| --- | --- | --- |
| Invocation to query | Private Generator/Controller correlation, query ID, exact SQL hash, success and times | Still record consistency; no authentication claim |
| Query to table | SQL returned transiently by the existing metadata read; local [offline target projection](generator_query_targets.md) now checks separately supplied SQL against source/release/receipt records | Private reader composition before SQL discard remains unimplemented; the projection binds the whole MERGE shape and same SQL hash, never inferring target from list position |
| Query to committed snapshot | No such field in current bundles | Require independently substantiated engine/catalog commit correlation; timestamps alone are insufficient |
| Snapshot to invocation | Current provenance input expects `writer_invocation_id` | Do not fill it from the enclosing run unless the query-to-commit link is established |
| Complete history / no other writer | Current provenance input expects `history_complete=true` | Endpoint heads and an ancestor chain cannot justify this assertion; missing history stays unavailable |
| New business keys | Complete pinned rows can be compared locally | Must separately attribute changes; generated counters are not insertion evidence |

Iceberg metadata exposes table UUID, schemas, current snapshot, snapshot parent
links, sequence numbers and snapshot creation timestamps. Its optional metadata
and snapshot logs can lose old entries; current-head history can differ from
parent ancestry. The specification does not define a Lambda invocation identity
on each snapshot. These documented fields motivate the separate unavailable
relationships above; their presence cannot authenticate them.
[Iceberg specification](https://iceberg.apache.org/spec/)

Athena query statistics may include a manifest location for files written or
intended by a failed query. This is not a guaranteed snapshot or invocation
binding, and this design does not assume a manifest exists for every MERGE.
[Athena query statistics](https://docs.aws.amazon.com/athena/latest/APIReference/API_QueryExecutionStatistics.html)

## Metadata read scope — locally implemented, live use not authorized

Prefer a bounded Glue/S3 metadata path so the first metadata inspection need not
execute SQL. Scope it only to the two fixed tables in
`ops/prepare_learning_evidence_collection.py`, within the private staging
database and region already bound by the release evidence.

| Operation | Proposed bound | Purpose |
| --- | --- | --- |
| `glue:GetTable` | Eight calls: two tables, before/after phases, opening/closing observations | Capture the catalog binding and metadata pointer at each fence |
| `s3:GetObject` | At most 32 distinct metadata JSON objects per table, including roots; at most 64 GET attempts total | Inspect exact privately allowlisted metadata objects and referenced retained history |
| Metadata bytes | At most 1 MiB/object and 32 MiB total | Reject oversized or partial evidence; no truncation or cap widening |
| Snapshot projection | At most 100 nodes/table, matching the existing provenance limit | Reject gaps, conflicts, cycles and unsupported branches |

The object limits are enforced ceilings, not proof that 32 files cover history.
No S3 listing, arbitrary path, manifest/data/delete-file download, CloudTrail
discovery, SQL, IAM change, metadata write or cleanup is included. Follow only
exact metadata pointers under independently approved private bucket/prefix
bindings. Capture actual request start/end times and response object/version
identifiers in memory. Hash raw bytes; an ETag is not substituted for SHA-256 or
authenticity. If a version is unavailable, record that limitation rather than
inventing immutable object identity. Use one attempt and bounded timeouts; no
polling or automatic retry. Crossing the current Sydney date or the shared
two-hour collection window rejects the attempt.

Glue GetTable supplies the catalog table response; it is not a guarantee of
complete writer history. Athena also exposes `$history`, `$snapshots` and `$refs`
through SELECT, but that alternative would require separately scoped query
execution and protected result handling. It is excluded from this metadata-only
proposal. [Glue GetTable](https://docs.aws.amazon.com/glue/latest/webapi/API_GetTable.html),
[Athena metadata queries](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg-table-data.html)

## Offline normalizer boundary

The implemented local normalizer accepts supplied metadata JSON and catalog/fence
records, with a synthetic-versus-supplied input label and strict byte/object
limits. It has no SDK, network, file output, credentials or execute option.
Initially support explicit Iceberg format v2 only; reject other versions instead
of implying deployed format inspection occurred today.

Validate table UUID, exact catalog/table binding, metadata reference consistency,
positive bigint snapshot IDs, snapshot uniqueness, parent relationships, main
reference, relevant schema IDs and timestamp syntax. Preserve creation time as
`created_at`; never rename snapshot `timestamp-ms` to an independently observed
catalog `committed_at`. If a snapshot's schema cannot be resolved from its
supplied metadata context, leave it unavailable; do not assume today's schema.

Define a local schema digest over canonical UTF-8 JSON of the resolved full
Iceberg schema object: sorted object keys, compact separators, retained array
order and no non-finite values. That is a project comparison recipe, not an AWS
digest or signature. Unknown schema content must not be silently discarded.

Return only aggregate structural results and fixed gap codes. Private parsed
metadata may be passed in memory to a later reviewed adapter. Even a structurally
valid result must retain `history_complete=false`, `writer_binding_verified=false`
and no projected `writer_invocation_id`. It must not invoke the existing
provenance validator with guessed true flags or fabricated commit timestamps.

## Before/after collection order and row reconciliation

For each phase, observe opening metadata for both tables before either data
query; use those exact two snapshot IDs for the fixed planner's SELECTs. Finish
both query executions and all result pages before closing metadata for either
table, then record the actual phase capture time. Opening and closing heads,
UUIDs and resolved schema digests must agree per table. Before-phase capture
must precede Controller/Generator start; the after phase begins after completion.
All phase observations, queries and execution occur on the same actual Sydney
logical date. A historical baseline snapshot may be older, but its observation
cannot be backdated or recreated after the run.

The four data SELECTs (two per phase) remain a separate unimplemented executor
scope, with the existing 32-page/query, 10,000-row/table and packet-size limits.
Before any execution proposal, bind result storage, encryption, retention,
timeout/cancellation and cleanup authority. Metadata-only read permission does
not cover result creation, result downloads, cancellation or deletion.

Preserve all OPERATIONAL rows, including inconsistent dates for rejection; do
not filter away evidence to make the comparator pass. Compare complete contents
under `(outcome_id, dt)` and `proposal_id` after the fixed operational-scope
filter. Separately identify added, removed and changed keys. Existing proposals
must be unchanged and unactivated. Physical file or record counts cannot replace
these business-key comparisons. A successful insert-only MERGE may match existing
keys, and retry-mode Outcome updates must not be relabelled as new versions.

Every acknowledged query must be accounted for, including writes to the seven
other table families. Classify unrelated targets without claiming their snapshots
were inspected. Do not assume one write equals one new snapshot, nor one snapshot
equals one new row. No-op writes and empty proposal sets still require explicit
evidence, not inferred path completion.

## Writer attribution gate and source compatibility

A future writer-proof design must provide a supported causal binding from each
relevant acknowledged query to a catalog commit/snapshot, account for every
intervening writer and preserve rollback/branch/history evidence. An engine-
specific query marker is only a candidate until its semantics, availability and
integrity are independently established. Catalog audit evidence or an enforced
exclusive-writer mechanism would require its own design, coverage checks and
human authority; neither is assumed available. Absence of competing events in
an incomplete log is not proof of exclusive writes. No runtime authorizer or
writer-identity derivation is implemented in this design.

If the supported records cannot establish these relationships, the result is
`UNVERIFIED`, even when row comparison or release binding succeeds. An unchanged
head cannot conceal an unseen rollback; a filtered ancestor chain cannot discard
other writers. Do not set `history_complete=true` based on an optional retained
log or operator-entered assertion.

There is also a hard compatibility gap: the Learning comparator and provenance
validator are pinned to `a10678bc324f62731a021b33d9919f39fcba7731`, while release
binding rejects that legacy source for lacking the new receipt producer. A new
receipt-producing release cannot currently be composed into those fixed-source
validators. Preserve the pin. A separately reviewed source-contract migration,
regressions and release evidence are prerequisites, not a side effect of metadata
normalization. Do not mislabel a newer receipt as evidence for the old source.

## Acceptance cases and remaining implementation

Use supplied synthetic fixtures for: unchanged heads; one linear change; missing
parent; expired metadata; UUID/schema change; ambiguous schema context; hidden
rollback; another writer; absent query-to-snapshot binding; multiple MERGEs per
table; no-op/retry counts; identical snapshots with different rows; incomplete
pages; cross-date capture; and legacy-source/new-receipt mismatch. Missing proof
must remain a visible gap, never become a positive writer/history flag. No live
run or SQL is needed to validate the normalizer's local behavior.

No existing receipt or validator schema changes here. Private per-query target
collection integration, authenticated writer evidence, complete history acquisition, pinned
row execution and source compatibility all remain open gates. The accompanying
JSON records those gaps and all-false authority; it is a design inventory, not
an executable acquisition contract or evidence packet. The normalizer implements
the metadata-only acceptance subset with synthetic fixtures; row/receipt/writer
cases remain separate validators or unresolved acquisition gates. The bounded
plan-first Glue/S3 metadata reader now supplies that packet in memory with mocked
validation only. It caches each location once and retains explicit gaps for
unrevalidated keys and unavailable immutable object identity. Its metadata-only
phase fences do not surround data SELECTs; that integration remains unimplemented.
The [offline source-bound query-target projection](generator_query_targets.md) is
now locally implemented for separately supplied SQL and full release evidence,
retaining the exact SQL hash without claiming query-to-commit identity. The next
recommended local feature is private receipt/target composition before transient
SQL is discarded. Live use still requires separate read authority.
