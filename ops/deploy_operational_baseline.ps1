[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [datetime]$AsOfDate = [datetime]"2026-08-06",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Athena identifier"
}
if ($AthenaOutputUri -notmatch '^s3://[^/]+/.+') {
    throw "AthenaOutputUri must be a prefix-scoped s3:// URI"
}

$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot "temporal_boundary.ps1")
$temporalContext = Resolve-TemporalContext `
    -LastLogicalDate $AsOfDate `
    -ExecutionMode "OPERATIONAL"
$cutoff = $AsOfDate.ToString("yyyy-MM-dd")

function Get-RenderedSql {
    param([Parameter(Mandatory)] [string]$Path)

    $sql = Get-Content -LiteralPath $Path -Raw
    $sql = $sql.Replace("{{SOURCE_DATABASE}}", $SourceDatabase)
    $sql = $sql.Replace("{{AS_OF_DATE}}", $cutoff)
    if ($sql -match '\{\{[^}]+\}\}') {
        throw "Operational baseline SQL contains an unresolved template token in $Path"
    }
    return [regex]::Replace($sql, '(?m)^\s*--.*$', '')
}

function Invoke-AthenaQuery {
    param([Parameter(Mandatory)] [string]$Query)

    $queryId = & aws athena start-query-execution `
        --query-string $Query `
        --query-execution-context "Database=$SourceDatabase" `
        --result-configuration "OutputLocation=$AthenaOutputUri" `
        --work-group $Workgroup `
        @awsScope `
        --query QueryExecutionId `
        --output text
    if ($LASTEXITCODE -ne 0 -or -not $queryId) {
        throw "Unable to start operational baseline Athena query"
    }
    do {
        Start-Sleep -Seconds 1
        $result = & aws athena get-query-execution `
            --query-execution-id $queryId @awsScope --output json | ConvertFrom-Json
        $state = $result.QueryExecution.Status.State
    } while ($state -in @("QUEUED", "RUNNING"))
    if ($state -ne "SUCCEEDED") {
        throw "Operational baseline query $state`: $($result.QueryExecution.Status.StateChangeReason)"
    }
    return $queryId
}

$viewSql = Get-RenderedSql -Path (Join-Path $root "sql/13_operational_baseline.sql")
$viewStatements = @($viewSql -split ';' | Where-Object { $_.Trim() })
$validationSql = Get-RenderedSql -Path (
    Join-Path $root "sql/14_operational_baseline_validation.sql"
)
$checkCount = [regex]::Matches($validationSql, "(?m)SELECT '[^']+' AS check_name").Count

if ($viewSql -match '(?i)\b(insert\s+into|merge\s+into|update\s+|delete\s+from|drop\s+)') {
    throw "Operational baseline contract must remain read-only"
}
if ($viewStatements.Count -ne 1 -or $viewStatements[0] -notmatch '(?i)^\s*CREATE\s+OR\s+REPLACE\s+VIEW') {
    throw "Operational baseline must render exactly one view statement"
}
if ($checkCount -ne 10) {
    throw "Operational baseline validation must contain exactly 10 fail-closed checks"
}

Write-Host "Operational-calendar baseline plan"
Write-Host "  Database: $SourceDatabase"
Write-Host "  Baseline as-of date: $cutoff"
Write-Host "  Sydney business date: $($temporalContext.as_of_date)"
Write-Host "  Temporal scope: OPERATIONAL"
Write-Host "  Source provenance: SIMULATED_MULTIMODAL_V1"
Write-Host "  Evidence class: SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE"
Write-Host "  Real-world evidence: False"
Write-Host "  View statements: $($viewStatements.Count)"
Write-Host "  Fail-closed checks: $checkCount"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after reviewing the cutoff and evidence boundary."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}

foreach ($statement in $viewStatements) {
    $null = Invoke-AthenaQuery -Query $statement.Trim()
}

$validationQueryId = Invoke-AthenaQuery -Query $validationSql.Trim()
$validationResult = & aws athena get-query-results `
    --query-execution-id $validationQueryId @awsScope --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $validationResult.ResultSet.Rows.Count -ne 11) {
    throw "Operational baseline validation must return exactly 10 checks"
}
$failures = @()
foreach ($row in @($validationResult.ResultSet.Rows | Select-Object -Skip 1)) {
    $name = $row.Data[0].VarCharValue
    $failureCount = [long]$row.Data[1].VarCharValue
    if ($failureCount -ne 0) {
        $failures += "$name=$failureCount"
    }
}
if ($failures) {
    throw "Operational baseline validation failed: $($failures -join ', ')"
}

$summarySql = @"
SELECT baseline_as_of_date, source_start_date, source_max_metric_date,
       shipment_count, new_booking_count, delivered_count,
       on_time_delivery_rate_pct, sla_breach_shipment_rate_pct,
       cost_variance_pct, signal_candidate_count,
       high_severity_signal_count, evidence_class, decision_use
FROM $SourceDatabase.vw_multimodal_operational_baseline_v1
WHERE dimension_type = 'ALL' AND dimension_value = 'ALL'
"@
$summaryQueryId = Invoke-AthenaQuery -Query $summarySql
$summaryResult = & aws athena get-query-results `
    --query-execution-id $summaryQueryId @awsScope --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $summaryResult.ResultSet.Rows.Count -ne 2) {
    throw "Operational baseline summary must return exactly one ALL row"
}
$headers = @($summaryResult.ResultSet.Rows[0].Data | ForEach-Object { $_.VarCharValue })
$values = @($summaryResult.ResultSet.Rows[1].Data | ForEach-Object { $_.VarCharValue })
$summary = @{}
for ($index = 0; $index -lt $headers.Count; $index++) {
    $summary[$headers[$index]] = $values[$index]
}

Write-Host "Operational-calendar baseline deployed and validated"
Write-Host "  Shipment count: $($summary['shipment_count'])"
Write-Host "  New bookings: $($summary['new_booking_count'])"
Write-Host "  Delivered: $($summary['delivered_count'])"
Write-Host "  On-time delivery rate: $($summary['on_time_delivery_rate_pct'])%"
Write-Host "  SLA breach shipment rate: $($summary['sla_breach_shipment_rate_pct'])%"
Write-Host "  Cost variance: $($summary['cost_variance_pct'])%"
Write-Host "  Signal candidates: $($summary['signal_candidate_count'])"
Write-Host "  High-severity signals: $($summary['high_severity_signal_count'])"
Write-Host "  Real-world evidence: False"
