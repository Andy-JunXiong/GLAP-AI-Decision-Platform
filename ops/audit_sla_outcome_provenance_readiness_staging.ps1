[CmdletBinding()]
param(
    [string]$Profile = "codex-readonly",
    [string]$Region = "us-east-1",
    [string]$ApiStackName = "glap-operations-api-staging",
    [string]$MinimumCreatedDate = "2026-08-27"
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

if ($MinimumCreatedDate -notmatch '^\d{4}-\d{2}-\d{2}$') {
    throw "Minimum created date must use YYYY-MM-DD"
}
$minimumDate = [DateTime]::ParseExact(
    $MinimumCreatedDate, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture
).Date
$sydneyToday = Get-SydneyBusinessDate
if ($minimumDate -gt $sydneyToday) {
    throw "Minimum created date is in the future; no AWS call was made"
}
$minimumDateText = $minimumDate.ToString("yyyy-MM-dd")
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
if (-not $auditTable) { $auditTable = "fact_lifecycle_action_audit_staging_v1" }
if (-not $actionView) { $actionView = "vw_lifecycle_action_current_staging_v1" }
if (-not $outcomeTable) { $outcomeTable = "fact_lifecycle_outcome_staging_v1" }
foreach ($identifier in @($database, $auditTable, $actionView, $outcomeTable)) {
    Assert-Identifier $identifier
}
if (-not $output.StartsWith("s3://")) { throw "Protected Athena output is unavailable" }
if (-not $workgroup) { throw "Athena workgroup is unavailable" }

$query = @"
WITH scoped_sla_actions AS (
    SELECT action.*
    FROM $database.$actionView AS action
    WHERE action.temporal_scope_id = 'OPERATIONAL'
      AND action.execution_mode = 'OPERATIONAL'
      AND action.time_basis = 'ACTUAL_CALENDAR'
      AND action.execution_scenario_id IS NULL
      AND action.alert_type = 'SLA_BREACH'
      AND action.provenance = 'SIMULATED'
      AND action.created_date BETWEEN DATE '$minimumDateText' AND DATE '$sydneyDateText'
      AND action.as_of_date <= DATE '$sydneyDateText'
),
event_summary AS (
    SELECT
        event.action_id,
        count_if(event.event_type = 'APPROVE') AS approve_event_count,
        count_if(event.event_type = 'REJECT') AS reject_event_count,
        count_if(event.event_type = 'COMPLETE') AS complete_event_count,
        count_if(
            event.event_type IN ('APPROVE', 'COMPLETE')
            AND (
                event.event_id IS NULL
                OR trim(event.event_id) = ''
                OR event.request_id IS NULL
                OR trim(event.request_id) = ''
                OR event.actor IS NULL
                OR trim(event.actor) = ''
                OR lower(trim(event.actor)) IN ('system', 'automation', 'model')
                OR event.reason IS NULL
                OR length(trim(event.reason)) < 3
            )
        ) AS invalid_human_audit_event_count
    FROM $database.$auditTable AS event
    WHERE event.temporal_scope_id = 'OPERATIONAL'
      AND event.execution_mode = 'OPERATIONAL'
      AND event.time_basis = 'ACTUAL_CALENDAR'
      AND event.execution_scenario_id IS NULL
      AND event.as_of_date <= DATE '$sydneyDateText'
      AND event.created_date <= DATE '$sydneyDateText'
    GROUP BY event.action_id
),
action_readiness AS (
    SELECT
        action.*,
        coalesce(
            action.decision_brief_version = 'decision-brief.v1'
            AND action.action_type = 'EXPEDITE_MILESTONE'
            AND action.selected_alternative = 'EXPEDITE_MILESTONE'
            AND action.selection_rationale IS NOT NULL
            AND trim(action.selection_rationale) <> '',
            false
        ) AS exact_binding_valid,
        coalesce(
            action.status = 'COMPLETED'
            AND action.approved_by IS NOT NULL
            AND trim(action.approved_by) <> ''
            AND lower(trim(action.approved_by)) NOT IN ('system', 'automation', 'model')
            AND action.completed_at IS NOT NULL
            AND events.approve_event_count = 1
            AND events.reject_event_count = 0
            AND events.complete_event_count = 1
            AND events.invalid_human_audit_event_count = 0,
            false
        ) AS human_completion_valid
    FROM scoped_sla_actions AS action
    LEFT JOIN event_summary AS events
      ON events.action_id = action.action_id
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
      AND outcome.execution_scenario_id IS NULL
      AND outcome.as_of_date <= DATE '$sydneyDateText'
      AND try_cast(outcome.dt AS date) <= DATE '$sydneyDateText'
),
action_outcomes AS (
    SELECT
        action.action_id,
        action.status,
        action.exact_binding_valid,
        action.human_completion_valid,
        count(outcome.outcome_id) AS outcome_count,
        count_if(
            outcome.status = 'PENDING'
            AND outcome.observed_date IS NULL
            AND outcome.effect_pct IS NULL
            AND outcome.observation_due_date IS NOT NULL
        ) AS valid_pending_outcome_count,
        count_if(
            outcome.status = 'PENDING'
            AND outcome.observed_date IS NULL
            AND outcome.effect_pct IS NULL
            AND outcome.observation_due_date IS NOT NULL
            AND outcome.observation_due_date <= DATE '$sydneyDateText'
        ) AS due_pending_outcome_count,
        count_if(
            outcome.status = 'PENDING'
            AND (
                outcome.observed_date IS NOT NULL
                OR outcome.effect_pct IS NOT NULL
                OR outcome.observation_due_date IS NULL
            )
        ) AS invalid_pending_outcome_count,
        count_if(
            outcome.status IN (
                'SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE'
            )
            AND outcome.observed_date IS NOT NULL
            AND is_finite(try_cast(outcome.effect_pct AS double))
            AND outcome.observed_date >= outcome.observation_due_date
            AND outcome.observed_date <= DATE '$sydneyDateText'
        ) AS valid_closed_outcome_count,
        count_if(
            outcome.status IN (
                'SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE'
            )
            AND (
                outcome.observed_date IS NULL
                OR outcome.effect_pct IS NULL
                OR outcome.observation_due_date IS NULL
                OR NOT is_finite(try_cast(outcome.effect_pct AS double))
                OR outcome.observed_date < outcome.observation_due_date
                OR outcome.observed_date > DATE '$sydneyDateText'
            )
        ) AS invalid_closed_outcome_count,
        count_if(
            outcome.outcome_id IS NOT NULL
            AND (
                outcome.status IS NULL
                OR outcome.status NOT IN (
                    'PENDING', 'SUCCESSFUL', 'PARTIALLY_SUCCESSFUL',
                    'FAILED', 'INCONCLUSIVE'
                )
            )
        ) AS invalid_outcome_status_count
    FROM action_readiness AS action
    LEFT JOIN ranked_outcomes AS outcome
      ON outcome.action_id = action.action_id
     AND outcome.row_rank = 1
    GROUP BY
        action.action_id,
        action.status,
        action.exact_binding_valid,
        action.human_completion_valid
)
SELECT
    count(*) AS proposal_count,
    count_if(exact_binding_valid) AS exact_binding_count,
    count_if(status = 'COMPLETED') AS completed_action_count,
    count_if(human_completion_valid) AS valid_completed_action_count,
    count_if(status = 'COMPLETED' AND NOT human_completion_valid)
        AS invalid_completed_action_count,
    count_if(human_completion_valid AND outcome_count = 0)
        AS completed_without_outcome_count,
    count_if(human_completion_valid AND outcome_count = 1)
        AS completed_single_outcome_count,
    count_if(NOT human_completion_valid AND outcome_count > 0)
        AS outcome_without_valid_completion_count,
    count_if(outcome_count > 1) AS multiple_outcome_action_count,
    coalesce(sum(valid_pending_outcome_count), 0) AS pending_outcome_count,
    coalesce(sum(due_pending_outcome_count), 0) AS due_pending_outcome_count,
    coalesce(sum(valid_closed_outcome_count), 0) AS closed_outcome_count,
    coalesce(sum(
        CASE
            WHEN exact_binding_valid THEN valid_closed_outcome_count
            ELSE 0
        END
    ), 0) AS valid_provenance_outcome_count,
    coalesce(sum(invalid_pending_outcome_count), 0) AS invalid_pending_outcome_count,
    coalesce(sum(invalid_closed_outcome_count), 0) AS invalid_closed_outcome_count,
    coalesce(sum(invalid_outcome_status_count), 0) AS invalid_outcome_status_count
FROM action_outcomes
"@

$started = Invoke-AwsJson @(
    "athena", "start-query-execution",
    "--query-string", $query,
    "--query-execution-context", "Database=$database",
    "--result-configuration", "OutputLocation=$output",
    "--work-group", $workgroup
)
$queryId = [string]$started.QueryExecutionId
if (-not $queryId) { throw "Athena did not accept the read-only readiness audit" }

$deadline = [DateTime]::UtcNow.AddSeconds(90)
do {
    Start-Sleep -Seconds 1
    $execution = Invoke-AwsJson @(
        "athena", "get-query-execution", "--query-execution-id", $queryId
    )
    $state = [string]$execution.QueryExecution.Status.State
    if ($state -in @("FAILED", "CANCELLED")) {
        throw "Read-only SLA Outcome provenance readiness query did not complete"
    }
} while ($state -ne "SUCCEEDED" -and [DateTime]::UtcNow -lt $deadline)
if ($state -ne "SUCCEEDED") {
    & aws athena stop-query-execution --query-execution-id $queryId @awsScope | Out-Null
    throw "Read-only SLA Outcome provenance readiness query timed out"
}

$result = Invoke-AwsJson @(
    "athena", "get-query-results", "--query-execution-id", $queryId,
    "--max-results", "2"
)
$rows = @($result.ResultSet.Rows)
if ($rows.Count -ne 2) { throw "Readiness audit returned an unexpected result shape" }
$headers = @($rows[0].Data | ForEach-Object { [string]$_.VarCharValue })
$values = @($rows[1].Data | ForEach-Object { [string]$_.VarCharValue })
$counts = @{}
for ($index = 0; $index -lt $headers.Count; $index++) {
    $counts[$headers[$index]] = [int]$values[$index]
}

$checks = [ordered]@{
    "Natural SLA Decision-bound proposal exists" = $counts.proposal_count -ge 1
    "Every scoped SLA proposal has the exact Decision pair" = (
        $counts.exact_binding_count -eq $counts.proposal_count
    )
    "A named-human completed SLA Action exists" = $counts.valid_completed_action_count -ge 1
    "Every completed SLA Action has a valid human audit chain" = (
        $counts.invalid_completed_action_count -eq 0
    )
    "No SLA Outcome exists without a valid human completion" = (
        $counts.outcome_without_valid_completion_count -eq 0
    )
    "Every completed SLA Action has at most one latest Outcome" = (
        $counts.multiple_outcome_action_count -eq 0
    )
    "Every latest SLA Outcome has a governed status and temporal shape" = (
        ($counts.invalid_pending_outcome_count -eq 0) -and
        ($counts.invalid_closed_outcome_count -eq 0) -and
        ($counts.invalid_outcome_status_count -eq 0)
    )
    "A pending SLA Outcome exists" = $counts.pending_outcome_count -ge 1
    "A pending SLA Outcome is due by the Sydney cutoff" = (
        $counts.due_pending_outcome_count -ge 1
    )
    "A closed observed SLA Outcome exists" = $counts.closed_outcome_count -ge 1
    "Every closed SLA Outcome preserves Decision provenance" = (
        ($counts.invalid_closed_outcome_count -eq 0) -and
        ($counts.valid_provenance_outcome_count -eq $counts.closed_outcome_count)
    )
    "Readiness evidence is actual-calendar and cutoff-bounded" = $true
}

$contractDrift = (
    ($counts.exact_binding_count -ne $counts.proposal_count) -or
    ($counts.invalid_completed_action_count -gt 0) -or
    ($counts.outcome_without_valid_completion_count -gt 0) -or
    ($counts.multiple_outcome_action_count -gt 0) -or
    ($counts.invalid_pending_outcome_count -gt 0) -or
    ($counts.invalid_closed_outcome_count -gt 0) -or
    ($counts.invalid_outcome_status_count -gt 0) -or
    ($counts.valid_provenance_outcome_count -ne $counts.closed_outcome_count)
)
if ($contractDrift) {
    $readiness = "BLOCKED_CONTRACT_DRIFT"
} elseif ($counts.proposal_count -eq 0) {
    $readiness = "NO_BOUND_SLA_PROPOSAL"
} elseif ($counts.valid_completed_action_count -eq 0) {
    $readiness = "WAITING_HUMAN_REVIEW"
} elseif ($counts.closed_outcome_count -ge 1) {
    $readiness = "READY_FOR_PROVENANCE_VERIFICATION"
} elseif ($counts.completed_without_outcome_count -ge 1) {
    $readiness = "WAITING_OUTCOME"
} elseif ($counts.due_pending_outcome_count -ge 1) {
    $readiness = "READY_FOR_OUTCOME_OBSERVATION"
} elseif ($counts.pending_outcome_count -ge 1) {
    $readiness = "WAITING_OBSERVATION_DUE_DATE"
} else {
    $readiness = "WAITING_OUTCOME"
}

foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key): $($entry.Value)"
}
Write-Host "SLA Outcome provenance readiness: $readiness"
Write-Host "Protected counts, identifiers, actor values, and Outcome values were not printed."
Write-Host "Lifecycle, Action, Outcome, API, and table mutations executed: False."
if ($readiness -eq "BLOCKED_CONTRACT_DRIFT") {
    throw "SLA Outcome provenance readiness audit failed closed on contract drift"
}
