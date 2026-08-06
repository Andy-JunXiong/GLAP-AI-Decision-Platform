-- GLAP stateful lifecycle configuration and staging contracts.
-- Replace {{SOURCE_DATABASE}} and {{SOURCE_BUCKET_URI}} before execution.
-- Business values are versioned rows; Lambda environment variables contain
-- only technical table names and execution settings.

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.dim_lifecycle_target_v1 (
    target_id string,
    stage_code string,
    origin_port string,
    destination_port string,
    target_days int,
    tolerance_hours int,
    effective_from date,
    effective_to date,
    status string,
    config_version string,
    updated_at timestamp,
    transport_mode string,
    target_hours int
)
LOCATION '{{SOURCE_BUCKET_URI}}/dim_lifecycle_target_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.dim_route_service_v1 (
    route_service_id string,
    origin_port string,
    destination_port string,
    carrier string,
    service_code string,
    service_level string,
    p2p_target_days int,
    departure_weekday int,
    frequency_days int,
    source_type string,
    source_reference string,
    effective_from date,
    effective_to date,
    status string,
    config_version string,
    updated_at timestamp,
    transport_mode string,
    provider_type string,
    operating_carrier string,
    origin_location_type string,
    destination_location_type string,
    p2p_target_hours int,
    equipment_type string
)
LOCATION '{{SOURCE_BUCKET_URI}}/dim_route_service_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.dim_rate_card_v1 (
    rate_card_id string,
    rate_type string,
    origin_port string,
    destination_port string,
    carrier string,
    service_code string,
    equipment_type string,
    charge_code string,
    calculation_basis string,
    amount decimal(18,4),
    percentage_rate decimal(9,6),
    currency string,
    effective_from date,
    effective_to date,
    status string,
    rate_source string,
    config_version string,
    updated_at timestamp,
    transport_mode string
)
LOCATION '{{SOURCE_BUCKET_URI}}/dim_rate_card_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.dim_rate_tier_v1 (
    rate_tier_id string,
    port_code string,
    carrier string,
    equipment_type string,
    charge_code string,
    from_day int,
    to_day int,
    daily_rate decimal(18,4),
    currency string,
    effective_from date,
    effective_to date,
    status string,
    config_version string,
    updated_at timestamp
)
LOCATION '{{SOURCE_BUCKET_URI}}/dim_rate_tier_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.dim_fx_rate_v1 (
    base_currency string,
    quote_currency string,
    fx_rate decimal(18,8),
    effective_date date,
    source_type string,
    config_version string,
    updated_at timestamp
)
LOCATION '{{SOURCE_BUCKET_URI}}/dim_fx_rate_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.dim_provider_v1 (
    provider_code string,
    provider_name string,
    provider_type string,
    supported_mode string,
    status string,
    config_version string,
    updated_at timestamp
)
LOCATION '{{SOURCE_BUCKET_URI}}/dim_provider_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

-- Isolated staging snapshot. Promotion into fact_shipment_v2 happens only
-- after replay, reconciliation and schema-compatibility evidence passes.
CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1 (
    shipment_id string,
    dt string,
    booking_at timestamp,
    gate_in_target_at timestamp,
    gate_in_at timestamp,
    etd timestamp,
    atd timestamp,
    eta timestamp,
    ata timestamp,
    discharge_target_at timestamp,
    discharged_at timestamp,
    delivery_target_at timestamp,
    delivered_at timestamp,
    lifecycle_stage string,
    lifecycle_status string,
    terminal_state boolean,
    origin_port string,
    destination_port string,
    carrier string,
    route_service_id string,
    route_config_version string,
    rate_card_version string,
    rate_locked_at timestamp,
    service_level string,
    equipment_type string,
    container_count int,
    journey_exception_type string,
    journey_exception_hours int,
    expected_total_cost decimal(18,2),
    accrued_total_cost decimal(18,2),
    actual_total_cost decimal(18,2),
    cost_currency string,
    simulation_seed string,
    created_at timestamp,
    updated_at timestamp,
    transport_mode string,
    provider_type string,
    operating_carrier string,
    origin_location_type string,
    destination_location_type string,
    origin_handover_target_at timestamp,
    origin_handover_at timestamp,
    destination_release_target_at timestamp,
    destination_release_at timestamp,
    piece_count int,
    gross_weight_kg decimal(18,2),
    volume_cbm decimal(18,3),
    chargeable_weight_kg decimal(18,2),
    temporal_scope_id string,
    execution_mode string,
    time_basis string,
    as_of_date date,
    execution_scenario_id string
)
PARTITIONED BY (dt)
LOCATION '{{SOURCE_BUCKET_URI}}/fact_shipment_lifecycle_staging_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.fact_shipment_lifecycle_event_staging_v1 (
    event_id string,
    shipment_id string,
    event_type string,
    event_time timestamp,
    observed_at timestamp,
    processed_at timestamp,
    location string,
    logical_run_date date,
    scenario_id string,
    simulation_seed string,
    transport_mode string,
    segment_type string,
    leg_seq int,
    location_type string,
    temporal_scope_id string,
    execution_mode string,
    time_basis string,
    as_of_date date,
    execution_scenario_id string
)
PARTITIONED BY (logical_run_date)
LOCATION '{{SOURCE_BUCKET_URI}}/fact_shipment_lifecycle_event_staging_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.fact_shipment_cost_staging_v1 (
    shipment_id string,
    dt string,
    charge_code string,
    cost_stage string,
    calculation_basis string,
    quantity decimal(18,4),
    unit_rate decimal(18,4),
    amount decimal(18,2),
    currency string,
    rate_card_id string,
    rate_card_version string,
    cost_status string,
    created_at timestamp,
    temporal_scope_id string,
    execution_mode string,
    time_basis string,
    as_of_date date,
    execution_scenario_id string
)
PARTITIONED BY (dt)
LOCATION '{{SOURCE_BUCKET_URI}}/fact_shipment_cost_staging_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1 (
    shipment_id string,
    dt string,
    lifecycle_stage string,
    lifecycle_status string,
    gate_in_performance string,
    gate_in_delay_hours double,
    departure_performance string,
    departure_delay_hours double,
    arrival_performance string,
    arrival_delay_hours double,
    discharge_performance string,
    discharge_delay_hours double,
    delivery_performance string,
    delivery_delay_hours double,
    planned_p2p_hours double,
    actual_p2p_hours double,
    sla_breach_flag boolean,
    sla_breach_stages string,
    computed_at timestamp,
    origin_performance string,
    origin_delay_hours double,
    destination_release_performance string,
    destination_release_delay_hours double,
    temporal_scope_id string,
    execution_mode string,
    time_basis string,
    as_of_date date,
    execution_scenario_id string
)
PARTITIONED BY (dt)
LOCATION '{{SOURCE_BUCKET_URI}}/fact_shipment_lifecycle_metrics_staging_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');

CREATE TABLE IF NOT EXISTS {{SOURCE_DATABASE}}.fact_shipment_signal_candidate_staging_v1 (
    signal_fingerprint string,
    shipment_id string,
    dt string,
    signal_type string,
    signal_grain string,
    signal_dimension string,
    metric_name string,
    metric_value double,
    threshold_value double,
    severity string,
    candidate_status string,
    simulation_provenance string,
    computed_at timestamp,
    temporal_scope_id string,
    execution_mode string,
    time_basis string,
    as_of_date date,
    execution_scenario_id string
)
PARTITIONED BY (dt)
LOCATION '{{SOURCE_BUCKET_URI}}/fact_shipment_signal_candidate_staging_v1/'
TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd');
