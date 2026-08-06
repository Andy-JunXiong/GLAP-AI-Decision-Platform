[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-operations-api-staging",
    [Parameter(Mandatory)] [string]$ArtifactBucket,
    [string]$ApiArtifactKey = "stateful-lifecycle-staging/artifacts/glap-operations-api.zip",
    [Parameter(Mandatory)] [string]$JwtIssuer,
    [Parameter(Mandatory)] [string]$JwtAudience,
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [Parameter(Mandatory)] [string]$AthenaResultsBucketArn,
    [Parameter(Mandatory)] [string]$LifecycleDataBucketArn,
    [Parameter(Mandatory)] [string]$AllowedOrigin,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if ($JwtIssuer -notmatch '^https://') { throw "JwtIssuer must be HTTPS" }
if ($AllowedOrigin -notmatch '^https://') { throw "AllowedOrigin must be one exact HTTPS origin" }
if ($AthenaOutputUri -notmatch '^s3://[^/]+/.+$') { throw "AthenaOutputUri must be prefix scoped" }
if ($ArtifactBucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') { throw "Invalid artifact bucket" }

$root = Split-Path $PSScriptRoot -Parent
$template = Join-Path $root "infrastructure/operations-api-staging.yaml"
$packageDir = Join-Path $root "dist/operations-api-package"
$archive = Join-Path $root "dist/glap-operations-api.zip"

Write-Host "Authenticated Operations API staging plan"
Write-Host "  Stack: $StackName"
Write-Host "  JWT issuer: $JwtIssuer"
Write-Host "  Allowed origin: $AllowedOrigin"
Write-Host "  Public Pages write access: False"
Write-Host "  Schedule or production alias: False"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after identity and origin review."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_operations_api.py") `
    -Destination (Join-Path $packageDir "lambda_function.py") -Force
Compress-Archive -LiteralPath (Join-Path $packageDir "lambda_function.py") `
    -DestinationPath $archive -Force
& aws s3 cp $archive "s3://$ArtifactBucket/$ApiArtifactKey" @awsScope --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Unable to upload Operations API artifact" }

& aws cloudformation deploy --template-file $template --stack-name $StackName `
    --capabilities CAPABILITY_NAMED_IAM @awsScope --no-fail-on-empty-changeset `
    --parameter-overrides `
      "ArtifactBucket=$ArtifactBucket" "ApiArtifactKey=$ApiArtifactKey" `
      "JwtIssuer=$JwtIssuer" "JwtAudience=$JwtAudience" `
      "AthenaOutputUri=$AthenaOutputUri" `
      "AthenaResultsBucketArn=$AthenaResultsBucketArn" `
      "LifecycleDataBucketArn=$LifecycleDataBucketArn" `
      "AllowedOrigin=$AllowedOrigin"
if ($LASTEXITCODE -ne 0) { throw "Operations API stack deployment failed" }
