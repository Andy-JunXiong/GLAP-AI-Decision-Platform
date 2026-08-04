[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-stateful-lifecycle-staging",
    [string]$FunctionName = "glap-stateful-lifecycle-generator-staging",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [string]$Workgroup = "primary",
    [Parameter(Mandatory)] [string]$ArtifactBucket,
    [Parameter(Mandatory)] [string]$LifecycleDataBucket,
    [string]$LifecycleDataPrefix = "stateful-lifecycle-staging",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$ArtifactKey = "stateful-lifecycle-staging/glap-stateful-lifecycle-generator.zip",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

foreach ($identifier in @($StackName, $FunctionName)) {
    if ($identifier -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$') {
        throw "StackName and FunctionName must use safe AWS names"
    }
}
foreach ($bucket in @($ArtifactBucket, $LifecycleDataBucket)) {
    if ($bucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') {
        throw "ArtifactBucket and LifecycleDataBucket must be valid bucket names"
    }
}
if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Athena identifier"
}
if ($Workgroup -notmatch '^[A-Za-z0-9._-]{1,128}$') {
    throw "Workgroup is not a safe Athena workgroup name"
}
if ($LifecycleDataPrefix -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,511}$' -or
    $LifecycleDataPrefix.Contains("..")) {
    throw "LifecycleDataPrefix is not a safe prefix"
}
if ($ArtifactKey -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,1023}$' -or
    $ArtifactKey.Contains("..")) {
    throw "ArtifactKey is not a safe object key"
}
if ($AthenaOutputUri -notmatch '^s3://([^/]+)/(.+)$') {
    throw "AthenaOutputUri must be a prefix-scoped s3:// URI"
}
$athenaResultsBucket = $Matches[1]
$athenaResultsPrefix = $Matches[2].Trim('/') + '/'
$dataPrefix = $LifecycleDataPrefix.Trim('/')

$root = Split-Path $PSScriptRoot -Parent
$templatePath = Join-Path $root "infrastructure/stateful-lifecycle-staging.yaml"
$distDir = Join-Path $root "dist"
$packageDir = Join-Path $distDir "stateful-lifecycle-package"
$archivePath = Join-Path $distDir "glap-stateful-lifecycle-generator.zip"

Write-Host "Stateful lifecycle staging stack plan"
Write-Host "  Stack: $StackName"
Write-Host "  Function: $FunctionName"
Write-Host "  Region: $Region"
Write-Host "  Source database: $SourceDatabase"
Write-Host "  Workgroup: $Workgroup"
Write-Host "  Artifact: s3://$ArtifactBucket/$ArtifactKey"
Write-Host "  Lifecycle data: s3://$LifecycleDataBucket/$dataPrefix/"
Write-Host "  Athena results prefix configured: True"
Write-Host "  Schedule created: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after validating buckets and the OIDC role."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}

$effectiveEngine = & aws athena get-work-group `
    --work-group $Workgroup `
    @awsScope `
    --query "WorkGroup.Configuration.EngineVersion.EffectiveEngineVersion" `
    --output text
if ($LASTEXITCODE -ne 0 -or $effectiveEngine -notmatch 'Athena engine version 3') {
    throw "Athena workgroup must use engine version 3 for transactional Iceberg MERGE"
}

New-Item -ItemType Directory -Path $packageDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_lifecycle_athena_adapter.py") `
    -Destination (Join-Path $packageDir "lambda_function.py") -Force
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_stateful_lifecycle_generator.py") `
    -Destination (Join-Path $packageDir "glap_stateful_lifecycle_generator.py") -Force
Compress-Archive -LiteralPath `
    (Join-Path $packageDir "lambda_function.py"), `
    (Join-Path $packageDir "glap_stateful_lifecycle_generator.py") `
    -DestinationPath $archivePath -Force

& aws s3 cp $archivePath "s3://$ArtifactBucket/$ArtifactKey" @awsScope --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw "Unable to upload the lifecycle Lambda artifact"
}

$parameterOverrides = @(
    "ArtifactBucket=$ArtifactBucket",
    "GeneratorArtifactKey=$ArtifactKey",
    "AthenaOutputUri=$AthenaOutputUri",
    "AthenaResultsBucketName=$athenaResultsBucket",
    "AthenaResultsPrefix=$athenaResultsPrefix",
    "LifecycleDataBucketArn=arn:aws:s3:::$LifecycleDataBucket",
    "LifecycleDataObjectArn=arn:aws:s3:::$LifecycleDataBucket/$dataPrefix/*",
    "AthenaWorkgroup=$Workgroup",
    "SourceDatabase=$SourceDatabase",
    "FunctionName=$FunctionName"
)
& aws cloudformation deploy `
    --stack-name $StackName `
    --template-file $templatePath `
    --capabilities CAPABILITY_IAM `
    --no-fail-on-empty-changeset `
    --parameter-overrides @parameterOverrides `
    @awsScope
if ($LASTEXITCODE -ne 0) {
    throw "Lifecycle staging stack deployment failed"
}

Write-Host "Lifecycle staging stack deployed without a schedule or production controller connection."
