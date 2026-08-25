[CmdletBinding()]
param(
    [string]$Profile = "codex-readonly",
    [string]$Region = "us-east-1",
    [string]$ApiStackName = "glap-operations-api-staging"
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
$outcomeTable = [string]$variables.LIFECYCLE_OUTCOME_TABLE
if (-not $auditTable) { $auditTable = "fact_lifecycle_action_audit_staging_v1" }
if (-not $actionView) { $actionView = "vw_lifecycle_action_current_staging_v1" }
if (-not $outcomeTable) { $outcomeTable = "fact_lifecycle_outcome_staging_v1" }
foreach ($identifier in @($database, $auditTable, $actionView, $outcomeTable)) {
    Assert-Identifier $identifier
}
if (-not $output.StartsWith("s3://")) { throw "Protected Athena output is unavailable" }
if (-not $workgroup) { throw "Athena workgroup is unavailable" }

$query = @"
WITH event_rollup AS (
    SELECT
        action_id,
        count_if(event_type = 'EDIT') AS edit_event_count,
        count_if(event_type = 'APPROVE') AS approve_event_count,
        count_if(event_type = 'REJECT') AS reject_event_count,
        count_if(event_type = 'COMPLETE') AS complete_event_count,
        count(DISTINCT IF(event_type IN ('EDIT', 'APPROVE'), actor, NULL))
            AS named_actor_count,
        max_by(action_owner, occurred_at) AS latest_action_owner,
        max_by(action_due_date, occurred_at) AS latest_action_due_date
    FROM $database.$auditTable
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
    GROUP BY action_id
),
outcome_rollup AS (
    SELECT action_id, count(*) AS outcome_count
    FROM $database.$outcomeTable
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
    GROUP BY action_id
),
candidate AS (
    SELECT
        events.edit_event_count,
        events.approve_event_count,
        events.reject_event_count,
        events.complete_event_count,
        events.named_actor_count,
        IF(
            current.action_owner = events.latest_action_owner
            AND current.action_due_date = events.latest_action_due_date,
            1,
            0
        ) AS assignment_match_count,
        COALESCE(outcomes.outcome_count, 0) AS outcome_count
    FROM event_rollup AS events
    INNER JOIN $database.$actionView AS current
      ON current.temporal_scope_id = 'OPERATIONAL'
     AND current.action_id = events.action_id
    LEFT JOIN outcome_rollup AS outcomes
      ON outcomes.action_id = events.action_id
    WHERE current.status = 'APPROVED'
      AND events.edit_event_count = 1
      AND events.approve_event_count = 1
      AND events.reject_event_count = 0
      AND events.complete_event_count = 0
      AND events.named_actor_count = 2
      AND trim(current.action_owner) <> ''
      AND current.action_due_date IS NOT NULL
)
SELECT
    count(*) AS candidate_action_count,
    COALESCE(sum(edit_event_count), 0) AS edit_event_count,
    COALESCE(sum(approve_event_count), 0) AS approve_event_count,
    COALESCE(sum(reject_event_count), 0) AS reject_event_count,
    COALESCE(sum(complete_event_count), 0) AS complete_event_count,
    count_if(named_actor_count = 2) AS separated_actor_count,
    COALESCE(sum(assignment_match_count), 0) AS assignment_match_count,
    COALESCE(sum(outcome_count), 0) AS outcome_count
FROM candidate
"@

$started = Invoke-AwsJson @(
    "athena", "start-query-execution",
    "--query-string", $query,
    "--query-execution-context", "Database=$database",
    "--result-configuration", "OutputLocation=$output",
    "--work-group", $workgroup
)
$queryId = [string]$started.QueryExecutionId
if (-not $queryId) { throw "Athena did not accept the read-only preflight" }

$deadline = [DateTime]::UtcNow.AddSeconds(90)
do {
    Start-Sleep -Seconds 1
    $execution = Invoke-AwsJson @(
        "athena", "get-query-execution", "--query-execution-id", $queryId
    )
    $state = [string]$execution.QueryExecution.Status.State
    if ($state -in @("FAILED", "CANCELLED")) {
        throw "Read-only preflight query did not complete"
    }
} while ($state -ne "SUCCEEDED" -and [DateTime]::UtcNow -lt $deadline)
if ($state -ne "SUCCEEDED") {
    & aws athena stop-query-execution --query-execution-id $queryId @awsScope | Out-Null
    throw "Read-only preflight query timed out"
}

$result = Invoke-AwsJson @(
    "athena", "get-query-results", "--query-execution-id", $queryId,
    "--max-results", "2"
)
$rows = @($result.ResultSet.Rows)
if ($rows.Count -ne 2) { throw "Preflight returned an unexpected result shape" }
$headers = @($rows[0].Data | ForEach-Object { [string]$_.VarCharValue })
$values = @($rows[1].Data | ForEach-Object { [string]$_.VarCharValue })
$counts = @{}
for ($index = 0; $index -lt $headers.Count; $index++) {
    $counts[$headers[$index]] = [int]$values[$index]
}

$checks = [ordered]@{
    "Exactly one approved candidate" = $counts.candidate_action_count -eq 1
    "Exactly one EDIT event" = $counts.edit_event_count -eq 1
    "Exactly one APPROVE event" = $counts.approve_event_count -eq 1
    "No REJECT event" = $counts.reject_event_count -eq 0
    "No COMPLETE event" = $counts.complete_event_count -eq 0
    "Operator and approver remain distinct" = $counts.separated_actor_count -eq 1
    "Assignment matches current state" = $counts.assignment_match_count -eq 1
    "No Outcome exists for candidate" = $counts.outcome_count -eq 0
}
foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key): $($entry.Value)"
}
if ($checks.Values -contains $false) {
    throw "COMPLETE-to-Outcome preflight failed closed"
}
Write-Host "COMPLETE-to-Outcome preflight passed. Protected identifiers were not printed."
