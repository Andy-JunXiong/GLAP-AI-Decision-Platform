# Public OPS snapshot

The GitHub Pages demo reads `data/ops-snapshot.json` instead of presenting its
operational funnel as live hard-coded data. The committed file is an explicitly
labelled synthetic fallback. A scheduled GitHub Actions deployment can replace
it at build time with a public-safe Athena aggregate.

## Published contract

The `1.7` snapshot contains only:

- generation and source timestamps;
- per-stage freshness and logical-run lag;
- current v3/v2 flywheel shipment, alert, insight/root-cause, decision, action,
  outcome, and learning counts;
- aggregate action-completion and simulated outcome-effectiveness rates;
- a 28-day total-volume history and transparent seven-day linear baseline,
  calculated by Athena engine v3;
- aggregate alert, action, and root-cause distributions from governed AWS v3/v2
  result tables;
- aggregate pipeline query status and data-completeness checks;
- the aggregate `ALL` row plus allowlisted transport-mode, provider, and
  market-lane rows from the stateful operational-calendar baseline, including
  shipment, booking, delivery, SLA-breach, governed signal, and aggregate cost
  counts;
- an outcome-label summary (`observed`, `pending`, `total`) and a population
  profile that prevents the UI from claiming multimodal comparison when only
  one transport mode is present;
- an outcome-maturity gate that keeps on-time and realized-cost measures
  unavailable until deliveries exist and requires 200 delivered outcomes before
  reporting `ENGINEERING_READY`.
- optional success-gated pipeline stage timing, completion state, safe failure
  category, quality-check results, and a public runbook link;
- explicit expected, completed, and successful stage counts plus the number of
  passed public quality checks.

Pipeline Health reports `current` only when the operational, actual-calendar
latest-run contract contains the exact governed six-stage order, all six stages
succeeded, both validation stages contain the complete five-check contract,
all ten checks passed, and the logical run date matches the aggregate source
date. A partial stage list, one validation gate, a future simulation, or a
missing status object is never rendered as healthy.

It excludes shipment IDs, entity keys, customer records, account IDs, ARNs, S3
paths, query execution IDs and individual decisions. Dimension values are
restricted to aggregate mode, provider, and market-lane labels. Forecast points contain only
daily total volume, a residual interval, and projected at-risk totals. They are
labelled as a statistical baseline, not an operational commitment.

The Control Tower presents two populations side by side instead of reconciling
unlike denominators: the existing v2/v3 decision-flywheel snapshot and the
stateful lifecycle baseline. The latter always retains
`SIMULATED_MULTIMODAL_V1`, `real_world_evidence=false`, and
`ENGINEERING_EVALUATION_ONLY`; its real-world status remains blocked.

The public site uses this same contract across Control Tower, Signals,
Shipments, Outcomes, and Analytics. Decisions shows the existing published
aggregate separately from a browser-only scenario lab. Scenario approval never
writes AWS state, changes shipment data, or contributes an observed outcome.

## GitHub configuration

The repository includes an idempotent PowerShell setup command for the current
GLAP deployment. It discovers the deployed Athena/Glue/S3 contract, creates or
updates the least-privilege GitHub OIDC role, and sets the core variables on the
`github-pages` environment:

```powershell
.\ops\configure_ops_snapshot_access.ps1
```

After the controller status object is deployed and a controlled failure test
passes, enable required verification explicitly:

```powershell
.\ops\configure_ops_snapshot_access.ps1 `
  -PipelineStatusS3Uri "s3://<private-bucket>/<private-prefix>/latest.json" `
  -RequirePipelineStatus
```

Run it after authenticating `gh`, the AWS `default` admin profile, and the
`codex-readonly` inspection profile. Profile, region, repository, environment,
and role names can also be supplied as script parameters.

When the GitHub environment variables already exist, update only AWS access
without requiring a `gh` login:

```powershell
.\ops\configure_ops_snapshot_access.ps1 -SkipGitHubVariables
```

Configure these repository variables before enabling the AWS export step:

| Variable | Purpose |
| --- | --- |
| `AWS_OPS_READ_ROLE_ARN` | OIDC role assumed only by the Pages workflow |
| `AWS_OPS_DATABASE` | Athena database; defaults to `curated_iceberg` |
| `AWS_OPS_SOURCE_DATABASE` | Canonical shipment and stateful baseline database; defaults to `simulated_iceberg_m` |
| `AWS_OPS_ATHENA_OUTPUT` | Private S3 query-result location |
| `AWS_OPS_WORKGROUP` | Athena workgroup; defaults to `primary` |
| `AWS_OPS_PIPELINE_STATUS_URI` | Optional S3 URI of the controller's sanitized latest-run contract |
| `AWS_OPS_PIPELINE_STATUS_REQUIRED` | Set to `true` only after the controller and read permission are deployed |

The role should trust the repository's GitHub OIDC subject for the
`github-pages` environment and grant only the reads required for the governed
six-input/six-output metric contract, plus Athena execution/status, the
sanitized pipeline-status object and the private query-result prefix. It does
not need
permission to mutate Lambda aliases, schedules, Iceberg tables, or production
decisions.

The governed target contract intentionally reuses `fact_ai_alerts_v3`,
`fact_ai_insights_v3`, `fact_ai_decisions_v3`, `fact_ai_actions_v2`,
`fact_ai_outcomes_v2`, and `fact_ai_learning_v1`. Root-cause distributions come
from insights v3 and action distributions come from actions v2. Legacy v1
root-cause/feedback tables and latest-decision trace views are not governed
public outputs and must not be used to imply current pipeline health.

Snapshot schema `1.4` removes the legacy shipment-events, v1 root-cause/feedback,
and decision-trace dependencies. Shipment volume comes from
`simulated_iceberg_m.fact_shipment_v2`; root-cause distribution comes from
insights v3 and action distribution comes from actions v2. Outcome improvement
is stored as a ratio and multiplied by 100 in Athena (`0.375` is published as
`37.5%`). Every public outcome aggregate is explicitly labelled simulated.
Because the canonical shipment snapshot has no synthetic `status` column,
`shipments_at_risk` counts distinct shipments whose route, carrier and ship mode
match an alerts v3 hotspot on the same logical date. It is an aggregate exposure
count, not an entity-level risk classification.

The governed analysis date is the successful pipeline logical run date. Shipment
volume is grouped from the canonical v2 Iceberg `dt` snapshot; a shipment's
future milestone time does not move the analysis date forward. All KPI,
distribution, completion-rate, trend and forecast calculations
run in Athena. GitHub Actions only assumes the read role, requests the governed
AWS result, validates the aggregate response contract, and publishes the JSON
artifact.

The inspected current daily path runs shipment generation at 00:05 and the v2
orchestrator at 00:30 in `Australia/Sydney`. The Pages refresh runs later and
checks every stage date. A source can therefore be fresh while the overall
pipeline is still reported `partial_or_stale` if any stage lags by more than one
logical run day.

If `AWS_OPS_READ_ROLE_ARN` is absent, Pages publishes the committed fallback and
the product displays **Synthetic validation snapshot · not live**. If the role
is configured but the export fails, the deployment fails and the last
successful site remains available; it does not silently publish a fresh-looking
fallback.

When `AWS_OPS_PIPELINE_STATUS_REQUIRED=true`, a missing, failed, stale, or
incomplete pipeline-run contract forces the published snapshot to `stale`; fresh
stage dates alone are no longer enough to claim `current`. Before that flag is
enabled, the snapshot labels its verification mode `stage_dates_only` for
backward-compatible rollout. The controller contract never includes Lambda
names, ARNs, query IDs, S3 locations, row identifiers, or exception text.

The controller source is `lambda/glap_pipeline_controller.py`. It reads an
ordered `PIPELINE_STAGES_JSON` configuration and requires
`PIPELINE_STATUS_S3_URI`. A stage marked `quality_gate` must report exactly these
checks as `passed` or `failed`: missing dates, empty inputs, duplicate business
keys, abnormal volume change, and stale stage outputs. Any missing or failed
check blocks every later stage. See the
[pipeline reliability runbook](runbooks/pipeline_reliability.md).
The verified six-stage replacement order and aggregate Athena validation
evidence are documented in [pipeline reliability](pipeline_reliability.md).

## Local export

With an authenticated AWS identity and the required environment variables:

```bash
python -m pip install boto3
python ops/export_ops_snapshot.py --output offline/data/ops-snapshot.json
```

The exporter queries only the allowlisted contracts in
`ops/export_ops_snapshot.py`. Reusable private analyst queries, the existing
asset inventory, and the matching seven-day forecast baseline are documented in
`sql/03_ops_analytics.sql`.

## Next boundary

This contract remains read-only and aggregate-only. Decision review, Action
updates, and Outcome reads are now implemented behind the separate authenticated
staging Operations API; they have not been added to the GitHub Pages role.
Production expansion still requires the cost, recovery, security, access, and
evidence gates in the [implementation roadmap](implementation_roadmap.md). See
the approved [stateful shipment lifecycle design](shipment_lifecycle_design.md)
for the isolated staging boundary.
