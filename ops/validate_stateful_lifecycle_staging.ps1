[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [datetime]$StartDate = "2026-08-04",
    [ValidateRange(1, 90)] [int]$Days = 28,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Athena identifier"
}
if ($AthenaOutputUri -notmatch '^s3://[^/]+/.+') {
    throw "AthenaOutputUri must be a prefix-scoped s3:// URI"
}

$dates = 0..($Days - 1) | ForEach-Object { $StartDate.Date.AddDays($_) }
Write-Host "Stateful lifecycle staging validation plan"
Write-Host "  Database: $SourceDatabase"
Write-Host "  First date: $($dates[0].ToString('yyyy-MM-dd'))"
Write-Host "  Last date: $($dates[-1].ToString('yyyy-MM-dd'))"
Write-Host "  Days: $Days"
Write-Host "  Expected result for every check: 0"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after the staging replay completes."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}
$root = Split-Path $PSScriptRoot -Parent
$validationTemplate = Get-Content -LiteralPath `
    (Join-Path $root "sql/06_stateful_lifecycle_validation.sql") -Raw

function Invoke-ValidationStatement {
    param(
        [Parameter(Mandatory)] [string]$Statement,
        [Parameter(Mandatory)] [string]$LogicalDate
    )

    $queryId = & aws athena start-query-execution `
        --query-string $Statement `
        --query-execution-context "Database=$SourceDatabase" `
        --result-configuration "OutputLocation=$AthenaOutputUri" `
        --work-group $Workgroup `
        @awsScope `
        --query QueryExecutionId `
        --output text
    if ($LASTEXITCODE -ne 0 -or -not $queryId) {
        throw "Unable to start lifecycle validation for $LogicalDate"
    }
    do {
        Start-Sleep -Seconds 1
        $execution = & aws athena get-query-execution `
            --query-execution-id $queryId `
            @awsScope `
            --output json | ConvertFrom-Json
        $state = $execution.QueryExecution.Status.State
    } while ($state -in @("QUEUED", "RUNNING"))
    if ($state -ne "SUCCEEDED") {
        throw "Lifecycle validation $state for $LogicalDate`: $($execution.QueryExecution.Status.StateChangeReason)"
    }
    $result = & aws athena get-query-results `
        --query-execution-id $queryId `
        --max-results 100 `
        @awsScope `
        --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read lifecycle validation results for $LogicalDate"
    }
    $rows = @($result.ResultSet.Rows | Select-Object -Skip 1)
    foreach ($row in $rows) {
        $checkName = [string]$row.Data[0].VarCharValue
        $failureCount = [int64]$row.Data[1].VarCharValue
        if ($failureCount -ne 0) {
            throw "Lifecycle validation failed for $LogicalDate`: $checkName=$failureCount"
        }
    }
    return $rows.Count
}

foreach ($logicalDate in $dates) {
    $day = $logicalDate.ToString("yyyy-MM-dd")
    $rendered = $validationTemplate.Replace("{{SOURCE_DATABASE}}", $SourceDatabase)
    $rendered = $rendered.Replace("{{LOGICAL_RUN_DATE}}", $day)
    if ($rendered -match '\{\{[^}]+\}\}') {
        throw "Unresolved validation template token for $day"
    }
    $rendered = [regex]::Replace($rendered, '(?m)^\s*--.*$', '')
    $statements = @($rendered -split ';' | Where-Object { $_.Trim() })
    $checkCount = 0
    foreach ($statement in $statements) {
        $checkCount += Invoke-ValidationStatement -Statement $statement.Trim() -LogicalDate $day
    }
    Write-Host "$day`: $checkCount validation checks passed"
}

Write-Host "All lifecycle staging validation checks passed for $Days logical dates."
