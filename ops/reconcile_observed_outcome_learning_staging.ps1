[CmdletBinding()]
param(
    [string]$Profile = "codex-readonly",
    [string]$Region = "us-east-1",
    [string]$ApiStackName = "glap-operations-api-staging",
    [string]$ObservationDueDate = "2026-08-28",
    [int]$BaselineEligibleOutcomeCount = 1,
    [int]$MinimumPolicyOutcomes = 20
)

$ErrorActionPreference = "Stop"

function Get-SydneyBusinessDate {
    $zone = $null
    foreach ($zoneId in @("Australia/Sydney", "AUS Eastern Standard Time")) {
        try {
            $zone = [TimeZoneInfo]::FindSystemTimeZoneById($zoneId)
            break
        } catch {
            continue
        }
    }
    if (-not $zone) { throw "Australia/Sydney timezone is unavailable" }
    return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone).Date
}

if ($ObservationDueDate -notmatch '^\d{4}-\d{2}-\d{2}$') {
    throw "Observation due date must use YYYY-MM-DD"
}
if ($BaselineEligibleOutcomeCount -lt 0 -or $MinimumPolicyOutcomes -lt 1) {
    throw "Learning gate counts must be non-negative and bounded"
}
$dueDate = [DateTime]::ParseExact(
    $ObservationDueDate, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture
).Date
$sydneyToday = Get-SydneyBusinessDate
if ($sydneyToday -lt $dueDate) {
    throw "Observation due date has not been reached; no AWS call was made"
}
$sydneyDateText = $sydneyToday.ToString("yyyy-MM-dd")

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
$proposalTable = [string]$variables.POLICY_PROPOSAL_TABLE
if (-not $auditTable) { $auditTable = "fact_lifecycle_action_audit_staging_v1" }
if (-not $actionView) { $actionView = "vw_lifecycle_action_current_staging_v1" }
if (-not $outcomeTable) { $outcomeTable = "fact_lifecycle_outcome_staging_v1" }
if (-not $proposalTable) { $proposalTable = "fact_policy_proposal_staging_v1" }
foreach ($identifier in @($database, $auditTable, $actionView, $outcomeTable, $proposalTable)) {
    Assert-Identifier $identifier
}
if (-not $output.StartsWith("s3://")) { throw "Protected Athena output is unavailable" }
if (-not $workgroup) { throw "Athena workgroup is unavailable" }

$query = @"
WITH completed_candidate AS (
    SELECT current.action_id, CAST(current.completed_at AS date) AS completed_date
    FROM $database.$actionView AS current
    INNER JOIN (
        SELECT
            action_id,
            count_if(event_type = 'EDIT') AS edit_event_count,
            count_if(event_type = 'APPROVE') AS approve_event_count,
            count_if(event_type = 'REJECT') AS reject_event_count,
            count_if(event_type = 'COMPLETE') AS complete_event_count
        FROM $database.$auditTable
        WHERE temporal_scope_id = 'OPERATIONAL'
          AND execution_mode = 'OPERATIONAL'
          AND time_basis = 'ACTUAL_CALENDAR'
        GROUP BY action_id
    ) AS events
      ON events.action_id = current.action_id
    WHERE current.temporal_scope_id = 'OPERATIONAL'
      AND current.status = 'COMPLETED'
      AND current.completed_at IS NOT NULL
      AND events.edit_event_count = 1
      AND events.approve_event_count = 1
      AND events.reject_event_count = 0
      AND events.complete_event_count = 1
),
ranked_outcomes AS (
    SELECT
        outcome.*,
        row_number() OVER (
            PARTITION BY outcome.outcome_id
            ORDER BY try_cast(outcome.dt AS date) DESC, outcome.as_of_date DESC
        ) AS row_rank
    FROM $database.$outcomeTable AS outcome
    WHERE outcome.temporal_scope_id = 'OPERATIONAL'
      AND outcome.execution_mode = 'OPERATIONAL'
      AND outcome.time_basis = 'ACTUAL_CALENDAR'
      AND outcome.as_of_date <= DATE '$sydneyDateText'
      AND try_cast(outcome.dt AS date) <= DATE '$sydneyDateText'
),
candidate_outcome AS (
    SELECT
        candidate.action_id,
        count(*) AS outcome_count,
        count_if(outcome.status IN (
            'SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE'
        )) AS closed_outcome_count,
        count_if(
            outcome.observed_date IS NOT NULL
            AND outcome.effect_pct IS NOT NULL
        ) AS observed_effect_count,
        count_if(outcome.provenance = 'SIMULATED') AS simulated_outcome_count,
        count_if(
            outcome.observation_due_date = date_add('day', 3, candidate.completed_date)
        ) AS due_date_match_count,
        count_if(outcome.observed_date >= outcome.observation_due_date)
            AS observed_on_or_after_due_count,
        count_if(outcome.observed_date <= DATE '$sydneyDateText')
            AS observed_by_cutoff_count
    FROM completed_candidate AS candidate
    INNER JOIN ranked_outcomes AS outcome
      ON outcome.action_id = candidate.action_id
     AND outcome.row_rank = 1
    GROUP BY candidate.action_id
),
eligible_summary AS (
    SELECT count(*) AS eligible_outcome_count
    FROM ranked_outcomes
    WHERE row_rank = 1
      AND status IN ('SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE')
      AND observed_date IS NOT NULL
      AND observed_date <= DATE '$sydneyDateText'
),
proposal_summary AS (
    SELECT
        count(*) AS proposal_count,
        count_if(
            status = 'APPROVED'
            OR approved_by IS NOT NULL
            OR effective_date IS NOT NULL
        ) AS activated_proposal_count
    FROM $database.$proposalTable
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '$sydneyDateText'
      AND created_date <= DATE '$sydneyDateText'
)
SELECT
    count(*) AS candidate_action_count,
    COALESCE(sum(candidate.outcome_count), 0) AS outcome_count,
    COALESCE(sum(candidate.closed_outcome_count), 0) AS closed_outcome_count,
    COALESCE(sum(candidate.observed_effect_count), 0) AS observed_effect_count,
    COALESCE(sum(candidate.simulated_outcome_count), 0) AS simulated_outcome_count,
    COALESCE(sum(candidate.due_date_match_count), 0) AS due_date_match_count,
    COALESCE(sum(candidate.observed_on_or_after_due_count), 0)
        AS observed_on_or_after_due_count,
    COALESCE(sum(candidate.observed_by_cutoff_count), 0) AS observed_by_cutoff_count,
    max(eligible.eligible_outcome_count) AS eligible_outcome_count,
    max(proposal.proposal_count) AS proposal_count,
    max(proposal.activated_proposal_count) AS activated_proposal_count
FROM candidate_outcome AS candidate
CROSS JOIN eligible_summary AS eligible
CROSS JOIN proposal_summary AS proposal
WHERE candidate.outcome_count = 1
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
        throw "Read-only observed Outcome reconciliation query did not complete"
    }
} while ($state -ne "SUCCEEDED" -and [DateTime]::UtcNow -lt $deadline)
if ($state -ne "SUCCEEDED") {
    & aws athena stop-query-execution --query-execution-id $queryId @awsScope | Out-Null
    throw "Read-only observed Outcome reconciliation query timed out"
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
    "Exactly one completed candidate" = $counts.candidate_action_count -eq 1
    "Exactly one latest Outcome exists" = $counts.outcome_count -eq 1
    "Outcome is closed" = $counts.closed_outcome_count -eq 1
    "Outcome has an observed date and effect" = $counts.observed_effect_count -eq 1
    "Outcome is explicitly simulated" = $counts.simulated_outcome_count -eq 1
    "Observation due date is completion plus three days" = $counts.due_date_match_count -eq 1
    "Outcome was observed on or after its due date" = $counts.observed_on_or_after_due_count -eq 1
    "Outcome was observed by the current Sydney cutoff" = $counts.observed_by_cutoff_count -eq 1
    "Eligible Outcome count advanced by exactly one" = (
        $counts.eligible_outcome_count - $BaselineEligibleOutcomeCount -eq 1
    )
    "Policy review threshold remains unmet" = $counts.eligible_outcome_count -lt $MinimumPolicyOutcomes
    "No policy proposal exists below the threshold" = $counts.proposal_count -eq 0
    "No policy proposal is activated" = $counts.activated_proposal_count -eq 0
}
foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key): $($entry.Value)"
}
if ($checks.Values -contains $false) {
    throw "Observed Outcome and Learning reconciliation failed closed"
}
Write-Host "Observed Outcome and Learning reconciliation passed. Protected identifiers were not printed."
