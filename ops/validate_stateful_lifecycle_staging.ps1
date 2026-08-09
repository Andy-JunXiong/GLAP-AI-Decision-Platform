[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [datetime]$StartDate = "2026-08-04",
    [ValidateRange(1, 90)] [int]$Days = 28,
    [ValidateSet("OPERATIONAL", "FUTURE_SIMULATION")]
    [string]$ExecutionMode = "OPERATIONAL",
    [string]$ScenarioId = "",
    [string]$LifecycleQualityGateFunction = "",
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
if ($LifecycleQualityGateFunction -and
    $LifecycleQualityGateFunction -notmatch '^[A-Za-z0-9_-]{1,64}$') {
    throw "LifecycleQualityGateFunction must use safe Lambda name characters"
}

$dates = 0..($Days - 1) | ForEach-Object { $StartDate.Date.AddDays($_) }
$temporalContext = Resolve-TemporalContext `
    -LastLogicalDate $dates[-1] `
    -ExecutionMode $ExecutionMode `
    -ScenarioId $ScenarioId
$temporalScopeId = if ($temporalContext.execution_mode -eq "OPERATIONAL") {
    "OPERATIONAL"
} else {
    "SIMULATION:$($temporalContext.scenario_id)"
}
Write-Host "Stateful lifecycle staging validation plan"
Write-Host "  Database: $SourceDatabase"
Write-Host "  First date: $($dates[0].ToString('yyyy-MM-dd'))"
Write-Host "  Last date: $($dates[-1].ToString('yyyy-MM-dd'))"
Write-Host "  Days: $Days"
Write-Host "  Execution mode: $($temporalContext.execution_mode)"
Write-Host "  Temporal scope: $temporalScopeId"
Write-Host "  Contracts: lifecycle + multimodal analytics"
Write-Host (
    "  Lifecycle validation path: " +
    $(if ($LifecycleQualityGateFunction) {
        "deployed quality-gate Lambda"
    } else {
        "direct Athena SQL"
    })
)
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
$validationTemplates = @()
if (-not $LifecycleQualityGateFunction) {
    $validationTemplates += Get-Content -LiteralPath `
        (Join-Path $root "sql/06_stateful_lifecycle_validation.sql") -Raw
}
$validationTemplates += Get-Content -LiteralPath `
    (Join-Path $root "sql/10_multimodal_ops_validation.sql") -Raw

function Invoke-DeployedLifecycleQualityGate {
    param([Parameter(Mandatory)] [string]$LogicalDate)

    $payload = @{
        logical_run_date = $LogicalDate
        pipeline_stage = "lifecycle_validation"
        quality_contract = "lifecycle_v1"
        execution_mode = $temporalContext.execution_mode
        scenario_id = $temporalContext.scenario_id
    } | ConvertTo-Json -Compress
    $payloadPath = [IO.Path]::GetTempFileName()
    $responsePath = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText(
            $payloadPath, $payload, [Text.UTF8Encoding]::new($false)
        )
        $metadataJson = & aws lambda invoke `
            --function-name $LifecycleQualityGateFunction `
            --payload "fileb://$payloadPath" `
            --cli-read-timeout 300 `
            --cli-connect-timeout 60 `
            @awsScope `
            $responsePath `
            --output json
        if ($LASTEXITCODE -ne 0 -or -not $metadataJson) {
            throw "Unable to invoke deployed lifecycle validation for $LogicalDate"
        }
        $metadata = $metadataJson | ConvertFrom-Json
        if ($metadata.FunctionError) {
            throw "Deployed lifecycle validation returned a FunctionError for $LogicalDate"
        }
        $response = Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
        if ($response.status -ne "success" -or
            $response.logical_run_date -ne $LogicalDate -or
            $response.pipeline_stage -ne "lifecycle_validation" -or
            $response.quality_contract -ne "lifecycle_v1") {
            throw "Deployed lifecycle validation returned an invalid contract for $LogicalDate"
        }
        $checks = @($response.quality_checks.psobject.Properties)
        if ($checks.Count -ne 28 -or
            @($checks | Where-Object {
                $_.Name -notmatch '^[a-z][a-z0-9_]{1,63}$' -or
                $_.Value -notin @("passed", "failed")
            }).Count -ne 0) {
            throw "Deployed lifecycle validation returned unsafe checks for $LogicalDate"
        }
        $failedChecks = @(
            $checks | Where-Object { $_.Value -eq "failed" } |
                ForEach-Object { $_.Name } | Sort-Object
        )
        if ($failedChecks.Count -ne 0) {
            throw (
                "Deployed lifecycle validation failed for $LogicalDate`: " +
                "$($failedChecks -join ',')"
            )
        }
        return $checks.Count
    } finally {
        Remove-Item -LiteralPath $payloadPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $responsePath -Force -ErrorAction SilentlyContinue
    }
}

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
    $checkCount = 0
    if ($LifecycleQualityGateFunction) {
        $checkCount += Invoke-DeployedLifecycleQualityGate -LogicalDate $day
    }
    foreach ($validationTemplate in $validationTemplates) {
        $rendered = $validationTemplate.Replace("{{SOURCE_DATABASE}}", $SourceDatabase)
        $rendered = $rendered.Replace("{{LOGICAL_RUN_DATE}}", $day)
        $rendered = $rendered.Replace("{{TEMPORAL_SCOPE_ID}}", $temporalScopeId)
        if ($rendered -match '\{\{[^}]+\}\}') {
            throw "Unresolved validation template token for $day"
        }
        $rendered = [regex]::Replace($rendered, '(?m)^\s*--.*$', '')
        $statements = @($rendered -split ';' | Where-Object { $_.Trim() })
        foreach ($statement in $statements) {
            $checkCount += Invoke-ValidationStatement `
                -Statement $statement.Trim() -LogicalDate $day
        }
    }
    Write-Host "$day`: $checkCount validation checks passed"
}

Write-Host "All lifecycle staging validation checks passed for $Days logical dates."
