# Private Generator execution receipt v1

Implemented and tested locally on 2026-09-22 Sydney time; undeployed. Source
delivery is recorded in Git history. This adds execution bookkeeping to the isolated staging Generator
and private Controller logs. It performs no additional AWS call and changes no
table, IAM policy, infrastructure template, deployment workflow, alias,
schedule, business rule, or public OPS/status contract.

## Purpose and placement

The [offline provenance validator](learning_evidence_provenance_contract.md)
needs invocation and writer evidence alongside before/after table snapshots.
Ordinary pipeline success was insufficient: the deployed source uses Athena
query IDs internally and does not retain them with Generator counts.

The local adapter now emits one final `generator-execution-receipt.v1` JSON
record to private Lambda stdout and attaches the same object as
`execution_receipt` to a successful private function response. It does not
write a separate receipt object to S3 or any table. Stdout emission is not
proof of CloudWatch delivery, immutable retention, or authenticated provenance.

The Controller supplies a fresh random `execution_link` only to its
`stateful_lifecycle_generation` stage. Private
`generator-controller-link.v1` REQUESTED and RETURNED log records correlate
the run/stage timestamps, link, and returned invocation ID. They never enter
the persisted/public run status or quality-check array. Other stage payloads
and the public aggregate contract are unchanged.

## Exact receipt fields

| Fields | Meaning and limit |
| --- | --- |
| `schema_version` | Fixed `generator-execution-receipt.v1` |
| `invocation_id`, `function_name`, `function_version` | Taken from Lambda context, never event identity fields; exact isolated staging function required |
| `controller_link`, `controller_link_trusted` | Optional exact `{link_id, run_started_at, stage_started_at}`; offset-aware ordered times, bounded random ID; trust is always false |
| `logical_date`, `temporal_context` | System-resolved `execution_mode`, `time_basis`, `as_of_date`, `scenario_id`; the existing Sydney temporal guard still runs before AWS access |
| `source_bundle_sha256` | Hash of a sorted compact JSON manifest of the four packaged source files and their raw-byte SHA-256 digests; adapter is named `lambda_function.py` in the manifest |
| `settings_sha256` | Hash of allowlisted resolved database, workgroup, output, table names, pipeline environment and future-simulation setting; no raw settings emitted |
| `request_parameters_sha256` | Hash of selected supplied seed/population/retry/threshold/policy arguments; omitted arguments are null, not inferred effective defaults |
| `started_at`, `finished_at`, `status`, `dry_run` | Offset-aware UTC receipt times; terminal `SUCCEEDED`, `DRY_RUN`, or `FAILED` |
| `generated_counts` | Outcome and proposal rows generated in memory; null if generation did not reach this point |
| `planned_write_statements`, `completed_write_statements` | Planned MERGEs and MERGEs for which Athena reported SUCCEEDED; plan is null until built |
| `queries` | Ordered bounded query records, described below |
| `complete` | True only for non-dry successful execution with all nine reads and every planned write acknowledged and fully processed |
| `runtime_verified`, `snapshot_lineage_verified`, `real_world_evidence` | Always false; receipt generation and local validation establish none of these |

The four source files are the existing adapter, lifecycle engine, temporal
boundary, and governed closed-loop module. This source-manifest digest is
neither a Git commit nor the deployed ZIP `CodeSha256`. The settings digest
does not cover the complete Lambda configuration. None is a digital signature.

Each query has exactly `sequence`, `purpose`, `query_id`, `statement_sha256`,
`started_at`, `finished_at`, `status`, `athena_state`, and `result_reused`.
The nine distinct read purposes are `READ_TARGETS`, `READ_ROUTES`, `READ_RATES`,
`READ_FX`, `READ_ACTIVE`, `READ_ALERTS`, `READ_ACTIONS`, `READ_OUTCOMES`, and
`READ_PROPOSALS`, followed by zero or more `WRITE_MERGE` entries. Statement
hashes cover the exact submitted SQL bytes. No SQL, entity row, raw exception,
ARN, or S3 path is included. Query and invocation IDs remain private.
`result_reused=null` means Athena did not supply a boolean, not no reuse.

Generated row counts are **not** inserted-row counts or net-new business-key
counts. A successful MERGE may match existing rows. An acquiring adapter must
separately reconcile snapshots and keys; it cannot copy these counters into
the offline validator as proof of new rows. Query success and hashes alone do
not prove freshness, exclusive writes, snapshot ancestry, or read consistency.

## Failure and compatibility behavior

- Bound execution to 256 total query records and 192 KiB final receipt JSON.
  Reject a plan exceeding the query budget before its first write.
- Invalid Lambda context, temporal input, non-boolean dry-run, malformed link,
  or unreadable source manifest fails before the first query. These early
  failures need not produce a receipt.
- A query failure or timeout emits an incomplete failed receipt and preserves
  the original exception. Existing timeout cancellation remains unchanged;
  the receipt feature adds no retry or cancellation call.
- If Athena acknowledges a MERGE but result retrieval then fails, retain that
  acknowledged write count while marking the query and receipt incomplete.
  Failure does not mean no data was written.
- A hard Lambda timeout/process termination can prevent the final log record.
  Missing delivery stays unverified; it does not authorize rerunning writes.
- If final log emission fails after successful business execution, the handler
  raises instead of returning a successful receipt. If emission fails while
  already handling an error, preserve that original error. Neither path rolls
  back writes or proves log delivery.
- A present malformed receipt fails the Controller stage as `invalid_response`.
  The Controller validates exact shape, counts, timestamps, link, query order,
  completion and false evidence flags, then logs `PRESENT_LOCALLY_VALIDATED`.
  It does not authenticate the record or compare source hashes to a release.
- An older Generator returning no receipt remains compatible and is explicitly
  logged as `UNAVAILABLE_LEGACY`. Pipeline success never implies receipt
  availability. A newer Generator invoked by an older Controller can emit an
  unlinked receipt; the old Controller will not preserve its private summary.

## Release and acquisition boundary

The current deployed artifact remains the independently checked `a10678b`
release. The new code has not been deployed or invoked. Its future release
would change source bytes, so the offline tools' fixed full source commit
must not be silently advanced to accept it. A separate reviewed release must
bind the new commit, package digest, four-file manifest and configuration.

The [private reader/correlation adapter](generator_receipt_reader.md) is now
implemented locally, with a plan-only default and a bounded two-log-group
FilterLogEvents/GetQueryExecution path. It has not run against AWS. It joins
logs and referenced query metadata, while snapshot/writer attribution and
net-new-key reconciliation remain absent. The
[release-binding validator](generator_release_binding.md) is now implemented
locally for Git/ZIP byte equality, receipt digests and supplied configuration
records. This adds no authenticated release or continuity claim. Next is a
release-evidence acquisition handoff for artifact/configuration capture.
The reader uses existing AWS access and adds no permissions. Collection,
Athena queries, deployment and continuation retain their separate authority;
no fresh run is justified merely to create receipts, and no historical proposal
is changed.

## Local verification

Mocked tests cover actual handler/query/Controller flow, source hashing,
spoofed event identity, public-status isolation, partial writes, result-fetch
failure, timeout, record bounds, logging failure, legacy absence and malformed
receipt rejection. No test contacts AWS.

```powershell
py -3.13 -m unittest discover -s tests -p test_generator_execution_receipt.py -v
```
