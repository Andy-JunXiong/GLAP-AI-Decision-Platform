[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$GitCommit,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9-]{1,128}$')][string]$ChangeSetName,
    [Parameter(Mandatory = $true)][ValidatePattern('^arn:aws(-[a-z]+)?:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}$')][string]$CloudFormationRoleArn,
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-stateful-lifecycle-staging"
)

$ErrorActionPreference = "Stop"
if ($Region -notmatch '^[a-z]{2}(-gov)?-[a-z]+-\d$' -or $StackName -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$') {
    throw "Region and StackName must use safe AWS names"
}
if ((git rev-parse HEAD).Trim() -ne $GitCommit -or (git status --porcelain)) {
    throw "Prepare requires the exact clean checked-out commit"
}

$root = Split-Path $PSScriptRoot -Parent
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("glap-action-mutation-prepare-" + [guid]::NewGuid().ToString("N"))
$packageDirectory = Join-Path $temporaryRoot "package"
$archivePath = Join-Path $temporaryRoot "glap-action-mutation.zip"
$changeSetCreated = $false
$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }

function Invoke-AwsJson([string[]]$Arguments, [string]$FailureMessage) {
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) { throw $FailureMessage }
    return ($json | ConvertFrom-Json)
}

function Assert-OneMutationChange($Description) {
    $changes = @($Description.Changes)
    if ($changes.Count -ne 1) { throw "Change set must contain exactly one resource change" }
    $change = $changes[0].ResourceChange
    $details = @($change.Details)
    if (
        $change.Action -ne "Modify" -or
        $change.LogicalResourceId -ne "ActionMutationFunction" -or
        $change.ResourceType -ne "AWS::Lambda::Function" -or
        [string]$change.Replacement -ne "False" -or
        $details.Count -lt 1 -or
        @($details | Where-Object { $_.Target.Attribute -ne "Properties" }).Count -ne 0
    ) { throw "Change set is outside the approved one-resource mutation boundary" }
}

try {
    New-Item -ItemType Directory -Path $packageDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root "lambda/glap_action_mutation.py") -Destination (Join-Path $packageDirectory "lambda_function.py")
    Copy-Item -LiteralPath (Join-Path $root "lambda/glap_temporal_boundary.py") -Destination (Join-Path $packageDirectory "glap_temporal_boundary.py")
    Compress-Archive -LiteralPath (Join-Path $packageDirectory "lambda_function.py"), (Join-Path $packageDirectory "glap_temporal_boundary.py") -DestinationPath $archivePath
    $artifactSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()

    $stack = (Invoke-AwsJson @("cloudformation", "describe-stacks", "--stack-name", $StackName) "Unable to inspect staging stack").Stacks[0]
    if ($stack.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE")) { throw "Staging stack is not stable" }
    $parameters = @($stack.Parameters)
    $bucket = ($parameters | Where-Object ParameterKey -eq "ArtifactBucket").ParameterValue
    $previousKey = ($parameters | Where-Object ParameterKey -eq "ActionMutationArtifactKey").ParameterValue
    if (-not $bucket -or -not $previousKey) { throw "Required existing artifact parameters are unavailable" }
    $artifactKey = "action-mutation/$GitCommit/glap-action-mutation-$artifactSha256.zip"
    $changeSetDescription = "Action mutation $GitCommit; execution-role=$CloudFormationRoleArn"

    & aws s3api put-object --bucket $bucket --key $artifactKey --body $archivePath --metadata "git-commit=$GitCommit,sha256=$artifactSha256" @awsScope --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Artifact upload failed" }

    $parameterArguments = @()
    foreach ($parameter in $parameters) {
        if ($parameter.ParameterKey -eq "ActionMutationArtifactKey") {
            $parameterArguments += "ParameterKey=$($parameter.ParameterKey),ParameterValue=$artifactKey"
        } else {
            $parameterArguments += "ParameterKey=$($parameter.ParameterKey),UsePreviousValue=true"
        }
    }
    & aws cloudformation create-change-set --stack-name $StackName --change-set-name $ChangeSetName --change-set-type UPDATE --use-previous-template --role-arn $CloudFormationRoleArn --capabilities CAPABILITY_NAMED_IAM --parameters @parameterArguments --description $changeSetDescription @awsScope --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the unexecuted change set" }
    $changeSetCreated = $true
    & aws cloudformation wait change-set-create-complete --stack-name $StackName --change-set-name $ChangeSetName @awsScope
    if ($LASTEXITCODE -ne 0) { throw "Change set did not become ready" }
    $description = Invoke-AwsJson @("cloudformation", "describe-change-set", "--stack-name", $StackName, "--change-set-name", $ChangeSetName) "Unable to inspect change set"
    # DescribeChangeSet does not return RoleARN. The Prepare role's
    # cloudformation:RoleArn IAM condition is the authoritative role gate; the
    # returned description binds the reviewed request across release phases.
    if ($description.Description -ne $changeSetDescription) { throw "Change set metadata does not match the reviewed execution-role request" }
    Assert-OneMutationChange $description

    Write-Host "Prepared an unexecuted, one-resource Action mutation change set"
    Write-Host "  Git commit: $GitCommit"
    Write-Host "  Artifact SHA256: $artifactSha256"
    Write-Host "  Execution-role request bound to reviewed metadata: True"
    Write-Host "  Previous artifact retained for rollback: True"
    Write-Host "  Change set executed: False"
    Write-Host "  Production effect: False"
} catch {
    if ($changeSetCreated) {
        & aws cloudformation delete-change-set --stack-name $StackName --change-set-name $ChangeSetName @awsScope | Out-Null
    }
    throw
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolved = (Resolve-Path -LiteralPath $temporaryRoot).Path
        $temp = (Resolve-Path -LiteralPath ([System.IO.Path]::GetTempPath())).Path
        if (-not $resolved.StartsWith((Join-Path $temp "glap-action-mutation-prepare-"), [System.StringComparison]::OrdinalIgnoreCase)) { throw "Refusing to clean an unexpected path" }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
