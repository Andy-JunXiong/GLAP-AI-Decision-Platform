[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$IdentityStackName = "glap-operations-identity-staging",
    [string]$ApiStackName = "glap-operations-api-staging",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$frontend = Join-Path $root "decision-brief-demo"
$archive = Join-Path $root "dist/glap-operations-internal-frontend.zip"
$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }

Write-Host "Internal Operations frontend staging plan"
Write-Host "  Identity stack: $IdentityStackName"
Write-Host "  API stack: $ApiStackName"
Write-Host "  Authentication: Cognito authorization code with PKCE"
Write-Host "  Browser token storage: Session only"
Write-Host "  Public Pages deployment: False"
Write-Host "  Production deployment: False"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after both staging stacks exist."
    return
}

function Get-StackOutput([string]$Stack, [string]$Key) {
    $value = & aws cloudformation describe-stacks --stack-name $Stack @awsScope `
        --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue | [0]" --output text
    if ($LASTEXITCODE -ne 0 -or -not $value -or $value -eq "None") {
        throw "Required protected stack output is unavailable: $Key"
    }
    return $value.Trim()
}

$apiUrl = Get-StackOutput $ApiStackName "ApiEndpoint"
$clientId = Get-StackOutput $IdentityStackName "JwtAudience"
$cognitoDomain = Get-StackOutput $IdentityStackName "CognitoHostedUiDomain"
$internalOrigin = Get-StackOutput $IdentityStackName "InternalOrigin"
$appId = Get-StackOutput $IdentityStackName "AmplifyAppId"
$branchName = Get-StackOutput $IdentityStackName "AmplifyBranchName"

$env:NEXT_PUBLIC_GLAP_OPERATIONS_API_URL = $apiUrl
$env:NEXT_PUBLIC_GLAP_COGNITO_CLIENT_ID = $clientId
$env:NEXT_PUBLIC_GLAP_COGNITO_DOMAIN = $cognitoDomain
$env:NEXT_PUBLIC_GLAP_INTERNAL_ORIGIN = $internalOrigin
$env:GLAP_INTERNAL_STATIC_EXPORT = "1"

$npm = if ($IsWindows -or $env:OS -eq "Windows_NT") { "npm.cmd" } else { "npm" }
Push-Location $frontend
try {
    & $npm run build:internal
    if ($LASTEXITCODE -ne 0) { throw "Internal frontend build failed" }
} finally {
    Pop-Location
}

$out = Join-Path $frontend "out"
if (-not (Test-Path -LiteralPath (Join-Path $out "index.html"))) {
    throw "Static export did not produce index.html"
}
New-Item -ItemType Directory -Path (Split-Path $archive -Parent) -Force | Out-Null
Compress-Archive -Path (Join-Path $out "*") -DestinationPath $archive -Force

$deploymentJson = & aws amplify create-deployment --app-id $appId `
    --branch-name $branchName @awsScope --output json
if ($LASTEXITCODE -ne 0 -or -not $deploymentJson) {
    throw "Unable to create the private Amplify deployment"
}
$deployment = $deploymentJson | ConvertFrom-Json
if (-not $deployment.zipUploadUrl -or -not $deployment.jobId) {
    throw "Amplify returned an incomplete deployment contract"
}
Invoke-WebRequest -Uri $deployment.zipUploadUrl -Method Put -InFile $archive `
    -ContentType "application/zip" -UseBasicParsing | Out-Null
& aws amplify start-deployment --app-id $appId --branch-name $branchName `
    --job-id $deployment.jobId @awsScope | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to start the private Amplify deployment" }

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $status = & aws amplify get-job --app-id $appId --branch-name $branchName `
        --job-id $deployment.jobId @awsScope --query "job.summary.status" --output text
    if ($status -eq "SUCCEED") {
        Write-Host "Internal Operations frontend deployed successfully."
        Write-Host "Protected origin and deployment identifiers were not printed."
        return
    }
    if ($status -in @("FAILED", "CANCELLED")) {
        throw "Internal Operations frontend deployment failed"
    }
    Start-Sleep -Seconds 10
}
throw "Timed out waiting for the internal Operations frontend deployment"
