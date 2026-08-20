[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-stateful-lifecycle-staging",
    [string]$FunctionName = "glap-stateful-lifecycle-generator-staging",
    [string]$ExecutionRoleName = "glap-stateful-lifecycle-generator-staging-role",
    [string]$IntegrationControllerFunctionName = "glap-stateful-lifecycle-controller-staging",
    [string]$IntegrationControllerRoleName = "glap-stateful-lifecycle-controller-staging-role",
    [string]$IntegrationQualityGateFunctionName = "glap-stateful-lifecycle-quality-gate-staging",
    [string]$IntegrationQualityGateRoleName = "glap-stateful-lifecycle-quality-gate-staging-role",
    [string]$ActionMutationFunctionName = "glap-lifecycle-action-mutation-staging",
    [string]$ActionMutationRoleName = "glap-lifecycle-action-mutation-staging-role",
    [string]$CloudFormationRoleArn = "",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [string]$Workgroup = "primary",
    [Parameter(Mandatory)] [string]$ArtifactBucket,
    [Parameter(Mandatory)] [string]$LifecycleDataBucket,
    [string]$LifecycleDataPrefix = "stateful-lifecycle-staging/data",
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$ArtifactKey = "stateful-lifecycle-staging/artifacts/glap-stateful-lifecycle-generator.zip",
    [string]$ControllerArtifactKey = "stateful-lifecycle-staging/artifacts/glap-stateful-lifecycle-controller.zip",
    [string]$QualityGateArtifactKey = "stateful-lifecycle-staging/artifacts/glap-stateful-lifecycle-quality-gate.zip",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

foreach ($identifier in @(
    $StackName,
    $FunctionName,
    $ExecutionRoleName,
    $IntegrationControllerFunctionName,
    $IntegrationControllerRoleName,
    $IntegrationQualityGateFunctionName,
    $IntegrationQualityGateRoleName,
    $ActionMutationFunctionName,
    $ActionMutationRoleName
)) {
    if ($identifier -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$') {
        throw "StackName, FunctionName and ExecutionRoleName must use safe AWS names"
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
foreach ($key in @(
    $ArtifactKey, $ControllerArtifactKey, $QualityGateArtifactKey
)) {
    if ($key -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,1023}$' -or
        $key.Contains("..")) {
        throw "Artifact keys must be safe object keys"
    }
}
if ($CloudFormationRoleArn -and $CloudFormationRoleArn -notmatch (
    '^arn:aws(-[a-z]+)?:iam::\d{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*' +
    'glap-stateful-lifecycle-cloudformation-staging-role$'
)) {
    throw "CloudFormationRoleArn must identify the dedicated lifecycle staging service role"
}
if ($AthenaOutputUri -notmatch '^s3://([^/]+)/(.+)$') {
    throw "AthenaOutputUri must be a prefix-scoped s3:// URI"
}
$athenaResultsBucket = $Matches[1]
$athenaResultsPrefix = $Matches[2].Trim('/') + '/'
$dataPrefix = $LifecycleDataPrefix.Trim('/')
$statusPrefix = "$dataPrefix/status"
$statusKey = "$statusPrefix/pipeline-integration-latest.json"

$root = Split-Path $PSScriptRoot -Parent
$templatePath = Join-Path $root "infrastructure/stateful-lifecycle-staging.yaml"
$distDir = Join-Path $root "dist"
$packageDir = Join-Path $distDir "stateful-lifecycle-package"
$archivePath = Join-Path $distDir "glap-stateful-lifecycle-generator.zip"
$controllerPackageDir = Join-Path $distDir "stateful-lifecycle-controller-package"
$controllerArchivePath = Join-Path $distDir "glap-stateful-lifecycle-controller.zip"
$qualityPackageDir = Join-Path $distDir "stateful-lifecycle-quality-package"
$qualityArchivePath = Join-Path $distDir "glap-stateful-lifecycle-quality-gate.zip"

Write-Host "Stateful lifecycle staging stack plan"
Write-Host "  Stack: $StackName"
Write-Host "  Function: $FunctionName"
Write-Host "  Execution role: $ExecutionRoleName"
Write-Host "  Integration controller: $IntegrationControllerFunctionName"
Write-Host "  Integration quality gate: $IntegrationQualityGateFunctionName"
Write-Host "  Region: $Region"
Write-Host "  Source database: $SourceDatabase"
Write-Host "  Workgroup: $Workgroup"
Write-Host "  Artifact: s3://$ArtifactBucket/$ArtifactKey"
Write-Host "  Controller artifact: s3://$ArtifactBucket/$ControllerArtifactKey"
Write-Host "  Quality artifact: s3://$ArtifactBucket/$QualityGateArtifactKey"
Write-Host "  Action mutation: $ActionMutationFunctionName"
Write-Host "  Action mutation artifact preserved from the existing stack: True"
Write-Host "  Dedicated CloudFormation service role configured: $([bool]$CloudFormationRoleArn)"
Write-Host "  Lifecycle data: s3://$LifecycleDataBucket/$dataPrefix/"
Write-Host "  Athena results prefix configured: True"
Write-Host "  Schedule created: False"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after validating buckets and the OIDC role."
    return
}
if (-not $CloudFormationRoleArn) {
    throw "CloudFormationRoleArn is required for lifecycle stack deployment"
}

$awsScope = @("--region", $Region)
if ($Profile) {
    $awsScope += @("--profile", $Profile)
}

$stackJson = & aws cloudformation describe-stacks `
    --stack-name $StackName @awsScope --output json
if ($LASTEXITCODE -ne 0 -or -not $stackJson) {
    throw "The existing lifecycle staging stack is required; bootstrap is a separate reviewed operation"
}
$stack = ($stackJson -join "`n" | ConvertFrom-Json).Stacks[0]
$stableStackStates = @("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE")
if ([string]$stack.StackStatus -notin $stableStackStates) {
    if ([string]$stack.StackStatus -eq "UPDATE_ROLLBACK_FAILED") {
        throw "Lifecycle staging stack rollback must be recovered before deployment"
    }
    throw "Lifecycle staging stack is not stable: $($stack.StackStatus)"
}
$actionMutationParameters = @(
    $stack.Parameters |
        Where-Object ParameterKey -eq "ActionMutationArtifactKey"
)
if ($actionMutationParameters.Count -ne 1) {
    throw "Existing Action mutation artifact identity is unavailable"
}
$actionMutationArtifactKey = [string]$actionMutationParameters[0].ParameterValue
if ($actionMutationArtifactKey -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,1023}$' -or
    $actionMutationArtifactKey.Contains("..")) {
    throw "Existing Action mutation artifact identity is unsafe"
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
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_temporal_boundary.py") `
    -Destination (Join-Path $packageDir "glap_temporal_boundary.py") -Force
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_governed_closed_loop.py") `
    -Destination (Join-Path $packageDir "glap_governed_closed_loop.py") -Force
Compress-Archive -LiteralPath `
    (Join-Path $packageDir "lambda_function.py"), `
    (Join-Path $packageDir "glap_stateful_lifecycle_generator.py"), `
    (Join-Path $packageDir "glap_temporal_boundary.py"), `
    (Join-Path $packageDir "glap_governed_closed_loop.py") `
    -DestinationPath $archivePath -Force

New-Item -ItemType Directory -Path $controllerPackageDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_pipeline_controller.py") `
    -Destination (Join-Path $controllerPackageDir "lambda_function.py") -Force
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_quality_contracts.py") `
    -Destination (Join-Path $controllerPackageDir "glap_quality_contracts.py") -Force
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_temporal_boundary.py") `
    -Destination (Join-Path $controllerPackageDir "glap_temporal_boundary.py") -Force
Compress-Archive -LiteralPath `
    (Join-Path $controllerPackageDir "lambda_function.py"), `
    (Join-Path $controllerPackageDir "glap_quality_contracts.py"), `
    (Join-Path $controllerPackageDir "glap_temporal_boundary.py") `
    -DestinationPath $controllerArchivePath -Force

New-Item -ItemType Directory -Path $qualityPackageDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_data_quality_gate.py") `
    -Destination (Join-Path $qualityPackageDir "lambda_function.py") -Force
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_quality_contracts.py") `
    -Destination (Join-Path $qualityPackageDir "glap_quality_contracts.py") -Force
Copy-Item -LiteralPath (Join-Path $root "lambda/glap_temporal_boundary.py") `
    -Destination (Join-Path $qualityPackageDir "glap_temporal_boundary.py") -Force
Copy-Item -LiteralPath (Join-Path $root "sql/06_stateful_lifecycle_validation.sql") `
    -Destination (Join-Path $qualityPackageDir "lifecycle_validation.sql") -Force
Copy-Item -LiteralPath (Join-Path $root "sql/10_multimodal_ops_validation.sql") `
    -Destination (Join-Path $qualityPackageDir "multimodal_ops_validation.sql") -Force
Compress-Archive -LiteralPath `
    (Join-Path $qualityPackageDir "lambda_function.py"), `
    (Join-Path $qualityPackageDir "glap_quality_contracts.py"), `
    (Join-Path $qualityPackageDir "glap_temporal_boundary.py"), `
    (Join-Path $qualityPackageDir "lifecycle_validation.sql"), `
    (Join-Path $qualityPackageDir "multimodal_ops_validation.sql") `
    -DestinationPath $qualityArchivePath -Force

& aws s3 cp $archivePath "s3://$ArtifactBucket/$ArtifactKey" @awsScope --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw "Unable to upload the lifecycle Lambda artifact"
}
& aws s3 cp $controllerArchivePath "s3://$ArtifactBucket/$ControllerArtifactKey" @awsScope --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw "Unable to upload the lifecycle integration controller artifact"
}
& aws s3 cp $qualityArchivePath "s3://$ArtifactBucket/$QualityGateArtifactKey" @awsScope --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw "Unable to upload the lifecycle integration quality artifact"
}
$parameterOverrides = @(
    "ArtifactBucket=$ArtifactBucket",
    "GeneratorArtifactKey=$ArtifactKey",
    "ControllerArtifactKey=$ControllerArtifactKey",
    "QualityGateArtifactKey=$QualityGateArtifactKey",
    "ActionMutationArtifactKey=$actionMutationArtifactKey",
    "AthenaOutputUri=$AthenaOutputUri",
    "AthenaResultsBucketName=$athenaResultsBucket",
    "AthenaResultsPrefix=$athenaResultsPrefix",
    "LifecycleDataBucketArn=arn:aws:s3:::$LifecycleDataBucket",
    "LifecycleDataObjectArn=arn:aws:s3:::$LifecycleDataBucket/$dataPrefix/*",
    "PipelineStatusS3Uri=s3://$LifecycleDataBucket/$statusKey",
    "PipelineStatusObjectArn=arn:aws:s3:::$LifecycleDataBucket/$statusKey",
    "PipelineStatusObjectsArn=arn:aws:s3:::$LifecycleDataBucket/$statusPrefix/*",
    "PipelineStatusPrefix=$statusPrefix",
    "AthenaWorkgroup=$Workgroup",
    "SourceDatabase=$SourceDatabase",
    "FunctionName=$FunctionName",
    "ExecutionRoleName=$ExecutionRoleName",
    "IntegrationControllerFunctionName=$IntegrationControllerFunctionName",
    "IntegrationControllerRoleName=$IntegrationControllerRoleName",
    "IntegrationQualityGateFunctionName=$IntegrationQualityGateFunctionName",
    "IntegrationQualityGateRoleName=$IntegrationQualityGateRoleName",
    "ActionMutationFunctionName=$ActionMutationFunctionName",
    "ActionMutationRoleName=$ActionMutationRoleName"
)
$changeSetName = "lifecycle-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$changeSetCreated = $false
try {
    $parameterArguments = @(
        $parameterOverrides | ForEach-Object {
            $parts = $_ -split '=', 2
            "ParameterKey=$($parts[0]),ParameterValue=$($parts[1])"
        }
    )
    & aws cloudformation create-change-set `
        --stack-name $StackName `
        --change-set-name $changeSetName `
        --change-set-type UPDATE `
        --template-body "file://$templatePath" `
        --role-arn $CloudFormationRoleArn `
        --capabilities CAPABILITY_NAMED_IAM `
        --parameters @parameterArguments `
        @awsScope `
        --output json | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the lifecycle staging change set"
    }
    $changeSetCreated = $true
    & aws cloudformation wait change-set-create-complete `
        --stack-name $StackName --change-set-name $changeSetName @awsScope
    if ($LASTEXITCODE -ne 0) {
        $failedChangeSetJson = & aws cloudformation describe-change-set `
            --stack-name $StackName --change-set-name $changeSetName @awsScope --output json
        if ($LASTEXITCODE -eq 0 -and $failedChangeSetJson) {
            $failedChangeSet = $failedChangeSetJson -join "`n" | ConvertFrom-Json
            if ([string]$failedChangeSet.Status -eq "FAILED" -and
                [string]$failedChangeSet.StatusReason -match (
                    "didn't contain changes|No updates are to be performed"
                )) {
                & aws cloudformation delete-change-set `
                    --stack-name $StackName --change-set-name $changeSetName @awsScope | Out-Null
                $changeSetCreated = $false
                $unchangedStackJson = & aws cloudformation describe-stacks `
                    --stack-name $StackName @awsScope --output json
                $unchangedStack = if ($LASTEXITCODE -eq 0 -and $unchangedStackJson) {
                    ($unchangedStackJson -join "`n" | ConvertFrom-Json).Stacks[0]
                } else {
                    $null
                }
                if (-not $unchangedStack -or
                    [string]$unchangedStack.StackStatus -notin $stableStackStates -or
                    [string]$unchangedStack.RoleARN -ne $CloudFormationRoleArn) {
                    throw "No lifecycle changes exist, but the dedicated stack role is not verified"
                }
                Write-Host "No lifecycle stack changes are required; the dedicated role remains verified."
                return
            }
        }
        throw "Lifecycle staging change set did not become ready"
    }
    $changeSetJson = & aws cloudformation describe-change-set `
        --stack-name $StackName --change-set-name $changeSetName @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $changeSetJson) {
        throw "Unable to inspect the lifecycle staging change set"
    }
    $changeSet = $changeSetJson -join "`n" | ConvertFrom-Json
    $protectedChanges = @(
        $changeSet.Changes | Where-Object {
            $_.ResourceChange.LogicalResourceId -in @(
                "ActionMutationFunction", "ActionMutationRole"
            )
        }
    )
    if ($protectedChanges.Count -ne 0) {
        throw "Lifecycle deployment cannot modify Action mutation resources"
    }
    & aws cloudformation execute-change-set `
        --stack-name $StackName --change-set-name $changeSetName @awsScope
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to execute the lifecycle staging change set"
    }
    & aws cloudformation wait stack-update-complete `
        --stack-name $StackName @awsScope
    if ($LASTEXITCODE -ne 0) {
        throw "Lifecycle staging stack deployment failed"
    }
    $updatedStackJson = & aws cloudformation describe-stacks `
        --stack-name $StackName @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $updatedStackJson) {
        throw "Unable to verify the lifecycle staging stack"
    }
    $updatedStack = ($updatedStackJson -join "`n" | ConvertFrom-Json).Stacks[0]
    if ([string]$updatedStack.StackStatus -ne "UPDATE_COMPLETE" -or
        [string]$updatedStack.RoleARN -ne $CloudFormationRoleArn) {
        throw "Lifecycle staging stack role or final status verification failed"
    }
    $changeSetCreated = $false
} catch {
    if ($changeSetCreated) {
        & aws cloudformation delete-change-set `
            --stack-name $StackName --change-set-name $changeSetName @awsScope 2>$null | Out-Null
    }
    throw
}

Write-Host "Lifecycle staging stack and isolated integration controller deployed without a schedule, production alias change, or Action mutation release."
