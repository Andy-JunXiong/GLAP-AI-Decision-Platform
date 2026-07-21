-- Sanitized output from SHOW CREATE TABLE executed in Athena on 2026-07-21.
-- Only environment-specific S3 locations have been replaced.

CREATE TABLE curated_iceberg.fact_shipment_events_extended_iceberg (
  shipment_id string,
  event_type string,
  event_time timestamp,
  location string,
  status string,
  dt string,
  carrier string,
  origin_port string,
  dest_port string)
LOCATION 's3://<redacted-bucket>/<redacted-prefix>'
TBLPROPERTIES (
  'table_type'='iceberg',
  'format'='parquet',
  'write_compression'='zstd'
);

CREATE TABLE curated_iceberg.fact_ai_anomaly_scores_v1 (
  run_date date,
  entity_type string,
  entity_key string,
  metric_name string,
  metric_value double,
  baseline_value double,
  stddev_value double,
  z_score double,
  anomaly_flag int,
  created_at timestamp)
LOCATION 's3://<redacted-bucket>/<redacted-prefix>'
TBLPROPERTIES (
  'table_type'='iceberg',
  'compression_level'='3',
  'format'='PARQUET',
  'write_compression'='ZSTD'
);
CREATE TABLE curated_iceberg.fact_ai_root_cause_v1 (
  run_date date,
  entity_key string,
  metric_name string,
  root_cause string,
  confidence_score double,
  supporting_metric string,
  created_at timestamp)
LOCATION 's3://<redacted-bucket>/<redacted-prefix>'
TBLPROPERTIES (
  'table_type'='iceberg',
  'compression_level'='3',
  'format'='PARQUET',
  'write_compression'='ZSTD'
);

CREATE TABLE curated_iceberg.fact_ai_decision_explanations_v1 (
  run_date date,
  entity_key string,
  metric_name string,
  recommended_action string,
  decision_reason string,
  action_priority string,
  created_at timestamp)
LOCATION 's3://<redacted-bucket>/<redacted-prefix>'
TBLPROPERTIES (
  'table_type'='iceberg',
  'compression_level'='3',
  'format'='PARQUET',
  'write_compression'='ZSTD'
);
