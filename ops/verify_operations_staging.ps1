[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$IdentityStackName = "glap-operations-identity-staging",
    [string]$ApiStackName = "glap-operations-api-staging"
)

$ErrorActionPreference = "Stop"
$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }

function Get-Stack([string]$Name) {
    $json = & aws cloudformation describe-stacks --stack-name $Name @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) { throw "Required staging stack is unavailable" }
    return ($json | ConvertFrom-Json).Stacks[0]
}

function Get-Output($Stack, [string]$Key) {
    $value = ($Stack.Outputs | Where-Object OutputKey -eq $Key).OutputValue
    if (-not $value) { throw "Required protected stack output is unavailable" }
    return $value
}

$identity = Get-Stack $IdentityStackName
$api = Get-Stack $ApiStackName
$origin = Get-Output $identity "InternalOrigin"
$endpoint = Get-Output $api "ApiEndpoint"
$functionName = Get-Output $api "ApiFunctionName"

$site = Invoke-WebRequest -Uri $origin -UseBasicParsing -TimeoutSec 20
$unauthorizedStatuses = @()
try {
    Invoke-WebRequest -Uri ($endpoint.TrimEnd('/') + "/v1/actions?limit=1") `
        -UseBasicParsing -TimeoutSec 20 | Out-Null
} catch {
    $unauthorizedStatuses += [int]$_.Exception.Response.StatusCode
}
try {
    Invoke-WebRequest -Uri ($endpoint.TrimEnd('/') + "/v1/risks?limit=1") `
        -UseBasicParsing -TimeoutSec 20 | Out-Null
} catch {
    $unauthorizedStatuses += [int]$_.Exception.Response.StatusCode
}
try {
    Invoke-WebRequest -Uri ($endpoint.TrimEnd('/') + "/v1/outcomes?limit=1") `
        -UseBasicParsing -TimeoutSec 20 | Out-Null
} catch {
    $unauthorizedStatuses += [int]$_.Exception.Response.StatusCode
}
$preflight = Invoke-WebRequest -Uri ($endpoint.TrimEnd('/') + "/v1/actions") `
    -Method Options -Headers @{
        Origin = $origin
        "Access-Control-Request-Method" = "GET"
        "Access-Control-Request-Headers" = "authorization"
    } -UseBasicParsing -TimeoutSec 20
$function = & aws lambda get-function-configuration --function-name $functionName `
    @awsScope --output json | ConvertFrom-Json
$alarmCount = & aws cloudwatch describe-alarms --alarm-name-prefix $ApiStackName `
    @awsScope --query "length(MetricAlarms)" --output text
$alarmStates = & aws cloudwatch describe-alarms --alarm-name-prefix $ApiStackName `
    @awsScope --query "MetricAlarms[].StateValue" --output text
$accessLogGroup = "/aws/apigateway/glap-operations-api-staging/access"
$logGroupCount = & aws logs describe-log-groups --log-group-name-prefix $accessLogGroup `
    @awsScope --query "length(logGroups[?logGroupName=='$accessLogGroup'])" --output text
$metricFilterCount = & aws logs describe-metric-filters --log-group-name $accessLogGroup `
    @awsScope --query "length(metricFilters)" --output text

$checks = [ordered]@{
    "Identity stack stable" = $identity.StackStatus -in @("CREATE_COMPLETE", "UPDATE_COMPLETE")
    "API stack stable" = $api.StackStatus -in @("CREATE_COMPLETE", "UPDATE_COMPLETE")
    "API Lambda active" = $function.State -eq "Active" -and $function.LastUpdateStatus -eq "Successful"
    "Internal frontend HTTP 200" = $site.StatusCode -eq 200
    "Internal sign-in rendered" = $site.Content -match "Internal sign in"
    "Unauthenticated API routes rejected with 401" = $unauthorizedStatuses.Count -eq 3 -and @($unauthorizedStatuses | Where-Object { $_ -ne 401 }).Count -eq 0
    "CORS preflight successful" = $preflight.StatusCode -ge 200 -and $preflight.StatusCode -lt 300
    "CORS origin exact match" = $preflight.Headers["access-control-allow-origin"] -eq $origin
    "API alarms present" = [int]$alarmCount -ge 2
    "API alarms currently OK" = @($alarmStates -split '\s+' | Where-Object { $_ -and $_ -ne "OK" }).Count -eq 0
    "Redacted API access log present" = [int]$logGroupCount -eq 1
    "API throttle metric filter present" = [int]$metricFilterCount -ge 1
}

foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key): $($entry.Value)"
}
if ($checks.Values -contains $false) {
    throw "Operations staging verification failed"
}
Write-Host "Operations staging verification passed. Protected identifiers were not printed."
