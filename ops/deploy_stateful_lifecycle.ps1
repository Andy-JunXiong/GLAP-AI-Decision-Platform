[CmdletBinding()]
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$SourceDatabase = "simulated_iceberg_m",
    [Parameter(Mandatory)] [string]$SourceBucketUri,
    [Parameter(Mandatory)] [string]$AthenaOutputUri,
    [string]$Workgroup = "primary",
    [switch]$IncludeSeed,
    [switch]$AnalyticsOnly,
    [switch]$Q4ConfigurationOnly,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

if ($SourceDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "SourceDatabase is not a safe Athena identifier"
}
if ($SourceBucketUri -notmatch '^s3://[^/]+/.+' -or $AthenaOutputUri -notmatch '^s3://[^/]+/.+') {
    throw "SourceBucketUri and AthenaOutputUri must be prefix-scoped s3:// URIs"
}
if ($AnalyticsOnly -and $IncludeSeed) {
    throw "AnalyticsOnly cannot be combined with IncludeSeed"
}
if ($Q4ConfigurationOnly -and ($AnalyticsOnly -or $IncludeSeed)) {
    throw "Q4ConfigurationOnly cannot be combined with AnalyticsOnly or IncludeSeed"
}

function Get-RenderedStatements {
    param([Parameter(Mandatory)] [string]$Path)

    $sql = Get-Content -LiteralPath $Path -Raw
    $sql = $sql.Replace("{{SOURCE_DATABASE}}", $SourceDatabase)
    $sql = $sql.Replace("{{SOURCE_BUCKET_URI}}", $SourceBucketUri.TrimEnd('/'))
    if ($sql -match '\{\{[^}]+\}\}') {
        throw "Unresolved SQL template token in $Path"
    }
    $sql = [regex]::Replace($sql, '(?m)^\s*--.*$', '')
    return @($sql -split ';' | Where-Object { $_.Trim() })
}

function Invoke-AthenaStatement {
    param([Parameter(Mandatory)] [string]$Statement)

    $awsScope = @("--region", $Region)
    if ($Profile) {
        $awsScope += @("--profile", $Profile)
    }
    $queryId = & aws athena start-query-execution `
        --query-string $Statement `
        --query-execution-context "Database=$SourceDatabase" `
        --result-configuration "OutputLocation=$AthenaOutputUri" `
        --work-group $Workgroup `
        @awsScope `
        --query QueryExecutionId `
        --output text
    if ($LASTEXITCODE -ne 0 -or -not $queryId) {
        throw "Unable to start Athena lifecycle statement"
    }
    do {
        Start-Sleep -Seconds 1
        $result = & aws athena get-query-execution `
            --query-execution-id $queryId `
            @awsScope `
            --output json | ConvertFrom-Json
        $state = $result.QueryExecution.Status.State
    } while ($state -in @("QUEUED", "RUNNING"))
    if ($state -ne "SUCCEEDED") {
        throw "Athena lifecycle statement $state`: $($result.QueryExecution.Status.StateChangeReason)"
    }
}

function Add-MissingIcebergColumns {
    param(
        [Parameter(Mandatory)] [string]$TableName,
        [Parameter(Mandatory)] [hashtable]$Columns
    )

    $awsScope = @("--region", $Region)
    if ($Profile) {
        $awsScope += @("--profile", $Profile)
    }
    $existing = @(& aws glue get-table `
        --database-name $SourceDatabase `
        --name $TableName `
        @awsScope `
        --query 'Table.StorageDescriptor.Columns[].Name' `
        --output text) -split '\s+' | Where-Object { $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Glue columns for $TableName"
    }
    $missing = @($Columns.Keys | Sort-Object | Where-Object { $_ -notin $existing })
    if (-not $missing) {
        return
    }
    $definitions = $missing | ForEach-Object { "$_ $($Columns[$_])" }
    Invoke-AthenaStatement -Statement (
        "ALTER TABLE $SourceDatabase.$TableName ADD COLUMNS (" +
        ($definitions -join ', ') + ")"
    )
}

$root = Split-Path $PSScriptRoot -Parent
$schemaFile = Join-Path $root "sql/04_stateful_lifecycle_config.sql"
$q4ConfigurationFile = Join-Path $root "sql/11_stateful_lifecycle_q4_rate_rollover.sql"
$configurationFiles = @(
    if ($Q4ConfigurationOnly) {
        $q4ConfigurationFile
    } else {
        if ($IncludeSeed) {
            Join-Path $root "sql/05_stateful_lifecycle_seed.sql"
        }
        Join-Path $root "sql/08_stateful_lifecycle_multimodal_seed.sql"
        $q4ConfigurationFile
    }
)
$viewFile = Join-Path $root "sql/07_stateful_lifecycle_compatibility_views.sql"
$analyticsViewFile = Join-Path $root "sql/09_multimodal_ops_analytics.sql"
$schemaStatements = @(
    if (-not $AnalyticsOnly -and -not $Q4ConfigurationOnly) {
        Get-RenderedStatements -Path $schemaFile
    }
)
$configurationStatements = @(
    if (-not $AnalyticsOnly) {
        $configurationFiles | ForEach-Object { Get-RenderedStatements -Path $_ }
    }
)
$viewStatements = @(
    if (-not $AnalyticsOnly -and -not $Q4ConfigurationOnly) {
        Get-RenderedStatements -Path $viewFile
    }
)
$analyticsViewStatements = @(
    if (-not $Q4ConfigurationOnly) {
        Get-RenderedStatements -Path $analyticsViewFile
    }
)
$statements = @(
    $schemaStatements + $configurationStatements + $viewStatements +
    $analyticsViewStatements
)
$columnEvolutions = @{
    "dim_lifecycle_target_v1" = @{
        transport_mode = "string"; target_hours = "int"
    }
    "dim_route_service_v1" = @{
        transport_mode = "string"; provider_type = "string";
        operating_carrier = "string"; origin_location_type = "string";
        destination_location_type = "string"; p2p_target_hours = "int";
        equipment_type = "string"
    }
    "dim_rate_card_v1" = @{ transport_mode = "string" }
    "fact_shipment_lifecycle_staging_v1" = @{
        transport_mode = "string"; provider_type = "string";
        operating_carrier = "string"; origin_location_type = "string";
        destination_location_type = "string";
        origin_handover_target_at = "timestamp"; origin_handover_at = "timestamp";
        destination_release_target_at = "timestamp"; destination_release_at = "timestamp";
        piece_count = "int"; gross_weight_kg = "decimal(18,2)";
        volume_cbm = "decimal(18,3)"; chargeable_weight_kg = "decimal(18,2)";
        temporal_scope_id = "string"; execution_mode = "string";
        time_basis = "string"; as_of_date = "date"; execution_scenario_id = "string"
    }
    "fact_shipment_lifecycle_event_staging_v1" = @{
        transport_mode = "string"; segment_type = "string";
        leg_seq = "int"; location_type = "string";
        temporal_scope_id = "string"; execution_mode = "string";
        time_basis = "string"; as_of_date = "date"; execution_scenario_id = "string"
    }
    "fact_shipment_cost_staging_v1" = @{
        temporal_scope_id = "string"; execution_mode = "string";
        time_basis = "string"; as_of_date = "date"; execution_scenario_id = "string"
    }
    "fact_shipment_lifecycle_metrics_staging_v1" = @{
        origin_performance = "string"; origin_delay_hours = "double";
        destination_release_performance = "string";
        destination_release_delay_hours = "double";
        temporal_scope_id = "string"; execution_mode = "string";
        time_basis = "string"; as_of_date = "date"; execution_scenario_id = "string"
    }
    "fact_shipment_signal_candidate_staging_v1" = @{
        temporal_scope_id = "string"; execution_mode = "string";
        time_basis = "string"; as_of_date = "date"; execution_scenario_id = "string"
    }
}

Write-Host "Stateful lifecycle deployment plan"
Write-Host "  Database: $SourceDatabase"
Write-Host "  Data root: $($SourceBucketUri.TrimEnd('/'))"
Write-Host "  SQL statements: $($statements.Count)"
Write-Host "  Idempotent schema-evolution tables: $(
    if ($AnalyticsOnly -or $Q4ConfigurationOnly) { 0 } else { $columnEvolutions.Count }
)"
Write-Host "  Seed included: $($IncludeSeed.IsPresent)"
Write-Host "  Analytics only: $($AnalyticsOnly.IsPresent)"
Write-Host "  Q4 configuration only: $($Q4ConfigurationOnly.IsPresent)"

if (-not $Apply) {
    Write-Host "Plan only. Re-run with -Apply after reviewing the target prefixes."
    return
}

foreach ($statement in $schemaStatements) {
    Invoke-AthenaStatement -Statement $statement.Trim()
}
if (-not $AnalyticsOnly -and -not $Q4ConfigurationOnly) {
    foreach ($tableName in ($columnEvolutions.Keys | Sort-Object)) {
        Add-MissingIcebergColumns -TableName $tableName -Columns $columnEvolutions[$tableName]
    }
}
foreach ($statement in $configurationStatements) {
    Invoke-AthenaStatement -Statement $statement.Trim()
}
foreach ($statement in $viewStatements) {
    Invoke-AthenaStatement -Statement $statement.Trim()
}
foreach ($statement in $analyticsViewStatements) {
    Invoke-AthenaStatement -Statement $statement.Trim()
}
Write-Host "Stateful lifecycle schema, compatibility views and multimodal analytics deployed. Run both validation contracts before enabling any writer."
