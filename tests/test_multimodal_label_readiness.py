from datetime import date
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "assess_multimodal_label_readiness.py"
SPEC = importlib.util.spec_from_file_location("assess_multimodal_label_readiness", MODULE_PATH)
readiness = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)


def summary(**overrides):
    values = {
        "transport_mode": "AIR",
        "provider_code": "DHL",
        "source_latest_date": date(2026, 9, 7),
        "cohort_shipments": 300,
        "pending_label_count": 50,
        "observed_label_count": 250,
        "sla_positive_count": 30,
        "sla_negative_count": 220,
        "delay_positive_count": 40,
        "delay_negative_count": 210,
        "cost_label_count": 250,
        "cost_variance_distinct_count": 100,
    }
    values.update(overrides)
    return readiness.LabelSummary(**values)


class MultimodalLabelReadinessTests(unittest.TestCase):
    def test_sufficient_observed_labels_permit_each_target(self):
        report = readiness.build_report([summary()], cutoff_date=date(2026, 9, 7))
        self.assertEqual(report["status"], "ready")
        self.assertTrue(all(
            target["training_permitted"]
            for target in report["groups"][0]["targets"].values()
        ))
        self.assertEqual(report["pending_label_policy"], "EXCLUDE_FROM_ALL_TRAINING")

    def test_pending_and_rare_classes_block_training(self):
        row = summary(
            cohort_shipments=50,
            pending_label_count=40,
            observed_label_count=10,
            sla_positive_count=1,
            sla_negative_count=9,
            delay_positive_count=0,
            delay_negative_count=10,
            cost_label_count=10,
            cost_variance_distinct_count=2,
        )
        report = readiness.build_report([row], cutoff_date=date(2026, 9, 7))
        self.assertEqual(report["status"], "blocked_insufficient_observed_labels")
        self.assertIn(
            "MIN_POSITIVE_LABELS",
            report["groups"][0]["targets"]["sla_breach"]["blockers"],
        )

    def test_loader_fails_when_pending_and_observed_do_not_reconcile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            path.write_text(
                ",".join(sorted(readiness.REQUIRED_COLUMNS)) + "\n" +
                "300,250,100,210,40,250,40,DHL,220,30,2026-09-07,AIR\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "reconcile"):
                readiness.load_summaries(path, expected_cutoff_date=date(2026, 9, 7))

    def test_loader_rejects_historical_cutoff_against_latest_view(self):
        fields = [
            "transport_mode", "provider_code", "source_latest_date", "cohort_shipments",
            "pending_label_count", "observed_label_count", "sla_positive_count",
            "sla_negative_count", "delay_positive_count", "delay_negative_count",
            "cost_label_count", "cost_variance_distinct_count",
        ]
        values = ["AIR", "DHL", "2026-09-08", "300", "50", "250", "30", "220",
                  "40", "210", "250", "100"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            path.write_text(",".join(fields) + "\n" + ",".join(values) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "latest available"):
                readiness.load_summaries(path, expected_cutoff_date=date(2026, 9, 7))


if __name__ == "__main__":
    unittest.main()
