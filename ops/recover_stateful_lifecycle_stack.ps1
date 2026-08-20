[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-stateful-lifecycle-staging",
    [Parameter(Mandatory)] [string]$CloudFormationRoleArn,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

if ($Region -notmatch '^[a-z]{2}(-gov)?-[a-z]+-\d$' -or
    $StackName -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$') {
    throw "Region and StackName must use safe AWS names"
}
if ($CloudFormationRoleArn -notmatch (
    '^arn:aws(-[a-z]+)?:iam::\d{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*' +
    'glap-stateful-lifecycle-cloudformation-staging-role$'
)) {
    throw "CloudFormationRoleArn must identify the dedicated lifecycle staging service role"
}

Write-Host "Stateful lifecycle stack rollback recovery plan"
Write-Host "  Stack: $StackName"
Write-Host "  Region: $Region"
Write-Host "  Dedicated CloudFormation service role configured: True"
Write-Host "  Resources skipped during rollback: False"
Write-Host "  Production alias or schedule permission: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after named-human approval."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}

$stackJson = & aws cloudformation describe-stacks `
    --stack-name $StackName @awsScope --output json
if ($LASTEXITCODE -ne 0 -or -not $stackJson) {
    throw "Unable to inspect the lifecycle staging stack"
}
$stack = ($stackJson -join "`n" | ConvertFrom-Json).Stacks[0]

if ([string]$stack.StackStatus -eq "UPDATE_ROLLBACK_COMPLETE" -and
    [string]$stack.RoleARN -eq $CloudFormationRoleArn) {
    Write-Host "Lifecycle staging rollback is already complete under the dedicated role."
    return
}
if ([string]$stack.StackStatus -ne "UPDATE_ROLLBACK_FAILED") {
    throw "Recovery requires UPDATE_ROLLBACK_FAILED; current status is $($stack.StackStatus)"
}

& aws cloudformation continue-update-rollback `
    --stack-name $StackName `
    --role-arn $CloudFormationRoleArn `
    @awsScope
if ($LASTEXITCODE -ne 0) {
    throw "Unable to continue lifecycle staging rollback"
}
& aws cloudformation wait stack-rollback-complete `
    --stack-name $StackName @awsScope
if ($LASTEXITCODE -ne 0) {
    throw "Lifecycle staging rollback did not complete"
}

$recoveredJson = & aws cloudformation describe-stacks `
    --stack-name $StackName @awsScope --output json
if ($LASTEXITCODE -ne 0 -or -not $recoveredJson) {
    throw "Unable to verify the recovered lifecycle staging stack"
}
$recovered = ($recoveredJson -join "`n" | ConvertFrom-Json).Stacks[0]
if ([string]$recovered.StackStatus -ne "UPDATE_ROLLBACK_COMPLETE" -or
    [string]$recovered.RoleARN -ne $CloudFormationRoleArn) {
    throw "Lifecycle staging rollback role or final status verification failed"
}

Write-Host "Lifecycle staging rollback recovered without skipping a resource."
Write-Host "Production alias changed: False"
Write-Host "Schedule created: False"
