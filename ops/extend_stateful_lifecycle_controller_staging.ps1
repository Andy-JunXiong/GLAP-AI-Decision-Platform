[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$ControllerFunction = "glap-stateful-lifecycle-controller-staging",
    [datetime]$StartDate = "2026-09-08",
    [ValidateRange(1, 12)] [int]$Days = 12,
    [ValidateRange(10, 55)] [int]$MaxElapsedMinutes = 50,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if ($ControllerFunction -notmatch '^[A-Za-z0-9-_]{1,64}$') {
    throw "ControllerFunction is not a safe Lambda name"
}

$dates = 0..($Days - 1) | ForEach-Object { $StartDate.Date.AddDays($_) }
Write-Host "Stateful lifecycle controller extension plan"
Write-Host "  Controller: $ControllerFunction"
Write-Host "  First date: $($dates[0].ToString('yyyy-MM-dd'))"
Write-Host "  Last date: $($dates[-1].ToString('yyyy-MM-dd'))"
Write-Host "  Days: $Days"
Write-Host "  Maximum elapsed time: $MaxElapsedMinutes minutes"
Write-Host "  Seed population: False"
Write-Host "  Expected checks per date: 19 lifecycle + 5 compatibility + 8 analytics"
Write-Host "  Production alias or schedule: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after confirming the prior logical date succeeded."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}
$expectedStages = @(
    "stateful_lifecycle_generation",
    "lifecycle_validation",
    "input_validation",
    "analytics_validation"
)
$expectedCheckCounts = @(0, 19, 5, 8)
$minimumRemainingMinutes = 5
$stopwatch = [Diagnostics.Stopwatch]::StartNew()

foreach ($logicalDate in $dates) {
    $day = $logicalDate.ToString("yyyy-MM-dd")
    if ($stopwatch.Elapsed.TotalMinutes -ge ($MaxElapsedMinutes - $minimumRemainingMinutes)) {
        throw (
            "Credential safety budget exhausted before $day after " +
            "$([Math]::Round($stopwatch.Elapsed.TotalMinutes, 2)) minutes. " +
            "Resume from $day in a new invocation."
        )
    }
    $payload = @{ logical_run_date = $day } | ConvertTo-Json -Compress
    $payloadPath = [IO.Path]::GetTempFileName()
    $responsePath = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText(
            $payloadPath, $payload, [Text.UTF8Encoding]::new($false)
        )
        $metadataJson = & aws lambda invoke `
            --function-name $ControllerFunction `
            --payload "fileb://$payloadPath" `
            --cli-read-timeout 900 `
            --cli-connect-timeout 60 `
            @awsScope `
            $responsePath `
            --output json
        if ($LASTEXITCODE -ne 0 -or -not $metadataJson) {
            throw "Controller invocation failed for $day"
        }
        $metadata = $metadataJson | ConvertFrom-Json
        if ($metadata.FunctionError) {
            $failureDetail = "sanitized failure detail unavailable"
            try {
                $failurePayload = Get-Content -LiteralPath $responsePath -Raw |
                    ConvertFrom-Json
                $candidate = [string]$failurePayload.errorMessage
                if ($candidate -match (
                    '^Pipeline failed at [a-z][a-z0-9_]{1,47}: ' +
                    '(dependency_failure|invalid_response|quality_gate_failed|' +
                    'quality_contract_invalid|unexpected_failure)$'
                )) {
                    $failureDetail = $candidate
                }
            } catch {
                $failureDetail = "sanitized failure detail unavailable"
            }
            throw "Controller returned a Lambda FunctionError for $day ($failureDetail)"
        }
        $response = Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
        if ($response.status -ne "succeeded" -or $response.logical_run_date -ne $day) {
            throw "Controller returned a non-success or mismatched contract for $day"
        }
        $stages = @($response.stages)
        if ($stages.Count -ne $expectedStages.Count) {
            throw "Controller returned an incomplete stage contract for $day"
        }
        for ($index = 0; $index -lt $expectedStages.Count; $index++) {
            $stage = $stages[$index]
            if ($stage.name -ne $expectedStages[$index] -or $stage.status -ne "succeeded") {
                throw "Controller stage order or status failed for $day"
            }
            $checks = @($stage.quality_checks)
            if ($checks.Count -ne $expectedCheckCounts[$index]) {
                throw "Controller quality-check count failed for $day/$($stage.name)"
            }
            if (@($checks | Where-Object { $_.status -ne "passed" }).Count -ne 0) {
                throw "Controller quality check failed for $day/$($stage.name)"
            }
        }
        $duration = ($stages | Measure-Object -Property duration_ms -Sum).Sum
        Write-Host "$day`: four stages and 32 checks passed in $duration ms"
    } finally {
        Remove-Item -LiteralPath $payloadPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $responsePath -Force -ErrorAction SilentlyContinue
    }
}

$stopwatch.Stop()
Write-Host (
    "Controller extension completed for $Days logical dates in " +
    "$([Math]::Round($stopwatch.Elapsed.TotalMinutes, 2)) minutes without a seed or schedule."
)
