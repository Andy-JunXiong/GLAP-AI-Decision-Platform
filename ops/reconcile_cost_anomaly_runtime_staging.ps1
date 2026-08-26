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
$sydneyDateText = $sydneyToday.ToString("yyyy-MM-dd")
$minimumDateText = $minimumDate.ToString("yyyy-MM-dd")

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
$alertTable = [string]$variables.LIFECYCLE_ALERT_TABLE
$actionTable = [string]$variables.LIFECYCLE_ACTION_TABLE
$actionView = [string]$variables.LIFECYCLE_ACTION_CURRENT_VIEW
if (-not $alertTable) { $alertTable = "fact_lifecycle_alert_staging_v1" }
if (-not $actionTable) { $actionTable = "fact_lifecycle_action_staging_v1" }
if (-not $actionView) { $actionView = "vw_lifecycle_action_current_staging_v1" }
foreach ($identifier in @($database, $alertTable, $actionTable, $actionView)) {
    Assert-Identifier $identifier
}
if (-not $output.StartsWith("s3://")) { throw "Protected Athena output is unavailable" }
if (-not $workgroup) { throw "Athena workgroup is unavailable" }

$query = @"
WITH scoped_cost_actions AS (
    SELECT action.*
    FROM $database.$actionTable AS action
    WHERE action.temporal_scope_id = 'OPERATIONAL'
      AND action.execution_mode = 'OPERATIONAL'
      AND action.time_basis = 'ACTUAL_CALENDAR'
      AND action.execution_scenario_id IS NULL
      AND action.alert_type = 'COST_ANOMALY'
      AND action.created_date BETWEEN DATE '$minimumDateText' AND DATE '$sydneyDateText'
      AND action.as_of_date <= DATE '$sydneyDateText'
),
cost_evidence AS (
    SELECT
        action.action_id,
        action.action_type,
        action.status,
        action.approval_required,
        action.approved_by,
        action.approved_at,
        action.completed_at,
        action.decision_brief_version,
        action.selected_alternative,
        action.selection_rationale,
        action.provenance,
        alert.alert_fingerprint,
        alert.alert_grain,
        alert.alert_dimension,
        alert.metric_name,
        alert.metric_value,
        alert.threshold_value,
        alert.severity,
        alert.status AS alert_status,
        current.decision_brief_version AS current_decision_brief_version,
        current.selected_alternative AS current_selected_alternative,
        current.selection_rationale AS current_selection_rationale
    FROM scoped_cost_actions AS action
    LEFT JOIN $database.$alertTable AS alert
      ON alert.temporal_scope_id = action.temporal_scope_id
     AND alert.alert_fingerprint = action.alert_fingerprint
     AND try_cast(alert.dt AS date) = action.created_date
     AND alert.execution_mode = 'OPERATIONAL'
     AND alert.time_basis = 'ACTUAL_CALENDAR'
     AND alert.execution_scenario_id IS NULL
     AND alert.as_of_date <= DATE '$sydneyDateText'
    LEFT JOIN $database.$actionView AS current
      ON current.temporal_scope_id = action.temporal_scope_id
     AND current.action_id = action.action_id
),
legacy_summary AS (
    SELECT count(*) AS legacy_bound_cost_action_count
    FROM $database.$actionTable
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND alert_type = 'COST_ANOMALY'
      AND created_date < DATE '$minimumDateText'
      AND (
          decision_brief_version IS NOT NULL
          OR selected_alternative IS NOT NULL
          OR selection_rationale IS NOT NULL
      )
)
SELECT
    count(*) AS candidate_action_count,
    count_if(
        alert_fingerprint IS NOT NULL
        AND alert_grain = 'SHIPMENT_COST'
        AND alert_dimension = 'TOTAL_COST'
        AND metric_name = 'cost_variance_pct'
        AND alert_status = 'OPEN'
        AND severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
        AND is_finite(try_cast(metric_value AS double))
        AND is_finite(try_cast(threshold_value AS double))
        AND try_cast(metric_value AS double) >= 0
        AND try_cast(threshold_value AS double) >= 0
        AND try_cast(metric_value AS double) > try_cast(threshold_value AS double)
    ) AS eligible_source_count,
    count_if(
        decision_brief_version = 'decision-brief.v1'
        AND action_type = 'REVIEW_COST'
        AND selected_alternative = 'REVIEW_COST'
        AND selection_rationale LIKE
            'Review the governed cost basis under stateful-cost-variance.v1; total cost variance is % percentage points above threshold.'
    ) AS valid_binding_count,
    count_if(
        decision_brief_version IS NULL
        OR decision_brief_version <> 'decision-brief.v1'
        OR action_type IS NULL
        OR action_type <> 'REVIEW_COST'
        OR selected_alternative IS NULL
        OR selected_alternative <> 'REVIEW_COST'
        OR selection_rationale IS NULL
        OR selection_rationale NOT LIKE
            'Review the governed cost basis under stateful-cost-variance.v1; total cost variance is % percentage points above threshold.'
    ) AS invalid_binding_count,
    count_if(
        status = 'PROPOSED'
        AND approval_required
        AND approved_by IS NULL
        AND approved_at IS NULL
        AND completed_at IS NULL
        AND provenance = 'SIMULATED'
    ) AS immutable_proposal_count,
    count_if(
        current_decision_brief_version = decision_brief_version
        AND current_selected_alternative = selected_alternative
        AND current_selection_rationale = selection_rationale
    ) AS current_view_binding_match_count,
    max(legacy.legacy_bound_cost_action_count) AS legacy_bound_cost_action_count
FROM cost_evidence
CROSS JOIN legacy_summary AS legacy
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
        throw "Read-only Cost runtime reconciliation query did not complete"
    }
} while ($state -ne "SUCCEEDED" -and [DateTime]::UtcNow -lt $deadline)
if ($state -ne "SUCCEEDED") {
    & aws athena stop-query-execution --query-execution-id $queryId @awsScope | Out-Null
    throw "Read-only Cost runtime reconciliation query timed out"
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
    "At least one naturally generated Cost proposal exists" = $counts.candidate_action_count -ge 1
    "Every Cost proposal has one eligible source Alert" = (
        $counts.eligible_source_count -eq $counts.candidate_action_count
    )
    "Every Cost proposal has the exact Decision binding" = (
        $counts.valid_binding_count -eq $counts.candidate_action_count
    )
    "No invalid Cost binding exists in the inspected cohort" = $counts.invalid_binding_count -eq 0
    "Every inspected Action remains an immutable unreviewed proposal" = (
        $counts.immutable_proposal_count -eq $counts.candidate_action_count
    )
    "Current view preserves every immutable Decision binding" = (
        $counts.current_view_binding_match_count -eq $counts.candidate_action_count
    )
    "Pre-release Cost Actions remain legacy-null" = $counts.legacy_bound_cost_action_count -eq 0
}
foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key): $($entry.Value)"
}
if ($checks.Values -contains $false) {
    throw "Cost runtime evidence reconciliation failed closed"
}
Write-Host "Cost runtime evidence reconciliation passed. Protected identifiers were not printed."
Write-Host "Lifecycle, API, and table mutations executed: False. Athena result storage is service-managed."
