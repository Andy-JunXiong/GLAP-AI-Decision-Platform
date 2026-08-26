[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-stateful-lifecycle-generator-staging",
    [string]$FunctionName = "glap-stateful-lifecycle-generator-staging",
    [Parameter(Mandatory)] [string]$ArtifactBucket,
    [Parameter(Mandatory)] [string]$ArtifactKey,
    [Parameter(Mandatory)] [string]$CloudFormationRoleArn,
    [switch]$InspectChangeSet,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if ($Apply -eq $InspectChangeSet) {
    throw "Choose exactly one of Apply or InspectChangeSet"
}
if ($StackName -ne "glap-stateful-lifecycle-generator-staging" -or
    $FunctionName -ne "glap-stateful-lifecycle-generator-staging") {
    throw "Independent generator release is fixed to isolated staging"
}
if ($ArtifactBucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$' -or
    $ArtifactKey -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,1023}$' -or
    $ArtifactKey.Contains("..")) {
    throw "Generator artifact location is unsafe"
}
if ($CloudFormationRoleArn -notmatch (
    '^arn:aws(-[a-z]+)?:iam::\d{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*' +
    'glap-stateful-lifecycle-cloudformation-staging-role$'
)) {
    throw "CloudFormationRoleArn must identify the lifecycle staging service role"
}

$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }
$stackJson = & aws cloudformation describe-stacks --stack-name $StackName @awsScope --output json
if ($LASTEXITCODE -ne 0 -or -not $stackJson) {
    throw "Independent generator stack must be created by the reviewed stack refactor first"
}
$stack = ($stackJson -join "`n" | ConvertFrom-Json).Stacks[0]
if ([string]$stack.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE")) {
    throw "Independent generator stack is not stable"
}
$resourcesJson = & aws cloudformation list-stack-resources --stack-name $StackName @awsScope --output json
if ($LASTEXITCODE -ne 0 -or -not $resourcesJson) { throw "Unable to inspect generator stack resources" }
$resources = @(($resourcesJson -join "`n" | ConvertFrom-Json).StackResourceSummaries)
if ($resources.Count -ne 1 -or
    [string]$resources[0].LogicalResourceId -ne "LifecycleGeneratorFunction" -or
    [string]$resources[0].ResourceType -ne "AWS::Lambda::Function" -or
    [string]$resources[0].PhysicalResourceId -ne $FunctionName) {
    throw "Independent generator stack must own exactly one expected Lambda function"
}
$artifactBucketParameter = @($stack.Parameters | Where-Object ParameterKey -eq "ArtifactBucket")
$generatorArtifactParameter = @($stack.Parameters | Where-Object ParameterKey -eq "GeneratorArtifactKey")
if ($artifactBucketParameter.Count -ne 1 -or
    [string]$artifactBucketParameter[0].ParameterValue -ne $ArtifactBucket -or
    $generatorArtifactParameter.Count -ne 1) {
    throw "Independent generator stack artifact parameters are unavailable or mismatched"
}
$parameterArguments = @(
    $stack.Parameters | ForEach-Object {
        $key = [string]$_.ParameterKey
        if ($key -notmatch '^[A-Za-z][A-Za-z0-9]{0,254}$') { throw "Unsafe stack parameter key" }
        if ($key -eq "GeneratorArtifactKey") {
            "ParameterKey=$key,ParameterValue=$ArtifactKey"
        } else {
            "ParameterKey=$key,UsePreviousValue=true"
        }
    }
)
if (@($parameterArguments | Where-Object { $_ -match ',ParameterValue=' }).Count -ne 1) {
    throw "Generator release must override exactly one stack parameter"
}

$root = Split-Path $PSScriptRoot -Parent
$distDir = Join-Path $root "dist"
$packageDir = Join-Path $distDir "stateful-lifecycle-generator-package"
$archivePath = Join-Path $distDir "glap-stateful-lifecycle-generator.zip"
if ($Apply) {
    New-Item -ItemType Directory -Path $packageDir -Force | Out-Null
    $copies = @{
        "lambda/glap_lifecycle_athena_adapter.py" = "lambda_function.py"
        "lambda/glap_stateful_lifecycle_generator.py" = "glap_stateful_lifecycle_generator.py"
        "lambda/glap_temporal_boundary.py" = "glap_temporal_boundary.py"
        "lambda/glap_governed_closed_loop.py" = "glap_governed_closed_loop.py"
    }
    foreach ($entry in $copies.GetEnumerator()) {
        Copy-Item -LiteralPath (Join-Path $root $entry.Key) -Destination (Join-Path $packageDir $entry.Value) -Force
    }
    Compress-Archive -LiteralPath @($copies.Values | ForEach-Object { Join-Path $packageDir $_ }) -DestinationPath $archivePath -Force
    & aws s3 cp $archivePath "s3://$ArtifactBucket/$ArtifactKey" @awsScope --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw "Unable to upload the independent generator artifact" }
}

$changeSetName = "generator-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$created = $false
try {
    & aws cloudformation create-change-set `
        --stack-name $StackName --change-set-name $changeSetName --change-set-type UPDATE `
        --use-previous-template --role-arn $CloudFormationRoleArn `
        --capabilities CAPABILITY_NAMED_IAM --parameters @parameterArguments @awsScope --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the independent generator change set" }
    $created = $true
    & aws cloudformation wait change-set-create-complete --stack-name $StackName --change-set-name $changeSetName @awsScope
    if ($LASTEXITCODE -ne 0) { throw "Independent generator change set did not become ready" }
    $changeSetJson = & aws cloudformation describe-change-set --stack-name $StackName --change-set-name $changeSetName @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $changeSetJson) { throw "Unable to inspect generator change set" }
    $changes = @(($changeSetJson -join "`n" | ConvertFrom-Json).Changes)
    if ($changes.Count -ne 1 -or
        [string]$changes[0].ResourceChange.Action -ne "Modify" -or
        [string]$changes[0].ResourceChange.LogicalResourceId -ne "LifecycleGeneratorFunction" -or
        [string]$changes[0].ResourceChange.ResourceType -ne "AWS::Lambda::Function" -or
        [string]$changes[0].ResourceChange.Replacement -ne "False") {
        throw "Independent generator change set must contain exactly one non-replacing Lambda modification"
    }
    Write-Host "Sanitized independent generator change set: Modify LifecycleGeneratorFunction; Replacement=False"
    if ($InspectChangeSet) {
        & aws cloudformation delete-change-set --stack-name $StackName --change-set-name $changeSetName @awsScope | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to delete inspected generator change set" }
        $created = $false
        Write-Host "Independent generator change set inspected and deleted without upload or execution."
        return
    }
    & aws cloudformation execute-change-set --stack-name $StackName --change-set-name $changeSetName @awsScope
    if ($LASTEXITCODE -ne 0) { throw "Unable to execute independent generator change set" }
    & aws cloudformation wait stack-update-complete --stack-name $StackName @awsScope
    if ($LASTEXITCODE -ne 0) { throw "Independent generator stack update failed" }
    $created = $false
} catch {
    if ($created) {
        & aws cloudformation delete-change-set --stack-name $StackName --change-set-name $changeSetName @awsScope 2>$null | Out-Null
    }
    throw
}
Write-Host "Independent lifecycle generator released without controller, role, alarm, schema, date, schedule, alias, Action, or production change."
