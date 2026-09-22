# Bounded snapshot metadata reader v1

Implemented and locally tested on 2026-09-23, Australia/Sydney. No live reads,
permission changes, deployment or business operation have occurred. This reader
implements the metadata-only scope in the [attribution design](snapshot_writer_attribution_design.md).
Its local test result does not refresh the last failed-closed Learning observation.

## Invocation and private lifetime

`python ops/read_snapshot_metadata.py` prints an aggregate `LOCAL_PLAN_ONLY`
report without loading the SDK, credentials, files or stdin. Any CLI argument,
including `--execute`, returns `UNVERIFIED` with exit 2. There is no live CLI.

Separately authorized code may call `start_capture(config)` to collect both
tables' before-opening observations, metadata and before-closing observations.
It returns an aggregate `BEFORE_CAPTURED_AFTER_PENDING` report and a private
in-memory `MetadataSession`. Both openings precede either closing. The caller
owns any independently authorized external business interval; this reader never
invokes it. `session.finish()` captures the after phase, calls the existing
[offline normalizer](snapshot_metadata_normalizer.md), and returns only its
aggregate structural status, counts and explicit gaps. It always discards the
private packet and response records. An explicit `discard()` abandons the before
capture locally; there is no cleanup API call. Handles are single-use and not
thread-safe. No private serializer, file writer or row-query callback is exposed.

The before capture is not a validation pass. Complete structural checks run
after both phases; no missing before evidence may be reconstructed afterward.
These metadata-only fences do not surround data-row SELECTs. Pinned-row capture
will require a separately reviewed integration and execution/storage authority.

## Exact config and bounds

The private `snapshot-metadata-acquisition-config.v1` object requires exactly
`schema_version`, `region`, `database`, `logical_date`, `catalog_id` and `tables`.
Region and database are fixed to the staging scope; table names come from the
existing two-table planner. `tables` requires exactly `outcomes` and `proposals`,
each containing only `metadata_prefix` and `bucket_owner`. Catalog and bucket
owners must be independently supplied 12-digit account bindings. Prefixes must
be nonoverlapping S3 directory prefixes, narrower than a bucket, ending in `/`.
Reject traversal, encoded/ambiguous paths and special S3 bucket types. Only exact
`.json` pointers under the appropriate prefix may be fetched. These config fields
bound a request; they neither establish IAM authority nor authorize collection.
Config is deep-copied before use. Tests may inject both clients and a clock;
injecting only one client is rejected before SDK creation.

| Resource | Hard limit |
| --- | --- |
| Glue GetTable | 8 total: two tables, two fences, two phases |
| S3 GetObject | 64 attempts total; 32 distinct metadata objects/table |
| UTF-8 metadata bytes | 1 MiB/object, 32 MiB total; no truncation |
| Metadata format / snapshot projection | Explicit v2; 100 snapshots/table through the normalizer |
| Collection window | Current Sydney date only, at most 7,200 seconds |
| SDK transport | One send per operation; 5-second connect / 10-second read timeout |

Each GetTable request includes the supplied catalog binding and exact fixed table.
Validate the returned catalog, database, table, external Iceberg type and absence
of a resource link before following `metadata_location`. Each GetObject includes
the independently supplied expected bucket owner. Follow only roots and retained
`metadata-log` pointers. Never list buckets/keys, fetch manifests/data/delete files,
execute SQL, discover audit logs, write, delete, invoke Lambda or change permissions.

Use the existing credential chain only on callable use. SDK configuration ignores
custom configured endpoints, selects regional standard HTTPS endpoints, and disables
retries. Before-call/before-send guards reject other SDK operations (including
redirect-related HeadBucket), a second wire send and nonregional endpoints. No
fallback or automatic scope widening follows a failure. Every request and stream
chunk is bounded by the current date and monotonic wall-clock observations; expiry,
clock reversal, partial content, encoding, JSON, scope or structural failure rejects
the capture with no partial counts. Streams close on failure as well as success.

## Evidence and privacy

Raw bytes are hashed with SHA-256. Actual request times, object locations, Glue
table version, S3 version and ETag remain private in memory until discard. ETag
is not treated as a digest or signature. Missing versions remain absent; even a
returned version is not automatically promoted to authenticated immutable proof.
Each location is fetched once and reused; the reader does not detect a later
overwrite at that same key. `CACHED_OBJECT_LOCATIONS_NOT_REVALIDATED` and
`IMMUTABLE_OBJECT_IDENTITY_NOT_GUARANTEED` remain visible in every report.

`METADATA_STRUCTURES_CONSISTENT_WITH_GAPS` means only the acquired projection
passes the existing structural checks. Runtime, complete-history, writer,
snapshot-attribution, net-new-row, real-world and authority flags stay false.
Source authenticity, query target, commit binding, writer exclusivity, missing
pinned rows and the legacy-source/new-receipt incompatibility remain explicit.
No source pin or provenance-validator input is changed. Reports and exception
handling expose no identifiers, paths, raw metadata or service error messages.
Private process inspection and SDK debug logging are outside this output contract;
do not enable private payload logging during an authorized collection.

## Verification and next recommendation

Synthetic fixtures exercise two-phase ordering, exact service scope, owner binding,
retained history/cycles, caching, expiry, limits, truncation, encoding, failures,
body closure, false authority, one-use handles, SDK send guards and plan-only CLI.
The drift gate protects the inventory, limits and evidence boundary. No AWS
collection or operational evidence is implied by these tests.

A local transport check with installed Boto3/Botocore 1.40.26, synthetic credentials
and a replaced HTTP sender also verified that a configured endpoint is ignored
and a synthetic S3 region redirect stops before a second send. No network was used.

The [offline source-bound query-target projection](generator_query_targets.md) is
now locally implemented: it recognizes the exact receipt-producing MERGE shape
and retains the target table with the same SQL hash. This connects separately
supplied query records to the fixed table names inspected here; it does not bind
a table UUID or prove query-to-snapshot causality, writer exclusivity or
compatibility with the fixed legacy source pin. Private composition with the
receipt reader before SQL discard is the next recommended local feature.
Live reads, pinned-row execution and source migration remain separately governed.

Technical references: [Glue GetTable](https://docs.aws.amazon.com/glue/latest/webapi/API_GetTable.html),
[S3 GetObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html),
[SDK configuration](https://docs.aws.amazon.com/botocore/latest/reference/config.html),
[SDK event hooks](https://docs.aws.amazon.com/boto3/latest/guide/events.html).
