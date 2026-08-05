[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$ControllerFunction = "glap-stateful-lifecycle-controller-staging",
    [datetime]$StartDate = "2026-09-08",
    [ValidateRange(1, 45)] [int]$Days = 28,
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

foreach ($logicalDate in $dates) {
    $day = $logicalDate.ToString("yyyy-MM-dd")
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
            throw "Controller returned a Lambda FunctionError for $day"
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

Write-Host "Controller extension completed for $Days logical dates without a seed or schedule."
