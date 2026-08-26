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
$functionJson = & aws lambda get-function-configuration --function-name $FunctionName @awsScope --output json
if ($LASTEXITCODE -ne 0 -or -not $functionJson) {
    throw "Unable to inspect the deployed independent generator"
}
$function = ($functionJson -join "`n" | ConvertFrom-Json)
$environment = $function.Environment.Variables
if ([string]$function.FunctionName -ne $FunctionName -or
    [string]$function.State -ne "Active" -or
    [string]$function.LastUpdateStatus -ne "Successful" -or
    [string]$function.Role -notmatch (
        '^arn:aws(-[a-z]+)?:iam::\d{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*' +
        'glap-stateful-lifecycle-generator-staging-role$'
    ) -or
    [string]$environment.ATHENA_OUTPUT -notmatch '^s3://[^/]+/.+$' -or
    [string]$environment.ATHENA_WORKGROUP -notmatch '^[A-Za-z0-9._-]{1,128}$' -or
    [string]$environment.ATHENA_SOURCE_DATABASE -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Deployed independent generator configuration is outside the release contract"
}

$safeValues = @{
    ARTIFACT_BUCKET = $ArtifactBucket
    GENERATOR_ARTIFACT_KEY = $ArtifactKey
    FUNCTION_NAME = $FunctionName
    EXECUTION_ROLE_ARN = [string]$function.Role
    ATHENA_OUTPUT_URI = [string]$environment.ATHENA_OUTPUT
    ATHENA_WORKGROUP = [string]$environment.ATHENA_WORKGROUP
    SOURCE_DATABASE = [string]$environment.ATHENA_SOURCE_DATABASE
}
foreach ($value in $safeValues.Values) {
    if ($value -match '["\r\n]' -or -not $value) {
        throw "Generator release template values must be non-empty single-line safe strings"
    }
}

$root = Split-Path $PSScriptRoot -Parent
$templatePath = Join-Path $root "infrastructure/stateful-lifecycle-generator-staging.yaml"
$renderedTemplate = [IO.File]::ReadAllText($templatePath)
foreach ($entry in $safeValues.GetEnumerator()) {
    $renderedTemplate = $renderedTemplate.Replace("{{$($entry.Key)}}", $entry.Value)
}
if ($renderedTemplate -match '{{[A-Z_]+}}') {
    throw "Generator release template contains unresolved placeholders"
}
foreach ($forbiddenSection in @("Parameters", "Mappings", "Conditions", "Rules", "Transform")) {
    if ($renderedTemplate -match "(?m)^$forbiddenSection\s*:") {
        throw "Generator release template cannot contain $forbiddenSection"
    }
}

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
$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ("glap-generator-release-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
$renderedTemplatePath = Join-Path $temporaryDirectory "generator.yaml"
[IO.File]::WriteAllText($renderedTemplatePath, $renderedTemplate, [Text.UTF8Encoding]::new($false))
try {
    & aws cloudformation create-change-set `
        --stack-name $StackName --change-set-name $changeSetName --change-set-type UPDATE `
        --template-body "file://$renderedTemplatePath" --role-arn $CloudFormationRoleArn `
        --capabilities CAPABILITY_NAMED_IAM @awsScope --output json | Out-Null
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
} finally {
    if (Test-Path -LiteralPath $temporaryDirectory) {
        Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
    }
}
Write-Host "Independent lifecycle generator released without controller, role, alarm, schema, date, schedule, alias, Action, or production change."
