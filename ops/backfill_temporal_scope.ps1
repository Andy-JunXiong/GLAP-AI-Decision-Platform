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
Write-Host "  Sydney cutoff: $($AsOfDate.ToString('yyyy-MM-dd'))"
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

Write-Host "Temporal scope backfill completed. Deploy operational views and run validation next."
