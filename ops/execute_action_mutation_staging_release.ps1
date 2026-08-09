[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$GitCommit,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9-]{1,128}$')][string]$ChangeSetName,
    [Parameter(Mandatory = $true)][ValidatePattern('^arn:aws(-[a-z]+)?:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}$')][string]$CloudFormationRoleArn,
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-stateful-lifecycle-staging",
    [string]$FunctionName = "glap-lifecycle-action-mutation-staging"
)

$ErrorActionPreference = "Stop"
if ($Region -notmatch '^[a-z]{2}(-gov)?-[a-z]+-\d$' -or $StackName -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$' -or $FunctionName -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$') {
    throw "Region, StackName, and FunctionName must use safe AWS names"
}
$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }
function Invoke-AwsJson([string[]]$Arguments, [string]$FailureMessage) {
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) { throw $FailureMessage }
    return ($json | ConvertFrom-Json)
}
function Assert-OneMutationChange($Description) {
    $changes = @($Description.Changes)
    $change = if ($changes.Count -eq 1) { $changes[0].ResourceChange } else { $null }
    $details = @($change.Details)
    if (-not $change -or $change.Action -ne "Modify" -or $change.LogicalResourceId -ne "ActionMutationFunction" -or $change.ResourceType -ne "AWS::Lambda::Function" -or [string]$change.Replacement -ne "False" -or $details.Count -lt 1 -or @($details | Where-Object { $_.Target.Attribute -ne "Properties" }).Count -ne 0) {
        throw "Change set is outside the approved one-resource mutation boundary"
    }
}

if ((git rev-parse HEAD).Trim() -ne $GitCommit -or (git status --porcelain)) { throw "Execute requires the exact clean checked-out commit" }
$stack = (Invoke-AwsJson @("cloudformation", "describe-stacks", "--stack-name", $StackName) "Unable to inspect staging stack").Stacks[0]
if ($stack.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE")) { throw "Staging stack is not stable" }
$description = Invoke-AwsJson @("cloudformation", "describe-change-set", "--stack-name", $StackName, "--change-set-name", $ChangeSetName) "Unable to inspect change set"
if ($description.Status -ne "CREATE_COMPLETE" -or $description.ExecutionStatus -ne "AVAILABLE" -or $description.Description -ne "Action mutation $GitCommit" -or $description.RoleARN -ne $CloudFormationRoleArn) { throw "Change set identity, role, or state changed" }
Assert-OneMutationChange $description
$artifactKey = @($description.Parameters | Where-Object ParameterKey -eq "ActionMutationArtifactKey").ParameterValue
$artifactBucket = @($stack.Parameters | Where-Object ParameterKey -eq "ArtifactBucket").ParameterValue
if (-not $artifactKey -or -not $artifactBucket -or $artifactKey -notmatch "^action-mutation/$GitCommit/glap-action-mutation-([0-9a-f]{64})\.zip$") { throw "Candidate artifact identity is not commit-addressed" }
$expectedArtifactSha256 = $Matches[1]
$object = Invoke-AwsJson @("s3api", "head-object", "--bucket", $artifactBucket, "--key", $artifactKey) "Unable to verify candidate artifact"
if ($object.Metadata.'git-commit' -ne $GitCommit -or $object.Metadata.sha256 -ne $expectedArtifactSha256) { throw "Candidate artifact metadata does not match the reviewed commit and digest" }
$oldConfiguration = Invoke-AwsJson @("lambda", "get-function-configuration", "--function-name", $FunctionName) "Unable to inspect current Lambda"

& aws cloudformation execute-change-set --stack-name $StackName --change-set-name $ChangeSetName @awsScope
if ($LASTEXITCODE -ne 0) { throw "Unable to execute approved change set" }
& aws cloudformation wait stack-update-complete --stack-name $StackName @awsScope
if ($LASTEXITCODE -ne 0) { throw "Stack update did not complete successfully" }

$newStack = (Invoke-AwsJson @("cloudformation", "describe-stacks", "--stack-name", $StackName) "Unable to verify updated stack").Stacks[0]
$newConfiguration = Invoke-AwsJson @("lambda", "get-function-configuration", "--function-name", $FunctionName) "Unable to verify updated Lambda"
if ($newStack.StackStatus -ne "UPDATE_COMPLETE" -or $newConfiguration.State -ne "Active" -or $newConfiguration.LastUpdateStatus -ne "Successful" -or $newConfiguration.CodeSha256 -eq $oldConfiguration.CodeSha256) {
    throw "Post-update Lambda verification failed"
}
Write-Host "Executed and verified the approved Action mutation change set"
Write-Host "  Git commit: $GitCommit"
Write-Host "  Lambda code digest changed: True"
Write-Host "  Stack status: UPDATE_COMPLETE"
Write-Host "  Production effect: False"
