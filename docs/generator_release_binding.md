# Generator release-binding validator v1

Implemented locally on 2026-09-22 Sydney time. No deployment, AWS read,
invocation, artifact download or new runtime observation occurred in this
slice. The private receipt producer remains undeployed. This is byte comparison
and supplied-record consistency, not an authenticated release acceptance.

## What is checked

`ops/validate_generator_release_binding.py` joins the
[reader's private bundle](generator_receipt_reader.md) with an explicit source
commit, supplied deployment ZIP bytes and two supplied Lambda configuration
records. It reads only the four fixed source blobs from the local Git object
database and never substitutes the uncommitted worktree for a commit.

| Comparison | Required result |
| --- | --- |
| Git to ZIP | Exactly four root-level packaged Python files, byte-for-byte equal to the named commit |
| Producer availability | Matched adapter source declares the v1 receipt schema and producer functions; legacy source is rejected |
| ZIP to expectation | Actual ZIP SHA-256 equals the independently supplied hexadecimal artifact expectation |
| ZIP to Lambda records | Each supplied `CodeSha256`, decoded from base64, equals the actual ZIP SHA-256 bytes |
| Source to receipt | Sorted compact JSON four-file manifest digest equals `source_bundle_sha256` |
| Configuration to expectation | Both selected configuration projections hash to the supplied configuration expectation |
| Settings to receipt | Recomputed ordered settings digest equals `settings_sha256` |
| Request to receipt | Exact selected request-parameter digest equals `request_parameters_sha256` |
| Time/revision | Before/after captures bracket the Controller run and Generator execution, share one revision and last-modified time, and have equal configuration projections |
| Reader bundle | Strictly revalidate its receipt, query identity/hash/purpose bindings, count and query windows |

Producer function/schema presence is a static compatibility check only. The
validator does not execute or import package code and does not prove its behavior.
The local Git object identity also does not authenticate human review, a pushed
branch, CI results, commit signing or deployment authorization.

## Input contract

Input is private JSON on stdin, at most 4 MiB, with exactly:

- `schema_version=generator-release-binding-input.v1`;
- `input_kind`: `SYNTHETIC_FIXTURE` or `SUPPLIED_STAGING_EXPORT`;
- `expectation`: `source_commit` (full 40-character lowercase Git ID),
  `artifact_sha256`, `configuration_sha256`, `request_parameters`;
- `artifact_zip_base64`: actual ZIP bytes, base64 encoded;
- `reader_config` and `private_bundle`: unchanged structures from the receipt reader;
- `configuration_before`, `configuration_after`: each contains `captured_at`
  and a supplied `configuration` response object.

The expectation is a separate input to compare, not a signature or approval
record. No user-supplied `approved=true` or authentication flag is accepted.
Fabricated but coherent records cannot be detected as authentic by this tool.

The seven selected request fields are `seed_population`, `population_size`,
`new_count`, `seed_version`, `retry_failed_run`, `minimum_policy_outcomes`, and
`policy_version`. Omitted original values must be represented as null; the
validator never inserts effective defaults. An explicit Learning threshold is
limited to the existing 20-Outcome scope. Logical date, identity and temporal
mode are checked independently through the reader contract.

ZIP input is capped at 2 MiB, each source at 1 MiB. Extra/missing/duplicate or
nested members, directories, symlinks, encrypted entries, unsupported
compression and comments fail closed. Files are read with CRC checking into
memory and are never extracted, imported or executed. Line endings are compared
exactly. Git receives fixed argument lists without a shell, with replacement
objects and lazy fetching disabled and inherited Git overrides removed. No
checkout, hook, commit, fetch, push or repository write is performed.
The two object-read controls follow the documented
[Git environment behavior](https://git-scm.com/docs/git#_environment_variables).

## Configuration boundary

The configuration projection covers function name/version, runtime, handler,
memory, timeout, package type, architecture, execution-role ARN, complete
allowlisted environment map and an empty layer list. It enforces the current
isolated staging function, Python 3.14, 512 MiB, 900 seconds, ZIP package and
handler contract. The role must retain the fixed staging role name. This checks
its binding only; it does not inspect the role's policies or permissions.

Environment keys are confined to the current Generator template's fields.
Fixed staging tables and shared dimension defaults preserve the producer's
settings-hash ordering. The source database and reader workgroup must agree;
private output location and all explicit environment values are included in
the projection hash. Missing optional table variables use the producer's known
defaults only when recomputing its settings hash. Unknown fields, a production
table/environment, or a layer prevents acceptance.

This projection is deliberately **not the full Lambda configuration**. VPC,
logging, tracing, KMS, tags, resource policy, concurrency, runtime patch version,
IAM policy contents and other non-projected service fields are not verified.
Their absence from the hash must not be presented as unchanged infrastructure.
The projection hash is also distinct from the receipt's narrower settings hash.

Both supplied responses must be Active/Successful, have the expected function
version and code digest, and contain an unchanged revision and last-modified
time. Captures must be no later than now, on the logical Sydney date, within a
two-hour span, and surround the execution. Late or stale observations cannot
stand in for the missing pre-run record. Even equal before/after records cannot
prove that mutable `$LATEST` was unchanged between them; that claim stays false.

## Output and invocation

The CLI has no options and accepts only private stdin. It performs local Git
reads and prints an aggregate report, with no commit, digest, identifier, role,
environment value, path, SQL, source bytes or ZIP bytes in the output.

```powershell
py -3.13 ops/validate_generator_release_binding.py
```

Supply the private JSON stream through the calling process; the validator does
not open an input path or write any artifact. Malformed JSON, duplicate keys,
oversized input, source absence and disagreement return `UNVERIFIED` (exit 2),
fixed reason codes and no partial-positive checks. Only full local agreement
returns `RELEASE_BINDING_RECORDS_CONSISTENT` (exit 0) with eight consistency
checks, four source files, two configuration observations and bounded query count.

Every report retains false values for runtime verification, AWS receipt
authentication, human-review authentication, authenticated release binding,
mutable-revision continuity, snapshot lineage, net-new rows, real-world evidence
and all operational authority. No output is wired into policy activation,
production readiness, public OPS status, or the fixed-source Learning validators.

## Remaining work

The [release-evidence acquisition handoff](generator_release_evidence_acquisition_handoff.md)
now defines the exact pre-run/post-run configuration and artifact read scope,
independent source/configuration expectations and stop conditions needed to feed
this validator. Its bounded two-phase artifact/configuration reader is now
implemented and locally tested, but has not executed against AWS. It composes
this validator without changing its schema or evidence claims. The
[private composition flow](generator_evidence_collection.md) is now implemented
and locally tested, with no live collection. The
[snapshot/writer attribution design](snapshot_writer_attribution_design.md) is
prepared and its [offline metadata normalizer](snapshot_metadata_normalizer.md)
and [bounded metadata reader](snapshot_metadata_reader.md) are locally implemented,
without live collection. The [offline source-bound query-target projection](generator_query_targets.md)
now composes this validator with supplied SQL and a reviewed adapter recipe.
Private receipt/target composition before SQL discard is next recommended.
The existing receipt reader already handles logs/query metadata; it does not
download packages or capture Lambda configuration, and this validator adds no
AWS client. The handoff must preserve the fact that a missing historical
pre-run record cannot be recreated afterward.

New source commit, push, release, configuration collection and any independently
justified lifecycle continuation retain separate authority. Nothing here
authorizes a new run to manufacture receipts or advances the offline comparator
past its fixed prior source. Snapshot/writer attribution and before/after
business-row reconciliation also remain unresolved. Historical Learning stays
failed closed at its last observed 2/20 state.

The service-field meanings come from the official
[Lambda GetFunctionConfiguration reference](https://docs.aws.amazon.com/lambda/latest/api/API_GetFunctionConfiguration.html).
This documents how supplied fields are interpreted; it is not evidence of a
new AWS observation.

## Local verification

CI packages and asserts all four release-owned Generator files. A regression
check requires its copy list, ZIP members and inventory assertion to match the
release-binding manifest; CI does not deploy this package.

Tests compose the real mocked producer and reader, compare exact ZIP/source
bytes, and exercise artifact/configuration/revision/request mismatches, stale
or future captures, unsafe archives, legacy-source claims, Git call isolation,
private-output protection and fixed authority boundaries. Positive tests use
explicit synthetic committed-source fixtures; they do not establish a new
source review or deployment merely because the implementation is committed.

```powershell
py -3.13 -m unittest discover -s tests -p test_generator_release_binding.py -v
```
