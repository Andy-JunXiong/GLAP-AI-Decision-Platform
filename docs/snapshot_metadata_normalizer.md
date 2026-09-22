# Offline snapshot metadata normalizer v1

Implemented locally on 2026-09-23 Sydney time.
Status: `IMPLEMENTED_OFFLINE_METADATA_NORMALIZER_RUNTIME_UNVERIFIED`.
No AWS read, query, file acquisition, deployment or source-pin change occurred.

`ops/normalize_snapshot_metadata.py` implements the local normalization step in
the [snapshot/writer attribution design](snapshot_writer_attribution_design.md).
It checks supplied catalog observations and selected Iceberg v2 metadata fields.
It is a bounded structural projection, not a complete Iceberg conformance checker,
AWS authenticator, data-row comparator or writer-attribution validator.

## Input and limits

The JSON packet has exactly:

| Field | Requirement |
| --- | --- |
| `schema_version` | `snapshot-metadata-input.v1` |
| `input_kind` | `SYNTHETIC_FIXTURE` or `SUPPLIED_STAGING_EXPORT`; neither authenticates input |
| `logical_date` | On or before the system-derived Sydney date |
| `region`, `database` | Fixed existing staging scope |
| `tables` | Exactly `outcomes` and `proposals`, using the existing collection planner's two table names |

Each table has exactly `metadata_objects` and `observations`. Each metadata
object has exactly `location` and `metadata_json`. The latter is the original
UTF-8 JSON text, not an already-projected metadata dict, so byte hashes and
duplicate-key checks remain meaningful. Locations are private S3-format strings
used only as in-memory reference keys; none is dereferenced or authenticated.

Observations contain exactly `before_open`, `before_close`, `after_open`,
`after_close`. Each has `database`, `table`, `metadata_location`, `started_at`
and `finished_at`. These are supplied catalog-response projections, not raw
GetTable responses or an assertion that a collector ran. Each pointer must name
one supplied metadata object for that table. Extra wrapper fields are rejected.

Limits: 32 objects/table, 1 MiB/object, 32 MiB total metadata, 100 distinct
snapshots/table across supplied files, and a two-hour observation window. The CLI
wrapper is capped at 40 MiB including escaped metadata strings; the independent
32 MiB raw-metadata cap still applies. Oversized, truncated, duplicate-key,
non-finite or malformed inputs fail closed. No automatic limit widening occurs.

## Structural checks and deliberate restrictions

The supported projection requires non-empty format-v2 snapshots, a positive
current snapshot, explicit resolvable snapshot schema IDs and positive sequence
numbers. Empty tables, other formats, secondary branches/tags, missing referenced
metadata or unresolved snapshot parents after the baseline are rejected as
unsupported or incomplete evidence. Such rejection is not a claim that every
rejected packet represents an invalid Iceberg table.

- Match catalog/table scope, stable UUID and table location; reject shared
  metadata object locations or shared table storage between the two tables.
- Hash complete original metadata bytes. Hash the full resolved schema object
  using sorted-key, compact, non-ASCII-preserving UTF-8 JSON, retaining arrays
  and extension fields. Check supported nested struct/list/map shapes, unique
  field IDs, basic identifier references and supported primitive type syntax.
  This is not an exhaustive validation of identifier semantics, partition
  transforms, sort orders or arbitrary extension fields.
- Require consistent duplicate snapshot definitions across files, unique
  sequences, ordered parent relationships and one supported ancestry chain.
  The baseline's predecessor may be outside the supplied packet, but that
  never proves earlier history. All supplied snapshots must belong to the
  after head's ancestry; discarded, disconnected or branching nodes cannot
  be silently dropped.
- Validate a present main reference against the current head. Check supplied
  snapshot-log order and reject visible rollback/repeated-head transitions.
  Follow only supplied metadata-log references, rejecting gaps, cycles,
  reversed time or unrelated extra objects. Optional absent logs do not clear
  the complete-history gap.
- Require per-phase stable heads and schema digests. Both opening observations
  finish before either closing observation begins; both before observations
  close before the after phase opens. All observations fall on the logical
  Sydney date, no later than now. Metadata cannot postdate the observation;
  snapshot creation cannot postdate its containing metadata.

Snapshot `timestamp-ms` is preserved as `created_at`, never converted into
an independently observed catalog commit time. The metadata structures and
optional-history behavior are defined by the
[Iceberg specification](https://iceberg.apache.org/spec/).
The extra rejection rules above are this tool's conservative evidence scope.

## Results and interfaces

```powershell
python ops/normalize_snapshot_metadata.py
python ops/normalize_snapshot_metadata.py --normalize
```

With no arguments, the CLI prints `LOCAL_PLAN_ONLY` without reading stdin.
`--normalize` reads one bounded private packet from stdin and prints only an
aggregate report. All other arguments, including `--execute`, are rejected.

`normalize(packet)` returns an aggregate report. `normalize_private(packet)`
returns a private in-memory projection only after all checks pass, or raises
a bounded validation error. Its table projections retain UUID, storage bindings,
raw metadata hashes, schema digests, ancestry nodes and observation timestamps.
They contain no inferred writer ID, commit timestamp or row count. Never print
or persist that private projection to public status or repository artifacts.
The CLI never returns it.

`METADATA_STRUCTURES_CONSISTENT_WITH_GAPS` (exit 0) means only the selected
supplied structures are consistent. `UNVERIFIED` (exit 2) contains fixed reasons
and no counts or partial private projection. Every report retains visible gaps
for source authenticity, commit times, query targets, query-to-commit identity,
complete history, exclusive writers, pinned rows and the legacy-source/new-
receipt incompatibility. Every runtime, history, attribution, row-proof and
authority flag stays false. Raw summary writer hints are not projected as truth.

The normalizer does not call the existing provenance validator or construct its
`history_complete=true` / `writer_invocation_id` inputs. Missing evidence cannot
be supplied by guessed booleans. The Learning source pin and its observed 2/20
state remain unchanged. No business behavior conclusion follows from exit 0.

## Verification and next step

Synthetic fixtures exercise a complete two-table packet, unchanged heads,
structural and reference conflicts, schema resolution, absent/expired history,
visible rollback, bad dates, shared observation windows, limits, duplicate JSON,
CLI privacy and false authority. No live metadata is inspected.

The [bounded plan-first Glue/S3 metadata reader](snapshot_metadata_reader.md)
now supplies this exact packet privately under the acquisition design's limits.
It is locally tested and needs separate authority before live use. Writer attribution, data-row
acquisition and source-contract migration remain separate unresolved gates;
metadata acquisition alone cannot close them.
