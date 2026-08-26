[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceStackName = "glap-stateful-lifecycle-staging",
    [string]$DestinationStackName = "glap-stateful-lifecycle-generator-staging",
    [string]$StackRefactorId = "",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

foreach ($name in @($SourceStackName, $DestinationStackName)) {
    if ($name -notmatch '^glap-stateful-lifecycle(?:-generator)?-staging$') {
        throw "Generator refactor stack names are fixed to isolated staging"
    }
}
if ($SourceStackName -ne "glap-stateful-lifecycle-staging" -or
    $DestinationStackName -ne "glap-stateful-lifecycle-generator-staging") {
    throw "Generator refactor source and destination stacks are fixed"
}
if ($Apply -and $StackRefactorId -notmatch (
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-' +
    '[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)) {
    throw "Execute requires the exact reviewed stack refactor ID"
}
if (-not $Apply -and $StackRefactorId) {
    throw "Plan creates a new refactor and does not accept a prior ID"
}

$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }
$root = Split-Path $PSScriptRoot -Parent
$sourceTemplatePath = Join-Path $root "infrastructure/stateful-lifecycle-staging.yaml"
$destinationTemplatePath = Join-Path $root "infrastructure/stateful-lifecycle-generator-staging.yaml"

function Invoke-AwsJson {
    param([string[]]$Arguments, [string]$Failure)
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) { throw $Failure }
    return (($json -join "`n") | ConvertFrom-Json)
}

function Test-StackIdentity {
    param([string]$Actual, [string]$Expected)
    return ($Actual -eq $Expected -or $Actual -match "/$([regex]::Escape($Expected))/")
}

function Assert-ExactMove {
    param([object[]]$Actions)
    $moves = @($Actions)
    if ($moves.Count -ne 1 -or [string]$moves[0].Action -ne "MOVE" -or
        [string]$moves[0].Entity -ne "RESOURCE" -or
        [string]$moves[0].ResourceMapping.Source.LogicalResourceId -ne "LifecycleGeneratorFunction" -or
        [string]$moves[0].ResourceMapping.Destination.LogicalResourceId -ne "LifecycleGeneratorFunction" -or
        -not (Test-StackIdentity ([string]$moves[0].ResourceMapping.Source.StackName) $SourceStackName) -or
        -not (Test-StackIdentity ([string]$moves[0].ResourceMapping.Destination.StackName) $DestinationStackName)) {
        throw "Stack refactor must contain exactly one lifecycle generator function MOVE"
    }
}

if (-not $Apply) {
    $source = Invoke-AwsJson @(
        "cloudformation", "describe-stacks", "--stack-name", $SourceStackName
    ) "Unable to inspect the source lifecycle stack"
    $stack = $source.Stacks[0]
    if ([string]$stack.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE")) {
        throw "Source lifecycle stack is not stable"
    }
    $parameters = @{}
    foreach ($parameter in @($stack.Parameters)) {
        $parameters[[string]$parameter.ParameterKey] = [string]$parameter.ParameterValue
    }
    foreach ($required in @(
        "ArtifactBucket", "GeneratorArtifactKey", "FunctionName", "AthenaOutputUri",
        "AthenaWorkgroup", "SourceDatabase"
    )) {
        if (-not $parameters.ContainsKey($required) -or -not $parameters[$required]) {
            throw "Source stack parameter $required is unavailable"
        }
    }
    $function = Invoke-AwsJson @(
        "lambda", "get-function-configuration", "--function-name", $parameters.FunctionName
    ) "Unable to inspect the deployed lifecycle generator"
    $roleOutputs = @($stack.Outputs | Where-Object OutputKey -eq "LifecycleGeneratorRoleArn")
    if ($roleOutputs.Count -ne 1 -or -not [string]$roleOutputs[0].OutputValue) {
        throw "Source lifecycle generator role output is unavailable"
    }
    if ([string]$function.FunctionName -ne $parameters.FunctionName -or
        [string]$function.State -ne "Active" -or
        [string]$function.LastUpdateStatus -ne "Successful" -or
        [string]$function.Role -ne [string]$roleOutputs[0].OutputValue) {
        throw "Lifecycle generator must be active before refactoring"
    }
    if ($parameters.FunctionName -ne "glap-stateful-lifecycle-generator-staging" -or
        $parameters.ArtifactBucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$' -or
        $parameters.GeneratorArtifactKey -notmatch '^[A-Za-z0-9][A-Za-z0-9!_.*''()/=-]{0,1023}$' -or
        $parameters.GeneratorArtifactKey.Contains("..") -or
        $parameters.AthenaOutputUri -notmatch '^s3://[^/]+/.+$' -or
        $parameters.AthenaWorkgroup -notmatch '^[A-Za-z0-9._-]{1,128}$' -or
        $parameters.SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$' -or
        [string]$function.Role -notmatch (
            '^arn:aws(-[a-z]+)?:iam::\d{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*' +
            'glap-stateful-lifecycle-generator-staging-role$'
        )) {
        throw "Deployed generator identity or parameters are outside the isolated staging contract"
    }

    $safeValues = @{
        ARTIFACT_BUCKET = $parameters.ArtifactBucket
        GENERATOR_ARTIFACT_KEY = $parameters.GeneratorArtifactKey
        FUNCTION_NAME = $parameters.FunctionName
        EXECUTION_ROLE_ARN = [string]$function.Role
        ATHENA_OUTPUT_URI = $parameters.AthenaOutputUri
        ATHENA_WORKGROUP = $parameters.AthenaWorkgroup
        SOURCE_DATABASE = $parameters.SourceDatabase
    }
    foreach ($value in $safeValues.Values) {
        if ($value -match '["\r\n]' -or -not $value) {
            throw "Generator refactor template values must be non-empty single-line safe strings"
        }
    }
    $renderedDestination = [IO.File]::ReadAllText($destinationTemplatePath)
    foreach ($entry in $safeValues.GetEnumerator()) {
        $renderedDestination = $renderedDestination.Replace("{{$($entry.Key)}}", $entry.Value)
    }
    if ($renderedDestination -match '{{[A-Z_]+}}') {
        throw "Generator refactor template contains unresolved placeholders"
    }
    foreach ($forbiddenSection in @("Parameters", "Mappings", "Conditions", "Rules", "Transform")) {
        if ($renderedDestination -match "(?m)^$forbiddenSection\s*:") {
            throw "Generator refactor destination template cannot contain $forbiddenSection"
        }
    }
    if ($renderedDestination -match '!Ref\s+(ArtifactBucket|GeneratorArtifactKey|FunctionName|ExecutionRoleArn|AthenaOutputUri|AthenaWorkgroup|SourceDatabase)') {
        throw "Generator refactor destination template must inline deployed configuration"
    }

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ("glap-generator-refactor-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
    try {
        $renderedPath = Join-Path $temporaryDirectory "generator.yaml"
        $requestPath = Join-Path $temporaryDirectory "request.json"
        [IO.File]::WriteAllText($renderedPath, $renderedDestination, [Text.UTF8Encoding]::new($false))
        $request = @{
            Description = "Move the isolated staging lifecycle generator into its one-resource stack"
            EnableStackCreation = $true
            ResourceMappings = @(@{
                Source = @{ StackName = $SourceStackName; LogicalResourceId = "LifecycleGeneratorFunction" }
                Destination = @{ StackName = $DestinationStackName; LogicalResourceId = "LifecycleGeneratorFunction" }
            })
            StackDefinitions = @(
                @{ StackName = $SourceStackName; TemplateBody = [IO.File]::ReadAllText($sourceTemplatePath) },
                @{ StackName = $DestinationStackName; TemplateBody = [IO.File]::ReadAllText($renderedPath) }
            )
        }
        [IO.File]::WriteAllText($requestPath, ($request | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        $created = Invoke-AwsJson @(
            "cloudformation", "create-stack-refactor", "--cli-input-json", "file://$requestPath"
        ) "Unable to create the generator stack refactor plan"
        $StackRefactorId = [string]$created.StackRefactorId
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

$deadline = [DateTime]::UtcNow.AddMinutes(10)
do {
    $description = Invoke-AwsJson @(
        "cloudformation", "describe-stack-refactor", "--stack-refactor-id", $StackRefactorId
    ) "Unable to inspect the generator stack refactor"
    if ([string]$description.Status -eq "CREATE_FAILED" -or
        [string]$description.ExecutionStatus -in @("EXECUTE_FAILED", "ROLLBACK_FAILED")) {
        throw "Generator stack refactor failed validation or execution"
    }
    if ([string]$description.Status -eq "CREATE_COMPLETE" -and
        [string]$description.ExecutionStatus -eq "AVAILABLE") { break }
    Start-Sleep -Seconds 5
} while ([DateTime]::UtcNow -lt $deadline)
if ([string]$description.Status -ne "CREATE_COMPLETE" -or
    [string]$description.ExecutionStatus -ne "AVAILABLE") {
    throw "Generator stack refactor did not become available before timeout"
}

$actions = Invoke-AwsJson @(
    "cloudformation", "list-stack-refactor-actions", "--stack-refactor-id", $StackRefactorId
) "Unable to inspect generator stack refactor actions"
Assert-ExactMove @($actions.StackRefactorActions)

if (-not $Apply) {
    Write-Host "Generator stack refactor plan is available."
    Write-Host "  Stack refactor ID: $StackRefactorId"
    Write-Host "  Action: MOVE"
    Write-Host "  Logical resource: LifecycleGeneratorFunction"
    Write-Host "  Resource count: 1"
    Write-Host "No stack refactor was executed. A separate human dispatch must supply this exact ID."
    return
}

& aws cloudformation execute-stack-refactor --stack-refactor-id $StackRefactorId @awsScope
if ($LASTEXITCODE -ne 0) { throw "Unable to execute the generator stack refactor" }

$deadline = [DateTime]::UtcNow.AddMinutes(20)
do {
    Start-Sleep -Seconds 5
    $description = Invoke-AwsJson @(
        "cloudformation", "describe-stack-refactor", "--stack-refactor-id", $StackRefactorId
    ) "Unable to verify the executed generator stack refactor"
    if ([string]$description.ExecutionStatus -eq "EXECUTE_COMPLETE") { break }
    if ([string]$description.ExecutionStatus -in @("EXECUTE_FAILED", "ROLLBACK_FAILED")) {
        throw "Generator stack refactor execution failed"
    }
} while ([DateTime]::UtcNow -lt $deadline)
if ([string]$description.ExecutionStatus -ne "EXECUTE_COMPLETE") {
    throw "Generator stack refactor execution timed out"
}
$destinationResources = Invoke-AwsJson @(
    "cloudformation", "list-stack-resources", "--stack-name", $DestinationStackName
) "Unable to verify the independent generator stack"
$sourceResources = Invoke-AwsJson @(
    "cloudformation", "list-stack-resources", "--stack-name", $SourceStackName
) "Unable to verify the shared lifecycle stack after refactor"
$destination = @($destinationResources.StackResourceSummaries)
$sourceGenerator = @(
    $sourceResources.StackResourceSummaries |
        Where-Object LogicalResourceId -eq "LifecycleGeneratorFunction"
)
if ($destination.Count -ne 1 -or
    [string]$destination[0].LogicalResourceId -ne "LifecycleGeneratorFunction" -or
    [string]$destination[0].ResourceType -ne "AWS::Lambda::Function" -or
    [string]$destination[0].PhysicalResourceId -ne "glap-stateful-lifecycle-generator-staging" -or
    $sourceGenerator.Count -ne 0) {
    throw "Post-refactor generator ownership verification failed"
}
Write-Host "LifecycleGeneratorFunction moved to the independent staging stack without invocation."
