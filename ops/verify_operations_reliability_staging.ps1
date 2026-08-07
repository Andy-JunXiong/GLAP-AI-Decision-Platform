[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$IdentityStackName = "glap-operations-identity-staging",
    [string]$ApiStackName = "glap-operations-api-staging",
    [int]$ThrottleRequestCount = 60,
    [int]$AlarmTimeoutSeconds = 300,
    [int]$RecoveryTimeoutSeconds = 600,
    [switch]$InjectFailure,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if ($ThrottleRequestCount -lt 25 -or $ThrottleRequestCount -gt 100) {
    throw "ThrottleRequestCount must be between 25 and 100"
}
if ($AlarmTimeoutSeconds -lt 120 -or $AlarmTimeoutSeconds -gt 600) {
    throw "AlarmTimeoutSeconds must be between 120 and 600"
}
if ($RecoveryTimeoutSeconds -lt 180 -or $RecoveryTimeoutSeconds -gt 900) {
    throw "RecoveryTimeoutSeconds must be between 180 and 900"
}

Write-Host "Operations staging reliability verification plan"
Write-Host "  Existing audit event replay only: True"
Write-Host "  New or changed Action expected: False"
Write-Host "  Same request ID sequential and concurrent replay: True"
Write-Host "  Throttle burst uses role-denied invalid operations: True"
Write-Host "  API stage throttle temporarily lowered then restored: True"
Write-Host "  Failure injection temporarily isolates the mutation dependency: $([bool]$InjectFailure)"
Write-Host "  Original Lambda environment restored in finally: True"
Write-Host "  Failure and throttle alarms must enter ALARM then recover to OK: True"
Write-Host "  Synchronous API DLQ boundary must remain empty: True"
Write-Host "  Temporary users deleted after verification: True"
Write-Host "  Tokens, users, Action IDs, request IDs, URLs, and AWS IDs printed: False"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply -InjectFailure after reviewing the temporary staging mutation outage."
    return
}
if (-not $InjectFailure) {
    throw "Apply requires -InjectFailure so the recovery evidence cannot be reported without a real controlled failure"
}

$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }
$script:ReliabilityUsers = [System.Collections.Generic.List[string]]::new()

function Invoke-AwsJson([string[]]$Arguments) {
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) { throw "Required AWS read failed" }
    return $json | ConvertFrom-Json
}

function Get-Stack([string]$Name) {
    $response = Invoke-AwsJson @("cloudformation", "describe-stacks", "--stack-name", $Name)
    return $response.Stacks[0]
}

function Get-Output($Stack, [string]$Key) {
    $value = ($Stack.Outputs | Where-Object OutputKey -eq $Key).OutputValue
    if (-not $value) { throw "Required protected stack output is unavailable" }
    return [string]$value
}

function Get-PhysicalResource([string]$StackName, [string]$LogicalId) {
    $resource = Invoke-AwsJson @(
        "cloudformation", "describe-stack-resource", "--stack-name", $StackName,
        "--logical-resource-id", $LogicalId
    )
    return [string]$resource.StackResourceDetail.PhysicalResourceId
}

function Invoke-AthenaRows([string]$Statement, [string]$Database, [string]$Output, [string]$Workgroup) {
    $queryId = & aws athena start-query-execution --query-string $Statement `
        --query-execution-context "Database=$Database" `
        --result-configuration "OutputLocation=$Output" `
        --work-group $Workgroup @awsScope --query QueryExecutionId --output text
    if ($LASTEXITCODE -ne 0 -or -not $queryId) { throw "Unable to start reliability evidence query" }
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        $execution = Invoke-AwsJson @(
            "athena", "get-query-execution", "--query-execution-id", $queryId
        )
        $state = [string]$execution.QueryExecution.Status.State
        if ($state -in @("FAILED", "CANCELLED")) { throw "Reliability evidence query failed" }
        if ($state -eq "SUCCEEDED") { break }
        if ([DateTime]::UtcNow -ge $deadline) { throw "Reliability evidence query timed out" }
        Start-Sleep -Milliseconds 500
    } while ($true)
    $result = Invoke-AwsJson @("athena", "get-query-results", "--query-execution-id", $queryId)
    $headers = @($result.ResultSet.ResultSetMetadata.ColumnInfo | ForEach-Object { [string]$_.Name })
    $rows = @()
    foreach ($row in @($result.ResultSet.Rows | Select-Object -Skip 1)) {
        $values = @($row.Data | ForEach-Object { [string]$_.VarCharValue })
        $record = [ordered]@{}
        for ($index = 0; $index -lt $headers.Count; $index++) {
            $record[$headers[$index]] = $(if ($index -lt $values.Count) { $values[$index] } else { $null })
        }
        $rows += [pscustomobject]$record
    }
    return $rows
}

function New-StrongPassword {
    $bytes = [byte[]]::new(32)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes) + "Aa1!"
}

function Write-TemporaryJson($Value) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) (
        "glap-operations-reliability-" + [guid]::NewGuid().ToString("N") + ".json"
    )
    $json = $Value | ConvertTo-Json -Depth 10 -Compress
    [System.IO.File]::WriteAllText(
        $path, $json, [System.Text.UTF8Encoding]::new($false)
    )
    return $path
}

function New-RoleSession([string]$Role, [string]$PoolId, [string]$ClientId, [string]$Suffix) {
    $login = "glap-reliability-$Role-$Suffix@example.invalid"
    $password = New-StrongPassword
    $username = & aws cognito-idp admin-create-user --user-pool-id $PoolId `
        --username $login --temporary-password $password --message-action SUPPRESS `
        --user-attributes "Name=email,Value=$login" "Name=email_verified,Value=true" `
        @awsScope --query User.Username --output text
    if ($LASTEXITCODE -ne 0 -or -not $username) { throw "Unable to create isolated reliability user" }
    $script:ReliabilityUsers.Add([string]$username)
    & aws cognito-idp admin-set-user-password --user-pool-id $PoolId `
        --username $username --password $password --permanent @awsScope | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to activate isolated reliability user" }
    & aws cognito-idp admin-add-user-to-group --user-pool-id $PoolId `
        --username $username --group-name $Role @awsScope | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to assign isolated reliability role" }
    $auth = & aws cognito-idp admin-initiate-auth --user-pool-id $PoolId `
        --client-id $ClientId --auth-flow ADMIN_USER_PASSWORD_AUTH `
        --auth-parameters "USERNAME=$login,PASSWORD=$password" @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $auth) { throw "Unable to authenticate isolated reliability user" }
    $token = ($auth | ConvertFrom-Json).AuthenticationResult.AccessToken
    if (-not $token) { throw "Reliability authentication returned no access token" }
    return [pscustomobject]@{ Username = $username; Token = $token }
}

function Invoke-Api([string]$Uri, [string]$Token, [string]$Body) {
    try {
        $response = Invoke-WebRequest -Uri $Uri -Method POST `
            -Headers @{Authorization = "Bearer $Token"} -ContentType "application/json" `
            -Body $Body -UseBasicParsing -TimeoutSec 45
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = [string]$response.Content }
    } catch {
        if ($_.Exception.Response) {
            return [pscustomobject]@{ Status = [int]$_.Exception.Response.StatusCode; Body = "" }
        }
        throw
    }
}

function Invoke-ConcurrentPosts([string]$Uri, [string]$Token, [string]$Body, [int]$Count) {
    Add-Type -AssemblyName System.Net.Http
    [System.Net.ServicePointManager]::DefaultConnectionLimit = [Math]::Max(100, $Count)
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds(45)
    $requests = @()
    $tasks = @()
    try {
        for ($index = 0; $index -lt $Count; $index++) {
            $request = [System.Net.Http.HttpRequestMessage]::new(
                [System.Net.Http.HttpMethod]::Post, $Uri
            )
            $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new(
                "Bearer", $Token
            )
            $request.Content = [System.Net.Http.StringContent]::new(
                $Body, [System.Text.Encoding]::UTF8, "application/json"
            )
            $requests += $request
            $tasks += $client.SendAsync($request)
        }
        [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]$tasks)
        $responses = @()
        foreach ($task in $tasks) {
            $response = $task.Result
            $content = $response.Content.ReadAsStringAsync().Result
            $responses += [pscustomobject]@{ Status = [int]$response.StatusCode; Body = $content }
            $response.Dispose()
        }
        return $responses
    } finally {
        foreach ($request in $requests) { $request.Dispose() }
        $client.Dispose()
    }
}

function Wait-Alarms([string[]]$AlarmNames, [string]$TargetState, [int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $states = @()
        foreach ($alarmName in $AlarmNames) {
            $alarm = Invoke-AwsJson @("cloudwatch", "describe-alarms", "--alarm-names", $alarmName)
            $states += [string]$alarm.MetricAlarms[0].StateValue
        }
        if (@($states | Where-Object { $_ -ne $TargetState }).Count -eq 0) { return $true }
        if ([DateTime]::UtcNow -ge $deadline) { return $false }
        Start-Sleep -Seconds 10
    } while ($true)
}

function Wait-AlarmsObserved([string[]]$AlarmNames, [int]$TimeoutSeconds) {
    $observed = @{}
    foreach ($alarmName in $AlarmNames) { $observed[$alarmName] = $false }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        foreach ($alarmName in $AlarmNames) {
            $alarm = Invoke-AwsJson @("cloudwatch", "describe-alarms", "--alarm-names", $alarmName)
            if ([string]$alarm.MetricAlarms[0].StateValue -eq "ALARM") {
                $observed[$alarmName] = $true
            }
        }
        if (@($observed.Values | Where-Object { $_ -ne $true }).Count -eq 0) { return $true }
        if ([DateTime]::UtcNow -ge $deadline) { return $false }
        Start-Sleep -Seconds 10
    } while ($true)
}

try { $sydneyZone = [TimeZoneInfo]::FindSystemTimeZoneById("Australia/Sydney") }
catch { $sydneyZone = [TimeZoneInfo]::FindSystemTimeZoneById("AUS Eastern Standard Time") }
$sydneyDate = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $sydneyZone).ToString("yyyy-MM-dd")
$identityStack = Get-Stack $IdentityStackName
$apiStack = Get-Stack $ApiStackName
$poolId = Get-Output $identityStack "UserPoolId"
$clientId = Get-Output $identityStack "JwtAudience"
$endpoint = (Get-Output $apiStack "ApiEndpoint").TrimEnd('/')
$functionName = Get-Output $apiStack "ApiFunctionName"
$apiId = Get-PhysicalResource $ApiStackName "OperationsApi"
$deadLetterArn = Get-Output $apiStack "DeadLetterQueueArn"
$function = Invoke-AwsJson @("lambda", "get-function-configuration", "--function-name", $functionName)
$database = [string]$function.Environment.Variables.ATHENA_SOURCE_DATABASE
$output = [string]$function.Environment.Variables.ATHENA_OUTPUT
$workgroup = [string]$function.Environment.Variables.ATHENA_WORKGROUP
$auditTable = "fact_lifecycle_action_audit_staging_v1"
$evidenceRows = @(Invoke-AthenaRows @"
SELECT action_id, request_id, event_type
FROM $database.$auditTable
WHERE temporal_scope_id = 'OPERATIONAL'
  AND created_date <= DATE '$sydneyDate'
  AND event_type IN ('APPROVE', 'REJECT', 'COMPLETE')
ORDER BY occurred_at DESC
LIMIT 1
"@ $database $output $workgroup)
if ($evidenceRows.Count -ne 1) { throw "No eligible operational audit event exists for safe replay" }
$evidence = $evidenceRows[0]
$safeValue = '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
if ($evidence.action_id -notmatch $safeValue -or $evidence.request_id -notmatch $safeValue) {
    throw "Existing audit evidence has unsafe identifiers"
}
$eventType = [string]$evidence.event_type
if ($eventType -notin @("APPROVE", "REJECT", "COMPLETE")) { throw "Unsupported replay event type" }

$countBefore = @(Invoke-AthenaRows @"
SELECT count(*) AS event_count
FROM $database.$auditTable
WHERE temporal_scope_id = 'OPERATIONAL'
  AND request_id = '$($evidence.request_id)'
"@ $database $output $workgroup)[0].event_count

$failureAlarm = Get-PhysicalResource $ApiStackName "OperationsApiFailureAlarm"
$throttleAlarm = Get-PhysicalResource $ApiStackName "OperationsApiThrottleAlarm"
$alarmNames = @($failureAlarm, $throttleAlarm)
$alarmConfiguration = Invoke-AwsJson @(
    "cloudwatch", "describe-alarms", "--alarm-names", $failureAlarm, $throttleAlarm
)
$externalAlarmActions = @(
    $alarmConfiguration.MetricAlarms | ForEach-Object {
        @($_.AlarmActions) + @($_.OKActions) + @($_.InsufficientDataActions)
    } | Where-Object { $_ }
)
if ($externalAlarmActions.Count -ne 0) {
    throw "Reliability verification refuses to trigger alarms with external actions"
}
if (-not (Wait-Alarms $alarmNames "OK" $RecoveryTimeoutSeconds)) {
    throw "Operations alarms were not OK before reliability verification"
}
$queueName = ($deadLetterArn -split ':')[-1]
$queueUrl = & aws sqs get-queue-url --queue-name $queueName @awsScope --query QueueUrl --output text
$dlqBefore = & aws sqs get-queue-attributes --queue-url $queueUrl `
    --attribute-names ApproximateNumberOfMessages @awsScope `
    --query 'Attributes.ApproximateNumberOfMessages' --output text

$tokens = @()
$suffix = [guid]::NewGuid().ToString("N").Substring(0, 12)
try {
    $administrator = New-RoleSession "administrator" $poolId $clientId $suffix
    $tokens += $administrator.Token

    $replayBody = @{
        operation = $eventType
        request_id = [string]$evidence.request_id
        reason = "Isolated reliability replay of existing audit evidence"
        logical_run_date = $sydneyDate
    } | ConvertTo-Json -Compress
    $replayUri = "$endpoint/v1/actions/$($evidence.action_id)/events"
    $firstReplay = Invoke-Api $replayUri $administrator.Token $replayBody
    $secondReplay = Invoke-Api $replayUri $administrator.Token $replayBody
    $firstBody = $(if ($firstReplay.Status -eq 200) { $firstReplay.Body | ConvertFrom-Json } else { $null })
    $secondBody = $(if ($secondReplay.Status -eq 200) { $secondReplay.Body | ConvertFrom-Json } else { $null })
    $sequentialReplayPassed = (
        $firstReplay.Status -eq 200 -and $secondReplay.Status -eq 200 -and
        $firstBody.action.idempotent_replay -eq $true -and
        $secondBody.action.idempotent_replay -eq $true -and
        $firstBody.action.event_id -eq $secondBody.action.event_id
    )

    $concurrent = @(Invoke-ConcurrentPosts $replayUri $administrator.Token $replayBody 2)
    $concurrentReplayPassed = $concurrent.Count -eq 2
    $concurrentEventIds = @()
    foreach ($response in $concurrent) {
        if ($response.Status -ne 200) { $concurrentReplayPassed = $false; continue }
        $body = $response.Body | ConvertFrom-Json
        if ($body.action.idempotent_replay -ne $true) { $concurrentReplayPassed = $false }
        $concurrentEventIds += [string]$body.action.event_id
    }
    if (@($concurrentEventIds | Sort-Object -Unique).Count -ne 1) {
        $concurrentReplayPassed = $false
    }

    $missingAction = "reliability-missing-" + [guid]::NewGuid().ToString("N")
    $failureBody = @{
        operation = "APPROVE"
        request_id = "reliability-failure-" + [guid]::NewGuid().ToString("N")
        reason = "Isolated missing-Action failure verification"
        logical_run_date = $sydneyDate
    } | ConvertTo-Json -Compress
    $originalEnvironment = @{}
    foreach ($entry in $function.Environment.Variables.PSObject.Properties) {
        $originalEnvironment[$entry.Name] = [string]$entry.Value
    }
    $isolatedEnvironment = @{} + $originalEnvironment
    $isolatedEnvironment.ACTION_MUTATION_FUNCTION = "glap-reliability-missing-dependency"
    $originalEnvironmentPath = Write-TemporaryJson @{Variables = $originalEnvironment}
    $isolatedEnvironmentPath = Write-TemporaryJson @{Variables = $isolatedEnvironment}
    $configurationChanged = $false
    $restoredEnvironment = $false
    try {
        & aws lambda update-function-configuration --function-name $functionName `
            --revision-id $function.RevisionId `
            --environment "file://$isolatedEnvironmentPath" @awsScope | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to isolate the staging mutation dependency" }
        $configurationChanged = $true
        & aws lambda wait function-updated-v2 --function-name $functionName @awsScope
        if ($LASTEXITCODE -ne 0) { throw "Staging failure injection did not become active" }
        $failureResponse = Invoke-Api "$endpoint/v1/actions/$missingAction/events" `
            $administrator.Token $failureBody
        $failureInjectionPassed = $failureResponse.Status -eq 503
    } finally {
        if ($configurationChanged) {
            $currentFunction = Invoke-AwsJson @(
                "lambda", "get-function-configuration", "--function-name", $functionName
            )
            & aws lambda update-function-configuration --function-name $functionName `
                --revision-id $currentFunction.RevisionId `
                --environment "file://$originalEnvironmentPath" @awsScope | Out-Null
            if ($LASTEXITCODE -eq 0) {
                & aws lambda wait function-updated-v2 --function-name $functionName @awsScope
                $restoredEnvironment = $LASTEXITCODE -eq 0
            }
        }
        Remove-Item -LiteralPath $originalEnvironmentPath, $isolatedEnvironmentPath `
            -Force -ErrorAction SilentlyContinue
    }
    if (-not $restoredEnvironment) { throw "Staging Lambda environment restoration failed" }
    $recoveryResponse = Invoke-Api "$endpoint/v1/actions/$missingAction/events" `
        $administrator.Token $failureBody
    $dependencyRecoveryPassed = $recoveryResponse.Status -eq 404

    $deniedBody = @{
        operation = "UNSUPPORTED"
        request_id = "reliability-throttle-" + [guid]::NewGuid().ToString("N")
        reason = "Isolated viewer-denied throttle verification"
        logical_run_date = $sydneyDate
    } | ConvertTo-Json -Compress
    $stage = Invoke-AwsJson @(
        "apigatewayv2", "get-stage", "--api-id", $apiId, "--stage-name", '$default'
    )
    $originalBurst = [int]$stage.DefaultRouteSettings.ThrottlingBurstLimit
    $originalRate = [double]$stage.DefaultRouteSettings.ThrottlingRateLimit
    $stageChanged = $false
    $stageRestored = $false
    try {
        & aws apigatewayv2 update-stage --api-id $apiId --stage-name '$default' `
            --default-route-settings "ThrottlingBurstLimit=1,ThrottlingRateLimit=1" `
            @awsScope | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to apply the bounded staging throttle" }
        $stageChanged = $true
        Start-Sleep -Seconds 2
        $burst = @(Invoke-ConcurrentPosts "$endpoint/v1/actions/$missingAction/events" `
            $administrator.Token $deniedBody $ThrottleRequestCount)
        $throttledCount = @($burst | Where-Object Status -eq 429).Count
        $unexpectedSuccessCount = @($burst | Where-Object Status -eq 200).Count
        $throttlePassed = $throttledCount -gt 0 -and $unexpectedSuccessCount -eq 0
    } finally {
        if ($stageChanged) {
            & aws apigatewayv2 update-stage --api-id $apiId --stage-name '$default' `
                --default-route-settings "ThrottlingBurstLimit=$originalBurst,ThrottlingRateLimit=$originalRate" `
                @awsScope | Out-Null
            $stageRestored = $LASTEXITCODE -eq 0
        }
    }
    if (-not $stageRestored) { throw "Staging API throttle restoration failed" }
    Start-Sleep -Seconds 3
    $recoveredRequest = Invoke-Api "$endpoint/v1/actions/$missingAction/events" `
        $administrator.Token $deniedBody
    $requestRecoveryPassed = $recoveredRequest.Status -eq 403

    $alarmsEnteredAlarm = Wait-AlarmsObserved $alarmNames $AlarmTimeoutSeconds
    $alarmsRecovered = $(if ($alarmsEnteredAlarm) {
        Wait-Alarms $alarmNames "OK" $RecoveryTimeoutSeconds
    } else { $false })

    $countAfter = @(Invoke-AthenaRows @"
SELECT count(*) AS event_count
FROM $database.$auditTable
WHERE temporal_scope_id = 'OPERATIONAL'
  AND request_id = '$($evidence.request_id)'
"@ $database $output $workgroup)[0].event_count
    $auditUnchanged = [string]$countBefore -eq [string]$countAfter -and [string]$countAfter -eq "1"
    $dlqAfter = & aws sqs get-queue-attributes --queue-url $queueUrl `
        --attribute-names ApproximateNumberOfMessages @awsScope `
        --query 'Attributes.ApproximateNumberOfMessages' --output text
    $dlqBoundaryPassed = [string]$dlqBefore -eq "0" -and [string]$dlqAfter -eq "0"

    $checks = [ordered]@{
        "Sequential same-request replay" = $sequentialReplayPassed
        "Concurrent same-request replay" = $concurrentReplayPassed
        "Audit event count remained one" = $auditUnchanged
        "Controlled dependency failure returned 503" = $failureInjectionPassed
        "Mutation dependency recovered to domain 404" = $dependencyRecoveryPassed
        "Gateway burst produced 429 without success" = $throttlePassed
        "API Gateway throttle settings restored" = $stageRestored
        "Request path recovered after burst" = $requestRecoveryPassed
        "Failure and throttle alarms entered ALARM" = $alarmsEnteredAlarm
        "Failure and throttle alarms recovered to OK" = $alarmsRecovered
        "Synchronous API DLQ remained empty" = $dlqBoundaryPassed
    }
    Write-Host "Throttle responses observed: $throttledCount"
    foreach ($entry in $checks.GetEnumerator()) {
        Write-Host "$($entry.Key): $($entry.Value)"
    }
    if ($checks.Values -contains $false) { throw "Operations reliability verification failed" }
    Write-Host "Operations reliability verification passed. Protected identifiers were not printed."
} finally {
    $tokens = @()
    $removedUsers = 0
    foreach ($username in $script:ReliabilityUsers) {
        & aws cognito-idp admin-delete-user --user-pool-id $poolId `
            --username $username @awsScope | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to remove an isolated reliability user" }
        $deleted = $false
        for ($attempt = 0; $attempt -lt 10; $attempt++) {
            $remainingUsers = Invoke-AwsJson @(
                "cognito-idp", "list-users", "--user-pool-id", $poolId
            )
            $stillPresent = @(
                $remainingUsers.Users | Where-Object { $_.Username -eq $username }
            ).Count -gt 0
            if (-not $stillPresent) { $deleted = $true; break }
            Start-Sleep -Seconds 2
        }
        if (-not $deleted) { throw "An isolated reliability user remained after cleanup" }
        $removedUsers++
    }
    Write-Host "Temporary reliability users removed and confirmed: $removedUsers"
}
