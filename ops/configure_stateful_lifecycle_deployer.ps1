[CmdletBinding()]
param(
    [string]$AdminProfile = "default",
    [string]$Region = "us-east-1",
    [string]$RoleName = "glap-github-staging-deployer",
    [string]$PolicyName = "GLAPStatefulLifecycleStagingDeploy",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [string]$Workgroup = "primary",
    [string]$StackName = "glap-stateful-lifecycle-staging",
    [string]$FunctionName = "glap-stateful-lifecycle-generator-staging",
    [string]$ExecutionRoleName = "glap-stateful-lifecycle-generator-staging-role",
    [string]$IntegrationControllerFunctionName = "glap-stateful-lifecycle-controller-staging",
    [string]$IntegrationControllerRoleName = "glap-stateful-lifecycle-controller-staging-role",
    [string]$IntegrationQualityGateFunctionName = "glap-stateful-lifecycle-quality-gate-staging",
    [string]$IntegrationQualityGateRoleName = "glap-stateful-lifecycle-quality-gate-staging-role",
    [Parameter(Mandatory)] [string]$ArtifactBucket,
    [string]$ArtifactPrefix = "stateful-lifecycle-staging/artifacts",
    [Parameter(Mandatory)] [string]$LifecycleDataBucket,
    [string]$LifecycleDataPrefix = "stateful-lifecycle-staging/data",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

foreach ($name in @(
    $RoleName,
    $PolicyName,
    $StackName,
    $FunctionName,
    $ExecutionRoleName,
    $IntegrationControllerFunctionName,
    $IntegrationControllerRoleName,
    $IntegrationQualityGateFunctionName,
    $IntegrationQualityGateRoleName
)) {
    if ($name -notmatch '^[A-Za-z0-9+=,.@_-]{1,128}$') {
        throw "Role, policy, stack and function names must use safe AWS characters"
    }
}
if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Glue/Athena identifier"
}
if ($Workgroup -notmatch '^[A-Za-z0-9._-]{1,128}$') {
    throw "Workgroup is not a safe Athena workgroup name"
}
foreach ($bucket in @($ArtifactBucket, $LifecycleDataBucket)) {
    if ($bucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') {
        throw "ArtifactBucket and LifecycleDataBucket must be valid bucket names"
    }
}
foreach ($prefix in @($ArtifactPrefix, $LifecycleDataPrefix)) {
    if ($prefix -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,511}$' -or
        $prefix.Contains("..")) {
        throw "ArtifactPrefix and LifecycleDataPrefix must be safe, prefix-scoped keys"
    }
}
if ($AthenaOutputUri -notmatch '^s3://([^/]+)/(.+)$') {
    throw "AthenaOutputUri must be a prefix-scoped s3:// URI"
}
$athenaBucket = $Matches[1]
$athenaPrefix = $Matches[2].Trim('/')
$artifactPrefix = $ArtifactPrefix.Trim('/')
$dataPrefix = $LifecycleDataPrefix.Trim('/')

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

$tableNames = @(
    "dim_lifecycle_target_v1",
    "dim_route_service_v1",
    "dim_rate_card_v1",
    "dim_rate_tier_v1",
    "dim_fx_rate_v1",
    "dim_provider_v1",
    "fact_shipment_lifecycle_staging_v1",
    "fact_shipment_lifecycle_event_staging_v1",
    "fact_shipment_cost_staging_v1",
    "fact_shipment_lifecycle_metrics_staging_v1",
    "fact_shipment_signal_candidate_staging_v1",
    "fact_lifecycle_alert_staging_v1",
    "fact_lifecycle_action_staging_v1",
    "fact_lifecycle_outcome_staging_v1",
    "fact_policy_proposal_staging_v1",
    "fact_lifecycle_action_audit_staging_v1",
    "vw_lifecycle_action_current_staging_v1",
    "vw_lifecycle_shipment_v2_compat",
    "vw_lifecycle_shipment_event_v2_compat",
    "vw_lifecycle_leg_metrics_v2_compat",
    "vw_lifecycle_cost_v2_compat",
    "vw_lifecycle_risk_v2_compat",
    "vw_lifecycle_product_allocation_v2_compat",
    "vw_lifecycle_shipment_v2_compat_context",
    "vw_lifecycle_shipment_event_v2_compat_context",
    "vw_lifecycle_leg_metrics_v2_compat_context",
    "vw_lifecycle_cost_v2_compat_context",
    "vw_lifecycle_risk_v2_compat_context",
    "vw_lifecycle_product_allocation_v2_compat_context",
    "vw_multimodal_shipment_daily_v1",
    "vw_multimodal_ops_daily_v1",
    "vw_multimodal_provider_daily_v1",
    "vw_multimodal_mode_decision_v1",
    "vw_multimodal_forecast_feature_daily_v1",
    "vw_multimodal_outcome_label_v1",
    "vw_multimodal_shipment_daily_context_v1",
    "vw_multimodal_ops_daily_context_v1",
    "vw_multimodal_provider_daily_context_v1",
    "vw_multimodal_mode_decision_context_v1",
    "vw_multimodal_forecast_feature_daily_context_v1",
    "vw_multimodal_outcome_label_context_v1",
    "vw_multimodal_operational_baseline_v1"
)
$bucketArns = @($ArtifactBucket, $LifecycleDataBucket, $athenaBucket) |
    Sort-Object -Unique |
    ForEach-Object { "arn:aws:s3:::$_" }
$listPrefixes = @(
    $artifactPrefix,
    "$artifactPrefix/*",
    $dataPrefix,
    "$dataPrefix/*",
    $athenaPrefix,
    "$athenaPrefix/*"
) | Sort-Object -Unique

$policy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "RunLifecycleAthena"
            Effect = "Allow"
            Action = @(
                "athena:GetWorkGroup",
                "athena:StartQueryExecution",
                "athena:GetQueryExecution",
                "athena:GetQueryResults",
                "athena:StopQueryExecution"
            )
            Resource = "arn:aws:athena:${Region}:${accountId}:workgroup/${Workgroup}"
        },
        @{
            Sid = "ManageLifecycleGlueContracts"
            Effect = "Allow"
            Action = @(
                "glue:GetDatabase",
                "glue:GetTable",
                "glue:GetTables",
                "glue:GetPartitions",
                "glue:CreateTable",
                "glue:UpdateTable"
            )
            Resource = @(
                "arn:aws:glue:${Region}:${accountId}:catalog",
                "arn:aws:glue:${Region}:${accountId}:database/${SourceDatabase}"
            ) + ($tableNames | ForEach-Object {
                "arn:aws:glue:${Region}:${accountId}:table/${SourceDatabase}/$_"
            })
        },
        @{
            Sid = "UseGovernedLifecycleData"
            Effect = "Allow"
            Action = "lakeformation:GetDataAccess"
            Resource = "*"
        },
        @{
            Sid = "LocateLifecycleBuckets"
            Effect = "Allow"
            Action = "s3:GetBucketLocation"
            Resource = $bucketArns
        },
        @{
            Sid = "ListLifecyclePrefixes"
            Effect = "Allow"
            Action = "s3:ListBucket"
            Resource = $bucketArns
            Condition = @{ StringLike = @{ "s3:prefix" = $listPrefixes } }
        },
        @{
            Sid = "UseLifecycleArtifacts"
            Effect = "Allow"
            Action = @("s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload")
            Resource = "arn:aws:s3:::${ArtifactBucket}/${artifactPrefix}/*"
        },
        @{
            Sid = "UseLifecycleDataPrefix"
            Effect = "Allow"
            Action = @(
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:AbortMultipartUpload"
            )
            Resource = "arn:aws:s3:::${LifecycleDataBucket}/${dataPrefix}/*"
        },
        @{
            Sid = "UseLifecycleAthenaResults"
            Effect = "Allow"
            Action = @(
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:AbortMultipartUpload"
            )
            Resource = "arn:aws:s3:::${athenaBucket}/${athenaPrefix}/*"
        },
        @{
            Sid = "DeployLifecycleStack"
            Effect = "Allow"
            Action = @(
                "cloudformation:CreateChangeSet",
                "cloudformation:DescribeChangeSet",
                "cloudformation:ExecuteChangeSet",
                "cloudformation:DeleteChangeSet",
                "cloudformation:DescribeStacks",
                "cloudformation:DescribeStackEvents",
                "cloudformation:ListStackResources"
            )
            Resource = "arn:aws:cloudformation:${Region}:${accountId}:stack/${StackName}/*"
        },
        @{
            Sid = "InspectLifecycleTemplate"
            Effect = "Allow"
            Action = @("cloudformation:ValidateTemplate", "cloudformation:GetTemplateSummary")
            Resource = "*"
        },
        @{
            Sid = "ManageLifecycleLambda"
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
                "lambda:InvokeFunction"
            )
            Resource = @(
                "arn:aws:lambda:${Region}:${accountId}:function:${FunctionName}",
                "arn:aws:lambda:${Region}:${accountId}:function:${FunctionName}:*",
                "arn:aws:lambda:${Region}:${accountId}:function:${IntegrationControllerFunctionName}",
                "arn:aws:lambda:${Region}:${accountId}:function:${IntegrationControllerFunctionName}:*",
                "arn:aws:lambda:${Region}:${accountId}:function:${IntegrationQualityGateFunctionName}",
                "arn:aws:lambda:${Region}:${accountId}:function:${IntegrationQualityGateFunctionName}:*"
            )
        },
        @{
            Sid = "ManageLifecycleExecutionRole"
            Effect = "Allow"
            Action = @(
                "iam:CreateRole",
                "iam:DeleteRole",
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:PutRolePolicy",
                "iam:DeleteRolePolicy",
                "iam:PassRole",
                "iam:TagRole",
                "iam:UntagRole"
            )
            Resource = @(
                "arn:aws:iam::${accountId}:role/${ExecutionRoleName}",
                "arn:aws:iam::${accountId}:role/${IntegrationControllerRoleName}",
                "arn:aws:iam::${accountId}:role/${IntegrationQualityGateRoleName}"
            )
        },
        @{
            Sid = "ManageLifecycleAlarm"
            Effect = "Allow"
            Action = @(
                "cloudwatch:PutMetricAlarm",
                "cloudwatch:DeleteAlarms",
                "cloudwatch:DescribeAlarms",
                "cloudwatch:TagResource",
                "cloudwatch:UntagResource"
            )
            Resource = "arn:aws:cloudwatch:${Region}:${accountId}:alarm:${StackName}-*"
        }
    )
}

$policyJson = $policy | ConvertTo-Json -Depth 20 -Compress
Write-Host "Stateful lifecycle GitHub deployer policy plan"
Write-Host "  Role: $RoleName"
Write-Host "  Inline policy: $PolicyName"
Write-Host "  Stack: $StackName"
Write-Host "  Function: $FunctionName"
Write-Host "  Execution role: $ExecutionRoleName"
Write-Host "  Integration controller: $IntegrationControllerFunctionName"
Write-Host "  Integration quality gate: $IntegrationQualityGateFunctionName"
Write-Host "  Database: $SourceDatabase"
Write-Host "  Workgroup: $Workgroup"
Write-Host "  Artifact prefix scoped: True"
Write-Host "  Lifecycle data prefix scoped: True"
Write-Host "  Athena results prefix scoped: True"
Write-Host "  Production alias or schedule permission: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply using an IAM administrator profile."
    return
}

$policyPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    "glap-lifecycle-deployer-" + [guid]::NewGuid().ToString("N") + ".json"
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
        throw "Unable to configure the lifecycle staging deployer policy"
    }
} finally {
    Remove-Item -LiteralPath $policyPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Lifecycle staging deployer policy configured. Run the workflow with action=plan before any deploy-replay-validate execution."
