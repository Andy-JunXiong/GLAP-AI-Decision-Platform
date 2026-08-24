[CmdletBinding()]
param(
    [string]$Profile = "codex-readonly",
    [string]$Region = "us-east-1",
    [string]$ApiStackName = "glap-operations-api-staging",
    [string]$ObservationDate = ""
)

$ErrorActionPreference = "Stop"
$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }

function Invoke-AwsJson([string[]]$Arguments) {
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) {
        throw "Required read-only AWS call failed"
    }
    return $json | ConvertFrom-Json
}

function Get-Stack([string]$Name) {
    return (Invoke-AwsJson @(
        "cloudformation", "describe-stacks", "--stack-name", $Name
    )).Stacks[0]
}

function Get-Output($Stack, [string]$Key) {
    $value = ($Stack.Outputs | Where-Object OutputKey -eq $Key).OutputValue
    if (-not $value) { throw "Required protected stack output is unavailable" }
    return [string]$value
}

function Assert-Identifier([string]$Value) {
    if ($Value -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "Unsafe Athena identifier"
    }
}

try { $sydneyZone = [TimeZoneInfo]::FindSystemTimeZoneById("Australia/Sydney") }
catch { $sydneyZone = [TimeZoneInfo]::FindSystemTimeZoneById("AUS Eastern Standard Time") }
$sydneyDate = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $sydneyZone).Date
if (-not $ObservationDate) { $ObservationDate = $sydneyDate.ToString("yyyy-MM-dd") }
try { $observedDate = [DateTime]::ParseExact($ObservationDate, "yyyy-MM-dd", $null).Date }
catch { throw "ObservationDate must use YYYY-MM-DD" }
if ($observedDate -gt $sydneyDate) { throw "ObservationDate cannot be future-dated" }

$stack = Get-Stack $ApiStackName
$functionName = Get-Output $stack "ApiFunctionName"
$function = Invoke-AwsJson @(
    "lambda", "get-function-configuration", "--function-name", $functionName
)
$variables = $function.Environment.Variables
$database = [string]$variables.ATHENA_SOURCE_DATABASE
$output = [string]$variables.ATHENA_OUTPUT
$workgroup = [string]$variables.ATHENA_WORKGROUP
$auditTable = [string]$variables.LIFECYCLE_ACTION_AUDIT_TABLE
$actionView = [string]$variables.LIFECYCLE_ACTION_CURRENT_VIEW
if (-not $auditTable) { $auditTable = "fact_lifecycle_action_audit_staging_v1" }
if (-not $actionView) { $actionView = "vw_lifecycle_action_current_staging_v1" }
foreach ($identifier in @($database, $auditTable, $actionView)) {
    Assert-Identifier $identifier
}
if (-not $output.StartsWith("s3://")) { throw "Protected Athena output is unavailable" }
if (-not $workgroup) { throw "Athena workgroup is unavailable" }

$query = @"
WITH matched_edit AS (
    SELECT action_id, request_id, actor, action_owner, action_due_date
    FROM $database.$auditTable
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND created_date = DATE '$ObservationDate'
      AND event_type = 'EDIT'
      AND previous_status = 'PROPOSED'
      AND new_status = 'EDITED'
      AND reason = 'Staging evidence refresh interaction canary'
)
SELECT
    count(*) AS edit_event_count,
    count(DISTINCT edit.action_id) AS distinct_action_count,
    count(DISTINCT edit.request_id) AS distinct_request_count,
    count(DISTINCT edit.actor) AS distinct_actor_count,
    count_if(
        trim(edit.actor) <> ''
        AND lower(trim(edit.actor)) NOT IN ('system', 'automation', 'model')
    ) AS named_actor_count,
    count_if(
        trim(edit.action_owner) <> ''
        AND edit.action_due_date >= DATE '$ObservationDate'
    ) AS valid_assignment_count,
    count_if(current.status = 'EDITED') AS current_edited_count,
    count_if(
        current.status = 'EDITED'
        AND current.action_owner = edit.action_owner
        AND current.action_due_date = edit.action_due_date
    ) AS current_assignment_match_count
FROM matched_edit AS edit
LEFT JOIN $database.$actionView AS current
  ON current.temporal_scope_id = 'OPERATIONAL'
 AND current.action_id = edit.action_id
"@

$started = Invoke-AwsJson @(
    "athena", "start-query-execution",
    "--query-string", $query,
    "--query-execution-context", "Database=$database",
    "--result-configuration", "OutputLocation=$output",
    "--work-group", $workgroup
)
$queryId = [string]$started.QueryExecutionId
if (-not $queryId) { throw "Athena did not accept the read-only reconciliation" }

$deadline = [DateTime]::UtcNow.AddSeconds(90)
do {
    Start-Sleep -Seconds 1
    $execution = Invoke-AwsJson @(
        "athena", "get-query-execution", "--query-execution-id", $queryId
    )
    $state = [string]$execution.QueryExecution.Status.State
    if ($state -in @("FAILED", "CANCELLED")) {
        throw "Read-only reconciliation query did not complete"
    }
} while ($state -ne "SUCCEEDED" -and [DateTime]::UtcNow -lt $deadline)
if ($state -ne "SUCCEEDED") {
    & aws athena stop-query-execution --query-execution-id $queryId @awsScope | Out-Null
    throw "Read-only reconciliation query timed out"
}

$result = Invoke-AwsJson @(
    "athena", "get-query-results", "--query-execution-id", $queryId,
    "--max-results", "2"
)
$rows = @($result.ResultSet.Rows)
if ($rows.Count -ne 2) { throw "Reconciliation returned an unexpected result shape" }
$headers = @($rows[0].Data | ForEach-Object { [string]$_.VarCharValue })
$values = @($rows[1].Data | ForEach-Object { [string]$_.VarCharValue })
$counts = @{}
for ($index = 0; $index -lt $headers.Count; $index++) {
    $counts[$headers[$index]] = [int]$values[$index]
}

$checks = [ordered]@{
    "Exactly one matching EDIT event" = $counts.edit_event_count -eq 1
    "Exactly one affected Action" = $counts.distinct_action_count -eq 1
    "Exactly one request ID" = $counts.distinct_request_count -eq 1
    "Exactly one named actor" = $counts.distinct_actor_count -eq 1 -and $counts.named_actor_count -eq 1
    "Assignment is valid" = $counts.valid_assignment_count -eq 1
    "Current Action is EDITED" = $counts.current_edited_count -eq 1
    "Current assignment matches audit" = $counts.current_assignment_match_count -eq 1
}
foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key): $($entry.Value)"
}
if ($checks.Values -contains $false) {
    throw "Action Evidence refresh reconciliation failed closed"
}
Write-Host "Action Evidence refresh reconciliation passed. Protected identifiers were not printed."
