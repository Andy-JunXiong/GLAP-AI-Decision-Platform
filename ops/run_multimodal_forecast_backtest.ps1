[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [datetime]$StartDate = "2026-08-04",
    [datetime]$EndDate = "2026-08-06",
    [ValidateRange(2, 90)] [int]$MinimumHistory = 14,
    [ValidateRange(1, 1099511627776)] [int64]$MaxScanBytes = 104857600,
    [string]$OutputDirectory = "artifacts/forecast-backtest",
    [ValidateSet("OPERATIONAL", "FUTURE_SIMULATION")]
    [string]$ExecutionMode = "OPERATIONAL",
    [string]$ScenarioId = "",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "temporal_boundary.ps1")
if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Athena identifier"
}
if ($AthenaOutputUri -notmatch '^s3://[^/]+/.+') {
    throw "AthenaOutputUri must be a prefix-scoped s3:// URI"
}
if ($StartDate.Date -gt $EndDate.Date) {
    throw "StartDate must not be after EndDate"
}
$temporalContext = Resolve-TemporalContext `
    -LastLogicalDate $EndDate `
    -ExecutionMode $ExecutionMode `
    -ScenarioId $ScenarioId

$root = Split-Path $PSScriptRoot -Parent
$rootPath = [IO.Path]::GetFullPath($root).TrimEnd(
    [IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
$requestedOutput = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path $root $OutputDirectory
}
$outputPath = [IO.Path]::GetFullPath($requestedOutput)
if (-not ($outputPath + [IO.Path]::DirectorySeparatorChar).StartsWith(
    $rootPath, [StringComparison]::OrdinalIgnoreCase
)) {
    throw "OutputDirectory must remain inside the repository workspace"
}

$firstDay = $StartDate.ToString("yyyy-MM-dd")
$lastDay = $EndDate.ToString("yyyy-MM-dd")
Write-Host "Multimodal forecast backtest plan"
Write-Host "  Source: $SourceDatabase.vw_multimodal_forecast_feature_daily_v1"
Write-Host "  Window: $firstDay through $lastDay"
Write-Host "  Minimum history: $MinimumHistory rows per mode/provider"
Write-Host "  Execution mode: $($temporalContext.execution_mode)"
Write-Host "  Time basis: $($temporalContext.time_basis)"
Write-Host "  Sydney as-of date: $($temporalContext.as_of_date)"
Write-Host "  Scenario: $($temporalContext.scenario_id)"
Write-Host "  Output: $outputPath"
Write-Host "  Production writes: False"
Write-Host "  Recurring schedule: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply to execute the read-only Athena query."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}
$query = @"
SELECT
    CAST(feature_date AS varchar) AS feature_date,
    transport_mode,
    provider_code,
    CAST(new_booking_count AS varchar) AS new_booking_count,
    CAST(feature_cutoff_date AS varchar) AS feature_cutoff_date,
    feature_contract_version,
    leakage_policy
FROM $SourceDatabase.vw_multimodal_forecast_feature_daily_v1
WHERE feature_date BETWEEN DATE '$firstDay' AND DATE '$lastDay'
ORDER BY transport_mode, provider_code, feature_date
"@

$queryId = & aws athena start-query-execution `
    --query-string $query `
    --query-execution-context "Database=$SourceDatabase" `
    --result-configuration "OutputLocation=$AthenaOutputUri" `
    --work-group $Workgroup `
    @awsScope `
    --query QueryExecutionId `
    --output text
if ($LASTEXITCODE -ne 0 -or -not $queryId) {
    throw "Unable to start the read-only forecast feature query"
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
    throw "Forecast feature query $state`: $($execution.QueryExecution.Status.StateChangeReason)"
}

$result = & aws athena get-query-results `
    --query-execution-id $queryId `
    @awsScope `
    --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read forecast feature results"
}
$resultRows = @($result.ResultSet.Rows)
if ($resultRows.Count -lt 2) {
    throw "Forecast feature query returned no data rows"
}
$headers = @($resultRows[0].Data | ForEach-Object { $_.VarCharValue })
$records = foreach ($row in ($resultRows | Select-Object -Skip 1)) {
    $record = [ordered]@{}
    for ($index = 0; $index -lt $headers.Count; $index++) {
        $record[$headers[$index]] = if ($index -lt $row.Data.Count) {
            [string]$row.Data[$index].VarCharValue
        } else {
            ""
        }
    }
    [pscustomobject]$record
}

New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$featurePath = Join-Path $outputPath "multimodal-forecast-features.csv"
$reportPath = Join-Path $outputPath "multimodal-forecast-backtest.json"
$records | Export-Csv -LiteralPath $featurePath -NoTypeInformation -Encoding utf8

$backtest = Join-Path $PSScriptRoot "backtest_multimodal_forecast.py"
& python $backtest $featurePath `
    --output $reportPath `
    --minimum-history $MinimumHistory `
    --require-contract
if ($LASTEXITCODE -ne 0) {
    throw "Multimodal forecast backtest failed"
}

$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
$report | Add-Member -NotePropertyName temporal_context -NotePropertyValue ([ordered]@{
    execution_mode = $temporalContext.execution_mode
    time_basis = $temporalContext.time_basis
    as_of_date = $temporalContext.as_of_date
    scenario_id = $temporalContext.scenario_id
})
$scannedBytes = [int64]$execution.QueryExecution.Statistics.DataScannedInBytes
$report | Add-Member -NotePropertyName athena_evidence -NotePropertyValue ([ordered]@{
    query_execution_id = $queryId
    data_scanned_bytes = $scannedBytes
    scan_budget_bytes = $MaxScanBytes
    scan_budget_status = if ($scannedBytes -le $MaxScanBytes) { "within_budget" } else { "exceeded" }
    source_database = $SourceDatabase
    source_view = "vw_multimodal_forecast_feature_daily_v1"
    window_start = $firstDay
    window_end = $lastDay
})
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding utf8

Write-Host "Backtest completed: $($records.Count) feature rows"
Write-Host "Athena bytes scanned: $scannedBytes"
Write-Host "Report: $reportPath"
