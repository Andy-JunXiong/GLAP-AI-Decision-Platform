[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$FunctionName = "glap-stateful-lifecycle-generator-staging",
    [datetime]$StartDate = "2026-08-04",
    [ValidateRange(1, 90)] [int]$Days = 28,
    [ValidateRange(1, 5000)] [int]$PopulationSize = 450,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if ($FunctionName -notmatch '^[A-Za-z0-9-_]{1,64}$') {
    throw "FunctionName is not a safe Lambda name"
}

$dates = 0..($Days - 1) | ForEach-Object { $StartDate.Date.AddDays($_) }
Write-Host "Stateful lifecycle staging replay plan"
Write-Host "  Function: $FunctionName"
Write-Host "  First date: $($dates[0].ToString('yyyy-MM-dd'))"
Write-Host "  Last date: $($dates[-1].ToString('yyyy-MM-dd'))"
Write-Host "  Days: $Days"
Write-Host "  Initial active population: $PopulationSize"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after schema, seed and IAM validation."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}
foreach ($logicalDate in $dates) {
    $isFirst = $logicalDate -eq $dates[0]
    $payload = @{
        logical_run_date = $logicalDate.ToString("yyyy-MM-dd")
        seed_population = $isFirst
        population_size = $PopulationSize
        seed_version = "lifecycle-2026.09-multimodal-v1"
    } | ConvertTo-Json -Compress
    $payloadPath = [System.IO.Path]::GetTempFileName()
    $responsePath = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($payloadPath, $payload, [System.Text.UTF8Encoding]::new($false))
        & aws lambda invoke `
            --function-name $FunctionName `
            --payload "fileb://$payloadPath" `
            --cli-read-timeout 900 `
            --cli-connect-timeout 60 `
            @awsScope `
            $responsePath | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Lambda invocation failed for $($logicalDate.ToString('yyyy-MM-dd'))"
        }
        $response = Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
        if ($response.status -ne "success") {
            throw "Lifecycle replay returned a non-success contract for $($logicalDate.ToString('yyyy-MM-dd'))"
        }
        Write-Host "$($logicalDate.ToString('yyyy-MM-dd')): $($response.active_snapshots) snapshots, $($response.events_created) events, $($response.cost_rows_created) cost rows, $($response.metric_rows_created) metric rows, $($response.signal_rows_created) signal candidates"
    } finally {
        Remove-Item -LiteralPath $payloadPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $responsePath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Replay completed. Run sql/06_stateful_lifecycle_validation.sql for every logical date before promotion."
