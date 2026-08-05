-- Idempotent multimodal configuration evolution for isolated lifecycle staging.
-- DHL is a simulated AIR provider at 3/17 of new bookings (17.65%).
-- Maersk and KN are simulated OCEAN providers at 7/17 each (41.18%).
-- Values are test profiles, not live schedules, quotes or provider performance.

UPDATE {{SOURCE_DATABASE}}.dim_lifecycle_target_v1
SET transport_mode = 'OCEAN', target_hours = target_days * 24
WHERE transport_mode IS NULL;

UPDATE {{SOURCE_DATABASE}}.dim_route_service_v1
SET transport_mode = 'OCEAN',
    provider_type = IF(carrier = 'MAERSK', 'OCEAN_CARRIER', 'LOGISTICS_PROVIDER'),
    operating_carrier = carrier,
    origin_location_type = 'PORT',
    destination_location_type = 'PORT',
    p2p_target_hours = p2p_target_days * 24,
    equipment_type = '40HC'
WHERE transport_mode IS NULL;

UPDATE {{SOURCE_DATABASE}}.dim_rate_card_v1
SET transport_mode = 'OCEAN'
WHERE transport_mode IS NULL;

MERGE INTO {{SOURCE_DATABASE}}.dim_provider_v1 AS target
USING (VALUES
    ('MAERSK', 'Maersk', 'OCEAN_CARRIER', 'OCEAN', 'ACTIVE', 'provider-2026.09-v1'),
    ('KN', 'Kuehne+Nagel', 'LOGISTICS_PROVIDER', 'OCEAN', 'ACTIVE', 'provider-2026.09-v1'),
    ('DHL', 'DHL', 'LOGISTICS_PROVIDER', 'AIR', 'ACTIVE', 'provider-2026.09-v1')
) AS source (provider_code, provider_name, provider_type, supported_mode, status, config_version)
ON target.provider_code = source.provider_code AND target.config_version = source.config_version
WHEN MATCHED THEN UPDATE SET
    provider_name = source.provider_name,
    provider_type = source.provider_type,
    supported_mode = source.supported_mode,
    status = source.status,
    updated_at = current_timestamp
WHEN NOT MATCHED THEN INSERT
    (provider_code, provider_name, provider_type, supported_mode, status, config_version, updated_at)
VALUES
    (source.provider_code, source.provider_name, source.provider_type,
     source.supported_mode, source.status, source.config_version, current_timestamp);

MERGE INTO {{SOURCE_DATABASE}}.dim_lifecycle_target_v1 AS target
USING (VALUES
    ('AIR-BOOK-ORIGIN', 'BOOKING_TO_ORIGIN_HANDOVER', '*', '*', 1, 6, 'AIR', 24),
    ('AIR-ORIGIN-DEPARTURE', 'ORIGIN_HANDOVER_TO_DEPARTURE', '*', '*', 1, 6, 'AIR', 12),
    ('AIR-ARRIVAL-RELEASE', 'ARRIVAL_TO_DESTINATION_RELEASE', '*', '*', 1, 6, 'AIR', 12),
    ('AIR-RELEASE-DELIVERY', 'DESTINATION_RELEASE_TO_DELIVERY', '*', '*', 1, 12, 'AIR', 24)
) AS source
    (target_id, stage_code, origin_port, destination_port, target_days,
     tolerance_hours, transport_mode, target_hours)
ON target.target_id = source.target_id AND target.config_version = 'lifecycle-2026.09-multimodal-v1'
WHEN MATCHED THEN UPDATE SET
    target_days = source.target_days,
    tolerance_hours = source.tolerance_hours,
    transport_mode = source.transport_mode,
    target_hours = source.target_hours,
    status = 'ACTIVE',
    updated_at = current_timestamp
WHEN NOT MATCHED THEN INSERT
    (target_id, stage_code, origin_port, destination_port, target_days,
     tolerance_hours, effective_from, effective_to, status, config_version,
     updated_at, transport_mode, target_hours)
VALUES
    (source.target_id, source.stage_code, source.origin_port, source.destination_port,
     source.target_days, source.tolerance_hours, DATE '2026-09-02', NULL, 'ACTIVE',
     'lifecycle-2026.09-multimodal-v1', current_timestamp, source.transport_mode,
     source.target_hours);

MERGE INTO {{SOURCE_DATABASE}}.dim_route_service_v1 AS target
USING (VALUES
    ('KN-CNSHA-AUSYD', 'CNSHA', 'AUSYD', 'KN', 17, 408),
    ('KN-CNSHA-AUMEL', 'CNSHA', 'AUMEL', 'KN', 21, 504),
    ('KN-CNSHA-AUBNE', 'CNSHA', 'AUBNE', 'KN', 26, 624),
    ('KN-CNNGB-AUSYD', 'CNNGB', 'AUSYD', 'KN', 20, 480),
    ('KN-CNNGB-AUMEL', 'CNNGB', 'AUMEL', 'KN', 24, 576),
    ('KN-CNNGB-AUBNE', 'CNNGB', 'AUBNE', 'KN', 29, 696),
    ('KN-SGSIN-AUSYD', 'SGSIN', 'AUSYD', 'KN', 20, 480),
    ('KN-SGSIN-AUMEL', 'SGSIN', 'AUMEL', 'KN', 15, 360),
    ('KN-SGSIN-AUBNE', 'SGSIN', 'AUBNE', 'KN', 18, 432),
    ('KN-KRPUS-AUSYD', 'KRPUS', 'AUSYD', 'KN', 22, 528),
    ('KN-KRPUS-AUMEL', 'KRPUS', 'AUMEL', 'KN', 25, 600),
    ('KN-KRPUS-AUBNE', 'KRPUS', 'AUBNE', 'KN', 20, 480),
    ('DHL-PVG-SYD', 'PVG', 'SYD', 'DHL', 1, 18),
    ('DHL-PVG-MEL', 'PVG', 'MEL', 'DHL', 1, 20),
    ('DHL-PVG-BNE', 'PVG', 'BNE', 'DHL', 1, 22),
    ('DHL-NGB-SYD', 'NGB', 'SYD', 'DHL', 1, 22),
    ('DHL-NGB-MEL', 'NGB', 'MEL', 'DHL', 1, 24),
    ('DHL-NGB-BNE', 'NGB', 'BNE', 'DHL', 2, 26),
    ('DHL-SIN-SYD', 'SIN', 'SYD', 'DHL', 1, 10),
    ('DHL-SIN-MEL', 'SIN', 'MEL', 'DHL', 1, 11),
    ('DHL-SIN-BNE', 'SIN', 'BNE', 'DHL', 1, 12),
    ('DHL-PUS-SYD', 'PUS', 'SYD', 'DHL', 1, 16),
    ('DHL-PUS-MEL', 'PUS', 'MEL', 'DHL', 1, 18),
    ('DHL-PUS-BNE', 'PUS', 'BNE', 'DHL', 1, 20)
) AS source
    (route_service_id, origin_port, destination_port, carrier,
     p2p_target_days, p2p_target_hours)
ON target.route_service_id = source.route_service_id
   AND target.config_version = 'route-2026.09-multimodal-v1'
WHEN MATCHED THEN UPDATE SET
    p2p_target_days = source.p2p_target_days,
    p2p_target_hours = source.p2p_target_hours,
    status = 'ACTIVE',
    updated_at = current_timestamp
WHEN NOT MATCHED THEN INSERT
    (route_service_id, origin_port, destination_port, carrier, service_code,
     service_level, p2p_target_days, departure_weekday, frequency_days,
     source_type, source_reference, effective_from, effective_to, status,
     config_version, updated_at, transport_mode, provider_type,
     operating_carrier, origin_location_type, destination_location_type,
     p2p_target_hours, equipment_type)
VALUES
    (source.route_service_id, source.origin_port, source.destination_port,
     source.carrier,
     IF(source.carrier = 'DHL', 'DHL-AIR-STANDARD', 'KN-OCEAN-STANDARD'),
     'STANDARD', source.p2p_target_days, 1, 1,
     'SIMULATED_PROVIDER_PROFILE', 'GLAP_MULTIMODAL_BASELINE_2026_09',
     DATE '2026-09-02', NULL, 'ACTIVE', 'route-2026.09-multimodal-v1',
     current_timestamp, IF(source.carrier = 'DHL', 'AIR', 'OCEAN'),
     'LOGISTICS_PROVIDER',
     IF(source.carrier = 'DHL', 'SIMULATED_AIRLINE', 'SIMULATED_OCEAN_OPERATOR'),
     IF(source.carrier = 'DHL', 'AIRPORT', 'PORT'),
     IF(source.carrier = 'DHL', 'AIRPORT', 'PORT'),
     source.p2p_target_hours, IF(source.carrier = 'DHL', 'AIR_CARGO', '40HC'));

MERGE INTO {{SOURCE_DATABASE}}.dim_rate_card_v1 AS target
USING (VALUES
    ('RC-KN-OCEAN-40HC', 'OCEAN', 'KN', '40HC', 'OCEAN_FREIGHT', 'PER_CONTAINER', 4050.0, NULL, 'USD'),
    ('RC-KN-ORIGIN-THC', 'OCEAN', 'KN', '40HC', 'ORIGIN_THC', 'PER_CONTAINER', 420.0, NULL, 'AUD'),
    ('RC-KN-DEST-THC', 'OCEAN', 'KN', '40HC', 'DESTINATION_THC', 'PER_CONTAINER', 610.0, NULL, 'AUD'),
    ('RC-KN-DEST-HAUL', 'OCEAN', 'KN', '40HC', 'DESTINATION_HAULAGE', 'PER_CONTAINER', 780.0, NULL, 'AUD'),
    ('RC-DHL-AIR-KG', 'AIR', 'DHL', 'AIR_CARGO', 'AIR_FREIGHT', 'PER_CHARGEABLE_KG', 7.25, NULL, 'USD'),
    ('RC-DHL-AIR-FUEL', 'AIR', 'DHL', 'AIR_CARGO', 'AIR_FUEL_SURCHARGE', 'PERCENT_OF_BASE', 0.0, 0.18, 'USD'),
    ('RC-DHL-AIR-ORIGIN', 'AIR', 'DHL', 'AIR_CARGO', 'ORIGIN_HANDLING', 'PER_SHIPMENT', 180.0, NULL, 'AUD'),
    ('RC-DHL-AIR-SECURITY', 'AIR', 'DHL', 'AIR_CARGO', 'SECURITY_SCREENING', 'PER_SHIPMENT', 95.0, NULL, 'AUD'),
    ('RC-DHL-AIR-DEST', 'AIR', 'DHL', 'AIR_CARGO', 'DESTINATION_HANDLING', 'PER_SHIPMENT', 260.0, NULL, 'AUD')
) AS source
    (rate_card_id, transport_mode, carrier, equipment_type, charge_code,
     calculation_basis, amount, percentage_rate, currency)
ON target.rate_card_id = source.rate_card_id
   AND target.config_version = 'rate-2026-Q3-multimodal-v1'
WHEN MATCHED THEN UPDATE SET
    amount = source.amount,
    percentage_rate = source.percentage_rate,
    status = 'ACTIVE',
    updated_at = current_timestamp,
    transport_mode = source.transport_mode
WHEN NOT MATCHED THEN INSERT
    (rate_card_id, rate_type, origin_port, destination_port, carrier,
     service_code, equipment_type, charge_code, calculation_basis, amount,
     percentage_rate, currency, effective_from, effective_to, status,
     rate_source, config_version, updated_at, transport_mode)
VALUES
    (source.rate_card_id, 'CONTRACT', '*', '*', source.carrier, '*',
     source.equipment_type, source.charge_code, source.calculation_basis,
     source.amount, source.percentage_rate, source.currency, DATE '2026-09-02',
     DATE '2026-09-30', 'ACTIVE', 'SIMULATED_PROVIDER_PROFILE',
     'rate-2026-Q3-multimodal-v1', current_timestamp, source.transport_mode);
