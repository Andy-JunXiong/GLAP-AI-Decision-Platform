[CmdletBinding()]
param(
    [string]$AdminProfile = "default",
    [string]$Region = "us-east-1",
    [string]$RoleName = "glap-stateful-lifecycle-cloudformation-staging-role",
    [string]$PolicyName = "GLAPStatefulLifecycleCloudFormationStagingExecution",
    [string]$FunctionName = "glap-stateful-lifecycle-generator-staging",
    [string]$ExecutionRoleName = "glap-stateful-lifecycle-generator-staging-role",
    [string]$IntegrationControllerFunctionName = "glap-stateful-lifecycle-controller-staging",
    [string]$IntegrationControllerRoleName = "glap-stateful-lifecycle-controller-staging-role",
    [string]$IntegrationQualityGateFunctionName = "glap-stateful-lifecycle-quality-gate-staging",
    [string]$IntegrationQualityGateRoleName = "glap-stateful-lifecycle-quality-gate-staging-role",
    [string]$ActionMutationFunctionName = "glap-lifecycle-action-mutation-staging",
    [string]$ActionMutationRoleName = "glap-lifecycle-action-mutation-staging-role",
    [Parameter(Mandatory)] [string]$ArtifactBucket,
    [string]$ArtifactPrefix = "stateful-lifecycle-staging/artifacts",
    [string]$ActionMutationArtifactPrefix = "action-mutation",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

foreach ($name in @(
    $RoleName, $PolicyName, $FunctionName, $ExecutionRoleName,
    $IntegrationControllerFunctionName, $IntegrationControllerRoleName,
    $IntegrationQualityGateFunctionName, $IntegrationQualityGateRoleName,
    $ActionMutationFunctionName, $ActionMutationRoleName
)) {
    if ($name -notmatch '^[A-Za-z0-9+=,.@_-]{1,128}$') {
        throw "Role, policy, and function names must use safe AWS characters"
    }
}
if ($RoleName -ne "glap-stateful-lifecycle-cloudformation-staging-role") {
    throw "RoleName must retain the reviewed lifecycle staging service-role name"
}
if ($ArtifactBucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') {
    throw "ArtifactBucket must be a valid bucket name"
}
foreach ($prefix in @($ArtifactPrefix, $ActionMutationArtifactPrefix)) {
    if ($prefix -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,511}$' -or
        $prefix.Contains("..")) {
        throw "Artifact prefixes must be safe, prefix-scoped keys"
    }
}

$artifactPrefix = $ArtifactPrefix.Trim('/')
$actionMutationPrefix = $ActionMutationArtifactPrefix.Trim('/')
$awsScope = @("--region", $Region)
if ($AdminProfile) {
    $awsScope += @("--profile", $AdminProfile)
}

function Invoke-AwsJson([string[]]$Arguments, [string]$FailureMessage) {
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) {
        throw $FailureMessage
    }
    return ($json -join "`n") | ConvertFrom-Json
}

function Invoke-AwsCommand([string[]]$Arguments, [string]$FailureMessage) {
    & aws @Arguments @awsScope | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Write-TemporaryJson([string]$Json, [string]$Label) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) (
        "glap-lifecycle-cloudformation-$Label-" + [guid]::NewGuid().ToString("N") + ".json"
    )
    [System.IO.File]::WriteAllText(
        $path,
        $Json,
        [System.Text.UTF8Encoding]::new($false)
    )
    return $path
}

$identity = Invoke-AwsJson @("sts", "get-caller-identity") `
    "Unable to resolve the AWS account from AdminProfile"
$accountId = [string]$identity.Account
$partition = ([string]$identity.Arn).Split(':')[1]
if ($accountId -notmatch '^\d{12}$' -or $partition -notmatch '^aws(-[a-z]+)?$') {
    throw "AWS returned an invalid account identity"
}

$roleArn = "arn:${partition}:iam::${accountId}:role/${RoleName}"
$trustPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Principal = @{ Service = "cloudformation.amazonaws.com" }
            Action = "sts:AssumeRole"
        }
    )
}
$runtimeRoleArns = @(
    $ExecutionRoleName,
    $IntegrationControllerRoleName,
    $IntegrationQualityGateRoleName,
    $ActionMutationRoleName
) | ForEach-Object { "arn:${partition}:iam::${accountId}:role/$_" }
$functionArns = @(
    $FunctionName,
    $IntegrationControllerFunctionName,
    $IntegrationQualityGateFunctionName,
    $ActionMutationFunctionName
) | ForEach-Object { "arn:${partition}:lambda:${Region}:${accountId}:function:$_" }
$executionPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "ReadLifecycleDeploymentArtifacts"
            Effect = "Allow"
            Action = @("s3:GetObject", "s3:GetObjectVersion")
            Resource = @(
                "arn:${partition}:s3:::${ArtifactBucket}/${artifactPrefix}/*",
                "arn:${partition}:s3:::${ArtifactBucket}/${actionMutationPrefix}/*"
            )
        },
        @{
            Sid = "MaintainLifecycleLambdaFunctions"
            Effect = "Allow"
            Action = @(
                "lambda:CreateFunction",
                "lambda:DeleteFunction",
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:TagResource",
                "lambda:UntagResource",
                "lambda:ListTags"
            )
            Resource = $functionArns
        },
        @{
            Sid = "MaintainLifecycleRuntimeRoles"
            Effect = "Allow"
            Action = @(
                "iam:CreateRole",
                "iam:DeleteRole",
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:ListRolePolicies",
                "iam:ListAttachedRolePolicies",
                "iam:PutRolePolicy",
                "iam:DeleteRolePolicy",
                "iam:UpdateAssumeRolePolicy",
                "iam:TagRole",
                "iam:UntagRole"
            )
            Resource = $runtimeRoleArns
        },
        @{
            Sid = "PassLifecycleRuntimeRolesToLambda"
            Effect = "Allow"
            Action = "iam:PassRole"
            Resource = $runtimeRoleArns
            Condition = @{
                StringEquals = @{ "iam:PassedToService" = "lambda.amazonaws.com" }
            }
        },
        @{
            Sid = "MaintainLifecycleAlarms"
            Effect = "Allow"
            Action = @(
                "cloudwatch:PutMetricAlarm",
                "cloudwatch:DeleteAlarms",
                "cloudwatch:DescribeAlarms",
                "cloudwatch:TagResource",
                "cloudwatch:UntagResource"
            )
            Resource = "arn:${partition}:cloudwatch:${Region}:${accountId}:alarm:glap-stateful-lifecycle-staging-*"
        }
    )
}

$trustJson = $trustPolicy | ConvertTo-Json -Depth 20 -Compress
$policyJson = $executionPolicy | ConvertTo-Json -Depth 20 -Compress
$inlinePolicyCharacterLimit = 10240
$minimumHeadroom = 1024
if ($policyJson.Length -gt ($inlinePolicyCharacterLimit - $minimumHeadroom)) {
    throw "Lifecycle CloudFormation policy does not retain required IAM quota headroom"
}

Write-Host "Stateful lifecycle CloudFormation service-role plan"
Write-Host "  Role: $RoleName"
Write-Host "  Trust: cloudformation.amazonaws.com only"
Write-Host "  Policy: $PolicyName ($($policyJson.Length)/$inlinePolicyCharacterLimit characters)"
Write-Host "  Lifecycle artifact prefix scoped: True"
Write-Host "  Action mutation rollback artifact prefix scoped: True"
Write-Host "  Runtime roles and functions exact-resource scoped: True"
Write-Host "  Direct GitHub assumption allowed: False"
Write-Host "  Production alias or schedule permission: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply using an IAM administrator profile."
    return
}

$trustPath = Write-TemporaryJson $trustJson "trust"
$policyPath = Write-TemporaryJson $policyJson "policy"
try {
    $roleExists = $true
    & aws iam get-role --role-name $RoleName @awsScope --output json 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $roleExists = $false
    }
    if (-not $roleExists) {
        Invoke-AwsCommand @(
            "iam", "create-role",
            "--role-name", $RoleName,
            "--assume-role-policy-document", "file://$trustPath",
            "--description", "CloudFormation-only execution role for the isolated GLAP lifecycle staging stack",
            "--tags", "Key=Project,Value=GLAP", "Key=Environment,Value=staging"
        ) "Unable to create the lifecycle CloudFormation service role"
    } else {
        Invoke-AwsCommand @(
            "iam", "update-assume-role-policy",
            "--role-name", $RoleName,
            "--policy-document", "file://$trustPath"
        ) "Unable to update the lifecycle CloudFormation trust policy"
    }
    Invoke-AwsCommand @(
        "iam", "put-role-policy",
        "--role-name", $RoleName,
        "--policy-name", $PolicyName,
        "--policy-document", "file://$policyPath"
    ) "Unable to configure the lifecycle CloudFormation execution policy"

    $verifiedRole = Invoke-AwsJson @("iam", "get-role", "--role-name", $RoleName) `
        "Unable to verify the lifecycle CloudFormation service role"
    $verifiedPolicy = Invoke-AwsJson @(
        "iam", "get-role-policy", "--role-name", $RoleName, "--policy-name", $PolicyName
    ) "Unable to verify the lifecycle CloudFormation execution policy"
    $verifiedInlinePolicies = Invoke-AwsJson @(
        "iam", "list-role-policies", "--role-name", $RoleName
    ) "Unable to verify lifecycle CloudFormation inline-policy isolation"
    $verifiedAttachedPolicies = Invoke-AwsJson @(
        "iam", "list-attached-role-policies", "--role-name", $RoleName
    ) "Unable to verify lifecycle CloudFormation managed-policy isolation"
    $trustStatements = @($verifiedRole.Role.AssumeRolePolicyDocument.Statement)
    $trust = if ($trustStatements.Count -eq 1) { $trustStatements[0] } else { $null }
    $expectedSids = @(
        "ReadLifecycleDeploymentArtifacts",
        "MaintainLifecycleLambdaFunctions",
        "MaintainLifecycleRuntimeRoles",
        "PassLifecycleRuntimeRolesToLambda",
        "MaintainLifecycleAlarms"
    )
    $verifiedSids = @(
        $verifiedPolicy.PolicyDocument.Statement | ForEach-Object { [string]$_.Sid }
    )
    if ([string]$verifiedRole.Role.Arn -ne $roleArn -or
        -not $verifiedPolicy.PolicyDocument -or
        -not $trust -or
        [string]$trust.Principal.Service -ne "cloudformation.amazonaws.com" -or
        [string]$trust.Action -ne "sts:AssumeRole" -or
        @(Compare-Object $expectedSids $verifiedSids).Count -ne 0 -or
        @($verifiedInlinePolicies.PolicyNames).Count -ne 1 -or
        [string]$verifiedInlinePolicies.PolicyNames[0] -ne $PolicyName -or
        @($verifiedAttachedPolicies.AttachedPolicies).Count -ne 0) {
        throw "Lifecycle CloudFormation service-role verification failed"
    }
} finally {
    Remove-Item -LiteralPath $trustPath, $policyPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Lifecycle CloudFormation service role configured and verified."
Write-Host "Set its ARN as the protected staging variable AWS_LIFECYCLE_CF_EXECUTION_ROLE_ARN."
