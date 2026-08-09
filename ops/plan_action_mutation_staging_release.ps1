[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-stateful-lifecycle-staging",
    [string]$FunctionName = "glap-lifecycle-action-mutation-staging",
    [switch]$InspectAws
)

$ErrorActionPreference = "Stop"
foreach ($name in @($StackName, $FunctionName)) {
    if ($name -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$') {
        throw "StackName and FunctionName must use safe AWS names"
    }
}
if ($Region -notmatch '^[a-z]{2}(-gov)?-[a-z]+-\d$') {
    throw "Region must be a safe AWS region name"
}

$root = Split-Path $PSScriptRoot -Parent
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "glap-action-mutation-plan-" + [guid]::NewGuid().ToString("N")
)
$packageDirectory = Join-Path $temporaryRoot "package"
$archivePath = Join-Path $temporaryRoot "glap-action-mutation.zip"

try {
    New-Item -ItemType Directory -Path $packageDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root "lambda/glap_action_mutation.py") `
        -Destination (Join-Path $packageDirectory "lambda_function.py") -Force
    Copy-Item -LiteralPath (Join-Path $root "lambda/glap_temporal_boundary.py") `
        -Destination (Join-Path $packageDirectory "glap_temporal_boundary.py") -Force
    Compress-Archive -LiteralPath `
        (Join-Path $packageDirectory "lambda_function.py"), `
        (Join-Path $packageDirectory "glap_temporal_boundary.py") `
        -DestinationPath $archivePath -Force
    $artifactSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash

    Write-Host "Action mutation staging release plan"
    Write-Host "  Mode: plan only"
    Write-Host "  Packaged files: 2"
    Write-Host "  Artifact SHA256: $artifactSha256"
    Write-Host "  Artifact upload: False"
    Write-Host "  Change set created or executed: False"
    Write-Host "  Lambda code updated: False"
    Write-Host "  IAM or CloudFormation modified: False"
    Write-Host "  Production effect: False"

    if (-not $InspectAws) {
        Write-Host "  AWS inspection: skipped"
        return
    }

    $awsScope = @("--region", $Region)
    if ($Profile) { $awsScope += @("--profile", $Profile) }

    & aws sts get-caller-identity @awsScope --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to verify the read-only AWS session" }

    $stackJson = & aws cloudformation describe-stacks `
        --stack-name $StackName @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $stackJson) {
        throw "Unable to inspect the staging stack"
    }
    $stackResult = $stackJson | ConvertFrom-Json
    if (@($stackResult.Stacks).Count -ne 1) {
        throw "Expected exactly one staging stack"
    }
    $stack = $stackResult.Stacks[0]
    if ($stack.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE")) {
        throw "Staging stack is not in a stable completed state"
    }
    $artifactParameter = @(
        $stack.Parameters | Where-Object {
            $_.ParameterKey -eq "ActionMutationArtifactKey"
        }
    )
    if ($artifactParameter.Count -ne 1 -or -not $artifactParameter[0].ParameterValue) {
        throw "The current mutation artifact parameter is unavailable"
    }

    $resourcesJson = & aws cloudformation list-stack-resources `
        --stack-name $StackName @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $resourcesJson) {
        throw "Unable to inspect staging stack resources"
    }
    $resources = ($resourcesJson | ConvertFrom-Json).StackResourceSummaries
    $mutationResources = @(
        $resources | Where-Object {
            $_.LogicalResourceId -eq "ActionMutationFunction"
        }
    )
    if (
        $mutationResources.Count -ne 1 -or
        $mutationResources[0].ResourceType -ne "AWS::Lambda::Function" -or
        $mutationResources[0].PhysicalResourceId -ne $FunctionName
    ) {
        throw "Action mutation Lambda ownership differs from the approved RFC"
    }

    $configurationJson = & aws lambda get-function-configuration `
        --function-name $FunctionName @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $configurationJson) {
        throw "Unable to inspect the Action mutation Lambda configuration"
    }
    $configuration = $configurationJson | ConvertFrom-Json
    if (
        $configuration.Runtime -ne "python3.14" -or
        $configuration.Handler -ne "lambda_function.lambda_handler" -or
        $configuration.State -ne "Active" -or
        $configuration.LastUpdateStatus -ne "Successful" -or
        -not $configuration.CodeSha256
    ) {
        throw "Action mutation Lambda is not a stable expected release target"
    }

    Write-Host "  AWS inspection: passed"
    Write-Host "  Stable stack state: True"
    Write-Host "  Previous artifact parameter retained privately: True"
    Write-Host "  CloudFormation ownership verified: True"
    Write-Host "  Stable Lambda configuration verified: True"
    Write-Host "  AWS write-authority review completed: False"
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporaryRoot = (Resolve-Path -LiteralPath $temporaryRoot).Path
        $systemTemporaryRoot = (
            Resolve-Path -LiteralPath ([System.IO.Path]::GetTempPath())
        ).Path
        $expectedPrefix = Join-Path `
            $systemTemporaryRoot "glap-action-mutation-plan-"
        if ($resolvedTemporaryRoot.StartsWith(
            $expectedPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
        } else {
            throw "Refusing to clean an unexpected temporary path"
        }
    }
}
