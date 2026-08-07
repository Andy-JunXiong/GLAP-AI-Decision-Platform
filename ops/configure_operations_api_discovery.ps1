[CmdletBinding()]
param(
    [string]$AdminProfile = "default",
    [string]$Region = "us-east-1",
    [string]$RoleName = "glap-github-staging-deployer",
    [string]$PolicyName = "GLAPOperationsIdentityDiscovery",
    [string]$IdentityStackName = "glap-operations-identity-staging",
    [string]$PipelineReliabilityStackName = "glap-pipeline-reliability-staging",
    [string]$ActionMutationFunctionName = "glap-lifecycle-action-mutation-staging",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

foreach ($name in @(
    $RoleName, $PolicyName, $IdentityStackName, $PipelineReliabilityStackName,
    $ActionMutationFunctionName
)) {
    if ($name -notmatch '^[A-Za-z0-9+=,.@_-]{1,128}$') {
        throw "Role and policy names must use safe AWS characters"
    }
}
if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase must be a safe Glue identifier"
}

$identityArgs = @("sts", "get-caller-identity", "--region", $Region, "--output", "json")
if ($AdminProfile) {
    $identityArgs += @("--profile", $AdminProfile)
}
$identityJson = & aws @identityArgs
if ($LASTEXITCODE -ne 0 -or -not $identityJson) {
    throw "Unable to resolve the AWS account from AdminProfile"
}
$accountId = ($identityJson | ConvertFrom-Json).Account
if ($accountId -notmatch '^\d{12}$') {
    throw "AWS returned an invalid account ID"
}

$policy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "ListOperationsIdentityCandidates"
            Effect = "Allow"
            Action = @(
                "cognito-idp:ListUserPools",
                "amplify:ListApps"
            )
            Resource = "*"
        },
        @{
            Sid = "ListOperationsAudienceCandidates"
            Effect = "Allow"
            Action = "cognito-idp:ListUserPoolClients"
            Resource = "arn:aws:cognito-idp:${Region}:${accountId}:userpool/*"
        },
        @{
            Sid = "ListOperationsCustomDomainCandidates"
            Effect = "Allow"
            Action = "apigateway:GET"
            Resource = "arn:aws:apigateway:${Region}::/domainnames*"
        },
        @{
            Sid = "ReadDedicatedOperationsIdentityOutputs"
            Effect = "Allow"
            Action = "cloudformation:DescribeStacks"
            Resource = @(
                "arn:aws:cloudformation:${Region}:${accountId}:stack/${IdentityStackName}/*",
                "arn:aws:cloudformation:${Region}:${accountId}:stack/${PipelineReliabilityStackName}/*"
            )
        },
        @{
            Sid = "VerifyOperationsMutationDependency"
            Effect = "Allow"
            Action = "lambda:GetFunction"
            Resource = "arn:aws:lambda:${Region}:${accountId}:function:${ActionMutationFunctionName}"
        },
        @{
            Sid = "VerifyOperationsQueueViewDependency"
            Effect = "Allow"
            Action = "glue:GetTable"
            Resource = @(
                "arn:aws:glue:${Region}:${accountId}:catalog",
                "arn:aws:glue:${Region}:${accountId}:database/${SourceDatabase}",
                "arn:aws:glue:${Region}:${accountId}:table/${SourceDatabase}/vw_lifecycle_action_current_staging_v1"
            )
        }
    )
}

$policyJson = $policy | ConvertTo-Json -Depth 10 -Compress
Write-Host "Operations API protected-configuration discovery policy plan"
Write-Host "  Role: $RoleName"
Write-Host "  Separate inline policy: $PolicyName"
Write-Host "  Cognito and origin discovery: Read only"
Write-Host "  Dedicated identity stack outputs: Read only"
Write-Host "  Pipeline reliability stack output: Read only"
Write-Host "  Named Lambda and Glue dependencies: Read only"
Write-Host "  Deployment permissions: False"
Write-Host "  Self-modifying deployer permission: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply using an IAM administrator profile."
    return
}

$policyPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    "glap-operations-discovery-" + [guid]::NewGuid().ToString("N") + ".json"
)
try {
    [System.IO.File]::WriteAllText(
        $policyPath,
        $policyJson,
        [System.Text.UTF8Encoding]::new($false)
    )
    $putArgs = @(
        "iam", "put-role-policy",
        "--role-name", $RoleName,
        "--policy-name", $PolicyName,
        "--policy-document", "file://$policyPath",
        "--region", $Region
    )
    if ($AdminProfile) {
        $putArgs += @("--profile", $AdminProfile)
    }
    & aws @putArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to configure Operations API discovery access"
    }
} finally {
    Remove-Item -LiteralPath $policyPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Read-only Operations API discovery access configured. Re-run the plan workflow."
