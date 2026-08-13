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
$migrationPath = Join-Path $root "sql/15_action_assignment_v1.sql"
$validationPath = Join-Path $root "sql/16_action_assignment_validation.sql"

function Get-RenderedSql {
    param([Parameter(Mandatory)] [string]$Path)

    $sql = (Get-Content -LiteralPath $Path -Raw).Replace(
        "{{SOURCE_DATABASE}}",
        $SourceDatabase
    )
    if ($sql -match '\{\{[^}]+\}\}') {
        throw "Action assignment SQL contains an unresolved template token"
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
    throw "Action assignment migration must contain exactly two statements"
}
if ((Get-StatementCount -Sql $validationSql) -ne 1) {
    throw "Action assignment validation must contain exactly one statement"
}
if ($migrationSql -match '(?i)\b(DROP|DELETE|INSERT|UPDATE|MERGE|TRUNCATE)\b') {
    throw "Action assignment migration must remain additive-only"
}
if (
    $migrationSql -notmatch 'ALTER\s+TABLE\s+[^\s]+\.fact_lifecycle_action_audit_staging_v1' -or
    $migrationSql -notmatch 'CREATE\s+OR\s+REPLACE\s+VIEW\s+[^\s]+\.vw_lifecycle_action_current_staging_v1'
) {
    throw "Action assignment migration targets differ from the reviewed contract"
}

Write-Host "Action assignment staging schema plan"
Write-Host "  Mode: local render only"
Write-Host "  Source database: $SourceDatabase"
Write-Host "  Migration statements: 2"
Write-Host "  Validation statements: 1"
Write-Host "  Additive-only guard: passed"
Write-Host "  AWS session inspected: False"
Write-Host "  Athena query started: False"
Write-Host "  Schema migration applied: False"
Write-Host "  Operations API or frontend released: False"
Write-Host "  Production effect: False"

if ($ShowSql) {
    Write-Host ""
    Write-Host "--- reviewed migration SQL ---"
    Write-Output $migrationSql.Trim()
    Write-Host ""
    Write-Host "--- read-only post-migration validation SQL ---"
    Write-Output $validationSql.Trim()
}
