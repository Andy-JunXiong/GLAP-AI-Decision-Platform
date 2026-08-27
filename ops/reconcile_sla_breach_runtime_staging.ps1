[CmdletBinding()]
param(
    [string]$Profile = "codex-readonly",
    [string]$Region = "us-east-1",
    [string]$ApiStackName = "glap-operations-api-staging",
    [string]$MinimumCreatedDate = "2026-08-27",
    [switch]$BindingDiagnostic,
    [switch]$RationaleDiagnostic
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
WITH scoped_sla_actions AS (
    SELECT action.*
    FROM $database.$actionTable AS action
    WHERE action.temporal_scope_id = 'OPERATIONAL'
      AND action.execution_mode = 'OPERATIONAL'
      AND action.time_basis = 'ACTUAL_CALENDAR'
      AND action.execution_scenario_id IS NULL
      AND action.alert_type = 'SLA_BREACH'
      AND action.created_date BETWEEN DATE '$minimumDateText' AND DATE '$sydneyDateText'
      AND action.as_of_date <= DATE '$sydneyDateText'
),
source_evidence AS (
    SELECT
        action.action_id,
        count(alert.alert_fingerprint) AS source_match_count,
        count_if(
            alert.alert_type = 'SLA_BREACH'
            AND alert.alert_grain = 'SHIPMENT_MILESTONE'
            AND alert.status = 'OPEN'
            AND alert.severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
            AND (
                (alert.alert_dimension = 'ORIGIN_GATE_IN' AND alert.metric_name = 'gate_in_delay_hours')
                OR (alert.alert_dimension = 'ORIGIN_HANDOVER' AND alert.metric_name = 'origin_delay_hours')
                OR (alert.alert_dimension = 'P2P_DEPARTURE' AND alert.metric_name = 'departure_delay_hours')
                OR (alert.alert_dimension = 'P2P_ARRIVAL' AND alert.metric_name = 'arrival_delay_hours')
                OR (alert.alert_dimension = 'DESTINATION_DISCHARGE' AND alert.metric_name = 'discharge_delay_hours')
                OR (alert.alert_dimension = 'DESTINATION_RELEASE' AND alert.metric_name = 'destination_release_delay_hours')
                OR (alert.alert_dimension = 'FINAL_DELIVERY' AND alert.metric_name = 'delivery_delay_hours')
            )
            AND is_finite(try_cast(alert.metric_value AS double))
            AND is_finite(try_cast(alert.threshold_value AS double))
            AND try_cast(alert.metric_value AS double) >= 0
            AND try_cast(alert.threshold_value AS double) >= 0
            AND try_cast(alert.metric_value AS double) > try_cast(alert.threshold_value AS double)
        ) AS eligible_source_match_count,
        max(alert.alert_dimension) AS alert_dimension,
        max(try_cast(alert.metric_value AS double)) AS metric_value,
        max(try_cast(alert.threshold_value AS double)) AS threshold_value
    FROM scoped_sla_actions AS action
    LEFT JOIN $database.$alertTable AS alert
      ON alert.temporal_scope_id = action.temporal_scope_id
     AND alert.alert_fingerprint = action.alert_fingerprint
     AND try_cast(alert.dt AS date) = action.created_date
     AND alert.execution_mode = 'OPERATIONAL'
     AND alert.time_basis = 'ACTUAL_CALENDAR'
     AND alert.execution_scenario_id IS NULL
     AND alert.as_of_date <= DATE '$sydneyDateText'
    GROUP BY action.action_id
),
sla_evidence AS (
    SELECT
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
        source.source_match_count,
        source.eligible_source_match_count,
        source.alert_dimension,
        source.metric_value,
        source.threshold_value,
        current.decision_brief_version AS current_decision_brief_version,
        current.selected_alternative AS current_selected_alternative,
        current.selection_rationale AS current_selection_rationale
    FROM scoped_sla_actions AS action
    JOIN source_evidence AS source
      ON source.action_id = action.action_id
    LEFT JOIN $database.$actionView AS current
      ON current.temporal_scope_id = action.temporal_scope_id
     AND current.action_id = action.action_id
),
rationale_inputs AS (
    SELECT
        *,
        concat(
            'Review an expedite intervention for ', alert_dimension,
            '; the governed delay is '
        ) AS expected_rationale_prefix,
        ' hours above threshold.' AS expected_rationale_suffix
    FROM sla_evidence
),
binding_components AS (
    SELECT
        *,
        coalesce(
            source_match_count = 1 AND eligible_source_match_count = 1,
            false
        ) AS source_valid,
        coalesce(
            decision_brief_version = 'decision-brief.v1',
            false
        ) AS brief_version_valid,
        coalesce(
            action_type = 'EXPEDITE_MILESTONE',
            false
        ) AS action_type_valid,
        coalesce(
            selected_alternative = 'EXPEDITE_MILESTONE',
            false
        ) AS selected_alternative_valid,
        coalesce(
            selection_rationale IS NOT NULL
            AND trim(selection_rationale) <> '',
            false
        ) AS rationale_present_valid,
        coalesce(
            starts_with(selection_rationale, expected_rationale_prefix),
            false
        ) AS rationale_prefix_valid,
        coalesce(
            length(selection_rationale) >= length(expected_rationale_suffix)
            AND substr(
                selection_rationale,
                length(selection_rationale) - length(expected_rationale_suffix) + 1
            ) = expected_rationale_suffix,
            false
        ) AS rationale_suffix_valid,
        coalesce(
            is_finite(
                try_cast(
                    replace(
                        replace(selection_rationale, expected_rationale_prefix, ''),
                        expected_rationale_suffix,
                        ''
                    ) AS double
                )
            )
            AND try_cast(
                replace(
                    replace(selection_rationale, expected_rationale_prefix, ''),
                    expected_rationale_suffix,
                    ''
                ) AS double
            ) >= 0,
            false
        ) AS rationale_numeric_token_valid,
        coalesce(
            try_cast(
                replace(
                    replace(selection_rationale, expected_rationale_prefix, ''),
                    expected_rationale_suffix,
                    ''
                ) AS double
            ) = round(metric_value - threshold_value, 2),
            false
        ) AS rationale_numeric_equality_valid,
        coalesce(
            status = 'PROPOSED'
            AND approval_required
            AND approved_by IS NULL
            AND approved_at IS NULL
            AND completed_at IS NULL
            AND provenance = 'SIMULATED',
            false
        ) AS immutable_proposal_valid,
        coalesce(
            current_decision_brief_version = decision_brief_version
            AND current_selected_alternative = selected_alternative
            AND current_selection_rationale = selection_rationale,
            false
        ) AS current_view_binding_valid
    FROM rationale_inputs
),
binding_diagnostics AS (
    SELECT
        *,
        coalesce(
            rationale_present_valid
            AND rationale_prefix_valid
            AND rationale_suffix_valid
            AND rationale_numeric_token_valid,
            false
        ) AS rationale_shape_valid,
        coalesce(
            rationale_numeric_equality_valid,
            false
        ) AS rationale_value_valid
    FROM binding_components
),
evaluated AS (
    SELECT
        *,
        coalesce(
            brief_version_valid
            AND action_type_valid
            AND selected_alternative_valid
            AND rationale_shape_valid
            AND rationale_value_valid,
            false
        ) AS binding_valid
    FROM binding_diagnostics
),
legacy_summary AS (
    SELECT count(*) AS legacy_bound_sla_action_count
    FROM $database.$actionTable
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND alert_type = 'SLA_BREACH'
      AND created_date < DATE '$minimumDateText'
      AND (
          decision_brief_version IS NOT NULL
          OR selected_alternative IS NOT NULL
          OR selection_rationale IS NOT NULL
      )
)
SELECT
    count(*) AS candidate_action_count,
    count_if(source_valid) AS eligible_source_count,
    count_if(binding_valid) AS valid_binding_count,
    count_if(NOT binding_valid) AS invalid_binding_count,
    count_if(brief_version_valid) AS valid_brief_version_count,
    count_if(action_type_valid) AS valid_action_type_count,
    count_if(selected_alternative_valid) AS valid_selected_alternative_count,
    count_if(rationale_shape_valid) AS valid_rationale_shape_count,
    count_if(rationale_value_valid) AS valid_rationale_value_count,
    count_if(rationale_present_valid) AS valid_rationale_present_count,
    count_if(rationale_prefix_valid) AS valid_rationale_prefix_count,
    count_if(rationale_suffix_valid) AS valid_rationale_suffix_count,
    count_if(rationale_numeric_token_valid) AS valid_rationale_numeric_token_count,
    count_if(rationale_numeric_equality_valid) AS valid_rationale_numeric_equality_count,
    count_if(immutable_proposal_valid) AS immutable_proposal_count,
    count_if(current_view_binding_valid) AS current_view_binding_match_count,
    max(legacy.legacy_bound_sla_action_count) AS legacy_bound_sla_action_count
FROM evaluated
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
        throw "Read-only SLA runtime reconciliation query did not complete"
    }
} while ($state -ne "SUCCEEDED" -and [DateTime]::UtcNow -lt $deadline)
if ($state -ne "SUCCEEDED") {
    & aws athena stop-query-execution --query-execution-id $queryId @awsScope | Out-Null
    throw "Read-only SLA runtime reconciliation query timed out"
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
    "At least one naturally generated SLA proposal exists" = $counts.candidate_action_count -ge 1
    "Every SLA proposal has exactly one eligible source Alert" = (
        $counts.eligible_source_count -eq $counts.candidate_action_count
    )
    "Every SLA proposal has the exact Decision binding" = (
        $counts.valid_binding_count -eq $counts.candidate_action_count
    )
    "No invalid SLA binding exists in the inspected cohort" = $counts.invalid_binding_count -eq 0
    "Every inspected Action remains an immutable unreviewed proposal" = (
        $counts.immutable_proposal_count -eq $counts.candidate_action_count
    )
    "Current view preserves every immutable Decision binding" = (
        $counts.current_view_binding_match_count -eq $counts.candidate_action_count
    )
    "Pre-release SLA Actions remain legacy-null" = $counts.legacy_bound_sla_action_count -eq 0
}
if ($BindingDiagnostic -or $RationaleDiagnostic) {
    $checks["Every SLA proposal has decision-brief.v1"] = (
        $counts.valid_brief_version_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA proposal has EXPEDITE_MILESTONE Action type"] = (
        $counts.valid_action_type_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA proposal selects EXPEDITE_MILESTONE"] = (
        $counts.valid_selected_alternative_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA rationale has the exact milestone-bound shape"] = (
        $counts.valid_rationale_shape_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA rationale has the calculated breach value"] = (
        $counts.valid_rationale_value_count -eq $counts.candidate_action_count
    )
}
if ($RationaleDiagnostic) {
    $checks["Every SLA rationale is present"] = (
        $counts.valid_rationale_present_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA rationale has the exact milestone prefix"] = (
        $counts.valid_rationale_prefix_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA rationale has the exact governed suffix"] = (
        $counts.valid_rationale_suffix_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA rationale has a finite non-negative numeric token"] = (
        $counts.valid_rationale_numeric_token_count -eq $counts.candidate_action_count
    )
    $checks["Every SLA rationale numeric token equals the calculated breach"] = (
        $counts.valid_rationale_numeric_equality_count -eq $counts.candidate_action_count
    )
}
foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key): $($entry.Value)"
}
if ($checks.Values -contains $false) {
    throw "SLA runtime evidence reconciliation failed closed"
}
Write-Host "SLA runtime evidence reconciliation passed. Protected identifiers were not printed."
Write-Host "Lifecycle, API, and table mutations executed: False. Athena result storage is service-managed."
