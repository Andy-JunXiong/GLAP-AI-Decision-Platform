[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [datetime]$AsOfDate = [datetime]"2026-08-06",
    [string]$LegacyScenarioId = "legacy-pre-boundary-2026",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Athena identifier"
}
if ($LegacyScenarioId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$') {
    throw "LegacyScenarioId must be a safe scenario identifier"
}
if ($AthenaOutputUri -notmatch '^s3://[^/]+/.+') {
    throw "AthenaOutputUri must be a prefix-scoped s3:// URI"
}

$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot "temporal_boundary.ps1")
$temporalContext = Resolve-TemporalContext `
    -LastLogicalDate $AsOfDate `
    -ExecutionMode "OPERATIONAL"
$sydneyBusinessDate = $temporalContext.as_of_date
$template = Get-Content -LiteralPath (
    Join-Path $root "sql/12_temporal_scope_backfill.sql"
) -Raw
$rendered = $template.Replace("{{SOURCE_DATABASE}}", $SourceDatabase)
$rendered = $rendered.Replace("{{AS_OF_DATE}}", $AsOfDate.ToString("yyyy-MM-dd"))
$rendered = $rendered.Replace("{{LEGACY_SCENARIO_ID}}", $LegacyScenarioId)
if ($rendered -match '\{\{[^}]+\}\}') {
    throw "Temporal scope backfill contains an unresolved template token"
}
$rendered = [regex]::Replace($rendered, '(?m)^\s*--.*$', '')
$statements = @($rendered -split ';' | Where-Object { $_.Trim() })

Write-Host "Temporal scope backfill plan"
Write-Host "  Database: $SourceDatabase"
Write-Host "  Legacy migration cutoff: $($AsOfDate.ToString('yyyy-MM-dd'))"
Write-Host "  Sydney business date: $sydneyBusinessDate"
Write-Host "  Legacy future scenario: $LegacyScenarioId"
Write-Host "  Iceberg updates: $($statements.Count)"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after reviewing the cutoff and database."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}
foreach ($statement in $statements) {
    $queryId = & aws athena start-query-execution `
        --query-string $statement.Trim() `
        --query-execution-context "Database=$SourceDatabase" `
        --result-configuration "OutputLocation=$AthenaOutputUri" `
        --work-group $Workgroup `
        @awsScope `
        --query QueryExecutionId `
        --output text
    if ($LASTEXITCODE -ne 0 -or -not $queryId) {
        throw "Unable to start temporal scope backfill statement"
    }
    do {
        Start-Sleep -Seconds 1
        $result = & aws athena get-query-execution `
            --query-execution-id $queryId @awsScope --output json | ConvertFrom-Json
        $state = $result.QueryExecution.Status.State
    } while ($state -in @("QUEUED", "RUNNING"))
    if ($state -ne "SUCCEEDED") {
        throw "Temporal scope backfill $state`: $($result.QueryExecution.Status.StateChangeReason)"
    }
}

$cutoff = $AsOfDate.ToString("yyyy-MM-dd")
$verification = @"
WITH temporal_rows AS (
    SELECT try_cast(dt AS date) AS row_date, temporal_scope_id, execution_mode,
           time_basis, as_of_date, execution_scenario_id
    FROM $SourceDatabase.fact_shipment_lifecycle_staging_v1
    UNION ALL
    SELECT logical_run_date, temporal_scope_id, execution_mode, time_basis,
           as_of_date, execution_scenario_id
    FROM $SourceDatabase.fact_shipment_lifecycle_event_staging_v1
    UNION ALL
    SELECT try_cast(dt AS date), temporal_scope_id, execution_mode, time_basis,
           as_of_date, execution_scenario_id
    FROM $SourceDatabase.fact_shipment_cost_staging_v1
    UNION ALL
    SELECT try_cast(dt AS date), temporal_scope_id, execution_mode, time_basis,
           as_of_date, execution_scenario_id
    FROM $SourceDatabase.fact_shipment_lifecycle_metrics_staging_v1
    UNION ALL
    SELECT try_cast(dt AS date), temporal_scope_id, execution_mode, time_basis,
           as_of_date, execution_scenario_id
    FROM $SourceDatabase.fact_shipment_signal_candidate_staging_v1
)
SELECT
    count_if(
        row_date IS NULL
        OR temporal_scope_id IS NULL OR execution_mode IS NULL OR time_basis IS NULL
        OR as_of_date IS NULL
        OR as_of_date > DATE '$sydneyBusinessDate'
        OR execution_mode NOT IN ('OPERATIONAL', 'FUTURE_SIMULATION')
        OR (
            execution_mode = 'OPERATIONAL'
            AND execution_scenario_id IS NOT NULL
        )
        OR (
            execution_mode = 'FUTURE_SIMULATION'
            AND execution_scenario_id IS NULL
        )
        OR temporal_scope_id <> IF(
            execution_mode = 'OPERATIONAL', 'OPERATIONAL',
            concat('SIMULATION:', execution_scenario_id)
        )
        OR time_basis <> IF(
            execution_mode = 'OPERATIONAL', 'ACTUAL_CALENDAR', 'FUTURE_SIMULATION'
        )
    ) AS invalid_temporal_rows,
    count_if(
        row_date > DATE '$cutoff'
        AND temporal_scope_id = 'SIMULATION:$LegacyScenarioId'
    ) AS legacy_future_rows,
    count_if(
        execution_mode = 'OPERATIONAL'
        AND (
            row_date > as_of_date
            OR row_date > DATE '$sydneyBusinessDate'
        )
    ) AS future_operational_rows,
    count_if(
        execution_mode = 'OPERATIONAL'
        AND row_date <= as_of_date
        AND as_of_date <= DATE '$sydneyBusinessDate'
    ) AS operational_rows
FROM temporal_rows
"@
$queryId = & aws athena start-query-execution `
    --query-string $verification `
    --query-execution-context "Database=$SourceDatabase" `
    --result-configuration "OutputLocation=$AthenaOutputUri" `
    --work-group $Workgroup `
    @awsScope `
    --query QueryExecutionId `
    --output text
if ($LASTEXITCODE -ne 0 -or -not $queryId) {
    throw "Unable to start temporal scope verification"
}
do {
    Start-Sleep -Seconds 1
    $result = & aws athena get-query-execution `
        --query-execution-id $queryId @awsScope --output json | ConvertFrom-Json
    $state = $result.QueryExecution.Status.State
} while ($state -in @("QUEUED", "RUNNING"))
if ($state -ne "SUCCEEDED") {
    throw "Temporal scope verification $state`: $($result.QueryExecution.Status.StateChangeReason)"
}
$verificationResult = & aws athena get-query-results `
    --query-execution-id $queryId @awsScope --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $verificationResult.ResultSet.Rows.Count -ne 2) {
    throw "Temporal scope verification returned an invalid result"
}
$values = @($verificationResult.ResultSet.Rows[1].Data | ForEach-Object {
    [long]$_.VarCharValue
})
if ($values.Count -ne 4) {
    throw "Temporal scope verification returned an invalid column count"
}
$invalidTemporalRows, $legacyFutureRows, $futureOperationalRows, $operationalRows = $values
if ($invalidTemporalRows -ne 0 -or $futureOperationalRows -ne 0) {
    throw "Temporal isolation failed: invalid=$invalidTemporalRows future_operational=$futureOperationalRows"
}
if ($legacyFutureRows -le 0 -or $operationalRows -le 0) {
    throw "Temporal isolation evidence is incomplete: legacy_future=$legacyFutureRows operational=$operationalRows"
}

$operationalViewQuery = @"
SELECT count(*) AS future_operational_view_rows
FROM $SourceDatabase.vw_multimodal_shipment_daily_v1
WHERE metric_date > as_of_date
   OR metric_date > DATE '$sydneyBusinessDate'
   OR as_of_date > DATE '$sydneyBusinessDate'
"@
$viewQueryId = & aws athena start-query-execution `
    --query-string $operationalViewQuery `
    --query-execution-context "Database=$SourceDatabase" `
    --result-configuration "OutputLocation=$AthenaOutputUri" `
    --work-group $Workgroup `
    @awsScope `
    --query QueryExecutionId `
    --output text
if ($LASTEXITCODE -ne 0 -or -not $viewQueryId) {
    throw "Unable to start operational view isolation verification"
}
do {
    Start-Sleep -Seconds 1
    $viewResult = & aws athena get-query-execution `
        --query-execution-id $viewQueryId @awsScope --output json | ConvertFrom-Json
    $viewState = $viewResult.QueryExecution.Status.State
} while ($viewState -in @("QUEUED", "RUNNING"))
if ($viewState -ne "SUCCEEDED") {
    throw "Operational view verification $viewState`: $($viewResult.QueryExecution.Status.StateChangeReason)"
}
$viewRows = & aws athena get-query-results `
    --query-execution-id $viewQueryId @awsScope --output json | ConvertFrom-Json
$futureOperationalViewRows = [long]$viewRows.ResultSet.Rows[1].Data[0].VarCharValue
if ($futureOperationalViewRows -ne 0) {
    throw "Operational view still exposes $futureOperationalViewRows future rows"
}

Write-Host "Temporal scope backfill and verification completed"
Write-Host "  Invalid temporal rows: $invalidTemporalRows"
Write-Host "  Legacy future rows: $legacyFutureRows"
Write-Host "  Future rows in operational scope: $futureOperationalRows"
Write-Host "  Operational rows: $operationalRows"
Write-Host "  Future rows in default operational view: $futureOperationalViewRows"
