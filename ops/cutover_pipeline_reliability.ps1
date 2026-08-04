[CmdletBinding()]
param(
    [string]$Profile = "default",
    [string]$ReadProfile = "codex-readonly",
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-pipeline-reliability-staging",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$aws = (Get-Command aws -ErrorAction Stop).Source
$currentSchedules = @(
    "glap_daily_generator",
    "glap_daily_orchestrator",
    "glap-ai-orchestrator-daily",
    "glap-ai-flywheel-orchestrator-daily",
    "glap-generator-daily"
)

function Invoke-AwsJson {
    param(
        [Parameter(Mandatory)] [string[]]$Arguments,
        [Parameter(Mandatory)] [string]$AwsProfile
    )
    $raw = & $aws @Arguments --profile $AwsProfile --region $Region --output json
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed: aws $($Arguments[0]) $($Arguments[1])"
    }
    return $raw | ConvertFrom-Json
}

function Write-TemporaryJson {
    param([Parameter(Mandatory)] $Value)
    $path = Join-Path ([System.IO.Path]::GetTempPath()) (
        "glap-cutover-" + [guid]::NewGuid().ToString("N") + ".json"
    )
    $json = $Value | ConvertTo-Json -Depth 30
    [System.IO.File]::WriteAllText(
        $path,
        $json,
        [System.Text.UTF8Encoding]::new($false)
    )
    return $path
}

function Get-ScheduleConfig {
    param([Parameter(Mandatory)] [string]$Name)
    return Invoke-AwsJson -Arguments @(
        "scheduler", "get-schedule", "--name", $Name
    ) -AwsProfile $ReadProfile
}

function New-ScheduleUpdateInput {
    param(
        [Parameter(Mandatory)] $Schedule,
        [Parameter(Mandatory)] [ValidateSet("ENABLED", "DISABLED")] [string]$State
    )
    $input = [ordered]@{
        Name = $Schedule.Name
        GroupName = $Schedule.GroupName
        ScheduleExpression = $Schedule.ScheduleExpression
        FlexibleTimeWindow = $Schedule.FlexibleTimeWindow
        Target = $Schedule.Target
        State = $State
    }
    foreach ($field in @(
        "Description",
        "StartDate",
        "EndDate",
        "ScheduleExpressionTimezone",
        "KmsKeyArn",
        "ActionAfterCompletion"
    )) {
        if ($null -ne $Schedule.$field -and "$($Schedule.$field)" -ne "") {
            $input[$field] = $Schedule.$field
        }
    }
    return $input
}

function Set-ScheduleState {
    param(
        [Parameter(Mandatory)] $Schedule,
        [Parameter(Mandatory)] [ValidateSet("ENABLED", "DISABLED")] [string]$State
    )
    $inputPath = Write-TemporaryJson -Value (
        New-ScheduleUpdateInput -Schedule $Schedule -State $State
    )
    try {
        & $aws scheduler update-schedule `
            --cli-input-json "file://$inputPath" `
            --profile $Profile `
            --region $Region `
            --output json | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to set schedule $($Schedule.Name) to $State"
        }
    } finally {
        Remove-Item -LiteralPath $inputPath -Force -ErrorAction SilentlyContinue
    }
}

$stack = Invoke-AwsJson -Arguments @(
    "cloudformation", "describe-stacks", "--stack-name", $StackName
) -AwsProfile $ReadProfile
$outputs = @{}
foreach ($output in $stack.Stacks[0].Outputs) {
    $outputs[$output.OutputKey] = $output.OutputValue
}
$replacementName = $outputs.ReplacementScheduleName
$statusUri = $outputs.PipelineStatusS3Uri
if (-not $replacementName -or -not $statusUri) {
    throw "Stack outputs do not include the replacement schedule and status URI"
}

$replacement = Get-ScheduleConfig -Name $replacementName
if ($replacement.State -ne "DISABLED") {
    throw "Replacement schedule must be DISABLED before cutover"
}
$existing = @($currentSchedules | ForEach-Object { Get-ScheduleConfig -Name $_ })

Write-Output "Replacement schedule: $replacementName ($($replacement.State))"
foreach ($schedule in $existing) {
    Write-Output "Current schedule: $($schedule.Name) ($($schedule.State))"
}
if (-not $Apply) {
    Write-Output "Plan only; rerun with -Apply to perform the reversible cutover"
    exit 0
}

if ($statusUri -notmatch '^s3://([^/]+)/(.*)$') {
    throw "Invalid private status URI"
}
$backupBucket = $Matches[1]
$backupPrefix = Split-Path -Parent $Matches[2]
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$backupKey = "$backupPrefix/cutover-backups/$timestamp.json"
$backup = [ordered]@{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    stack_name = $StackName
    replacement = $replacement
    existing = $existing
}
$backupPath = Write-TemporaryJson -Value $backup
try {
    & $aws s3api put-object `
        --bucket $backupBucket `
        --key $backupKey `
        --body $backupPath `
        --server-side-encryption AES256 `
        --profile $Profile `
        --region $Region `
        --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to write private schedule backup" }
} finally {
    Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
}

$changed = @()
try {
    foreach ($schedule in $existing) {
        if ($schedule.State -ne "DISABLED") {
            Set-ScheduleState -Schedule $schedule -State "DISABLED"
            $changed += $schedule
        }
    }
    Set-ScheduleState -Schedule $replacement -State "ENABLED"
} catch {
    try { Set-ScheduleState -Schedule $replacement -State "DISABLED" } catch {}
    foreach ($schedule in $changed) {
        try { Set-ScheduleState -Schedule $schedule -State $schedule.State } catch {}
    }
    throw
}

Write-Output "Cutover complete; private rollback configuration was saved"
Write-Output "Replacement schedule: ENABLED"
Write-Output "Previous schedules: DISABLED"
