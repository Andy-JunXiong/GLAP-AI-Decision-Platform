from datetime import date, timedelta
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "lambda" / "glap_stateful_lifecycle_generator.py"
SPEC = importlib.util.spec_from_file_location("stateful_lifecycle_generator", MODULE_PATH)
generator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generator)

TARGETS = {
    "BOOKING_TO_GATE_IN": 7,
    "GATE_IN_TO_ETD": 1,
    "ATA_TO_DISCHARGED": 3,
    "DISCHARGED_TO_DELIVERED": 4,
}
ROUTES = [
    {
        "route_service_id": "CNSHA-AUSYD-QILIN",
        "origin_port": "CNSHA",
        "destination_port": "AUSYD",
        "carrier": "MAERSK",
        "service_code": "QILIN",
        "service_level": "PREMIUM",
        "p2p_target_days": 14,
        "config_version": "route-2026.08-v1",
    }
]


class StatefulLifecycleGeneratorTests(unittest.TestCase):
    def test_booking_targets_and_p2p_commitments_are_calculated_once(self):
        shipment = generator.create_shipment(date(2026, 8, 4), 1, ROUTES, TARGETS)
        self.assertEqual((shipment["gate_in_target_at"] - shipment["booking_at"]).days, 7)
        self.assertEqual((shipment["etd"] - shipment["gate_in_target_at"]).days, 1)
        self.assertEqual((shipment["eta"] - shipment["etd"]).days, 14)
        self.assertIsNone(shipment["atd"])
        self.assertIsNone(shipment["ata"])

    def test_shipment_progresses_across_dates_without_changing_etd_or_eta(self):
        shipment = generator.create_shipment(date(2026, 8, 4), 1, ROUTES, TARGETS)
        shipment["journey_exception_type"] = None
        shipment["journey_exception_hours"] = 0
        original_etd = shipment["etd"]
        original_eta = shipment["eta"]

        day7, events = generator.advance_shipment(shipment, date(2026, 8, 11), TARGETS)
        self.assertEqual(day7["lifecycle_stage"], "GATE_IN")
        self.assertEqual([event["event_type"] for event in events], ["GATE_IN"])

        day8, events = generator.advance_shipment(day7, date(2026, 8, 12), TARGETS)
        self.assertEqual(day8["lifecycle_stage"], "IN_TRANSIT")
        self.assertEqual(day8["atd"], original_etd)
        self.assertEqual([event["event_type"] for event in events], ["DEPARTED"])

        arrival, events = generator.advance_shipment(day8, original_eta.date(), TARGETS)
        self.assertEqual(arrival["ata"], original_eta)
        self.assertEqual(arrival["discharge_target_at"], original_eta + timedelta(days=3))
        self.assertEqual(arrival["etd"], original_etd)
        self.assertEqual(arrival["eta"], original_eta)

        discharged, _ = generator.advance_shipment(
            arrival, (original_eta + timedelta(days=3)).date(), TARGETS
        )
        self.assertEqual(
            discharged["delivery_target_at"], discharged["discharged_at"] + timedelta(days=4)
        )

    def test_lifecycle_metrics_distinguish_overdue_from_observed_late(self):
        shipment = generator.create_shipment(date(2026, 8, 4), 1, ROUTES, TARGETS)
        shipment["journey_exception_type"] = "ORIGIN_DELAY"
        shipment["journey_exception_hours"] = 48
        overdue, _ = generator.advance_shipment(shipment, shipment["etd"].date(), TARGETS)
        metrics = generator.calculate_lifecycle_metrics(overdue, shipment["etd"].date())
        self.assertEqual(metrics["departure_performance"], "OVERDUE")
        self.assertTrue(metrics["sla_breach_flag"])
        departed, _ = generator.advance_shipment(
            overdue, (shipment["etd"] + timedelta(days=2)).date(), TARGETS
        )
        metrics = generator.calculate_lifecycle_metrics(
            departed, (shipment["etd"] + timedelta(days=2)).date()
        )
        self.assertEqual(metrics["departure_performance"], "LATE")
        self.assertEqual(metrics["departure_delay_hours"], 48)

    def test_signal_candidates_have_stable_grain_and_simulated_provenance(self):
        shipment = generator.create_shipment(date(2026, 8, 4), 1, ROUTES, TARGETS)
        shipment["journey_exception_type"] = "P2P_DELAY"
        shipment["journey_exception_hours"] = 72
        snapshot, _ = generator.advance_shipment(
            shipment, (shipment["eta"] + timedelta(days=3)).date(), TARGETS
        )
        metrics = generator.calculate_lifecycle_metrics(
            snapshot, (shipment["eta"] + timedelta(days=3)).date()
        )
        signals = generator.build_candidate_signals(snapshot, metrics)
        arrival = next(row for row in signals if row["signal_dimension"] == "P2P_ARRIVAL")
        self.assertEqual(arrival["signal_type"], "SLA_BREACH")
        self.assertEqual(arrival["signal_grain"], "SHIPMENT_MILESTONE")
        self.assertEqual(arrival["severity"], "CRITICAL")
        self.assertEqual(arrival["simulation_provenance"], "SIMULATED")
        self.assertEqual(
            arrival["signal_fingerprint"],
            generator.build_candidate_signals(snapshot, metrics)[0]["signal_fingerprint"],
        )

    def test_cost_anomaly_candidate_uses_expected_cost_variance(self):
        shipment = generator.create_shipment(date(2026, 8, 4), 1, ROUTES, TARGETS)
        shipment["expected_total_cost"] = 10000
        shipment["accrued_total_cost"] = 12300
        metrics = generator.calculate_lifecycle_metrics(shipment, date(2026, 8, 4))
        signal = next(
            row for row in generator.build_candidate_signals(shipment, metrics)
            if row["signal_type"] == "COST_ANOMALY"
        )
        self.assertEqual(signal["metric_value"], 23.0)
        self.assertEqual(signal["severity"], "HIGH")

    def test_delivered_shipment_has_final_snapshot_then_stops_active_updates(self):
        shipment = generator.create_shipment(date(2026, 8, 4), 2, ROUTES, TARGETS)
        shipment["journey_exception_type"] = None
        shipment["journey_exception_hours"] = 0
        delivery_date = shipment["eta"].date() + timedelta(days=7)
        final_snapshot, events = generator.advance_shipment(shipment, delivery_date, TARGETS)
        self.assertTrue(final_snapshot["terminal_state"])
        self.assertEqual(final_snapshot["lifecycle_stage"], "DELIVERED")
        self.assertEqual(final_snapshot["lifecycle_status"], "CLOSED")
        self.assertIn("DELIVERED", [event["event_type"] for event in events])
        later_snapshot, later_events = generator.advance_shipment(
            final_snapshot, delivery_date + timedelta(days=1), TARGETS
        )
        self.assertIsNone(later_snapshot)
        self.assertEqual(later_events, [])

    def test_exception_cohort_is_journey_level_and_reproducible(self):
        first = [
            generator.create_shipment(date(2026, 8, 4), index, ROUTES, TARGETS)
            for index in range(1, 1001)
        ]
        second = [
            generator.create_shipment(date(2026, 8, 4), index, ROUTES, TARGETS)
            for index in range(1, 1001)
        ]
        exceptions = [row for row in first if row["journey_exception_type"]]
        self.assertGreaterEqual(len(exceptions), 30)
        self.assertLessEqual(len(exceptions), 70)
        self.assertEqual(
            [(row["journey_exception_type"], row["journey_exception_hours"]) for row in first],
            [(row["journey_exception_type"], row["journey_exception_hours"]) for row in second],
        )

    def test_normal_daily_volume_is_reproducible_and_between_14_and_18(self):
        first = generator.run_day([], date(2026, 8, 4), ROUTES, TARGETS)
        second = generator.run_day([], date(2026, 8, 4), ROUTES, TARGETS)
        self.assertGreaterEqual(first["new_shipments"], 14)
        self.assertLessEqual(first["new_shipments"], 18)
        self.assertEqual(first, second)

    def test_first_run_seeds_representative_active_population(self):
        population = generator.seed_population(
            date(2026, 8, 4), ROUTES, TARGETS, population_size=300
        )
        self.assertEqual(len(population), 300)
        self.assertTrue(all(not row["terminal_state"] for row in population))
        self.assertTrue(all(row["lifecycle_status"] == "OPEN" for row in population))
        stages = {row["lifecycle_stage"] for row in population}
        self.assertTrue({"ORIGIN_PROCESSING", "GATE_IN", "IN_TRANSIT"}.issubset(stages))
        replay = generator.seed_population(
            date(2026, 8, 4), ROUTES, TARGETS, population_size=300
        )
        self.assertEqual(population, replay)

    def test_twenty_eight_day_replay_carries_open_ids_and_closes_delivered(self):
        start = date(2026, 8, 4)
        active = generator.seed_population(start, ROUTES, TARGETS, population_size=300)
        previous_open = {row["shipment_id"] for row in active}
        all_shipments = dict((row["shipment_id"], row) for row in active)
        delivered_yesterday: set[str] = set()
        for offset in range(28):
            day = start + timedelta(days=offset)
            result = generator.run_day(active, day, ROUTES, TARGETS)
            self.assertGreaterEqual(result["new_shipments"], 14)
            self.assertLessEqual(result["new_shipments"], 18)
            self.assertEqual(len(result["metrics"]), len(result["snapshots"]))
            today_ids = {row["shipment_id"] for row in result["snapshots"]}
            self.assertFalse(delivered_yesterday & today_ids)
            if offset:
                self.assertTrue(previous_open & today_ids)
            delivered_yesterday = {
                row["shipment_id"] for row in result["snapshots"]
                if row["lifecycle_status"] == "CLOSED"
            }
            active = result["snapshots"]
            previous_open = {
                row["shipment_id"] for row in active if row["lifecycle_status"] == "OPEN"
            }
            all_shipments.update((row["shipment_id"], row) for row in active)
        exception_rate = 100 * sum(
            bool(row["journey_exception_type"]) for row in all_shipments.values()
        ) / len(all_shipments)
        self.assertGreaterEqual(exception_rate, 3)
        self.assertLessEqual(exception_rate, 7)

    def test_tiered_demurrage_honours_free_days_and_inclusive_tiers(self):
        tiers = [
            {"from_day": 1, "to_day": 3, "daily_rate": 0},
            {"from_day": 4, "to_day": 7, "daily_rate": 180},
            {"from_day": 8, "to_day": 10, "daily_rate": 260},
            {"from_day": 11, "to_day": None, "daily_rate": 380},
        ]
        self.assertEqual(generator.calculate_tiered_charge(3, tiers), 0)
        self.assertEqual(generator.calculate_tiered_charge(7, tiers), 720)
        self.assertEqual(generator.calculate_tiered_charge(9, tiers), 1240)
        self.assertEqual(generator.calculate_tiered_charge(12, tiers), 2260)

    def test_expected_cost_uses_specific_base_rate_surcharges_and_fx(self):
        rates = [
            {"rate_card_id": "global", "origin_port": "*", "destination_port": "*",
             "carrier": "*", "service_code": "*", "equipment_type": "40HC",
             "charge_code": "OCEAN_FREIGHT", "calculation_basis": "PER_CONTAINER",
             "amount": 2100, "percentage_rate": None, "currency": "USD",
             "config_version": "rate-v1", "status": "ACTIVE",
             "effective_from": "2026-07-01", "effective_to": "2026-09-30"},
            {"rate_card_id": "specific", "origin_port": "CNSHA", "destination_port": "AUSYD",
             "carrier": "MAERSK", "service_code": "QILIN", "equipment_type": "40HC",
             "charge_code": "OCEAN_FREIGHT", "calculation_basis": "PER_CONTAINER",
             "amount": 2350, "percentage_rate": None, "currency": "USD",
             "config_version": "rate-v1", "status": "ACTIVE",
             "effective_from": "2026-07-01", "effective_to": "2026-09-30"},
            {"rate_card_id": "baf", "origin_port": "CNSHA", "destination_port": "AUSYD",
             "carrier": "MAERSK", "service_code": "QILIN", "equipment_type": "40HC",
             "charge_code": "BAF", "calculation_basis": "PERCENT_OF_BASE", "amount": 0,
             "percentage_rate": 0.12, "currency": "USD", "config_version": "rate-v1",
             "status": "ACTIVE", "effective_from": "2026-07-01",
             "effective_to": "2026-09-30"},
            {"rate_card_id": "dest", "origin_port": "*", "destination_port": "*",
             "carrier": "*", "service_code": "*", "equipment_type": "40HC",
             "charge_code": "DESTINATION_THC", "calculation_basis": "PER_CONTAINER",
             "amount": 610, "percentage_rate": None, "currency": "AUD",
             "config_version": "rate-v1", "status": "ACTIVE"},
        ]
        shipment = generator.create_shipment(
            date(2026, 8, 4), 1, ROUTES, TARGETS, rate_cards=rates,
            fx_rates={("USD", "AUD"): 1.52, ("AUD", "AUD"): 1.0},
        )
        containers = shipment["container_count"]
        expected = ((2350 * containers) + (2350 * containers * 0.12)) * 1.52 + 610 * containers
        self.assertEqual(shipment["expected_total_cost"], round(expected, 2))
        self.assertEqual(
            next(line for line in shipment["expected_cost_lines"]
                 if line["charge_code"] == "OCEAN_FREIGHT")["rate_card_id"],
            "specific",
        )
        self.assertEqual(shipment["rate_locked_at"], shipment["booking_at"])

    def test_booking_in_q1_keeps_q1_rate_when_etd_is_in_q2(self):
        long_origin_targets = dict(TARGETS, BOOKING_TO_GATE_IN=7, GATE_IN_TO_ETD=1)
        rates = [
            {"rate_card_id": "q1", "origin_port": "*", "destination_port": "*",
             "carrier": "*", "service_code": "*", "equipment_type": "40HC",
             "charge_code": "OCEAN_FREIGHT", "calculation_basis": "PER_CONTAINER",
             "amount": 3000, "currency": "USD", "config_version": "2026-Q1-v1",
             "effective_from": "2026-01-01", "effective_to": "2026-03-31",
             "status": "ACTIVE"},
            {"rate_card_id": "q2", "origin_port": "*", "destination_port": "*",
             "carrier": "*", "service_code": "*", "equipment_type": "40HC",
             "charge_code": "OCEAN_FREIGHT", "calculation_basis": "PER_CONTAINER",
             "amount": 4500, "currency": "USD", "config_version": "2026-Q2-v1",
             "effective_from": "2026-04-01", "effective_to": "2026-06-30",
             "status": "ACTIVE"},
        ]
        shipment = generator.create_shipment(
            date(2026, 3, 25), 1, ROUTES, long_origin_targets,
            rate_cards=rates, fx_rates={("USD", "AUD"): 1.5},
        )
        self.assertEqual(shipment["etd"].date(), date(2026, 4, 2))
        self.assertEqual(shipment["rate_card_version"], "2026-Q1-v1")
        self.assertEqual(
            shipment["expected_total_cost"], 3000 * shipment["container_count"] * 1.5
        )

    def test_expected_cost_fails_closed_without_fx(self):
        shipment = generator.create_shipment(date(2026, 8, 4), 1, ROUTES, TARGETS)
        with self.assertRaisesRegex(ValueError, "Missing FX rate"):
            generator.calculate_expected_cost(
                shipment,
                [{"rate_card_id": "ocean", "origin_port": "*", "destination_port": "*",
                  "carrier": "*", "service_code": "*", "equipment_type": "40HC",
                  "charge_code": "OCEAN_FREIGHT", "calculation_basis": "PER_CONTAINER",
                  "amount": 2100, "currency": "USD", "config_version": "rate-v1",
                  "status": "ACTIVE"}],
                {},
            )

    def test_invalid_or_duplicate_contracts_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Missing lifecycle targets"):
            generator.create_shipment(date(2026, 8, 4), 1, ROUTES, {})
        with self.assertRaisesRegex(ValueError, "Duplicate route_service_id"):
            generator.create_shipment(date(2026, 8, 4), 1, ROUTES * 2, TARGETS)
        with self.assertRaisesRegex(ValueError, "continuous"):
            generator.calculate_tiered_charge(
                5,
                [
                    {"from_day": 1, "to_day": 3, "daily_rate": 0},
                    {"from_day": 5, "to_day": None, "daily_rate": 100},
                ],
            )

    def test_lambda_response_excludes_private_rows_by_default(self):
        response = generator.lambda_handler(
            {
                "logical_run_date": "2026-08-04",
                "routes": ROUTES,
                "targets": TARGETS,
                "new_count": 1,
            },
            None,
        )
        self.assertEqual(response["status"], "success")
        self.assertNotIn("snapshots", response)
        self.assertNotIn("events", response)


if __name__ == "__main__":
    unittest.main()
