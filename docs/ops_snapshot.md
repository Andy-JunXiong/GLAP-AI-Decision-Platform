# Public OPS snapshot

The GitHub Pages demo reads `data/ops-snapshot.json` instead of presenting its
operational funnel as live hard-coded data. The committed file is an explicitly
labelled synthetic fallback. A scheduled GitHub Actions deployment can replace
it at build time with a public-safe Athena aggregate.

## Published contract

The snapshot contains only:

- generation and source timestamps;
- freshness and connection status;
- daily aggregate shipment, alert, root-cause and decision counts;
- aggregate pipeline query status.

It excludes shipment IDs, entity keys, carriers, account IDs, ARNs, S3 paths,
query execution IDs and individual decisions. Actions and outcomes remain
`null` until their deployed schemas are added to the verified public contract.

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
`github-pages` environment and grant only the reads required for the four
verified tables, plus Athena execution/status and the private query-result
prefix. It does not need permission to mutate Lambda aliases, schedules,
Iceberg tables, or production decisions.

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

The export query is intentionally limited to schemas retained in
`sql/00_core_table_ddl.sql`.
