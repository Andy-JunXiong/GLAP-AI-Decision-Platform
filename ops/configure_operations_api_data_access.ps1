[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$StackName = "glap-operations-api-staging",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [string]$ActionView = "vw_lifecycle_action_current_staging_v1",
    [string]$BaseActionTable = "fact_lifecycle_action_audit_staging_v1",
    [string]$CurrentActionTable = "fact_lifecycle_action_staging_v1",
    [string]$AlertTable = "fact_lifecycle_alert_staging_v1",
    [string]$OutcomeTable = "fact_lifecycle_outcome_staging_v1",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if ($StackName -notmatch '^[A-Za-z][A-Za-z0-9-]{0,127}$') {
    throw "Invalid CloudFormation stack name"
}
if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid Glue database name"
}
if ($ActionView -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid Glue view name"
}
if ($BaseActionTable -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid Glue base table name"
}
if ($CurrentActionTable -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid Glue current table name"
}
if ($AlertTable -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid Glue Alert table name"
}
if ($OutcomeTable -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid Glue Outcome table name"
}

Write-Host "Operations API governed-read access plan"
Write-Host "  Database permission: DESCRIBE"
Write-Host "  Action view permissions: SELECT, DESCRIBE"
Write-Host "  Two backing Action tables: SELECT, DESCRIBE"
Write-Host "  Operational Alert table: SELECT, DESCRIBE"
Write-Host "  Operational Outcome table: SELECT, DESCRIBE"
Write-Host "  Other tables or views: False"
Write-Host "  Write or grantable permissions: False"
Write-Host "  Production resources: False"
if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply using a Lake Formation administrator profile."
    return
}

$awsScope = @("--region", $Region)
if ($Profile) { $awsScope += @("--profile", $Profile) }

function Invoke-AwsJson([string[]]$Arguments) {
    $json = & aws @Arguments @awsScope --output json
    if ($LASTEXITCODE -ne 0 -or -not $json) {
        throw "AWS read operation failed"
    }
    return $json | ConvertFrom-Json
}

function Write-TemporaryJson($Value) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) (
        "glap-operations-lf-" + [guid]::NewGuid().ToString("N") + ".json"
    )
    $json = $Value | ConvertTo-Json -Depth 8 -Compress
    [System.IO.File]::WriteAllText(
        $path, $json, [System.Text.UTF8Encoding]::new($false)
    )
    return $path
}

function Grant-MissingPermissions(
    [string]$PrincipalPath,
    [string]$ResourcePath,
    [string[]]$RequiredPermissions
) {
    $current = Invoke-AwsJson @(
        "lakeformation", "list-permissions",
        "--principal", "file://$PrincipalPath",
        "--resource", "file://$ResourcePath"
    )
    $present = @(
        $current.PrincipalResourcePermissions |
            ForEach-Object { $_.Permissions } |
            Sort-Object -Unique
    )
    $missing = @($RequiredPermissions | Where-Object { $_ -notin $present })
    if ($missing.Count -eq 0) { return $false }

    & aws lakeformation grant-permissions `
        --principal "file://$PrincipalPath" `
        --resource "file://$ResourcePath" `
        --permissions $missing @awsScope | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to grant the exact governed-read permissions"
    }
    return $true
}

$stack = Invoke-AwsJson @("cloudformation", "describe-stacks", "--stack-name", $StackName)
$stackStatus = [string]$stack.Stacks[0].StackStatus
if ($stackStatus -notmatch '^(CREATE|UPDATE)_COMPLETE$') {
    throw "Operations API staging stack is not stable"
}
$roleResource = Invoke-AwsJson @(
    "cloudformation", "describe-stack-resource",
    "--stack-name", $StackName,
    "--logical-resource-id", "OperationsApiRole"
)
$roleName = [string]$roleResource.StackResourceDetail.PhysicalResourceId
$role = Invoke-AwsJson @("iam", "get-role", "--role-name", $roleName)
$roleArn = [string]$role.Role.Arn
$identity = Invoke-AwsJson @("sts", "get-caller-identity")
$catalogId = [string]$identity.Account
$null = Invoke-AwsJson @(
    "glue", "get-table", "--database-name", $SourceDatabase, "--name", $ActionView
)
$null = Invoke-AwsJson @(
    "glue", "get-table", "--database-name", $SourceDatabase, "--name", $BaseActionTable
)
$null = Invoke-AwsJson @(
    "glue", "get-table", "--database-name", $SourceDatabase, "--name", $CurrentActionTable
)
$null = Invoke-AwsJson @(
    "glue", "get-table", "--database-name", $SourceDatabase, "--name", $AlertTable
)
$null = Invoke-AwsJson @(
    "glue", "get-table", "--database-name", $SourceDatabase, "--name", $OutcomeTable
)

$principalPath = Write-TemporaryJson @{DataLakePrincipalIdentifier = $roleArn}
$databasePath = Write-TemporaryJson @{
    Database = @{CatalogId = $catalogId; Name = $SourceDatabase}
}
$tablePath = Write-TemporaryJson @{
    Table = @{CatalogId = $catalogId; DatabaseName = $SourceDatabase; Name = $ActionView}
}
$baseTablePath = Write-TemporaryJson @{
    Table = @{CatalogId = $catalogId; DatabaseName = $SourceDatabase; Name = $BaseActionTable}
}
$currentTablePath = Write-TemporaryJson @{
    Table = @{CatalogId = $catalogId; DatabaseName = $SourceDatabase; Name = $CurrentActionTable}
}
$alertTablePath = Write-TemporaryJson @{
    Table = @{CatalogId = $catalogId; DatabaseName = $SourceDatabase; Name = $AlertTable}
}
$outcomeTablePath = Write-TemporaryJson @{
    Table = @{CatalogId = $catalogId; DatabaseName = $SourceDatabase; Name = $OutcomeTable}
}
try {
    $databaseChanged = Grant-MissingPermissions $principalPath $databasePath @("DESCRIBE")
    $tableChanged = Grant-MissingPermissions $principalPath $tablePath @("SELECT", "DESCRIBE")
    $baseTableChanged = Grant-MissingPermissions $principalPath $baseTablePath @("SELECT", "DESCRIBE")
    $currentTableChanged = Grant-MissingPermissions $principalPath $currentTablePath @("SELECT", "DESCRIBE")
    $alertTableChanged = Grant-MissingPermissions $principalPath $alertTablePath @("SELECT", "DESCRIBE")
    $outcomeTableChanged = Grant-MissingPermissions $principalPath $outcomeTablePath @("SELECT", "DESCRIBE")
} finally {
    Remove-Item -LiteralPath $principalPath, $databasePath, $tablePath, `
        $baseTablePath, $currentTablePath, $alertTablePath, $outcomeTablePath `
        -Force -ErrorAction SilentlyContinue
}

Write-Host "Governed database permission configured: True"
Write-Host "Governed Action view permissions configured: True"
Write-Host "Governed backing Action table permissions configured: True"
Write-Host "Governed operational Alert table permissions configured: True"
Write-Host "Governed operational Outcome table permissions configured: True"
Write-Host "Permissions changed in this run: $([bool]($databaseChanged -or $tableChanged -or $baseTableChanged -or $currentTableChanged -or $alertTableChanged -or $outcomeTableChanged))"
Write-Host "No account IDs, ARNs, database names, view names, or paths were printed"
