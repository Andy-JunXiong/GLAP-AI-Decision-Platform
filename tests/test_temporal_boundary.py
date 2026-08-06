from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "lambda" / "glap_temporal_boundary.py"
SPEC = importlib.util.spec_from_file_location("glap_temporal_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(boundary)


NOW = datetime(2026, 8, 6, 2, tzinfo=timezone.utc)


class TemporalBoundaryTests(unittest.TestCase):
    def test_operational_mode_accepts_today_and_rejects_future(self):
        context = boundary.resolve_temporal_context(
            "2026-08-06", {}, now=NOW, allow_future_simulation=False
        )
        self.assertEqual(context["execution_mode"], "OPERATIONAL")
        self.assertEqual(context["time_basis"], "ACTUAL_CALENDAR")
        self.assertEqual(context["as_of_date"], "2026-08-06")
        self.assertIsNone(context["scenario_id"])

        with self.assertRaisesRegex(ValueError, "exceeds Sydney as_of_date"):
            boundary.resolve_temporal_context(
                "2026-09-01", {}, now=NOW, allow_future_simulation=False
            )

    def test_future_simulation_requires_enabled_staging_and_scenario(self):
        event = {
            "execution_mode": "FUTURE_SIMULATION",
            "scenario_id": "q4-lifecycle-2026",
        }
        with self.assertRaisesRegex(ValueError, "explicitly enabled staging"):
            boundary.resolve_temporal_context(
                "2026-10-05", event, now=NOW, allow_future_simulation=False,
                environment="staging",
            )
        with self.assertRaisesRegex(ValueError, "explicitly enabled staging"):
            boundary.resolve_temporal_context(
                "2026-10-05", event, now=NOW, allow_future_simulation=True,
                environment="production",
            )

        context = boundary.resolve_temporal_context(
            "2026-10-05", event, now=NOW, allow_future_simulation=True,
            environment="staging",
        )
        self.assertEqual(context["time_basis"], "FUTURE_SIMULATION")
        self.assertEqual(context["scenario_id"], "q4-lifecycle-2026")
        self.assertEqual(context["as_of_date"], "2026-08-06")

    def test_rejects_forged_metadata(self):
        with self.assertRaisesRegex(ValueError, "system-derived"):
            boundary.resolve_temporal_context(
                "2026-08-06", {"as_of_date": "2026-10-05"}, now=NOW
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            boundary.resolve_temporal_context(
                "2026-08-06", {"time_basis": "FUTURE_SIMULATION"}, now=NOW
            )
        with self.assertRaisesRegex(ValueError, "safe scenario_id"):
            boundary.resolve_temporal_context(
                "2026-10-05",
                {"execution_mode": "FUTURE_SIMULATION", "scenario_id": "x"},
                now=NOW,
                allow_future_simulation=True,
                environment="staging",
            )

    def test_sydney_date_fallback_respects_standard_and_daylight_time(self):
        with patch.object(
            boundary, "ZoneInfo", side_effect=boundary.ZoneInfoNotFoundError
        ):
            standard = boundary.sydney_business_date(
                datetime(2026, 8, 5, 14, 30, tzinfo=timezone.utc)
            )
            daylight = boundary.sydney_business_date(
                datetime(2026, 12, 5, 13, 30, tzinfo=timezone.utc)
            )
        self.assertEqual(standard.isoformat(), "2026-08-06")
        self.assertEqual(daylight.isoformat(), "2026-12-06")


if __name__ == "__main__":
    unittest.main()
