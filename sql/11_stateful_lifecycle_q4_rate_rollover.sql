-- Isolated staging-only Q4 simulation configuration.
-- Carries the Q3 test rates forward without changing any historical row.
-- Values are synthetic decision-platform inputs, not live quotes or tariffs.

MERGE INTO {{SOURCE_DATABASE}}.dim_rate_card_v1 AS target
USING (
    SELECT rate_card_id, rate_type, origin_port, destination_port, carrier,
           service_code, equipment_type, charge_code, calculation_basis,
           amount, percentage_rate, currency, DATE '2026-10-01' AS effective_from,
           DATE '2026-12-31' AS effective_to, 'ACTIVE' AS status,
           'SIMULATED_Q3_ROLLOVER' AS rate_source,
           'rate-2026-Q4-simulated-rollover-v1' AS config_version,
           transport_mode
    FROM {{SOURCE_DATABASE}}.dim_rate_card_v1
    WHERE status = 'ACTIVE'
      AND effective_to = DATE '2026-09-30'
      AND config_version IN (
          'rate-2026-Q3-v1',
          'rate-2026-Q3-multimodal-v1'
      )
) AS source
ON target.rate_card_id = source.rate_card_id
   AND target.config_version = source.config_version
WHEN NOT MATCHED THEN INSERT
    (rate_card_id, rate_type, origin_port, destination_port, carrier,
     service_code, equipment_type, charge_code, calculation_basis, amount,
     percentage_rate, currency, effective_from, effective_to, status,
     rate_source, config_version, updated_at, transport_mode)
VALUES
    (source.rate_card_id, source.rate_type, source.origin_port,
     source.destination_port, source.carrier, source.service_code,
     source.equipment_type, source.charge_code, source.calculation_basis,
     source.amount, source.percentage_rate, source.currency,
     source.effective_from, source.effective_to, source.status,
     source.rate_source, source.config_version, current_timestamp,
     source.transport_mode);

MERGE INTO {{SOURCE_DATABASE}}.dim_rate_tier_v1 AS target
USING (
    SELECT rate_tier_id, port_code, carrier, equipment_type, charge_code,
           from_day, to_day, daily_rate, currency,
           DATE '2026-10-01' AS effective_from,
           DATE '2026-12-31' AS effective_to, 'ACTIVE' AS status,
           'rate-2026-Q4-simulated-rollover-v1' AS config_version
    FROM {{SOURCE_DATABASE}}.dim_rate_tier_v1
    WHERE status = 'ACTIVE'
      AND effective_to = DATE '2026-09-30'
      AND config_version = 'rate-2026-Q3-v1'
) AS source
ON target.rate_tier_id = source.rate_tier_id
   AND target.config_version = source.config_version
WHEN NOT MATCHED THEN INSERT
    (rate_tier_id, port_code, carrier, equipment_type, charge_code, from_day,
     to_day, daily_rate, currency, effective_from, effective_to, status,
     config_version, updated_at)
VALUES
    (source.rate_tier_id, source.port_code, source.carrier,
     source.equipment_type, source.charge_code, source.from_day,
     source.to_day, source.daily_rate, source.currency,
     source.effective_from, source.effective_to, source.status,
     source.config_version, current_timestamp);

MERGE INTO {{SOURCE_DATABASE}}.dim_fx_rate_v1 AS target
USING (
    SELECT base_currency, quote_currency, fx_rate,
           DATE '2026-10-01' AS effective_date,
           'SIMULATED_Q3_ROLLOVER' AS source_type,
           'fx-2026-Q4-simulated-rollover-v1' AS config_version
    FROM {{SOURCE_DATABASE}}.dim_fx_rate_v1
    WHERE config_version = 'fx-2026-Q3-v1'
) AS source
ON target.base_currency = source.base_currency
   AND target.quote_currency = source.quote_currency
   AND target.config_version = source.config_version
WHEN NOT MATCHED THEN INSERT
    (base_currency, quote_currency, fx_rate, effective_date, source_type,
     config_version, updated_at)
VALUES
    (source.base_currency, source.quote_currency, source.fx_rate,
     source.effective_date, source.source_type, source.config_version,
     current_timestamp);
