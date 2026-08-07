[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-operations-identity-staging",
    [string]$InternalBranchName = "staging",
    [string]$UserPoolDomainPrefix = "",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
foreach ($name in @($StackName, $InternalBranchName)) {
    if ($name -notmatch '^[A-Za-z0-9-]{1,128}$') {
        throw "Stack and branch names must use safe characters"
    }
}
if ($UserPoolDomainPrefix -and $UserPoolDomainPrefix -notmatch '^[a-z0-9-]{1,63}$') {
    throw "UserPoolDomainPrefix must use lowercase letters, digits, and hyphens"
}

$root = Split-Path $PSScriptRoot -Parent
$template = Join-Path $root "infrastructure/operations-identity-staging.yaml"
$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }

Write-Host "Operations identity and internal hosting staging plan"
Write-Host "  Stack: $StackName"
Write-Host "  Region: $Region"
Write-Host "  Internal branch: $InternalBranchName"
Write-Host "  Cognito self-sign-up: False"
Write-Host "  OAuth flow: Authorization code with PKCE"
Write-Host "  Public Pages connection: False"
Write-Host "  Repository connection: False"
Write-Host "  Production resources: False"

& aws cloudformation validate-template --template-body "file://$template" @awsScope | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Identity stack template validation failed" }

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply to create the staging resources."
    return
}

$parameters = @("InternalBranchName=$InternalBranchName")
if ($UserPoolDomainPrefix) {
    $parameters += "UserPoolDomainPrefix=$UserPoolDomainPrefix"
}
& aws cloudformation deploy --template-file $template --stack-name $StackName `
    @awsScope --no-fail-on-empty-changeset --parameter-overrides @parameters
if ($LASTEXITCODE -ne 0) { throw "Operations identity stack deployment failed" }

Write-Host "Operations identity and internal hosting staging stack deployed."
Write-Host "Protected output values were not printed."
