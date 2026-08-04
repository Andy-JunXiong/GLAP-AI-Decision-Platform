[CmdletBinding()]
param(
    [string]$AdminProfile = "default",
    [string]$ReadProfile = "codex-readonly",
    [string]$Region = "us-east-1",
    [string]$Repository = "Andy-JunXiong/GLAP-AI-Decision-Platform",
    [string]$Environment = "github-pages",
    [string]$RoleName = "GLAPGithubPagesOpsRead",
    [string]$PipelineStatusS3Uri = "",
    [switch]$RequirePipelineStatus,
    [switch]$SkipGitHubVariables
)

$ErrorActionPreference = "Stop"

function Invoke-AwsJson {
    param(
        [Parameter(Mandatory)] [string[]]$Arguments,
        [Parameter(Mandatory)] [string]$Profile
    )

    $raw = & aws @Arguments --profile $Profile --region $Region --output json
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed: aws $($Arguments[0]) ..."
    }
    if (-not $raw) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function ConvertFrom-S3Uri {
    param([Parameter(Mandatory)] [string]$Value)

    if ($Value -notmatch '^s3://([^/]+)(?:/(.*))?$') {
        throw "Expected an s3:// URI"
    }
    return [pscustomobject]@{
        Bucket = $Matches[1]
        Prefix = if ($Matches[2]) { $Matches[2].TrimEnd('/') } else { "" }
    }
}

function ConvertTo-CompressedJson {
    param([Parameter(Mandatory)] $Value)
    return $Value | ConvertTo-Json -Depth 20 -Compress
}

function Invoke-AwsAllowFailure {
    param([Parameter(Mandatory)] [string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & aws @Arguments *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Write-TemporaryJsonFile {
    param([Parameter(Mandatory)] [string]$Json)

    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("glap-ops-" + [guid]::NewGuid().ToString("N") + ".json")
    [System.IO.File]::WriteAllText($path, $Json, [System.Text.UTF8Encoding]::new($false))
    return $path
}

$adminIdentity = Invoke-AwsJson -Arguments @("sts", "get-caller-identity") -Profile $AdminProfile
$readIdentity = Invoke-AwsJson -Arguments @("sts", "get-caller-identity") -Profile $ReadProfile
if ($adminIdentity.Account -ne $readIdentity.Account) {
    throw "AdminProfile and ReadProfile must target the same AWS account"
}
$accountId = $adminIdentity.Account

if ($RequirePipelineStatus -and -not $PipelineStatusS3Uri) {
    throw "PipelineStatusS3Uri is required when RequirePipelineStatus is set"
}
$pipelineStatusLocation = if ($PipelineStatusS3Uri) {
    ConvertFrom-S3Uri -Value $PipelineStatusS3Uri
} else {
    $null
}
if ($pipelineStatusLocation -and -not $pipelineStatusLocation.Prefix) {
    throw "PipelineStatusS3Uri must identify one object, not only a bucket"
}

$providers = Invoke-AwsJson -Arguments @("iam", "list-open-id-connect-providers") -Profile $AdminProfile
$githubProviderArn = $providers.OpenIDConnectProviderList.Arn |
    Where-Object { $_ -like "*:oidc-provider/token.actions.githubusercontent.com" } |
    Select-Object -First 1
if (-not $githubProviderArn) {
    throw "GitHub Actions OIDC provider is not configured in this AWS account"
}

$lambdaConfig = Invoke-AwsJson -Arguments @(
    "lambda", "get-function-configuration",
    "--function-name", "glap-ai-agent-orchestrator"
) -Profile $ReadProfile
$database = if ($lambdaConfig.Environment.Variables.ATHENA_DATABASE) {
    $lambdaConfig.Environment.Variables.ATHENA_DATABASE
} else {
    "curated_iceberg"
}
$athenaOutput = $lambdaConfig.Environment.Variables.ATHENA_OUTPUT
$workgroup = if ($lambdaConfig.Environment.Variables.ATHENA_WORKGROUP) {
    $lambdaConfig.Environment.Variables.ATHENA_WORKGROUP
} else {
    "primary"
}
if (-not $athenaOutput) {
    throw "The deployed orchestrator does not expose ATHENA_OUTPUT"
}

$tables = @(
    "fact_shipment_events_extended_iceberg",
    "fact_ai_alerts_v3",
    "fact_ai_root_causes_v1",
    "fact_ai_insights_v3",
    "fact_ai_decisions_v3",
    "fact_ai_actions_v2",
    "fact_ai_outcomes_v2",
    "fact_ai_learning_feedback_v1",
    "fact_ai_learning_v1"
)
$views = @(
    "ai_decision_trace_v1",
    "v_ai_latest_decision_trace"
)
$catalogObjects = $tables + $views
$dataLocations = foreach ($tableName in $tables) {
    $table = Invoke-AwsJson -Arguments @(
        "glue", "get-table",
        "--database-name", $database,
        "--name", $tableName
    ) -Profile $ReadProfile
    if (-not $table.Table.StorageDescriptor.Location) {
        throw "Glue table $tableName has no S3 location"
    }
    ConvertFrom-S3Uri -Value $table.Table.StorageDescriptor.Location
}
$resultLocation = ConvertFrom-S3Uri -Value $athenaOutput

$subject = "repo:${Repository}:environment:${Environment}"
$trustPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Principal = @{ Federated = $githubProviderArn }
            Action = "sts:AssumeRoleWithWebIdentity"
            Condition = @{
                StringEquals = @{
                    "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
                    "token.actions.githubusercontent.com:sub" = $subject
                }
            }
        }
    )
}
$trustJson = ConvertTo-CompressedJson -Value $trustPolicy
$trustPath = Write-TemporaryJsonFile -Json $trustJson

try {
    $roleExists = Invoke-AwsAllowFailure -Arguments @(
        "iam", "get-role", "--role-name", $RoleName,
        "--profile", $AdminProfile, "--region", $Region, "--output", "json"
    )
    if ($roleExists) {
        & aws iam update-assume-role-policy `
            --role-name $RoleName `
            --policy-document "file://$trustPath" `
            --profile $AdminProfile `
            --region $Region | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to update the OPS role trust policy" }
        $roleAction = "updated"
    } else {
        & aws iam create-role `
            --role-name $RoleName `
            --description "Read-only public-safe GLAP OPS aggregate export from GitHub Pages" `
            --assume-role-policy-document "file://$trustPath" `
            --tags Key=Project,Value=GLAP Key=Purpose,Value=PublicOpsSnapshot `
            --profile $AdminProfile `
            --region $Region `
            --output json | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the OPS read role" }
        $roleAction = "created"
    }
} finally {
    Remove-Item -LiteralPath $trustPath -Force -ErrorAction SilentlyContinue
}

$dataBucketArns = $dataLocations |
    ForEach-Object { "arn:aws:s3:::$($_.Bucket)" } |
    Sort-Object -Unique
$dataObjectArns = $dataLocations |
    ForEach-Object {
        if ($_.Prefix) { "arn:aws:s3:::$($_.Bucket)/$($_.Prefix)/*" }
        else { "arn:aws:s3:::$($_.Bucket)/*" }
    } |
    Sort-Object -Unique
$resultBucketArn = "arn:aws:s3:::$($resultLocation.Bucket)"
$resultObjectArn = if ($resultLocation.Prefix) {
    "arn:aws:s3:::$($resultLocation.Bucket)/$($resultLocation.Prefix)/*"
} else {
    "arn:aws:s3:::$($resultLocation.Bucket)/*"
}

$permissions = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "RunAggregateQuery"
            Effect = "Allow"
            Action = @(
                "athena:StartQueryExecution",
                "athena:GetQueryExecution",
                "athena:GetQueryResults",
                "athena:StopQueryExecution",
                "athena:GetWorkGroup"
            )
            Resource = "arn:aws:athena:${Region}:${accountId}:workgroup/${workgroup}"
        },
        @{
            Sid = "ReadVerifiedGlueContracts"
            Effect = "Allow"
            Action = @(
                "glue:GetDatabase",
                "glue:GetTable",
                "glue:GetTableVersion",
                "glue:GetTableVersions",
                "glue:GetPartitions"
            )
            Resource = @(
                "arn:aws:glue:${Region}:${accountId}:catalog",
                "arn:aws:glue:${Region}:${accountId}:database/${database}"
            ) + ($catalogObjects | ForEach-Object { "arn:aws:glue:${Region}:${accountId}:table/${database}/$_" })
        },
        @{
            Sid = "RequestGovernedTableData"
            Effect = "Allow"
            Action = "lakeformation:GetDataAccess"
            Resource = "*"
        },
        @{
            Sid = "ListSourceBuckets"
            Effect = "Allow"
            Action = @("s3:GetBucketLocation", "s3:ListBucket")
            Resource = $dataBucketArns
        },
        @{
            Sid = "ReadSourceObjects"
            Effect = "Allow"
            Action = "s3:GetObject"
            Resource = $dataObjectArns
        },
        @{
            Sid = "ListQueryResults"
            Effect = "Allow"
            Action = @("s3:GetBucketLocation", "s3:ListBucket")
            Resource = $resultBucketArn
        },
        @{
            Sid = "UseQueryResultsPrefix"
            Effect = "Allow"
            Action = @("s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload")
            Resource = $resultObjectArn
        }
    )
}
if ($pipelineStatusLocation) {
    $permissions.Statement += @(
        @{
            Sid = "ReadPipelineStatusObject"
            Effect = "Allow"
            Action = "s3:GetObject"
            Resource = "arn:aws:s3:::$($pipelineStatusLocation.Bucket)/$($pipelineStatusLocation.Prefix)"
        }
    )
}
$permissionsJson = ConvertTo-CompressedJson -Value $permissions
$permissionsPath = Write-TemporaryJsonFile -Json $permissionsJson
try {
    & aws iam put-role-policy `
        --role-name $RoleName `
        --policy-name GLAPPagesOpsSnapshotRead `
        --policy-document "file://$permissionsPath" `
        --profile $AdminProfile `
        --region $Region | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to attach the OPS read policy" }
} finally {
    Remove-Item -LiteralPath $permissionsPath -Force -ErrorAction SilentlyContinue
}

$role = Invoke-AwsJson -Arguments @("iam", "get-role", "--role-name", $RoleName) -Profile $AdminProfile
$roleArn = $role.Role.Arn

$lakeFormationGranted = $true
$databaseResource = ConvertTo-CompressedJson -Value @{ Database = @{ Name = $database } }
$databaseResourcePath = Write-TemporaryJsonFile -Json $databaseResource
try {
    $databaseGrant = Invoke-AwsAllowFailure -Arguments @(
        "lakeformation", "grant-permissions",
        "--principal", "DataLakePrincipalIdentifier=$roleArn",
        "--resource", "file://$databaseResourcePath",
        "--permissions", "DESCRIBE",
        "--profile", $AdminProfile,
        "--region", $Region
    )
} finally {
    Remove-Item -LiteralPath $databaseResourcePath -Force -ErrorAction SilentlyContinue
}
if (-not $databaseGrant) { $lakeFormationGranted = $false }
foreach ($tableName in $catalogObjects) {
    $tableResource = ConvertTo-CompressedJson -Value @{
        Table = @{ DatabaseName = $database; Name = $tableName }
    }
    $tableResourcePath = Write-TemporaryJsonFile -Json $tableResource
    try {
        $tableGrant = Invoke-AwsAllowFailure -Arguments @(
            "lakeformation", "grant-permissions",
            "--principal", "DataLakePrincipalIdentifier=$roleArn",
            "--resource", "file://$tableResourcePath",
            "--permissions", "SELECT", "DESCRIBE",
            "--profile", $AdminProfile,
            "--region", $Region
        )
    } finally {
        Remove-Item -LiteralPath $tableResourcePath -Force -ErrorAction SilentlyContinue
    }
    if (-not $tableGrant) { $lakeFormationGranted = $false }
}

$variables = @{
    AWS_OPS_READ_ROLE_ARN = $roleArn
    AWS_OPS_DATABASE = $database
    AWS_OPS_ATHENA_OUTPUT = $athenaOutput
    AWS_OPS_WORKGROUP = $workgroup
}
if ($PipelineStatusS3Uri) {
    $variables.AWS_OPS_PIPELINE_STATUS_URI = $PipelineStatusS3Uri
    $variables.AWS_OPS_PIPELINE_STATUS_REQUIRED = $(if ($RequirePipelineStatus) { "true" } else { "false" })
}
if (-not $SkipGitHubVariables) {
    foreach ($entry in $variables.GetEnumerator()) {
        & gh variable set $entry.Key `
            --env $Environment `
            --repo $Repository `
            --body $entry.Value
        if ($LASTEXITCODE -ne 0) { throw "Failed to set GitHub environment variable $($entry.Key)" }
    }
}

Write-Output "OPS read role: $roleAction"
Write-Output "Inline least-privilege policy: configured"
Write-Output "Lake Formation named-resource grants: $(if ($lakeFormationGranted) { 'configured' } else { 'not required or not permitted; verify only if Athena reports Lake Formation denial' })"
Write-Output "GitHub environment variables: $(if ($SkipGitHubVariables) { 'unchanged' } else { 'configured' })"
Write-Output "No account IDs, ARNs, bucket names, or query paths were printed"
