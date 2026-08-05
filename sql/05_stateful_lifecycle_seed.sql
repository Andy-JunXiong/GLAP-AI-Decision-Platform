-- Initial GLAP lifecycle, route and synthetic rate configuration.
-- Replace {{SOURCE_DATABASE}} before execution. Values are simulation inputs,
-- not live carrier quotes or customer tariffs.

INSERT INTO {{SOURCE_DATABASE}}.dim_lifecycle_target_v1
(target_id, stage_code, origin_port, destination_port, target_days, tolerance_hours,
 effective_from, effective_to, status, config_version, updated_at) VALUES
('GLOBAL-BOOK-GATE', 'BOOKING_TO_GATE_IN', '*', '*', 7, 24, DATE '2026-07-01', NULL, 'ACTIVE', 'lifecycle-2026-Q3-v1', current_timestamp),
('GLOBAL-GATE-ETD', 'GATE_IN_TO_ETD', '*', '*', 1, 12, DATE '2026-07-01', NULL, 'ACTIVE', 'lifecycle-2026-Q3-v1', current_timestamp),
('GLOBAL-ATA-DISCHARGE', 'ATA_TO_DISCHARGED', '*', '*', 3, 24, DATE '2026-07-01', NULL, 'ACTIVE', 'lifecycle-2026-Q3-v1', current_timestamp),
('GLOBAL-DISCHARGE-DELIVERY', 'DISCHARGED_TO_DELIVERED', '*', '*', 4, 24, DATE '2026-07-01', NULL, 'ACTIVE', 'lifecycle-2026-Q3-v1', current_timestamp);

INSERT INTO {{SOURCE_DATABASE}}.dim_route_service_v1
(route_service_id, origin_port, destination_port, carrier, service_code,
 service_level, p2p_target_days, departure_weekday, frequency_days, source_type,
 source_reference, effective_from, effective_to, status, config_version, updated_at) VALUES
('CNSHA-AUSYD-QILIN', 'CNSHA', 'AUSYD', 'MAERSK', 'QILIN', 'PREMIUM', 14, 5, 7, 'CARRIER_SCHEDULE', 'MAERSK_QILIN_2026_07', DATE '2026-07-24', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('CNSHA-AUSYD-DRAGON', 'CNSHA', 'AUSYD', 'MAERSK', 'DRAGON', 'STANDARD', 17, 3, 7, 'CARRIER_SCHEDULE', 'MAERSK_DRAGON_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('CNSHA-AUMEL-QILIN', 'CNSHA', 'AUMEL', 'MAERSK', 'QILIN', 'PREMIUM', 17, 5, 7, 'CARRIER_SCHEDULE', 'MAERSK_QILIN_2026_07', DATE '2026-07-24', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('CNSHA-AUMEL-DRAGON', 'CNSHA', 'AUMEL', 'MAERSK', 'DRAGON', 'STANDARD', 21, 3, 7, 'CARRIER_SCHEDULE', 'MAERSK_DRAGON_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('CNSHA-AUBNE-DRAGON', 'CNSHA', 'AUBNE', 'MAERSK', 'DRAGON', 'STANDARD', 26, 3, 7, 'CARRIER_SCHEDULE', 'MAERSK_DRAGON_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('CNNGB-AUSYD-DRAGON', 'CNNGB', 'AUSYD', 'MAERSK', 'DRAGON', 'STANDARD', 20, 1, 7, 'CARRIER_SCHEDULE', 'MAERSK_DRAGON_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('CNNGB-AUMEL-DRAGON', 'CNNGB', 'AUMEL', 'MAERSK', 'DRAGON', 'STANDARD', 24, 1, 7, 'CARRIER_SCHEDULE', 'MAERSK_DRAGON_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('CNNGB-AUBNE-DRAGON', 'CNNGB', 'AUBNE', 'MAERSK', 'DRAGON', 'STANDARD', 29, 1, 7, 'CARRIER_SCHEDULE', 'MAERSK_DRAGON_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('SGSIN-AUMEL-GAC080', 'SGSIN', 'AUMEL', 'MAERSK', 'GAC080', 'STANDARD', 15, 4, 7, 'CARRIER_SCHEDULE', 'MAERSK_GAC080_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('SGSIN-AUSYD-GAC080', 'SGSIN', 'AUSYD', 'MAERSK', 'GAC080', 'STANDARD', 20, 4, 7, 'CARRIER_SCHEDULE', 'MAERSK_GAC080_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('SGSIN-AUBNE-SYNTH', 'SGSIN', 'AUBNE', 'MAERSK', 'REGIONAL', 'STANDARD', 18, 4, 7, 'CALIBRATED_ASSUMPTION', 'GLAP_ROUTE_BASELINE_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('KRPUS-AUBNE-JSTAR', 'KRPUS', 'AUBNE', 'MAERSK', 'JSTAR', 'STANDARD', 20, 2, 7, 'CARRIER_SCHEDULE', 'MAERSK_JSTAR_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('KRPUS-AUSYD-SYNTH', 'KRPUS', 'AUSYD', 'MAERSK', 'REGIONAL', 'STANDARD', 22, 2, 7, 'CALIBRATED_ASSUMPTION', 'GLAP_ROUTE_BASELINE_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp),
('KRPUS-AUMEL-SYNTH', 'KRPUS', 'AUMEL', 'MAERSK', 'REGIONAL', 'STANDARD', 25, 2, 7, 'CALIBRATED_ASSUMPTION', 'GLAP_ROUTE_BASELINE_2026_08', DATE '2026-07-01', NULL, 'ACTIVE', 'route-2026.08-v1', current_timestamp);

-- Stable synthetic contract rates in USD. Market indices remain separate.
INSERT INTO {{SOURCE_DATABASE}}.dim_rate_card_v1
(rate_card_id, rate_type, origin_port, destination_port, carrier, service_code,
 equipment_type, charge_code, calculation_basis, amount, percentage_rate, currency,
 effective_from, effective_to, status, rate_source, config_version, updated_at) VALUES
('RC-GLOBAL-OCEAN-40HC', 'CONTRACT', '*', '*', '*', '*', '40HC', 'OCEAN_FREIGHT', 'PER_CONTAINER', 3900, NULL, 'USD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'SYNTHETIC_MARKET_CALIBRATED', 'rate-2026-Q3-v1', current_timestamp),
('RC-CNSHA-AUSYD-QILIN-40HC', 'CONTRACT', 'CNSHA', 'AUSYD', 'MAERSK', 'QILIN', '40HC', 'OCEAN_FREIGHT', 'PER_CONTAINER', 4600, NULL, 'USD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'SYNTHETIC_MARKET_CALIBRATED', 'rate-2026-Q3-v1', current_timestamp),
('RC-CNSHA-AUSYD-QILIN-BAF', 'CONTRACT', 'CNSHA', 'AUSYD', 'MAERSK', 'QILIN', '40HC', 'BAF', 'PERCENT_OF_BASE', 0, 0.12, 'USD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'SYNTHETIC_MARKET_CALIBRATED', 'rate-2026-Q3-v1', current_timestamp),
('RC-GLOBAL-ORIGIN-THC-40HC', 'CONTRACT', '*', '*', '*', '*', '40HC', 'ORIGIN_THC', 'PER_CONTAINER', 420, NULL, 'AUD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'SYNTHETIC_MARKET_CALIBRATED', 'rate-2026-Q3-v1', current_timestamp),
('RC-GLOBAL-DEST-THC-40HC', 'CONTRACT', '*', '*', '*', '*', '40HC', 'DESTINATION_THC', 'PER_CONTAINER', 610, NULL, 'AUD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'SYNTHETIC_MARKET_CALIBRATED', 'rate-2026-Q3-v1', current_timestamp),
('RC-GLOBAL-DEST-HAUL-40HC', 'CONTRACT', '*', '*', '*', '*', '40HC', 'DESTINATION_HAULAGE', 'PER_CONTAINER', 780, NULL, 'AUD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'SYNTHETIC_MARKET_CALIBRATED', 'rate-2026-Q3-v1', current_timestamp);

INSERT INTO {{SOURCE_DATABASE}}.dim_rate_tier_v1
(rate_tier_id, port_code, carrier, equipment_type, charge_code, from_day, to_day,
 daily_rate, currency, effective_from, effective_to, status, config_version, updated_at) VALUES
('AUSYD-DEM-40HC-01', 'AUSYD', '*', '40HC', 'DEMURRAGE', 1, 3, 0, 'AUD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'rate-2026-Q3-v1', current_timestamp),
('AUSYD-DEM-40HC-02', 'AUSYD', '*', '40HC', 'DEMURRAGE', 4, 7, 180, 'AUD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'rate-2026-Q3-v1', current_timestamp),
('AUSYD-DEM-40HC-03', 'AUSYD', '*', '40HC', 'DEMURRAGE', 8, 10, 260, 'AUD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'rate-2026-Q3-v1', current_timestamp),
('AUSYD-DEM-40HC-04', 'AUSYD', '*', '40HC', 'DEMURRAGE', 11, NULL, 380, 'AUD', DATE '2026-07-01', DATE '2026-09-30', 'ACTIVE', 'rate-2026-Q3-v1', current_timestamp);

INSERT INTO {{SOURCE_DATABASE}}.dim_fx_rate_v1
(base_currency, quote_currency, fx_rate, effective_date, source_type, config_version,
 updated_at) VALUES
('USD', 'AUD', 1.52, DATE '2026-07-01', 'SYNTHETIC_REFERENCE_RATE', 'fx-2026-Q3-v1', current_timestamp),
('AUD', 'AUD', 1.00, DATE '2026-07-01', 'IDENTITY', 'fx-2026-Q3-v1', current_timestamp);
