[CmdletBinding()]
param(
    [string]$AdminProfile = "default",
    [string]$Region = "us-east-1",
    [string]$RoleName = "glap-github-staging-deployer",
    [string]$LegacyInlinePolicyName = "GLAPStatefulLifecycleStagingDeploy",
    [string]$CatalogPolicyName = "GLAPStatefulLifecycleCatalogStagingDeploy",
    [string]$StoragePolicyName = "GLAPStatefulLifecycleStorageStagingDeploy",
    [string]$DeploymentPolicyName = "GLAPStatefulLifecycleRuntimeStagingDeploy",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [string]$Workgroup = "primary",
    [string]$StackName = "glap-stateful-lifecycle-staging",
    [string]$FunctionName = "glap-stateful-lifecycle-generator-staging",
    [string]$ExecutionRoleName = "glap-stateful-lifecycle-generator-staging-role",
    [string]$IntegrationControllerFunctionName = "glap-stateful-lifecycle-controller-staging",
    [string]$IntegrationControllerRoleName = "glap-stateful-lifecycle-controller-staging-role",
    [string]$IntegrationQualityGateFunctionName = "glap-stateful-lifecycle-quality-gate-staging",
    [string]$IntegrationQualityGateRoleName = "glap-stateful-lifecycle-quality-gate-staging-role",
    [string]$CloudFormationRoleName = "glap-stateful-lifecycle-cloudformation-staging-role",
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
    $LegacyInlinePolicyName,
    $CatalogPolicyName,
    $StoragePolicyName,
    $DeploymentPolicyName,
    $StackName,
    $FunctionName,
    $ExecutionRoleName,
    $IntegrationControllerFunctionName,
    $IntegrationControllerRoleName,
    $IntegrationQualityGateFunctionName,
    $IntegrationQualityGateRoleName,
    $CloudFormationRoleName
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

function Write-TemporaryPolicy([string]$Json, [string]$Label) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) (
        "glap-lifecycle-$Label-" + [guid]::NewGuid().ToString("N") + ".json"
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
    ForEach-Object { "arn:${partition}:s3:::$_" }
$listPrefixes = @(
    $artifactPrefix,
    "$artifactPrefix/*",
    $dataPrefix,
    "$dataPrefix/*",
    $athenaPrefix,
    "$athenaPrefix/*"
) | Sort-Object -Unique

$statements = @(
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
            Resource = "arn:${partition}:athena:${Region}:${accountId}:workgroup/${Workgroup}"
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
                "arn:${partition}:glue:${Region}:${accountId}:catalog",
                "arn:${partition}:glue:${Region}:${accountId}:database/${SourceDatabase}"
            ) + ($tableNames | ForEach-Object {
                "arn:${partition}:glue:${Region}:${accountId}:table/${SourceDatabase}/$_"
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
            Resource = "arn:${partition}:s3:::${ArtifactBucket}/${artifactPrefix}/*"
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
            Resource = "arn:${partition}:s3:::${LifecycleDataBucket}/${dataPrefix}/*"
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
            Resource = "arn:${partition}:s3:::${athenaBucket}/${athenaPrefix}/*"
        },
        @{
            Sid = "DeployLifecycleStack"
            Effect = "Allow"
            Action = @(
                "cloudformation:CreateChangeSet",
                "cloudformation:DescribeChangeSet",
                "cloudformation:ExecuteChangeSet",
                "cloudformation:DeleteChangeSet",
                "cloudformation:ContinueUpdateRollback",
                "cloudformation:DescribeStacks",
                "cloudformation:DescribeStackEvents",
                "cloudformation:ListStackResources"
            )
            Resource = "arn:${partition}:cloudformation:${Region}:${accountId}:stack/${StackName}/*"
        },
        @{
            Sid = "InspectLifecycleTemplate"
            Effect = "Allow"
            Action = @("cloudformation:ValidateTemplate", "cloudformation:GetTemplateSummary")
            Resource = "*"
        },
        @{
            Sid = "PassLifecycleCloudFormationRole"
            Effect = "Allow"
            Action = "iam:PassRole"
            Resource = "arn:${partition}:iam::${accountId}:role/${CloudFormationRoleName}"
            Condition = @{
                StringEquals = @{
                    "iam:PassedToService" = "cloudformation.amazonaws.com"
                }
            }
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
                "arn:${partition}:lambda:${Region}:${accountId}:function:${FunctionName}",
                "arn:${partition}:lambda:${Region}:${accountId}:function:${FunctionName}:*",
                "arn:${partition}:lambda:${Region}:${accountId}:function:${IntegrationControllerFunctionName}",
                "arn:${partition}:lambda:${Region}:${accountId}:function:${IntegrationControllerFunctionName}:*",
                "arn:${partition}:lambda:${Region}:${accountId}:function:${IntegrationQualityGateFunctionName}",
                "arn:${partition}:lambda:${Region}:${accountId}:function:${IntegrationQualityGateFunctionName}:*"
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
                "arn:${partition}:iam::${accountId}:role/${ExecutionRoleName}",
                "arn:${partition}:iam::${accountId}:role/${IntegrationControllerRoleName}",
                "arn:${partition}:iam::${accountId}:role/${IntegrationQualityGateRoleName}"
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
            Resource = "arn:${partition}:cloudwatch:${Region}:${accountId}:alarm:${StackName}-*"
        }
)

$catalogSids = @(
    "RunLifecycleAthena",
    "ManageLifecycleGlueContracts",
    "UseGovernedLifecycleData"
)
$storageSids = @(
    "LocateLifecycleBuckets",
    "ListLifecyclePrefixes",
    "UseLifecycleArtifacts",
    "UseLifecycleDataPrefix",
    "UseLifecycleAthenaResults"
)
$deploymentSids = @(
    "DeployLifecycleStack",
    "InspectLifecycleTemplate",
    "PassLifecycleCloudFormationRole",
    "ManageLifecycleLambda",
    "ManageLifecycleExecutionRole",
    "ManageLifecycleAlarm"
)
$assignedSids = @($catalogSids + $storageSids + $deploymentSids)
$statementSids = @($statements | ForEach-Object { [string]$_.Sid })
if (@($assignedSids | Sort-Object -Unique).Count -ne $assignedSids.Count -or
    @(Compare-Object $statementSids $assignedSids).Count -ne 0) {
    throw "Every lifecycle permission statement must belong to exactly one managed policy"
}
$catalogPolicy = @{
    Version = "2012-10-17"
    Statement = @($statements | Where-Object Sid -in $catalogSids)
}
$storagePolicy = @{
    Version = "2012-10-17"
    Statement = @($statements | Where-Object Sid -in $storageSids)
}
$deploymentPolicy = @{
    Version = "2012-10-17"
    Statement = @($statements | Where-Object Sid -in $deploymentSids)
}
$managedPolicyCharacterLimit = 6144
$managedPolicyMinimumHeadroom = 512
$managedPolicyAttachmentLimit = 10
$managedPolicies = @(
    @{
        Name = $CatalogPolicyName
        Arn = "arn:${partition}:iam::${accountId}:policy/${CatalogPolicyName}"
        Description = "Staging-only Athena, Glue, and Lake Formation access for the GLAP lifecycle workflow"
        Document = $catalogPolicy
    },
    @{
        Name = $StoragePolicyName
        Arn = "arn:${partition}:iam::${accountId}:policy/${StoragePolicyName}"
        Description = "Prefix-scoped staging S3 access for the GLAP lifecycle workflow"
        Document = $storagePolicy
    },
    @{
        Name = $DeploymentPolicyName
        Arn = "arn:${partition}:iam::${accountId}:policy/${DeploymentPolicyName}"
        Description = "Exact-resource staging deployment access for the GLAP lifecycle workflow"
        Document = $deploymentPolicy
    }
)
foreach ($managedPolicy in $managedPolicies) {
    $json = $managedPolicy.Document | ConvertTo-Json -Depth 20 -Compress
    $managedPolicy.Json = $json
    $managedPolicy.Characters = $json.Length
    if ($json.Length + $managedPolicyMinimumHeadroom -gt $managedPolicyCharacterLimit) {
        throw "Managed lifecycle policy does not retain the required 512-character IAM quota headroom: $($managedPolicy.Name)"
    }
}

$attachedPolicies = Invoke-AwsJson `
    @("iam", "list-attached-role-policies", "--role-name", $RoleName) `
    "Unable to inspect the lifecycle staging deployer's managed policies"
$attachedPolicyArns = @(
    $attachedPolicies.AttachedPolicies | ForEach-Object { [string]$_.PolicyArn }
)
$newAttachmentCount = @(
    $managedPolicies | Where-Object Arn -notin $attachedPolicyArns
).Count
if (@($attachedPolicyArns).Count + $newAttachmentCount -gt $managedPolicyAttachmentLimit) {
    throw "Lifecycle managed-policy migration would exceed the role attachment limit"
}
$inlinePolicies = Invoke-AwsJson `
    @("iam", "list-role-policies", "--role-name", $RoleName) `
    "Unable to inspect the lifecycle staging deployer's inline policies"
$legacyInlineExists = $LegacyInlinePolicyName -in @($inlinePolicies.PolicyNames)

Write-Host "Stateful lifecycle GitHub deployer policy plan"
Write-Host "  Role: $RoleName"
Write-Host "  Legacy inline policy migration required: $legacyInlineExists"
Write-Host "  Customer-managed policy split: Catalog, Storage, Deployment"
foreach ($managedPolicy in $managedPolicies) {
    $headroom = $managedPolicyCharacterLimit - $managedPolicy.Characters
    Write-Host "  Managed policy: $($managedPolicy.Name) ($($managedPolicy.Characters)/$managedPolicyCharacterLimit characters; $headroom headroom)"
}
Write-Host "  Managed policy attachments after migration: $(@($attachedPolicyArns).Count + $newAttachmentCount)/$managedPolicyAttachmentLimit"
Write-Host "  Stack: $StackName"
Write-Host "  Function: $FunctionName"
Write-Host "  Execution role: $ExecutionRoleName"
Write-Host "  Integration controller: $IntegrationControllerFunctionName"
Write-Host "  Integration quality gate: $IntegrationQualityGateFunctionName"
Write-Host "  CloudFormation service role: $CloudFormationRoleName"
Write-Host "  Database: $SourceDatabase"
Write-Host "  Workgroup: $Workgroup"
Write-Host "  Artifact prefix scoped: True"
Write-Host "  Lifecycle data prefix scoped: True"
Write-Host "  Athena results prefix scoped: True"
Write-Host "  Database-wide Glue table wildcard: False"
Write-Host "  Production alias or schedule permission: False"
Write-Host "  GitHub role self-modification permission: False"
Write-Host "  CloudFormation rollback continuation permission: True"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply using an IAM administrator profile."
    return
}

$policyPaths = @{}
$stagedPolicies = @()
$defaultSwitches = @()
$newAttachments = @()
$migrationCommitted = $false
try {
    foreach ($managedPolicy in $managedPolicies) {
        $policyPaths[$managedPolicy.Name] = Write-TemporaryPolicy `
            $managedPolicy.Json $managedPolicy.Name
    }

    $localPolicies = Invoke-AwsJson `
        @("iam", "list-policies", "--scope", "Local") `
        "Unable to inspect customer-managed lifecycle policies"
    foreach ($managedPolicy in $managedPolicies) {
        $existing = @(
            $localPolicies.Policies | Where-Object Arn -eq $managedPolicy.Arn
        )
        if ($existing.Count -gt 1) {
            throw "More than one lifecycle managed policy matched the expected ARN"
        }
        if ($existing.Count -eq 0) {
            $created = Invoke-AwsJson @(
                "iam", "create-policy",
                "--policy-name", $managedPolicy.Name,
                "--policy-document", "file://$($policyPaths[$managedPolicy.Name])",
                "--description", $managedPolicy.Description,
                "--tags", "Key=Project,Value=GLAP", "Key=Environment,Value=staging"
            ) "Unable to create lifecycle managed policy: $($managedPolicy.Name)"
            if ([string]$created.Policy.Arn -ne $managedPolicy.Arn) {
                throw "Created lifecycle managed policy ARN did not match the reviewed target"
            }
            $stagedPolicies += @{
                Name = $managedPolicy.Name
                Arn = $managedPolicy.Arn
                StagedVersionId = [string]$created.Policy.DefaultVersionId
                OriginalDefaultVersionId = $null
                WasCreated = $true
            }
            continue
        }

        $metadata = Invoke-AwsJson `
            @("iam", "get-policy", "--policy-arn", $managedPolicy.Arn) `
            "Unable to inspect lifecycle managed policy: $($managedPolicy.Name)"
        $originalDefaultVersionId = [string]$metadata.Policy.DefaultVersionId
        $versionsResponse = Invoke-AwsJson `
            @("iam", "list-policy-versions", "--policy-arn", $managedPolicy.Arn) `
            "Unable to inspect lifecycle managed policy versions: $($managedPolicy.Name)"
        $versions = @($versionsResponse.Versions)
        while ($versions.Count -ge 5) {
            $oldestNonDefault = @(
                $versions |
                    Where-Object IsDefaultVersion -eq $false |
                    Sort-Object CreateDate |
                    Select-Object -First 1
            )
            if ($oldestNonDefault.Count -ne 1) {
                throw "No removable lifecycle policy version is available"
            }
            Invoke-AwsCommand @(
                "iam", "delete-policy-version",
                "--policy-arn", $managedPolicy.Arn,
                "--version-id", $oldestNonDefault[0].VersionId
            ) "Unable to prune the oldest non-default lifecycle policy version"
            $versions = @(
                $versions | Where-Object VersionId -ne $oldestNonDefault[0].VersionId
            )
        }
        $createdVersion = Invoke-AwsJson @(
            "iam", "create-policy-version",
            "--policy-arn", $managedPolicy.Arn,
            "--policy-document", "file://$($policyPaths[$managedPolicy.Name])"
        ) "Unable to stage lifecycle managed policy version: $($managedPolicy.Name)"
        $stagedPolicies += @{
            Name = $managedPolicy.Name
            Arn = $managedPolicy.Arn
            StagedVersionId = [string]$createdVersion.PolicyVersion.VersionId
            OriginalDefaultVersionId = $originalDefaultVersionId
            WasCreated = $false
        }
    }

    foreach ($stagedPolicy in $stagedPolicies | Where-Object WasCreated -eq $false) {
        Invoke-AwsCommand @(
            "iam", "set-default-policy-version",
            "--policy-arn", $stagedPolicy.Arn,
            "--version-id", $stagedPolicy.StagedVersionId
        ) "Unable to activate lifecycle managed policy: $($stagedPolicy.Name)"
        $defaultSwitches += $stagedPolicy
    }

    foreach ($stagedPolicy in $stagedPolicies) {
        if ($stagedPolicy.Arn -notin $attachedPolicyArns) {
            Invoke-AwsCommand @(
                "iam", "attach-role-policy",
                "--role-name", $RoleName,
                "--policy-arn", $stagedPolicy.Arn
            ) "Unable to attach lifecycle managed policy: $($stagedPolicy.Name)"
            $newAttachments += $stagedPolicy
        }
    }

    $verifiedAttachments = Invoke-AwsJson `
        @("iam", "list-attached-role-policies", "--role-name", $RoleName) `
        "Unable to verify lifecycle managed-policy attachments"
    $verifiedAttachmentArns = @(
        $verifiedAttachments.AttachedPolicies | ForEach-Object { [string]$_.PolicyArn }
    )
    foreach ($stagedPolicy in $stagedPolicies) {
        if ($stagedPolicy.Arn -notin $verifiedAttachmentArns) {
            throw "Lifecycle managed-policy attachment verification failed"
        }
        $verifiedPolicy = Invoke-AwsJson `
            @("iam", "get-policy", "--policy-arn", $stagedPolicy.Arn) `
            "Unable to verify lifecycle managed-policy version"
        if ([string]$verifiedPolicy.Policy.DefaultVersionId -ne $stagedPolicy.StagedVersionId) {
            throw "Lifecycle managed-policy default-version verification failed"
        }
    }

    if ($legacyInlineExists) {
        Invoke-AwsCommand @(
            "iam", "delete-role-policy",
            "--role-name", $RoleName,
            "--policy-name", $LegacyInlinePolicyName
        ) "Unable to remove the superseded lifecycle inline policy"
    }
    $migrationCommitted = $true
} catch {
    $failureMessage = $_.Exception.Message
    if (-not $migrationCommitted) {
        foreach ($defaultSwitch in @($defaultSwitches) | Sort-Object Name -Descending) {
            try {
                Invoke-AwsCommand @(
                    "iam", "set-default-policy-version",
                    "--policy-arn", $defaultSwitch.Arn,
                    "--version-id", $defaultSwitch.OriginalDefaultVersionId
                ) "Unable to restore a prior lifecycle policy version"
            } catch {
                Write-Warning "A prior managed-policy version needs human recovery: $($defaultSwitch.Name)"
            }
        }
        if ($legacyInlineExists) {
            foreach ($newAttachment in @($newAttachments)) {
                try {
                    Invoke-AwsCommand @(
                        "iam", "detach-role-policy",
                        "--role-name", $RoleName,
                        "--policy-arn", $newAttachment.Arn
                    ) "Unable to detach an incomplete lifecycle policy migration"
                } catch {
                    Write-Warning "An incomplete managed-policy attachment needs human recovery: $($newAttachment.Name)"
                }
            }
        }
    }
    throw $failureMessage
} finally {
    if ($policyPaths.Count -gt 0) {
        Remove-Item -LiteralPath @($policyPaths.Values) -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Lifecycle staging deployer managed policies configured."
Write-Host "Legacy inline lifecycle policy present: False"
Write-Host "Run the workflow with action=plan before any deployment or recovery execution."
