[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$IdentityStackName = "glap-operations-identity-staging",
    [string]$ApiStackName = "glap-operations-api-staging",
    [string]$PlanPath = "",
    [switch]$AuthorizedSustainedReadLoad,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $PlanPath) {
    $PlanPath = Join-Path $scriptRoot "..\docs\operations_authenticated_read_load_plan_v1.json"
}
$validatorPath = Join-Path $scriptRoot "validate_operations_authenticated_read_load_plan.py"
$resolvedPlanPath = (Resolve-Path -LiteralPath $PlanPath).Path

& py -3.11 $validatorPath --plan $resolvedPlanPath --format json | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Authenticated read-load plan validation failed" }
$plan = Get-Content -LiteralPath $resolvedPlanPath -Raw | ConvertFrom-Json
$scheduledRequests = $plan.load_shape.ramp_up_seconds + `
    (($plan.load_shape.duration_seconds - $plan.load_shape.ramp_up_seconds) * `
    $plan.load_shape.target_requests_per_second)

Write-Host "Operations authenticated read-load staging plan"
Write-Host "  Contract status: $($plan.status)"
Write-Host "  Scope: $($plan.scope)"
Write-Host "  Viewer-safe GET routes: $(@($plan.routes).Count)"
Write-Host "  Duration seconds: $($plan.load_shape.duration_seconds)"
Write-Host "  Target requests/second: $($plan.load_shape.target_requests_per_second)"
Write-Host "  Deterministic scheduled requests: $scheduledRequests"
Write-Host "  Temporary viewer identity planned: True"
Write-Host "  Email delivery: False"
Write-Host "  Token storage: Process memory only"
Write-Host "  Aggregate-only result: True"
Write-Host "  Raw request records retained: False"
Write-Host "  Operational mutation expected: False"
Write-Host "  Production access expected: False"
Write-Host "  Recurring schedule expected: False"
if (-not $Apply) {
    Write-Host "  AWS calls executed: False"
    Write-Host "  External requests executed: False"
    Write-Host "Plan only. A named human must separately authorize -Apply -AuthorizedSustainedReadLoad."
    return
}
if (-not $AuthorizedSustainedReadLoad) {
    throw "Apply requires -AuthorizedSustainedReadLoad from a named human"
}

$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }
$allowedRoutes = @{}
foreach ($route in @($plan.routes)) {
    if ($route.method -ne "GET") { throw "UNEXPECTED_HTTP_METHOD" }
    if ($route.path -match '/events|/shipments|\{|\}') { throw "NON_ALLOWLISTED_ROUTE" }
    $allowedRoutes[$route.id] = $route
}

function Get-Stack([string]$Name) {
    $json = & aws cloudformation describe-stacks --stack-name $Name @awsScope `
        --output json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json) { throw "Required staging stack is unavailable" }
    return ($json | ConvertFrom-Json).Stacks[0]
}

function Get-Output($Stack, [string]$Key) {
    $value = ($Stack.Outputs | Where-Object OutputKey -eq $Key).OutputValue
    if (-not $value) { throw "Required protected stack output is unavailable" }
    return $value
}

function Test-UserAbsent([string]$UserPoolId, [string]$Username) {
    $usersJson = & aws cognito-idp list-users --user-pool-id $UserPoolId `
        @awsScope --output json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $usersJson) { return $false }
    $users = @((($usersJson | ConvertFrom-Json).Users))
    return -not ($users.Username -contains $Username)
}

function New-StrongPassword {
    $bytes = [byte[]]::new(32)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes) + "Aa1!"
}

function Get-Percentile([System.Collections.Generic.List[int]]$Values, [double]$Percentile) {
    if ($Values.Count -eq 0) { return 0 }
    $sorted = @($Values | Sort-Object)
    $index = [Math]::Ceiling(($Percentile / 100.0) * $sorted.Count) - 1
    return [int]$sorted[[Math]::Max(0, $index)]
}

function New-RouteMetrics([string]$RouteId) {
    return [ordered]@{
        route_id = $RouteId
        requests_completed = 0
        responses_2xx = 0
        responses_429 = 0
        responses_other_4xx = 0
        responses_5xx = 0
        latencies = [System.Collections.Generic.List[int]]::new()
    }
}

function Get-RouteSequence($Routes, [int]$Count) {
    $sequence = [System.Collections.Generic.List[object]]::new()
    $assigned = @{}
    foreach ($route in $Routes) { $assigned[$route.id] = 0 }
    for ($index = 1; $index -le $Count; $index++) {
        $selected = $null
        $bestDeficit = [double]::NegativeInfinity
        foreach ($route in $Routes) {
            $expected = $index * ([double]$route.weight_pct / 100.0)
            $deficit = $expected - $assigned[$route.id]
            if ($deficit -gt $bestDeficit) {
                $selected = $route
                $bestDeficit = $deficit
            }
        }
        $sequence.Add($selected)
        $assigned[$selected.id]++
    }
    return $sequence
}

function Get-SydneyDate {
    try { $zone = [TimeZoneInfo]::FindSystemTimeZoneById("Australia/Sydney") }
    catch { $zone = [TimeZoneInfo]::FindSystemTimeZoneById("AUS Eastern Standard Time") }
    return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone).ToString("yyyy-MM-dd")
}

$identity = Get-Stack $IdentityStackName
$api = Get-Stack $ApiStackName
$poolId = Get-Output $identity "UserPoolId"
$clientId = Get-Output $identity "JwtAudience"
$endpoint = (Get-Output $api "ApiEndpoint").TrimEnd('/')
$clientFlows = & aws cognito-idp describe-user-pool-client --user-pool-id $poolId `
    --client-id $clientId @awsScope --query "UserPoolClient.ExplicitAuthFlows" `
    --output text 2>$null
if ($clientFlows -notmatch "ALLOW_ADMIN_USER_PASSWORD_AUTH") {
    throw "The staging client is not ready for IAM-administered read-load verification"
}

$username = $null
$accessToken = $null
$cleanupConfirmed = $false
$runStatus = "FAILED_CLOSED"
$abortReason = "RESULT_RECONCILIATION_FAILED"
$attempted = 0
$completed = 0
$responses2xx = 0
$responses429 = 0
$responsesOther4xx = 0
$responses5xx = 0
$consecutiveFailures = 0
$latencies = [System.Collections.Generic.List[int]]::new()
$routeMetrics = [ordered]@{}
foreach ($route in @($plan.routes)) { $routeMetrics[$route.id] = New-RouteMetrics $route.id }

try {
    $login = "glap-read-load-$([guid]::NewGuid().ToString('N').Substring(0, 12))@example.invalid"
    $password = New-StrongPassword
    $username = & aws cognito-idp admin-create-user --user-pool-id $poolId `
        --username $login --temporary-password $password --message-action SUPPRESS `
        --user-attributes "Name=email,Value=$login" "Name=email_verified,Value=true" `
        @awsScope --query "User.Username" --output text 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $username) { throw "Unable to create isolated viewer" }
    & aws cognito-idp admin-set-user-password --user-pool-id $poolId `
        --username $username --password $password --permanent @awsScope 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Unable to activate isolated viewer" }
    & aws cognito-idp admin-add-user-to-group --user-pool-id $poolId `
        --username $username --group-name viewer @awsScope 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Unable to assign isolated viewer group" }
    $auth = & aws cognito-idp admin-initiate-auth --user-pool-id $poolId `
        --client-id $clientId --auth-flow ADMIN_USER_PASSWORD_AUTH `
        --auth-parameters "USERNAME=$login,PASSWORD=$password" @awsScope `
        --output json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $auth) { throw "Unable to authenticate isolated viewer" }
    $accessToken = ($auth | ConvertFrom-Json).AuthenticationResult.AccessToken
    if (-not $accessToken) { throw "Authentication returned no access token" }

    $sequence = Get-RouteSequence @($plan.routes) $scheduledRequests
    $runClock = [System.Diagnostics.Stopwatch]::StartNew()
    for ($index = 0; $index -lt $sequence.Count; $index++) {
        $offsetMilliseconds = if ($index -lt $plan.load_shape.ramp_up_seconds) {
            $index * 1000
        } else {
            ($plan.load_shape.ramp_up_seconds * 1000) + `
                (($index - $plan.load_shape.ramp_up_seconds) * 500)
        }
        while ($runClock.ElapsedMilliseconds -lt $offsetMilliseconds) {
            $remaining = $offsetMilliseconds - $runClock.ElapsedMilliseconds
            Start-Sleep -Milliseconds ([Math]::Min(250, [Math]::Max(1, $remaining)))
        }
        $route = $sequence[$index]
        if (-not $allowedRoutes.ContainsKey($route.id)) {
            $abortReason = "NON_ALLOWLISTED_ROUTE"
            break
        }
        if ($route.method -ne "GET") {
            $abortReason = "UNEXPECTED_HTTP_METHOD"
            break
        }

        $attempted++
        $requestClock = [System.Diagnostics.Stopwatch]::StartNew()
        $statusCode = 0
        try {
            $response = Invoke-WebRequest -Uri "$endpoint$($route.path)" -Method GET `
                -Headers @{ Authorization = "Bearer $accessToken" } -UseBasicParsing `
                -TimeoutSec ([Math]::Ceiling($plan.load_shape.request_timeout_ms / 1000))
            $statusCode = [int]$response.StatusCode
        } catch {
            if ($_.Exception.Response) { $statusCode = [int]$_.Exception.Response.StatusCode }
            else { $statusCode = 500 }
        } finally {
            $requestClock.Stop()
        }
        $latency = [int]$requestClock.ElapsedMilliseconds
        $completed++
        $latencies.Add($latency)
        $metric = $routeMetrics[$route.id]
        $metric.requests_completed++
        $metric.latencies.Add($latency)
        if ($statusCode -ge 200 -and $statusCode -lt 300) {
            $responses2xx++
            $metric.responses_2xx++
            $consecutiveFailures = 0
        } elseif ($statusCode -eq 429) {
            $responses429++
            $metric.responses_429++
            $consecutiveFailures++
        } elseif ($statusCode -ge 500) {
            $responses5xx++
            $metric.responses_5xx++
            $consecutiveFailures++
        } else {
            $responsesOther4xx++
            $metric.responses_other_4xx++
            $consecutiveFailures = 0
        }
        if ($statusCode -in @(401, 403)) { $abortReason = "AUTHORIZATION_FAILURE"; break }
        if ($consecutiveFailures -ge $plan.abort_gates.max_consecutive_failures) {
            $abortReason = "CONSECUTIVE_FAILURES_EXCEEDED"; break
        }
        if ($completed -ge 20) {
            if (($responses429 * 100.0 / $completed) -gt $plan.abort_gates.max_429_rate_pct) {
                $abortReason = "THROTTLE_RATE_EXCEEDED"; break
            }
            if (($responses5xx * 100.0 / $completed) -gt $plan.abort_gates.max_5xx_rate_pct) {
                $abortReason = "SERVER_ERROR_RATE_EXCEEDED"; break
            }
            if ((Get-Percentile $latencies 95) -gt $plan.abort_gates.max_p95_latency_ms) {
                $abortReason = "P95_LATENCY_EXCEEDED"; break
            }
        }
    }
    $runClock.Stop()
    if ($abortReason -eq "RESULT_RECONCILIATION_FAILED") {
        $runStatus = "COMPLETED"
        $abortReason = "NONE"
    } else {
        $runStatus = "ABORTED"
    }
} finally {
    $accessToken = $null
    $auth = $null
    $password = $null
    $login = $null
    if ($username) {
        & aws cognito-idp admin-delete-user --user-pool-id $poolId `
            --username $username @awsScope 2>$null
        if ($LASTEXITCODE -eq 0) {
            $cleanupConfirmed = Test-UserAbsent $poolId $username
        }
    }
}

if (-not $cleanupConfirmed) {
    $runStatus = "FAILED_CLOSED"
    $abortReason = "IDENTITY_CLEANUP_FAILED"
}
$routeResults = @()
foreach ($route in @($plan.routes)) {
    $metric = $routeMetrics[$route.id]
    $routeResults += [ordered]@{
        route_id = $route.id
        requests_completed = [int]$metric.requests_completed
        responses_2xx = [int]$metric.responses_2xx
        responses_429 = [int]$metric.responses_429
        responses_other_4xx = [int]$metric.responses_other_4xx
        responses_5xx = [int]$metric.responses_5xx
        latency_p50_ms = Get-Percentile $metric.latencies 50
        latency_p95_ms = Get-Percentile $metric.latencies 95
        latency_p99_ms = Get-Percentile $metric.latencies 99
    }
}
$baseline = [ordered]@{
    schema_version = "operations-authenticated-read-load-baseline.v1"
    as_of_date = Get-SydneyDate
    business_timezone = "Australia/Sydney"
    scope = "PRIVATE_OPERATIONS_STAGING"
    plan_schema_version = $plan.schema_version
    evidence_class = "STAGING_ENGINEERING"
    run_status = $runStatus
    load_shape = [ordered]@{
        duration_seconds = [int]$plan.load_shape.duration_seconds
        target_requests_per_second = [int]$plan.load_shape.target_requests_per_second
        max_concurrency = [int]$plan.load_shape.max_concurrency
    }
    summary = [ordered]@{
        requests_attempted = [int]$attempted
        requests_completed = [int]$completed
        responses_2xx = [int]$responses2xx
        responses_429 = [int]$responses429
        responses_other_4xx = [int]$responsesOther4xx
        responses_5xx = [int]$responses5xx
        latency_p50_ms = Get-Percentile $latencies 50
        latency_p95_ms = Get-Percentile $latencies 95
        latency_p99_ms = Get-Percentile $latencies 99
        abort_reason_code = $abortReason
    }
    routes = $routeResults
    authority = [ordered]@{
        operational_mutation_executed = $false
        production_accessed = $false
        recurring_schedule_created = $false
    }
    claim_boundary = [ordered]@{
        production_readiness = $false
        production_sla = $false
        real_logistics_performance = $false
    }
}

$baselinePath = Join-Path ([System.IO.Path]::GetTempPath()) `
    "glap-authenticated-read-load-$([guid]::NewGuid().ToString('N')).json"
try {
    $baselineJson = $baseline | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        $baselinePath,
        $baselineJson,
        [System.Text.UTF8Encoding]::new($false)
    )
    & py -3.11 $validatorPath --plan $resolvedPlanPath --baseline $baselinePath
    if ($LASTEXITCODE -ne 0) { throw "RESULT_RECONCILIATION_FAILED" }
} finally {
    $baselineJson = $null
    if (Test-Path -LiteralPath $baselinePath) {
        Remove-Item -LiteralPath $baselinePath -Force
    }
}

Write-Host "Authenticated read-load aggregate result"
Write-Host "  Run status: $runStatus"
Write-Host "  Abort reason: $abortReason"
Write-Host "  Requests completed: $completed"
Write-Host "  Responses 2xx/429/other4xx/5xx: $responses2xx/$responses429/$responsesOther4xx/$responses5xx"
Write-Host "  P95 latency ms: $(Get-Percentile $latencies 95)"
Write-Host "  Temporary viewer removed and confirmed: $cleanupConfirmed"
Write-Host "  Persisted result artifact: False"
Write-Host "  Tokens, identity values, endpoint, and infrastructure identifiers printed: False"
if ($runStatus -ne "COMPLETED") { throw "Authenticated read-load stopped by a fail-closed gate" }
