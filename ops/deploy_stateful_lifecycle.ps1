[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$SourceBucketUri,
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [switch]$IncludeSeed,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Athena identifier"
}
if ($SourceBucketUri -notmatch '^s3://[^/]+/.+' -or $AthenaOutputUri -notmatch '^s3://[^/]+/.+') {
    throw "SourceBucketUri and AthenaOutputUri must be prefix-scoped s3:// URIs"
}

function Get-RenderedStatements {
    param([Parameter(Mandatory)] [string]$Path)

    $sql = Get-Content -LiteralPath $Path -Raw
    $sql = $sql.Replace("{{SOURCE_DATABASE}}", $SourceDatabase)
    $sql = $sql.Replace("{{SOURCE_BUCKET_URI}}", $SourceBucketUri.TrimEnd('/'))
    if ($sql -match '\{\{[^}]+\}\}') {
        throw "Unresolved SQL template token in $Path"
    }
    $sql = [regex]::Replace($sql, '(?m)^\s*--.*$', '')
    return @($sql -split ';' | Where-Object { $_.Trim() })
}

function Invoke-AthenaStatement {
    param([Parameter(Mandatory)] [string]$Statement)

    $awsScope = @("--region", $Region)
    if ($Profile) {
        $awsScope += @("--profile", $Profile)
    }
    $queryId = & aws athena start-query-execution `
        --query-string $Statement `
        --query-execution-context "Database=$SourceDatabase" `
        --result-configuration "OutputLocation=$AthenaOutputUri" `
        --work-group $Workgroup `
        @awsScope `
        --query QueryExecutionId `
        --output text
    if ($LASTEXITCODE -ne 0 -or -not $queryId) {
        throw "Unable to start Athena lifecycle statement"
    }
    do {
        Start-Sleep -Seconds 1
        $result = & aws athena get-query-execution `
            --query-execution-id $queryId `
            @awsScope `
            --output json | ConvertFrom-Json
        $state = $result.QueryExecution.Status.State
    } while ($state -in @("QUEUED", "RUNNING"))
    if ($state -ne "SUCCEEDED") {
        throw "Athena lifecycle statement $state`: $($result.QueryExecution.Status.StateChangeReason)"
    }
}

$root = Split-Path $PSScriptRoot -Parent
$files = @((Join-Path $root "sql/04_stateful_lifecycle_config.sql"))
if ($IncludeSeed) {
    $files += Join-Path $root "sql/05_stateful_lifecycle_seed.sql"
}
$statements = @($files | ForEach-Object { Get-RenderedStatements -Path $_ })

Write-Host "Stateful lifecycle deployment plan"
Write-Host "  Database: $SourceDatabase"
Write-Host "  Data root: $($SourceBucketUri.TrimEnd('/'))"
Write-Host "  SQL statements: $($statements.Count)"
Write-Host "  Seed included: $($IncludeSeed.IsPresent)"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after reviewing the target prefixes."
    return
}

foreach ($statement in $statements) {
    Invoke-AthenaStatement -Statement $statement.Trim()
}
Write-Host "Stateful lifecycle schema deployment completed. Run sql/06_stateful_lifecycle_validation.sql before enabling any writer."
