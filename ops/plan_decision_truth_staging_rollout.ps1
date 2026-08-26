[CmdletBinding()]
param(
    [string]$SourceDatabase = "simulated_iceberg_m",
    [switch]$ShowSql
)

$ErrorActionPreference = "Stop"
if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,254}$') {
    throw "SourceDatabase must be a safe Athena identifier"
}

$root = Split-Path $PSScriptRoot -Parent
$migrationPath = Join-Path $root "sql/16_decision_action_binding_v1.sql"
$validationPath = Join-Path $root "sql/17_decision_action_binding_validation.sql"

function Get-RenderedSql {
    param([Parameter(Mandatory)] [string]$Path)

    $sql = (Get-Content -LiteralPath $Path -Raw).Replace(
        "{{SOURCE_DATABASE}}",
        $SourceDatabase
    )
    if ($sql -match '\{\{[^}]+\}\}') {
        throw "Decision Truth SQL contains an unresolved template token"
    }
    return $sql
}

function Get-StatementCount {
    param([Parameter(Mandatory)] [string]$Sql)

    $withoutComments = [regex]::Replace($Sql, '(?m)^\s*--.*$', '')
    return @(
        $withoutComments.Split(';') | Where-Object { $_.Trim() }
    ).Count
}

$migrationSql = Get-RenderedSql -Path $migrationPath
$validationSql = Get-RenderedSql -Path $validationPath

if ((Get-StatementCount -Sql $migrationSql) -ne 2) {
    throw "Decision binding migration must contain exactly two statements"
}
if ((Get-StatementCount -Sql $validationSql) -ne 1) {
    throw "Decision binding validation must contain exactly one statement"
}
if ($migrationSql -match '(?i)\b(DROP|DELETE|INSERT|UPDATE|MERGE|TRUNCATE)\b') {
    throw "Decision binding migration must remain additive-only"
}
if ($validationSql -match '(?i)\b(ALTER|CREATE|DROP|DELETE|INSERT|UPDATE|MERGE|TRUNCATE)\b') {
    throw "Decision binding validation must remain read-only"
}
if (
    $migrationSql -notmatch 'ALTER\s+TABLE\s+[^\s]+\.fact_lifecycle_action_staging_v1' -or
    $migrationSql -notmatch 'CREATE\s+OR\s+REPLACE\s+VIEW\s+[^\s]+\.vw_lifecycle_action_current_staging_v1'
) {
    throw "Decision binding migration targets differ from the reviewed contract"
}
foreach ($field in @(
    "decision_brief_version",
    "selected_alternative",
    "selection_rationale"
)) {
    if (-not $migrationSql.Contains($field) -or -not $validationSql.Contains($field)) {
        throw "Decision binding field is missing from migration or validation: $field"
    }
}
foreach ($checkName in @(
    "missing_action_binding_columns",
    "missing_action_current_binding_columns",
    "partial_action_binding",
    "invalid_decision_brief_v1_binding",
    "invalid_cost_decision_brief_v1_binding",
    "current_view_binding_mismatch"
)) {
    if (-not $validationSql.Contains($checkName)) {
        throw "Decision binding validation check is missing: $checkName"
    }
}

Write-Host "Decision Truth private staging rollout plan"
Write-Host "  Mode: local render only"
Write-Host "  Source database: $SourceDatabase"
Write-Host "  Migration statements: 2"
Write-Host "  Aggregate validation statements: 1"
Write-Host "  Aggregate validation checks: 6"
Write-Host "  Additive-only guard: passed"
Write-Host "  Read-only validation guard: passed"
Write-Host "  Release order: schema, validation, lifecycle producer, Operations API, private frontend, read-only verification"
Write-Host "  Existing Actions backfilled: False"
Write-Host "  COST_ANOMALY binding source present: True"
Write-Host "  COST_ANOMALY staging producer released: True"
Write-Host "  COST_ANOMALY staging readers released: True"
Write-Host "  COST_ANOMALY runtime binding observed: False"
Write-Host "  AWS session inspected: False"
Write-Host "  Athena query started: False"
Write-Host "  Schema migration applied: False"
Write-Host "  Staging package deployed: False"
Write-Host "  Operational continuation authorized: False"
Write-Host "  Public Pages deployment: False"
Write-Host "  Production effect: False"

if ($ShowSql) {
    Write-Host ""
    Write-Host "--- reviewed additive migration SQL ---"
    Write-Output $migrationSql.Trim()
    Write-Host ""
    Write-Host "--- reviewed aggregate-only validation SQL ---"
    Write-Output $validationSql.Trim()
}
