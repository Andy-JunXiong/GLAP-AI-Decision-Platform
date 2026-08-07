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
    foreach ($role in $roles) {
        $readStatuses[$role] = Invoke-ApiStatus "$endpoint/v1/actions?limit=1" $tokens[$role]
        $riskReadStatuses[$role] = Invoke-ApiStatus "$endpoint/v1/risks?status=OPEN&limit=1" $tokens[$role]
    }
    $riskPayload = Invoke-ApiJson "$endpoint/v1/risks?status=OPEN&limit=100" $tokens.viewer
    $riskItems = @($riskPayload.items)
    $riskDatesValid = @(
        $riskItems | Where-Object {
            -not $_.as_of_date -or [datetime]$_.as_of_date -gt [datetime]$logicalDate
        }
    ).Count -eq 0
    $riskStatusesValid = @($riskItems | Where-Object { $_.status -ne "OPEN" }).Count -eq 0

    $checks = [ordered]@{
        "viewer read allowed" = $readStatuses.viewer -eq 200
        "viewer risk read allowed" = $riskReadStatuses.viewer -eq 200
        "risk response contract valid" = $riskPayload.schema_version -eq "operations-api.v1"
        "risk cutoff dates valid" = $riskDatesValid
        "risk status filter valid" = $riskStatusesValid
        "viewer approve denied" = (Action-Status "viewer" "APPROVE") -eq 403
        "viewer complete denied" = (Action-Status "viewer" "COMPLETE") -eq 403
        "operator read allowed" = $readStatuses.operator -eq 200
        "operator risk read allowed" = $riskReadStatuses.operator -eq 200
        "operator approve denied" = (Action-Status "operator" "APPROVE") -eq 403
        "operator complete allowed by role" = (Action-Status "operator" "COMPLETE") -notin @(401, 403)
        "approver read allowed" = $readStatuses.approver -eq 200
        "approver risk read allowed" = $riskReadStatuses.approver -eq 200
        "approver approve allowed by role" = (Action-Status "approver" "APPROVE") -notin @(401, 403)
        "approver complete denied" = (Action-Status "approver" "COMPLETE") -eq 403
        "administrator read allowed" = $readStatuses.administrator -eq 200
        "administrator risk read allowed" = $riskReadStatuses.administrator -eq 200
        "administrator approve allowed by role" = (Action-Status "administrator" "APPROVE") -notin @(401, 403)
        "administrator complete allowed by role" = (Action-Status "administrator" "COMPLETE") -notin @(401, 403)
    }
    Write-Host "Queue read HTTP statuses: viewer=$($readStatuses.viewer), operator=$($readStatuses.operator), approver=$($readStatuses.approver), administrator=$($readStatuses.administrator)"
    Write-Host "Risk read HTTP statuses: viewer=$($riskReadStatuses.viewer), operator=$($riskReadStatuses.operator), approver=$($riskReadStatuses.approver), administrator=$($riskReadStatuses.administrator)"
    Write-Host "Open operational Risk rows returned: $($riskItems.Count)"
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
