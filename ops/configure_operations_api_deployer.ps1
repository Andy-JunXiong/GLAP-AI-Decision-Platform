[CmdletBinding()]
param(
    [string]$AdminProfile = "default",
    [string]$Region = "us-east-1",
    [string]$GitHubRoleName = "glap-github-staging-deployer",
    [string]$GitHubPolicyName = "GLAPOperationsApiStagingDeploy",
    [string]$ExecutionRoleName = "glap-operations-api-cloudformation-staging-role",
    [string]$ExecutionPolicyName = "GLAPOperationsApiStackExecution",
    [string]$StackName = "glap-operations-api-staging",
    [Parameter(Mandatory)] [string]$ArtifactBucket,
    [string]$ArtifactPrefix = "stateful-lifecycle-staging/artifacts",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
foreach ($name in @(
    $GitHubRoleName, $GitHubPolicyName, $ExecutionRoleName,
    $ExecutionPolicyName, $StackName
)) {
    if ($name -notmatch '^[A-Za-z0-9+=,.@_-]{1,128}$') {
        throw "Role, policy, and stack names must use safe AWS characters"
    }
}
if ($ArtifactBucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') {
    throw "Invalid artifact bucket"
}
if ($ArtifactPrefix -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{1,254}$' -or
    $ArtifactPrefix.Contains("..")) {
    throw "Invalid artifact prefix"
}
$ArtifactPrefix = $ArtifactPrefix.Trim('/')

$awsScope = @("--region", $Region)
if ($AdminProfile) { $awsScope += @("--profile", $AdminProfile) }

function Invoke-AwsJson([string[]]$Arguments) {
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) { throw "Required AWS read failed" }
    return $json | ConvertFrom-Json
}

function Get-PhysicalResource($Resources, [string]$LogicalId) {
    $value = [string](
        $Resources | Where-Object LogicalResourceId -eq $LogicalId
    ).PhysicalResourceId
    if (-not $value) { throw "Required stack resource is unavailable: $LogicalId" }
    return $value
}

function Write-TemporaryJson($Value, [string]$Label) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) (
        "glap-operations-$Label-" + [guid]::NewGuid().ToString("N") + ".json"
    )
    [System.IO.File]::WriteAllText(
        $path,
        ($Value | ConvertTo-Json -Depth 30 -Compress),
        [System.Text.UTF8Encoding]::new($false)
    )
    return $path
}

$identity = Invoke-AwsJson @("sts", "get-caller-identity")
$accountId = [string]$identity.Account
$partition = ([string]$identity.Arn).Split(':')[1]
if ($accountId -notmatch '^\d{12}$' -or $partition -notmatch '^aws(-[a-z]+)?$') {
    throw "AWS returned an invalid account identity"
}
$stack = Invoke-AwsJson @(
    "cloudformation", "describe-stacks", "--stack-name", $StackName
)
if ([string]$stack.Stacks[0].StackStatus -notmatch '^(CREATE|UPDATE)_COMPLETE$') {
    throw "Operations API staging stack is not stable"
}
$resources = @((Invoke-AwsJson @(
    "cloudformation", "describe-stack-resources", "--stack-name", $StackName
)).StackResources)
$apiId = Get-PhysicalResource $resources "OperationsApi"
$functionName = Get-PhysicalResource $resources "OperationsApiFunction"
$runtimeRoleName = Get-PhysicalResource $resources "OperationsApiRole"
$queueUrl = Get-PhysicalResource $resources "OperationsApiDLQ"
$accessLogGroup = Get-PhysicalResource $resources "OperationsApiAccessLogGroup"
$failureAlarm = Get-PhysicalResource $resources "OperationsApiFailureAlarm"
$throttleAlarm = Get-PhysicalResource $resources "OperationsApiThrottleAlarm"
if ($apiId -notmatch '^[a-z0-9]{10}$' -or
    $functionName -ne "glap-operations-api-staging" -or
    $runtimeRoleName -notmatch '^glap-operations-api-staging-OperationsApiRole-[A-Za-z0-9]+$' -or
    $accessLogGroup -ne "/aws/apigateway/glap-operations-api-staging/access" -or
    $failureAlarm -notmatch '^glap-operations-api-staging-' -or
    $throttleAlarm -notmatch '^glap-operations-api-staging-') {
    throw "Operations API physical resources do not match the reviewed staging boundary"
}
$queue = Invoke-AwsJson @(
    "sqs", "get-queue-attributes", "--queue-url", $queueUrl,
    "--attribute-names", "QueueArn"
)
$queueArn = [string]$queue.Attributes.QueueArn
if ($queueArn -notmatch "^arn:$partition`:sqs:$Region`:$accountId`:glap-operations-api-staging-") {
    throw "Operations API queue is outside the reviewed staging boundary"
}

$executionRoleArn = "arn:${partition}:iam::${accountId}:role/${ExecutionRoleName}"
$githubPolicyArn = "arn:${partition}:iam::${accountId}:policy/${GitHubPolicyName}"
$runtimeRoleArn = "arn:${partition}:iam::${accountId}:role/${runtimeRoleName}"
$functionArn = "arn:${partition}:lambda:${Region}:${accountId}:function:${functionName}"
$stackArn = "arn:${partition}:cloudformation:${Region}:${accountId}:stack/${StackName}/*"
$apiArn = "arn:${partition}:apigateway:${Region}::/apis/${apiId}*"
$logGroupArn = "arn:${partition}:logs:${Region}:${accountId}:log-group:${accessLogGroup}:*"
$alarmArns = @(
    "arn:${partition}:cloudwatch:${Region}:${accountId}:alarm:${failureAlarm}",
    "arn:${partition}:cloudwatch:${Region}:${accountId}:alarm:${throttleAlarm}"
)
$artifactBucketArn = "arn:${partition}:s3:::${ArtifactBucket}"
$artifactObjectArn = "${artifactBucketArn}/${ArtifactPrefix}/*"

$trustPolicy = @{
    Version = "2012-10-17"
    Statement = @(@{
        Effect = "Allow"
        Principal = @{Service = "cloudformation.amazonaws.com"}
        Action = "sts:AssumeRole"
    })
}
$executionPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "ReadOperationsApiArtifact"
            Effect = "Allow"
            Action = @("s3:GetBucketLocation", "s3:GetObject")
            Resource = @($artifactBucketArn, $artifactObjectArn)
        },
        @{
            Sid = "UpdateOperationsApiLambda"
            Effect = "Allow"
            Action = @(
                "lambda:GetFunction", "lambda:GetFunctionConfiguration",
                "lambda:GetFunctionCodeSigningConfig", "lambda:GetFunctionRecursionConfig",
                "lambda:GetRuntimeManagementConfig",
                "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
                "lambda:AddPermission", "lambda:RemovePermission",
                "lambda:TagResource", "lambda:UntagResource", "lambda:ListTags"
            )
            Resource = @($functionArn, "${functionArn}:*")
        },
        @{
            Sid = "UpdateOperationsApiRuntimeRole"
            Effect = "Allow"
            Action = @(
                "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies",
                "iam:ListAttachedRolePolicies",
                "iam:PutRolePolicy", "iam:DeleteRolePolicy",
                "iam:UpdateAssumeRolePolicy", "iam:TagRole", "iam:UntagRole"
            )
            Resource = $runtimeRoleArn
        },
        @{
            Sid = "PassOperationsApiRuntimeRoleToLambda"
            Effect = "Allow"
            Action = "iam:PassRole"
            Resource = $runtimeRoleArn
            Condition = @{StringEquals = @{"iam:PassedToService" = "lambda.amazonaws.com"}}
        },
        @{
            Sid = "UpdateExistingOperationsApiGateway"
            Effect = "Allow"
            Action = @("apigateway:GET", "apigateway:POST", "apigateway:PUT", "apigateway:PATCH", "apigateway:DELETE")
            Resource = $apiArn
        },
        @{
            Sid = "UpdateOperationsApiQueue"
            Effect = "Allow"
            Action = @(
                "sqs:GetQueueAttributes", "sqs:SetQueueAttributes",
                "sqs:GetQueueUrl", "sqs:ListQueueTags", "sqs:TagQueue", "sqs:UntagQueue"
            )
            Resource = $queueArn
        },
        @{
            Sid = "ReadOperationsApiLogConfiguration"
            Effect = "Allow"
            Action = @(
                "logs:DescribeIndexPolicies", "logs:DescribeLogGroups",
                "logs:DescribeResourcePolicies"
            )
            Resource = "*"
        },
        @{
            Sid = "UpdateOperationsApiLogs"
            Effect = "Allow"
            Action = @(
                "logs:DescribeMetricFilters", "logs:PutMetricFilter", "logs:DeleteMetricFilter",
                "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
                "logs:ListTagsForResource", "logs:TagResource", "logs:UntagResource"
            )
            Resource = $logGroupArn
        },
        @{
            Sid = "ReadOperationsApiAlarms"
            Effect = "Allow"
            Action = "cloudwatch:DescribeAlarms"
            Resource = "*"
        },
        @{
            Sid = "UpdateOperationsApiAlarms"
            Effect = "Allow"
            Action = @(
                "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms",
                "cloudwatch:TagResource", "cloudwatch:UntagResource"
            )
            Resource = $alarmArns
        }
    )
}
$githubPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "UseOperationsApiArtifactPrefix"
            Effect = "Allow"
            Action = @("s3:GetBucketLocation", "s3:ListBucket")
            Resource = $artifactBucketArn
            Condition = @{StringLike = @{"s3:prefix" = @(
                $ArtifactPrefix, "${ArtifactPrefix}/*"
            )}}
        },
        @{
            Sid = "WriteOperationsApiArtifacts"
            Effect = "Allow"
            Action = @("s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload")
            Resource = $artifactObjectArn
        },
        @{
            Sid = "DeployExistingOperationsApiStack"
            Effect = "Allow"
            Action = @(
                "cloudformation:CreateChangeSet", "cloudformation:DescribeChangeSet",
                "cloudformation:ExecuteChangeSet", "cloudformation:DeleteChangeSet",
                "cloudformation:DescribeStacks", "cloudformation:DescribeStackEvents",
                "cloudformation:ListStackResources"
            )
            Resource = $stackArn
        },
        @{
            Sid = "InspectOperationsApiTemplate"
            Effect = "Allow"
            Action = @("cloudformation:ValidateTemplate", "cloudformation:GetTemplateSummary")
            Resource = "*"
        },
        @{
            Sid = "PassOperationsApiExecutionRoleToCloudFormation"
            Effect = "Allow"
            Action = "iam:PassRole"
            Resource = $executionRoleArn
            Condition = @{StringEquals = @{"iam:PassedToService" = "cloudformation.amazonaws.com"}}
        }
    )
}

Write-Host "Operations API GitHub deployer policy plan"
Write-Host "  GitHub role orchestration only: True"
Write-Host "  GitHub orchestration policy is customer-managed: True"
Write-Host "  Dedicated CloudFormation execution role: True"
Write-Host "  Existing Operations API stack and physical resources only: True"
Write-Host "  Artifact prefix scoped: True"
Write-Host "  Top-level resource creation or replacement permission: False"
Write-Host "  Production resource permission: False"
Write-Host "  Schedule or alias permission: False"
Write-Host "  GitHub role self-modification permission: False"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply using an IAM administrator profile."
    return
}

$trustPath = Write-TemporaryJson $trustPolicy "cf-trust"
$executionPath = Write-TemporaryJson $executionPolicy "cf-policy"
$githubPath = Write-TemporaryJson $githubPolicy "github-policy"
try {
    $roles = Invoke-AwsJson @("iam", "list-roles")
    $roleExists = @(
        $roles.Roles | Where-Object RoleName -eq $ExecutionRoleName
    ).Count -eq 1
    if ($roleExists) {
        & aws iam update-assume-role-policy --role-name $ExecutionRoleName `
            --policy-document "file://$trustPath" @awsScope
    } else {
        & aws iam create-role --role-name $ExecutionRoleName `
            --assume-role-policy-document "file://$trustPath" `
            --description "Staging-only CloudFormation execution role for the existing GLAP Operations API stack" `
            --tags Key=Project,Value=GLAP Key=Environment,Value=staging `
            @awsScope | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "Unable to configure the execution role trust" }
    & aws iam put-role-policy --role-name $ExecutionRoleName `
        --policy-name $ExecutionPolicyName --policy-document "file://$executionPath" @awsScope
    if ($LASTEXITCODE -ne 0) { throw "Unable to configure the execution role policy" }

    $localPolicies = Invoke-AwsJson @("iam", "list-policies", "--scope", "Local")
    $githubManagedPolicyExists = @(
        $localPolicies.Policies | Where-Object Arn -eq $githubPolicyArn
    ).Count -eq 1
    if ($githubManagedPolicyExists) {
        $versions = Invoke-AwsJson @(
            "iam", "list-policy-versions", "--policy-arn", $githubPolicyArn
        )
        foreach ($version in @($versions.Versions | Where-Object IsDefaultVersion -eq $false)) {
            & aws iam delete-policy-version --policy-arn $githubPolicyArn `
                --version-id $version.VersionId @awsScope
            if ($LASTEXITCODE -ne 0) { throw "Unable to prune an old deployer policy version" }
        }
        & aws iam create-policy-version --policy-arn $githubPolicyArn `
            --policy-document "file://$githubPath" --set-as-default @awsScope | Out-Null
    } else {
        & aws iam create-policy --policy-name $GitHubPolicyName `
            --policy-document "file://$githubPath" `
            --description "GitHub orchestration for the existing GLAP Operations API staging stack" `
            --tags Key=Project,Value=GLAP Key=Environment,Value=staging `
            @awsScope | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "Unable to configure the GitHub managed deployer policy" }
    & aws iam attach-role-policy --role-name $GitHubRoleName `
        --policy-arn $githubPolicyArn @awsScope
    if ($LASTEXITCODE -ne 0) { throw "Unable to attach the GitHub deployer policy" }

    $inlinePolicies = Invoke-AwsJson @(
        "iam", "list-role-policies", "--role-name", $GitHubRoleName
    )
    if ($GitHubPolicyName -in @($inlinePolicies.PolicyNames)) {
        & aws iam delete-role-policy --role-name $GitHubRoleName `
            --policy-name $GitHubPolicyName @awsScope
        if ($LASTEXITCODE -ne 0) { throw "Unable to remove the superseded inline policy" }
    }
} finally {
    Remove-Item -LiteralPath @($trustPath, $executionPath, $githubPath) `
        -Force -ErrorAction SilentlyContinue
}
Write-Host "Operations API staging deployer and execution roles configured."
Write-Host "Account IDs, ARNs, physical IDs, and paths were not printed."
