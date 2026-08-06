[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [datetime]$CohortStartDate = "2026-08-04",
    [datetime]$CutoffDate = "2026-08-06",
    [ValidateRange(1, 100000)] [int]$MinimumObserved = 200,
    [ValidateRange(1, 100000)] [int]$MinimumClass = 20,
    [ValidateRange(2, 100000)] [int]$MinimumCostDistinct = 10,
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
if ($CohortStartDate.Date -gt $CutoffDate.Date) {
    throw "CohortStartDate must not be after CutoffDate"
}
$temporalContext = Resolve-TemporalContext `
    -LastLogicalDate $CutoffDate `
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

$firstDay = $CohortStartDate.ToString("yyyy-MM-dd")
$lastDay = $CutoffDate.ToString("yyyy-MM-dd")
Write-Host "Multimodal outcome-label readiness plan"
Write-Host "  Source: $SourceDatabase.vw_multimodal_outcome_label_v1"
Write-Host "  Booking cohort: $firstDay through $lastDay"
Write-Host "  Required observed labels: $MinimumObserved per mode/provider"
Write-Host "  Required binary class labels: $MinimumClass per class"
Write-Host "  Pending labels used for training: False"
Write-Host "  Execution mode: $($temporalContext.execution_mode)"
Write-Host "  Time basis: $($temporalContext.time_basis)"
Write-Host "  Sydney as-of date: $($temporalContext.as_of_date)"
Write-Host "  Scenario: $($temporalContext.scenario_id)"
Write-Host "  Production writes: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply to execute the aggregate read-only query."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}
$query = @"
WITH boundary AS (
    SELECT max(label_observed_through_date) AS source_latest_date
    FROM $SourceDatabase.vw_multimodal_outcome_label_v1
    WHERE label_observed_through_date <= DATE '$lastDay'
), cohort AS (
    SELECT labels.*
    FROM $SourceDatabase.vw_multimodal_outcome_label_v1 AS labels
    WHERE booking_cohort_date BETWEEN DATE '$firstDay' AND DATE '$lastDay'
)
SELECT
    cohort.transport_mode,
    cohort.provider_code,
    CAST(boundary.source_latest_date AS varchar) AS source_latest_date,
    CAST(count(*) AS varchar) AS cohort_shipments,
    CAST(count_if(cohort.outcome_status = 'PENDING') AS varchar) AS pending_label_count,
    CAST(count_if(cohort.outcome_status = 'OBSERVED') AS varchar) AS observed_label_count,
    CAST(count_if(cohort.outcome_status = 'OBSERVED' AND cohort.sla_breach_label) AS varchar)
        AS sla_positive_count,
    CAST(count_if(cohort.outcome_status = 'OBSERVED' AND NOT cohort.sla_breach_label) AS varchar)
        AS sla_negative_count,
    CAST(count_if(cohort.outcome_status = 'OBSERVED' AND cohort.delivery_late_label) AS varchar)
        AS delay_positive_count,
    CAST(count_if(cohort.outcome_status = 'OBSERVED' AND NOT cohort.delivery_late_label) AS varchar)
        AS delay_negative_count,
    CAST(count_if(cohort.outcome_status = 'OBSERVED' AND cohort.cost_variance_pct_label IS NOT NULL)
        AS varchar) AS cost_label_count,
    CAST(count(DISTINCT IF(
        cohort.outcome_status = 'OBSERVED', cohort.cost_variance_pct_label, NULL
    )) AS varchar) AS cost_variance_distinct_count
FROM cohort
CROSS JOIN boundary
GROUP BY cohort.transport_mode, cohort.provider_code, boundary.source_latest_date
ORDER BY cohort.transport_mode, cohort.provider_code
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
    throw "Unable to start the aggregate label-readiness query"
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
    throw "Label-readiness query $state`: $($execution.QueryExecution.Status.StateChangeReason)"
}

$result = & aws athena get-query-results `
    --query-execution-id $queryId `
    @awsScope `
    --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read label-readiness results"
}
$resultRows = @($result.ResultSet.Rows)
if ($resultRows.Count -lt 2) {
    throw "Label-readiness query returned no mode/provider rows"
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
$summaryPath = Join-Path $outputPath "multimodal-label-summary.csv"
$reportPath = Join-Path $outputPath "multimodal-label-readiness.json"
$records | Export-Csv -LiteralPath $summaryPath -NoTypeInformation -Encoding utf8

$assessor = Join-Path $PSScriptRoot "assess_multimodal_label_readiness.py"
& python $assessor $summaryPath `
    --cutoff-date $lastDay `
    --output $reportPath `
    --minimum-observed $MinimumObserved `
    --minimum-class $MinimumClass `
    --minimum-cost-distinct $MinimumCostDistinct
if ($LASTEXITCODE -ne 0) {
    throw "Multimodal outcome-label readiness assessment failed"
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
    source_view = "vw_multimodal_outcome_label_v1"
    booking_cohort_start = $firstDay
    cutoff_date = $lastDay
})
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding utf8

Write-Host "Label readiness completed: $($records.Count) mode/provider rows"
Write-Host "Athena bytes scanned: $scannedBytes"
Write-Host "Report: $reportPath"
