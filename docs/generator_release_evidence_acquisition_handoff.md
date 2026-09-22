# Generator release-evidence acquisition handoff

Prepared on 2026-09-23 (Australia/Sydney). The accompanying two-phase reader is
`IMPLEMENTED_LOCAL_READER_NOT_EXECUTED`. This handoff is not release approval,
permission grant or evidence of an AWS read. The receipt producer and Controller
extension remain undeployed; the reader remains unexecuted. The last observed
Learning result remains failed closed at 2/20.

## Entry conditions and separate authority

The [release-binding validator](generator_release_binding.md) consumes the
[receipt reader](generator_receipt_reader.md)'s private bundle plus package and
configuration records. Before any collection, a named human must identify the
exact staging function/version, reviewed full source commit, independent artifact
and configuration expectations, permitted read window and acquisition scope.
Keep private values outside repository documents, CLI arguments and logs.

The proposed target is only the fixed Generator and region in
`ops/read_generator_execution_receipt.py`; no alias, arbitrary function or
production target is substituted. Use the existing credential chain only after
read authorization. Missing access is a stop, not permission to change IAM.

Deployment of the receipt-producing Generator and matching Controller correlation
is a separate prerequisite requiring separate approval. The independent Generator
release cannot deploy the Controller. Confirm both paths are available before
planning a receipt collection; do not expand the one-resource release boundary.
A lifecycle continuation needs its own independent operational purpose and human
authority. Neither this handoff nor a successful validator justifies a new run.

## Proposed exact acquisition scope

`ops/read_generator_release_evidence.py` implements the three package/configuration
operations below as a private callable. The existing receipt reader remains a
separate acquisition; the new reader accepts its supplied private bundle without
making log or query-metadata calls itself.

| Acquisition | Proposed maximum and target | Private result |
| --- | --- | --- |
| `lambda:GetFunction` | One call, exact Generator/version | Package location and response configuration for cross-checking |
| HTTPS package download | One GET to that response's temporary package location, no redirects or arbitrary URL input | At most 2 MiB of ZIP bytes in memory |
| `lambda:GetFunctionConfiguration` | Two calls to the same Generator/version: before and after the independently authorized execution | Two configuration objects and actual capture timestamps |
| Existing receipt reader | Only its two fixed log groups and receipt-referenced query IDs, within its existing limits | Validated private receipt/query bundle |

The artifact route uses the package returned by
[Lambda GetFunction](https://docs.aws.amazon.com/lambda/latest/api/API_GetFunction.html),
whose download link expires after ten minutes. Discard the link after use and
never print it. No S3 listing, separate S3 artifact discovery, CloudFormation,
IAM, alias inventory, SQL execution, result download or invocation is included.
Expiry, redirects, oversized content or a failed request stop this attempt;
there is no automatic retry or scope expansion. Proposed SDK limits follow the
reader: one total attempt, five-second connect and ten-second read timeout.

[GetFunctionConfiguration](https://docs.aws.amazon.com/lambda/latest/api/API_GetFunctionConfiguration.html)
supplies version-specific settings. Retain the fields consumed by the validator,
including `CodeSha256`, `RevisionId`, `LastModified`, `State` and
`LastUpdateStatus`, as well as its selected configuration projection. Capture
completion time from the collector's actual offset-aware clock; do not use
`LastModified` or an intended schedule as `captured_at`. Privately retain request
start/end times to detect uncertain ordering; do not add these fields to the
validator's strict input schema.

The reader separately caps each log group at 20 pages, 200 returned events and
2 MiB, and query metadata at 256 reads. Its `GetQueryExecution` reads submitted
SQL transiently but never starts a query. That existing scope must be included
explicitly in any collection authorization; Lambda read approval alone does
not authorize it.

## Freeze independent expectations before observation

| Validator input | Preparation and source |
| --- | --- |
| `expectation.source_commit` | Full 40-character reviewed Git commit, with all four fixed blobs available locally; no worktree substitution |
| `expectation.artifact_sha256` | SHA-256 of the independently reviewed release ZIP, frozen before downloading the observed package; never copied from the observed Lambda digest |
| `expectation.configuration_sha256` | `object_digest(configuration_projection(expected_configuration))` using independently reviewed intended settings, not the observed response |
| `expectation.request_parameters` | Original seven selected request values; omitted values stay null and an explicit minimum remains 20 |
| Reader source digest | Sorted compact JSON manifest of the four committed file SHA-256 values, using the validator's canonical helper |
| Reader settings digest | `settings_digest` over expected environment values and the producer's fixed table ordering/defaults |
| Reader request digest | `object_digest` of the same seven original request fields |
| Reader identity/window | Exact expected version, database/workgroup, actual target invocation identity and bounded observed time window |

The four files and ZIP root names are defined by `FILES` in
`ops/validate_generator_release_binding.py`. Preserve bytes and line endings.
Do not re-ZIP observed source to force the artifact digest to match. Require the
v1 receipt producer; the earlier deployed cardinality-fix source alone cannot
satisfy that requirement. Never copy expected hashes from receipt logs merely
to make equality succeed. Supplied expectations are not authenticated review.

## Capture order and calendar gate

1. Freeze the private expectation packet and confirm the separate release,
   collection and operational authorities. Check the current Sydney clock.
   This v1 collection requires the logical date to equal the actual Sydney
   execution date; an old operational cutoff or future scenario cannot fit it.
2. Acquire and check the package in memory. Cross-check the GetFunction
   configuration against the subsequent pre-run capture, including version,
   code digest and revision; stop on drift. This is an additional acquisition
   check, not an extra field accepted by the offline validator.
3. Finish the pre-run configuration capture before Controller run start. Require
   Active/Successful status and the expected package/configuration. A missing
   pre-run observation cannot be recreated later.
4. Observe only the independently authorized execution. This plan performs no
   invocation, retry, date advancement or recovery. Obtain the actual invocation
   identity from its private execution evidence, not a guessed identifier.
5. Start the post-run capture after the Generator has finished. Both captures
   must be on the logical Sydney date, no later than now, and at most two hours
   apart. The reader window must independently satisfy its two-hour, same-day
   and no-future bounds and include the required Controller records.
6. Read and correlate the complete receipt bundle within the authorized scope.
   Assemble `generator-release-binding-input.v1` in memory with
   `input_kind=SUPPLIED_STAGING_EXPORT`, unchanged `reader_config` and
   `private_bundle`, base64 ZIP bytes and the two configuration observations.
   The complete stdin packet must fit 4 MiB; do not truncate evidence to fit.
7. Run the offline validator. Publish only its bounded aggregate result and
   fixed reasons in a private review handoff. Dispose of transient raw values;
   no repository file, workflow artifact, telemetry or public OPS output is
   added. Any durable private evidence retention needs a separately reviewed
   destination and retention scope.

The required ordering is pre-capture <= Controller start <= Generator start
< Generator finish <= post-capture. Cross-midnight, delayed, missing, ambiguous,
inaccessible or inconsistent evidence leaves the attempt unverified. Do not
re-run the business operation to repair an evidence-collection failure.

## Interpretation and remaining gap

`RELEASE_BINDING_RECORDS_CONSISTENT` means eight local consistency checks passed,
covering four source files, two configuration observations and bounded query
bindings. It does not authenticate AWS records, human review, log authorship or
continuous integrity of mutable `$LATEST`. Equal endpoint revisions cannot
prove nothing changed between them. The configuration projection does not
verify IAM policy contents, VPC, logging, KMS, concurrency or other omitted fields.

Every existing runtime/authentication, snapshot-lineage, net-new-row, real-world
evidence and authority flag remains false. No report activates a policy or
updates readiness. Generated counts still are not independently observed new
keys. The offline Learning validators retain their fixed source pin; this plan
neither advances it nor resolves the historical unexpected proposal.

## Implemented local reader

With no arguments, `python ops/read_generator_release_evidence.py` prints a
redacted `LOCAL_PLAN_ONLY` inventory without importing the AWS SDK, resolving
credentials, reading stdin or contacting AWS. All CLI arguments are rejected.
Execution is callable-only because the two phases must surround an independently
authorized run; an immediate before/after command would not establish that order.

`start_capture(config)` returns an aggregate report and, only on success, a
private in-memory `CaptureSession`. Config has exactly `schema_version` equal
to `generator-release-acquisition-config.v1`, `region`, `logical_date`,
`function_version` and the existing release-binding `expectation` object.
Malformed scope and non-current Sydney dates fail before credentials or network.
The source is checked locally before the single GetFunction and package read.

The session retains the downloaded bytes, frozen expectations and actual
pre-capture time. It never runs a business operation. After the external run and
separately authorized receipt read, call `session.finish(reader_config,
private_bundle)`. Invalid or unbracketed receipt input stops before the second
configuration read. A valid bundle permits one post-run capture, then the existing
offline validator checks the assembled packet. `finish` always closes the session,
including on failure; `discard()` abandons it without a read. No partial private
packet is printed or persisted, and a closed session cannot retry. Private values
are released from session references; this is not a claim of secure memory erasure.

Downloads accept only the GetFunction-provided regional S3 HTTPS location for
the fixed region. No user URL, proxy, redirect, encoded/chunked response or missing
Content-Length is accepted. The 2 MiB limit and a 30-second download deadline
bound the direct TLS read; other package-host formats fail closed. SDK calls use
one attempt and 5/10-second connect/read timeouts and ignore configured custom
endpoint URLs. Existing credential resolution is unchanged. Source/package code
is neither extracted nor executed. Configuration captures discard unconsumed
AWS fields and preserve the validator's selected projection and state fields.

`PRE_RUN_CAPTURE_READY` is only a local acquisition-stage result and grants no
invocation authority. Pre-capture failures return `PRE_RUN_ACQUISITION_FAILED`;
finish exceptions return `ACQUISITION_OR_BINDING_FAILED`. The offline validator's
bounded reason codes are preserved. No raw exception, package URL, role, SQL,
identifier, source, digest or private configuration appears in reports.

Local tests cover the complete two-phase composition with synthetic producer and
reader evidence, wrong source/package/configuration, revision drift, stale or
unbracketed runs, current-day checks, session destruction, one-shot behavior,
download limits and privacy. No live acquisition has run. The deterministic drift
audit additionally guards call inventory, limits, CLI mode and false authority.

The [private composition flow](generator_evidence_collection.md) now connects
these two phases to the existing receipt reader for a supplied external run.
It is implemented locally with mocked end-to-end tests and has not run against
AWS. Its pre-log check binds reader expectations to the frozen package and
configuration; per-call window guards stop further reads after expiry. No
invocation or persistence is added. The
[snapshot/writer attribution acquisition design](snapshot_writer_attribution_design.md)
now has an [offline metadata normalizer](snapshot_metadata_normalizer.md) with
explicit gaps. A bounded plan-first metadata reader is next recommended;
no live read or source-pin change has occurred.
Snapshot/writer attribution, before/after row acquisition and source-pin
reconciliation remain separate prerequisites for any business-behavior conclusion.
