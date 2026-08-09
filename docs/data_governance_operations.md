# Data governance and operations contract

**Status:** governance baseline; infrastructure controls remain unapproved

All logistics content is synthetic. AWS runtime, CI/CD, version, and reliability
records are operational engineering evidence. This distinction survives every
classification, retention, recovery, and incident action.

## Classification

| Class | Examples | Allowed boundary |
| --- | --- | --- |
| `PUBLIC_AGGREGATE` | sanitized OPS KPIs, aggregate mode/provider/lane counts | GitHub Pages and public documentation |
| `PRIVATE_OPERATIONAL` | synthetic shipment IDs, lanes, milestones, Action and Outcome rows | authenticated staging roles only |
| `RESTRICTED_IDENTITY` | Cognito claims, user email, actor subject, access logs | identity administrators and restricted runtime logs |
| `SECRET_CONFIGURATION` | tokens, passwords, account IDs, ARNs, bucket paths, signed URLs | approved secret/configuration stores only; never repository or public output |

Public export must fail closed when classification is missing. Redaction removes
entity identifiers, infrastructure identifiers, query IDs, raw errors, and
private locations before publication.

## Proposed retention and deletion

These are design defaults, not deployed lifecycle policies:

- temporary Athena results and workflow evidence: 14 days;
- private API access logs: 30 days;
- synthetic staging shipment/entity rows: 90 days after the last governed use;
- governed Action audit and Outcome evidence: 365 days;
- Cognito access: disable immediately when no longer required, then delete only
  after the access owner confirms audit preservation.

Deletion must be scope-bounded, reviewed, logged, and followed by Iceberg
snapshot/orphan verification. No automated deletion job is authorized yet.

## Recovery ownership and targets

The staging lifecycle data steward owns Iceberg recovery; the Operations API
owner owns authenticated service recovery; the analytics steward owns query and
watermark recovery. Named people are still required before recurring execution.

The initial engineering target is recovery within eight business hours to the
last verified Iceberg snapshot and versioned controller status. This is a
staging target, not a production SLA. Recovery must preserve the failed run,
temporal scope, audit rows, and idempotency keys.

## SLO and incident baseline

- private Operations API engineering availability target: 99.0% monthly;
- current pipeline status target: within 24 hours of an approved operational
  run; manual staging without an approved run is `not scheduled`, not an outage;
- zero tolerance for public entity/identity leakage, unauthorized mutation,
  future-simulation leakage, or automatic policy activation.

Severity 1 covers credential/public-data exposure or unauthorized production
effect. Severity 2 covers mutation integrity, audit loss, or temporal-boundary
failure. Severity 3 covers stale private analytics or a recoverable staging
failure. Responders preserve evidence, disable the affected caller, classify
scope, recover from the last verified point, and record follow-up ownership.

## Iceberg maintenance design

Compaction, snapshot expiration, and orphan-file cleanup remain plan-only. A
future maintenance change must record table/scope, snapshot before/after,
retention horizon, candidate file counts, scan estimate, rollback point, and
reconciliation results. It must exclude production tables unless separately
approved and must never run concurrently with lifecycle mutation or recovery.

Backup, restore, load, security, and failure-injection exercises remain required
before production expansion. Documentation completion is not runtime proof.
