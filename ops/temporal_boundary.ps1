function Get-SydneyBusinessDate {
    $timeZone = $null
    foreach ($timeZoneId in @("Australia/Sydney", "AUS Eastern Standard Time")) {
        try {
            $timeZone = [TimeZoneInfo]::FindSystemTimeZoneById($timeZoneId)
            break
        } catch {
            $timeZone = $null
        }
    }
    if (-not $timeZone) {
        throw "Australia/Sydney timezone data is required"
    }
    return [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $timeZone).Date
}

function Resolve-TemporalContext {
    param(
        [Parameter(Mandatory)] [datetime]$LastLogicalDate,
        [ValidateSet("OPERATIONAL", "FUTURE_SIMULATION")]
        [string]$ExecutionMode = "OPERATIONAL",
        [string]$ScenarioId = ""
    )

    $asOfDate = Get-SydneyBusinessDate
    if ($ExecutionMode -eq "OPERATIONAL") {
        if ($LastLogicalDate.Date -gt $asOfDate) {
            throw (
                "Operational logical date $($LastLogicalDate.ToString('yyyy-MM-dd')) " +
                "exceeds Sydney as-of date $($asOfDate.ToString('yyyy-MM-dd'))"
            )
        }
        if ($ScenarioId) {
            throw "OPERATIONAL runs must not set ScenarioId"
        }
        $timeBasis = "ACTUAL_CALENDAR"
        $safeScenarioId = $null
    } else {
        if ($ScenarioId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$') {
            throw "FUTURE_SIMULATION requires a safe ScenarioId of 3 to 64 characters"
        }
        $timeBasis = "FUTURE_SIMULATION"
        $safeScenarioId = $ScenarioId
    }

    return [pscustomobject]@{
        execution_mode = $ExecutionMode
        time_basis = $timeBasis
        as_of_date = $asOfDate.ToString("yyyy-MM-dd")
        scenario_id = $safeScenarioId
    }
}
