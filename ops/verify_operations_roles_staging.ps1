[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$IdentityStackName = "glap-operations-identity-staging",
    [string]$ApiStackName = "glap-operations-api-staging",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }

Write-Host "Operations staging role-matrix verification plan"
Write-Host "  Temporary users: viewer, operator, approver, administrator"
Write-Host "  Email delivery: False"
Write-Host "  Existing Action mutation: False (unguessable missing Action ID)"
Write-Host "  Test users deleted after verification: True"
Write-Host "  Tokens or user identifiers printed: False"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply to create and remove isolated test users."
    return
}

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

function Invoke-ApiStatus(
    [string]$Uri, [string]$Token, [string]$Method = "GET", [string]$Body = ""
) {
    $arguments = @{
        Uri = $Uri
        Method = $Method
        Headers = @{ Authorization = "Bearer $Token" }
        UseBasicParsing = $true
        TimeoutSec = 30
    }
    if ($Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body
    }
    try {
        return [int](Invoke-WebRequest @arguments).StatusCode
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        throw
    }
}

function Invoke-ApiJson([string]$Uri, [string]$Token) {
    $response = Invoke-WebRequest -Uri $Uri -Method GET `
        -Headers @{ Authorization = "Bearer $Token" } `
        -UseBasicParsing -TimeoutSec 30
    if ([int]$response.StatusCode -ne 200) { throw "Authenticated API read failed" }
    return $response.Content | ConvertFrom-Json
}

function New-StrongPassword {
    $bytes = [byte[]]::new(32)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes) + "Aa1!"
}

$identity = Get-Stack $IdentityStackName
$api = Get-Stack $ApiStackName
$poolId = Get-Output $identity "UserPoolId"
$clientId = Get-Output $identity "JwtAudience"
$endpoint = (Get-Output $api "ApiEndpoint").TrimEnd('/')
$clientFlows = & aws cognito-idp describe-user-pool-client --user-pool-id $poolId `
    --client-id $clientId @awsScope --query "UserPoolClient.ExplicitAuthFlows" --output text
if ($clientFlows -notmatch "ALLOW_ADMIN_USER_PASSWORD_AUTH") {
    throw "The staging client is not ready for IAM-administered role verification"
}

$roles = @("viewer", "operator", "approver", "administrator")
$users = @()
$tokens = @{}
$suffix = [guid]::NewGuid().ToString("N").Substring(0, 12)
try {
    foreach ($role in $roles) {
        $login = "glap-$role-$suffix@example.invalid"
        $password = New-StrongPassword
        $internalUsername = & aws cognito-idp admin-create-user --user-pool-id $poolId `
            --username $login --temporary-password $password --message-action SUPPRESS `
            --user-attributes "Name=email,Value=$login" "Name=email_verified,Value=true" `
            @awsScope --query "User.Username" --output text
        if ($LASTEXITCODE -ne 0 -or -not $internalUsername) {
            throw "Unable to create an isolated role-check user"
        }
        $users += $internalUsername
        & aws cognito-idp admin-set-user-password --user-pool-id $poolId `
            --username $internalUsername --password $password --permanent @awsScope
        if ($LASTEXITCODE -ne 0) { throw "Unable to activate an isolated role-check user" }
        & aws cognito-idp admin-add-user-to-group --user-pool-id $poolId `
            --username $internalUsername --group-name $role @awsScope
        if ($LASTEXITCODE -ne 0) { throw "Unable to assign an isolated role-check group" }
        $auth = & aws cognito-idp admin-initiate-auth --user-pool-id $poolId `
            --client-id $clientId --auth-flow ADMIN_USER_PASSWORD_AUTH `
            --auth-parameters "USERNAME=$login,PASSWORD=$password" @awsScope --output json
        if ($LASTEXITCODE -ne 0 -or -not $auth) { throw "Unable to authenticate an isolated role-check user" }
        $tokens[$role] = ($auth | ConvertFrom-Json).AuthenticationResult.AccessToken
        if (-not $tokens[$role]) { throw "Role-check authentication returned no access token" }
    }

    try { $sydneyZone = [TimeZoneInfo]::FindSystemTimeZoneById("Australia/Sydney") }
    catch { $sydneyZone = [TimeZoneInfo]::FindSystemTimeZoneById("AUS Eastern Standard Time") }
    $logicalDate = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $sydneyZone).ToString("yyyy-MM-dd")
    $missingAction = "role-check-" + [guid]::NewGuid().ToString("N")
    function Action-Status([string]$Role, [string]$Operation) {
        $body = @{
            operation = $Operation
            request_id = [guid]::NewGuid().ToString("N")
            reason = "Isolated staging role-matrix verification"
            logical_run_date = $logicalDate
        } | ConvertTo-Json -Compress
        return Invoke-ApiStatus "$endpoint/v1/actions/$missingAction/events" `
            $tokens[$Role] "POST" $body
    }

    $readStatuses = [ordered]@{}
    $riskReadStatuses = [ordered]@{}
    $outcomeReadStatuses = [ordered]@{}
    $healthReadStatuses = [ordered]@{}
    $forecastReadStatuses = [ordered]@{}
    foreach ($role in $roles) {
        $readStatuses[$role] = Invoke-ApiStatus "$endpoint/v1/actions?limit=1" $tokens[$role]
        $riskReadStatuses[$role] = Invoke-ApiStatus "$endpoint/v1/risks?status=OPEN&limit=1" $tokens[$role]
        $outcomeReadStatuses[$role] = Invoke-ApiStatus "$endpoint/v1/outcomes?limit=1" $tokens[$role]
        $healthReadStatuses[$role] = Invoke-ApiStatus "$endpoint/v1/pipeline-health" $tokens[$role]
        $forecastReadStatuses[$role] = Invoke-ApiStatus "$endpoint/v1/forecasts" $tokens[$role]
    }
    $riskPayload = Invoke-ApiJson "$endpoint/v1/risks?status=OPEN&limit=100" $tokens.viewer
    $riskItems = @($riskPayload.items)
    $riskDatesValid = @(
        $riskItems | Where-Object {
            -not $_.as_of_date -or [datetime]$_.as_of_date -gt [datetime]$logicalDate
        }
    ).Count -eq 0
    $riskStatusesValid = @($riskItems | Where-Object { $_.status -ne "OPEN" }).Count -eq 0
    $outcomePayload = Invoke-ApiJson "$endpoint/v1/outcomes?limit=100" $tokens.viewer
    $outcomeItems = @($outcomePayload.items)
    $pendingOutcomes = @($outcomeItems | Where-Object { $_.outcome_status -eq "PENDING" })
    $observedOutcomes = @($outcomeItems | Where-Object { $_.outcome_status -ne "PENDING" })
    $outcomeCutoffValid = @(
        $outcomeItems | Where-Object {
            -not $_.as_of_date -or [datetime]$_.as_of_date -gt [datetime]$logicalDate -or
            ($_.observed_date -and [datetime]$_.observed_date -gt [datetime]$logicalDate)
        }
    ).Count -eq 0
    $pendingEvidenceValid = @(
        $pendingOutcomes | Where-Object {
            $_.observed_date -or $_.effect_pct -or $_.evidence_status -ne "NOT_OBSERVED"
        }
    ).Count -eq 0
    $observedEvidenceValid = @(
        $observedOutcomes | Where-Object {
            -not $_.observed_date -or $_.evidence_status -ne "OBSERVED_ACTUAL_CALENDAR"
        }
    ).Count -eq 0
    $healthPayload = Invoke-ApiJson "$endpoint/v1/pipeline-health" $tokens.viewer
    $healthStages = @($healthPayload.stages)
    $expectedStages = @(
        "generation", "raw_to_iceberg", "input_validation",
        "decision_pipeline", "decision_flywheel", "output_validation"
    )
    $healthStageContractValid = $healthStages.Count -eq 6 -and `
        (($healthStages | ForEach-Object name) -join ",") -eq ($expectedStages -join ",")
    $healthTemporalBoundaryValid = -not $healthPayload.logical_run_date -or `
        [datetime]$healthPayload.logical_run_date -le [datetime]$logicalDate
    $healthQualityContractValid = [int]$healthPayload.quality_checks_total -eq 10 -and `
        [int]$healthPayload.quality_checks_succeeded -le 10
    $healthSafeJson = $healthPayload | ConvertTo-Json -Depth 10 -Compress
    $healthRedacted = $healthSafeJson -notmatch 'function_name|s3://|arn:'
    $forecastPayload = Invoke-ApiJson "$endpoint/v1/forecasts" $tokens.viewer
    $forecastPoints = @($forecastPayload.forecast.points)
    $forecastHistory = @($forecastPayload.history)
    $forecastTemporalBoundaryValid = `
        $forecastPayload.source.execution_mode -eq "OPERATIONAL" -and `
        $forecastPayload.source.time_basis -eq "ACTUAL_CALENDAR" -and `
        @($forecastHistory | Where-Object { [datetime]$_.date -gt [datetime]$logicalDate }).Count -eq 0 -and `
        @($forecastPoints | Where-Object {
            [datetime]$_.date -le [datetime]$logicalDate -or
            $_.evidence_status -ne "ADVISORY_FORECAST_NOT_OBSERVED"
        }).Count -eq 0
    $forecastSimulationValid = `
        $forecastPayload.forecast.execution_mode -eq "FUTURE_SIMULATION" -and `
        $forecastPayload.forecast.time_basis -eq "MODEL_PROJECTION" -and `
        $forecastPayload.forecast.scenario_id -eq "internal-advisory-forecast-$logicalDate" -and `
        $forecastPayload.forecast.production_effect -eq $false
    $forecastEvidenceValid = `
        $forecastPayload.source.evidence_class -eq "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE" -and `
        $forecastPayload.accuracy.evidence_class -eq "SYNTHETIC_ENGINEERING_BACKTEST" -and `
        $forecastPayload.accuracy.model_promotion_status -eq "BLOCKED"
    $forecastSafeJson = $forecastPayload | ConvertTo-Json -Depth 10 -Compress
    $forecastRedacted = $forecastSafeJson -notmatch 'shipment_id|function_name|s3://|arn:'

    $checks = [ordered]@{
        "viewer read allowed" = $readStatuses.viewer -eq 200
        "viewer risk read allowed" = $riskReadStatuses.viewer -eq 200
        "viewer outcome read allowed" = $outcomeReadStatuses.viewer -eq 200
        "viewer pipeline health read allowed" = $healthReadStatuses.viewer -eq 200
        "viewer forecast read allowed" = $forecastReadStatuses.viewer -eq 200
        "pipeline health response contract valid" = $healthPayload.schema_version -eq "operations-api.v1"
        "pipeline health six-stage contract valid" = $healthStageContractValid
        "pipeline health temporal boundary valid" = $healthTemporalBoundaryValid
        "pipeline health quality contract valid" = $healthQualityContractValid
        "pipeline health infrastructure identifiers redacted" = $healthRedacted
        "forecast response contract valid" = $forecastPayload.schema_version -eq "operations-api.v1"
        "forecast temporal boundary valid" = $forecastTemporalBoundaryValid
        "forecast future simulation isolated" = $forecastSimulationValid
        "forecast evidence classification valid" = $forecastEvidenceValid
        "forecast entity and infrastructure identifiers redacted" = $forecastRedacted
        "risk response contract valid" = $riskPayload.schema_version -eq "operations-api.v1"
        "risk cutoff dates valid" = $riskDatesValid
        "risk status filter valid" = $riskStatusesValid
        "outcome response contract valid" = $outcomePayload.schema_version -eq "operations-api.v1"
        "outcome cutoff dates valid" = $outcomeCutoffValid
        "pending outcomes remain not observed" = $pendingEvidenceValid
        "observed outcome evidence valid" = $observedEvidenceValid
        "viewer approve denied" = (Action-Status "viewer" "APPROVE") -eq 403
        "viewer complete denied" = (Action-Status "viewer" "COMPLETE") -eq 403
        "operator read allowed" = $readStatuses.operator -eq 200
        "operator risk read allowed" = $riskReadStatuses.operator -eq 200
        "operator outcome read allowed" = $outcomeReadStatuses.operator -eq 200
        "operator pipeline health read allowed" = $healthReadStatuses.operator -eq 200
        "operator forecast read allowed" = $forecastReadStatuses.operator -eq 200
        "operator approve denied" = (Action-Status "operator" "APPROVE") -eq 403
        "operator complete allowed by role" = (Action-Status "operator" "COMPLETE") -notin @(401, 403)
        "approver read allowed" = $readStatuses.approver -eq 200
        "approver risk read allowed" = $riskReadStatuses.approver -eq 200
        "approver outcome read allowed" = $outcomeReadStatuses.approver -eq 200
        "approver pipeline health read allowed" = $healthReadStatuses.approver -eq 200
        "approver forecast read allowed" = $forecastReadStatuses.approver -eq 200
        "approver approve allowed by role" = (Action-Status "approver" "APPROVE") -notin @(401, 403)
        "approver complete denied" = (Action-Status "approver" "COMPLETE") -eq 403
        "administrator read allowed" = $readStatuses.administrator -eq 200
        "administrator risk read allowed" = $riskReadStatuses.administrator -eq 200
        "administrator outcome read allowed" = $outcomeReadStatuses.administrator -eq 200
        "administrator pipeline health read allowed" = $healthReadStatuses.administrator -eq 200
        "administrator forecast read allowed" = $forecastReadStatuses.administrator -eq 200
        "administrator approve allowed by role" = (Action-Status "administrator" "APPROVE") -notin @(401, 403)
        "administrator complete allowed by role" = (Action-Status "administrator" "COMPLETE") -notin @(401, 403)
    }
    Write-Host "Queue read HTTP statuses: viewer=$($readStatuses.viewer), operator=$($readStatuses.operator), approver=$($readStatuses.approver), administrator=$($readStatuses.administrator)"
    Write-Host "Risk read HTTP statuses: viewer=$($riskReadStatuses.viewer), operator=$($riskReadStatuses.operator), approver=$($riskReadStatuses.approver), administrator=$($riskReadStatuses.administrator)"
    Write-Host "Outcome read HTTP statuses: viewer=$($outcomeReadStatuses.viewer), operator=$($outcomeReadStatuses.operator), approver=$($outcomeReadStatuses.approver), administrator=$($outcomeReadStatuses.administrator)"
    Write-Host "Pipeline Health read HTTP statuses: viewer=$($healthReadStatuses.viewer), operator=$($healthReadStatuses.operator), approver=$($healthReadStatuses.approver), administrator=$($healthReadStatuses.administrator)"
    Write-Host "Forecast read HTTP statuses: viewer=$($forecastReadStatuses.viewer), operator=$($forecastReadStatuses.operator), approver=$($forecastReadStatuses.approver), administrator=$($forecastReadStatuses.administrator)"
    Write-Host "Open operational Risk rows returned: $($riskItems.Count)"
    Write-Host "Operational Outcome rows returned: pending=$($pendingOutcomes.Count), observed=$($observedOutcomes.Count)"
    Write-Host "Pipeline Health summary: status=$($healthPayload.status), logical_run_date=$($healthPayload.logical_run_date), stages=$($healthPayload.stages_succeeded)/$($healthPayload.stage_count), quality_checks=$($healthPayload.quality_checks_succeeded)/$($healthPayload.quality_checks_total)"
    Write-Host "Forecast summary: forecast_status=$($forecastPayload.forecast.status), accuracy_status=$($forecastPayload.accuracy.status), eligible_dates=$($forecastPayload.coverage.eligible_dates), holdouts=$($forecastPayload.accuracy.metrics.forecast_count)"
    foreach ($entry in $checks.GetEnumerator()) {
        Write-Host "$($entry.Key): $($entry.Value)"
    }
    if ($checks.Values -contains $false) { throw "Operations role-matrix verification failed" }
    Write-Host "Operations role-matrix verification passed. Tokens and users were not printed."
} finally {
    $tokens.Clear()
    foreach ($username in $users) {
        & aws cognito-idp admin-delete-user --user-pool-id $poolId `
            --username $username @awsScope 2>$null
    }
    Write-Host "Temporary role-check users removed: $($users.Count)"
}
