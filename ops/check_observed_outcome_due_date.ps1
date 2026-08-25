[CmdletBinding()]
param(
    [string]$ContractPath = ""
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

if (-not $ContractPath) {
    $ContractPath = Join-Path $PSScriptRoot "..\docs\action_complete_outcome_canary_v1.json"
}
$resolvedContract = (Resolve-Path -LiteralPath $ContractPath).Path
$contract = Get-Content -LiteralPath $resolvedContract -Raw | ConvertFrom-Json
$dueText = [string]$contract.runtime_pending_outcome.observation_due_date
$dueBasis = [string]$contract.runtime_pending_outcome.observation_due_date_basis
if ($dueText -notmatch '^\d{4}-\d{2}-\d{2}$' -or
    $dueBasis -ne "SYSTEM_COMPUTED_FUTURE_GATE_NOT_OBSERVED") {
    throw "The governed observation due-date contract is invalid"
}

$dueDate = [DateTime]::ParseExact(
    $dueText, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture
).Date
$sydneyToday = Get-SydneyBusinessDate
Write-Host "Sydney business date: $($sydneyToday.ToString('yyyy-MM-dd'))"
Write-Host "Observation due date: $dueText"
Write-Host "External writes executed: False"

if ($sydneyToday -lt $dueDate) {
    Write-Host "BLOCKED: observation due date has not been reached"
    exit 2
}

Write-Host "READY: due-date gate is satisfied; observed continuation still requires separate authorization"
