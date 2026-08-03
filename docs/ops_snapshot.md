# Public OPS snapshot

The GitHub Pages demo reads `data/ops-snapshot.json` instead of presenting its
operational funnel as live hard-coded data. The committed file is an explicitly
labelled synthetic fallback. A scheduled GitHub Actions deployment can replace
it at build time with a public-safe Athena aggregate.

## Published contract

The `1.1` snapshot contains only:

- generation and source timestamps;
- per-stage freshness and logical-run lag;
- current v3/v2 flywheel shipment, alert, root-cause, decision, action, outcome,
  and learning counts;
- aggregate action-completion and outcome-effectiveness rates;
- a 28-day total-volume history and transparent seven-day linear baseline;
- aggregate pipeline query status and data-completeness checks.

It excludes shipment IDs, entity keys, carriers, account IDs, ARNs, S3 paths,
query execution IDs and individual decisions. Forecast points contain only
daily total volume, a residual interval, and projected at-risk totals. They are
labelled as a statistical baseline, not an operational commitment.

## GitHub configuration

The repository includes an idempotent PowerShell setup command for the current
GLAP deployment. It discovers the deployed Athena/Glue/S3 contract, creates or
updates the least-privilege GitHub OIDC role, and sets the four variables on the
`github-pages` environment:

```powershell
.\ops\configure_ops_snapshot_access.ps1
```

Run it after authenticating `gh`, the AWS `default` admin profile, and the
`codex-readonly` inspection profile. Profile, region, repository, environment,
and role names can also be supplied as script parameters.

Configure these repository variables before enabling the AWS export step:

| Variable | Purpose |
| --- | --- |
| `AWS_OPS_READ_ROLE_ARN` | OIDC role assumed only by the Pages workflow |
| `AWS_OPS_DATABASE` | Athena database; defaults to `curated_iceberg` |
| `AWS_OPS_ATHENA_OUTPUT` | Private S3 query-result location |
| `AWS_OPS_WORKGROUP` | Athena workgroup; defaults to `primary` |

The role should trust the repository's GitHub OIDC subject for the
`github-pages` environment and grant only the reads required for the seven
verified current-flywheel tables, plus Athena execution/status and the private
query-result prefix. It does not need permission to mutate Lambda aliases,
schedules, Iceberg tables, or production decisions.

The published contract intentionally reads `fact_ai_alerts_v3`,
`fact_ai_insights_v3`, `fact_ai_decisions_v3`, `fact_ai_actions_v2`,
`fact_ai_outcomes_v2`, and `fact_ai_learning_v1`. The March 2026 anomaly,
root-cause, and decision v1 tables remain historical contracts and are not used
to claim current pipeline health.

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

## Local export

With an authenticated AWS identity and the required environment variables:

```bash
python -m pip install boto3
python ops/export_ops_snapshot.py --output offline/data/ops-snapshot.json
```

The exporter queries only the allowlisted contracts in
`ops/export_ops_snapshot.py`. Reusable private analyst queries and the matching
seven-day forecast baseline are documented in `sql/03_ops_analytics.sql`.

## Next boundary

This contract remains read-only and aggregate-only. Decision review, Action
updates, and observed Outcome writes will be implemented behind an authenticated
internal API; they will not be added to the GitHub Pages role. Pipeline
reliability gates must be completed before that write path is enabled. See the
[implementation roadmap](implementation_roadmap.md).
