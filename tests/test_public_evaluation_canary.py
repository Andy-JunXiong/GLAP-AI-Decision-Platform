import copy
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "canary_public_evaluation",
    ROOT / "ops" / "canary_public_evaluation.py",
)
CANARY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CANARY
SPEC.loader.exec_module(CANARY)


class PublicEvaluationCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = CANARY.PAGE_PATH.read_bytes()
        cls.snapshot = json.loads(CANARY.SNAPSHOT_PATH.read_text(encoding="utf-8"))

    def fetcher(self, page=None, snapshot=None):
        page_body = self.page if page is None else page
        snapshot_body = (
            json.dumps(self.snapshot).encode("utf-8")
            if snapshot is None
            else json.dumps(snapshot).encode("utf-8")
        )

        def fetch(url, _timeout):
            path = urlsplit(url).path
            if path.endswith("/data/evaluation-snapshot.json"):
                return snapshot_body
            return page_body

        return fetch

    def test_canary_reconciles_live_snapshot_loader_and_all_false_authority(self):
        report = CANARY.run_canary(
            "https://example.test/glap/",
            today=date(2026, 8, 25),
            cache_bust="commit-123",
            fetcher=self.fetcher(),
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["mode"], "READ_ONLY")
        self.assertTrue(all(report["checks"].values()))
        self.assertTrue(all(value is False for value in report["authority"].values()))
        self.assertEqual(report["aggregate"]["locked_review_record_count"], 150)

    def test_canary_fails_when_live_snapshot_does_not_match_source(self):
        changed = copy.deepcopy(self.snapshot)
        changed["corpus"]["locked_review_record_count"] = 149
        with self.assertRaisesRegex(ValueError, "governed source projection"):
            CANARY.run_canary(
                "https://example.test/glap/",
                today=date(2026, 8, 25),
                fetcher=self.fetcher(snapshot=changed),
            )

    def test_canary_fails_when_live_page_drops_loader_or_fail_closed_state(self):
        changed = self.page.replace(
            b'fetch("data/evaluation-snapshot.json",{cache:"no-store"})',
            b'fetch("data/other.json")',
        )
        with self.assertRaisesRegex(ValueError, "validated Pages source"):
            CANARY.run_canary(
                "https://example.test/glap/",
                today=date(2026, 8, 25),
                fetcher=self.fetcher(page=changed),
            )

    def test_canary_fails_when_live_authority_expands(self):
        changed = copy.deepcopy(self.snapshot)
        changed["authority"]["action_mutation_allowed"] = True
        with self.assertRaisesRegex(ValueError, "governed source projection"):
            CANARY.run_canary(
                "https://example.test/glap/",
                today=date(2026, 8, 25),
                fetcher=self.fetcher(snapshot=changed),
            )

    def test_cli_retries_transient_publication_lag(self):
        with (
            mock.patch.object(
                CANARY,
                "run_canary",
                side_effect=[ValueError("old artifact"), {"status": "PASS"}],
            ) as run,
            mock.patch.object(CANARY.time, "sleep") as sleep,
            mock.patch.object(
                sys,
                "argv",
                [
                    "canary_public_evaluation.py",
                    "--base-url",
                    "https://example.test/glap/",
                    "--attempts",
                    "2",
                    "--retry-seconds",
                    "0",
                ],
            ),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(CANARY.main(), 0)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(0.0)


if __name__ == "__main__":
    unittest.main()
