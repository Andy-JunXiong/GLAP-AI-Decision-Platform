# Private Generator release-evidence composition v1

Implemented locally on 2026-09-23 Sydney time. Status:
`IMPLEMENTED_LOCAL_COMPOSITION_NOT_EXECUTED`. No live AWS collection, deployment,
lifecycle continuation or source-pin change occurred. The receipt producer and
Controller extension remain undeployed. Learning retains the last observed
failed-closed 2/20 result; no historical anomaly is resolved here.

## Purpose and entry conditions

`ops/collect_generator_release_evidence.py` connects the
[two-phase package/configuration reader](generator_release_evidence_acquisition_handoff.md)
to the existing [receipt reader](generator_receipt_reader.md) and
[offline release-binding validator](generator_release_binding.md). Callers no
longer need to pass a manually assembled receipt bundle between them. The
private bundle exists only inside `finish`; only a bounded aggregate report is
returned. No independent evidence is synthesized.

Actual use still requires named-human read authority covering the union of the
two readers' scope. Producer and Controller deployment and an independently
justified operational continuation remain separately authorized prerequisites.
There is no invocation argument, callback or automatic continuation. A successful
pre-capture result grants no permission to run the business operation.

## Two-phase callable flow

1. Before the external run, call `start_collection(config)`. Config is exactly
   the existing `generator-release-acquisition-config.v1` object: fixed region,
   current Sydney logical date, exact function version and independent release
   expectations. It reads the committed sources, package and pre-run configuration
   using the existing acquisition reader. It returns an aggregate report plus a
   private `EvidenceCollectionSession` only if pre-capture succeeds.
2. The independently authorized external run occurs outside this code. The
   caller obtains its actual invocation identity and a completed bounded log
   window. No run is initiated, waited for, polled, retried or invented here.
3. Call `session.finish(reader_config)`. The existing strict receipt-reader
   configuration supplies the target invocation and window. Before SDK setup or
   any log access, its date, version, database, workgroup and all three digests
   must agree with the frozen package/configuration/request evidence. Expected
   digests are derived from the pre-run evidence, never copied from returned logs.
   The receipt window must begin at or after pre-capture and end no later than
   the current clock, on the same Sydney day and within the two-hour bound.
4. The existing reader fetches and correlates Generator and Controller records
   and metadata for only the referenced query IDs. The composition checks the
   capture date/window before and after each log/metadata call. Missing,
   ambiguous, inaccessible, expired or inconsistent records stop the attempt
   before any further read; there is no application retry.
5. A complete private bundle feeds the acquisition session's post-run capture
   and the existing binding validator. Both captures still must bracket the
   recorded run and retain matching configuration revisions. Any mismatch
   withholds the complete set of positive checks.

The handle is consumed at the start of `finish` and closed on every outcome.
Repeated or reentrant finish calls cannot read again. `discard()` abandons the
handle without receipt or post-configuration reads. Abandoning the process loses
the pre-run evidence: it cannot be resumed from a file or reconstructed later.
Releasing references is not a secure memory-erasure guarantee.

The callable dependency-injection arguments exist for trusted in-process testing
and integration only. They are not JSON fields or caller-selectable AWS targets.
Both injected receipt clients must be supplied together, or neither is supplied.
Default SDK clients use the existing credential chain, fixed region, one attempt,
5/10-second connect/read timeouts and no configured custom endpoint URLs.

## Read inventory and default CLI

| Operation | Maximum scope per handle |
| --- | --- |
| `lambda:GetFunction` | One exact staging Generator/version |
| Package HTTPS download | One regional S3 response location, at most 2 MiB, 30-second deadline |
| `lambda:GetFunctionConfiguration` | Two captures around the external run |
| `logs:FilterLogEvents` | Two fixed staging groups; each at most 20 pages, 200 events and 2 MiB |
| `athena:GetQueryExecution` | At most 256 receipt-referenced executions; no SQL submitted |

All scopes remain confined to the existing two-hour, actual-calendar Sydney
window. Per-call timeouts bound individual network waits; an in-flight request
may finish after the window expires, in which case its response is rejected and
no subsequent call is issued. No list/discovery API, result-row download, query
execution, IAM change, deployment, alias, schedule, Action or policy mutation is
available. Public OPS contracts and exports are unchanged.

```powershell
python ops/collect_generator_release_evidence.py
```

The CLI prints only `LOCAL_PLAN_ONLY`, does not read stdin, import the AWS SDK,
resolve credentials or start collection. All arguments, including `--read`,
are rejected with exit 2. Live use is callable-only and is not authorized by
running this plan.

## Results, privacy and evidence limits

`PRE_RUN_CAPTURE_READY` describes acquisition-stage availability only.
`RELEASE_BINDING_RECORDS_CONSISTENT` retains the offline validator's eight
consistency checks and bounded file/capture/query counts. `UNVERIFIED` exposes
no partial-positive checks. Pre-capture and binding failures retain existing
bounded reasons; composition errors use `COLLECTION_OR_CORRELATION_FAILED`.
`read_attempted` refers to the current start or finish operation, not earlier
phases. SDK setup failure before receipt reads leaves it false for finish.

No raw logs, SQL, digest, invocation identity, URL, role, environment value, ZIP
bytes, exception text or private bundle is returned or persisted by composition.
Record consistency still authenticates neither AWS records nor named-human
review. Mutable-version continuity, snapshot lineage, net-new keys, real-world
impact, runtime verification and every operational authority remain false.
The fixed-source Learning validators are unchanged. No output enters policy
activation, model promotion, readiness or public status.

## Verification and next boundary

Mocked end-to-end tests use the real producer, receipt reader, acquisition reader
and binding validator. They cover successful composition, scope/digest mismatch
before log access, missing/ambiguous/wrong-invocation records, Controller and
query disagreement, mid-read expiry, post-run drift, sanitized failures, input
copying, handle destruction, reentrancy and plan-only CLI behavior. The drift
audit protects the read inventory, bounds and absence of invocation/persistence
authority. These tests establish local behavior only.

The [snapshot/writer attribution design](snapshot_writer_attribution_design.md)
now identifies the missing query-target, commit, writer and complete-history
relationships. It also records the incompatibility between the legacy Learning
source pin and the new receipt producer. The [offline metadata normalizer](snapshot_metadata_normalizer.md)
and [bounded metadata reader](snapshot_metadata_reader.md) are now implemented
and locally tested without live collection. The [offline query-target projection](generator_query_targets.md)
now checks separately supplied SQL against full release evidence. Private
receipt/target composition before SQL discard is the next local recommendation. This
composition's aggregate result cannot supply private snapshot attribution.
No query execution, new collection, source-pin advancement or lifecycle run is
authorized by that recommendation.
