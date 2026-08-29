import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "canary_public_claims", ROOT / "ops" / "canary_public_claims.py"
)
CANARY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CANARY
SPEC.loader.exec_module(CANARY)


class PublicClaimCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "offline" / "glap-demo.html").read_bytes()

    @staticmethod
    def fetcher(page: bytes):
        def fetch(_url, _timeout):
            return page

        return fetch

    def test_canary_returns_only_aggregate_claim_evidence(self):
        report = CANARY.run_canary(
            "https://example.test/glap/",
            cache_bust="commit-123",
            fetcher=self.fetcher(self.page),
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["mode"], "READ_ONLY")
        self.assertTrue(all(report["checks"].values()))
        self.assertTrue(all(value is False for value in report["authority"].values()))
        self.assertEqual(report["aggregate"]["claim_count"], 2)
        self.assertEqual(
            report["aggregate"]["classification_counts"],
            {"ILLUSTRATIVE": 1, "MODELLED_SYNTHETIC": 1, "RUNTIME_BACKED": 0},
        )
        serialized = json.dumps(report)
        self.assertNotIn("pages-port-diversion", serialized)
        self.assertNotIn("Illustrative decision exercise", serialized)

    def test_canary_fails_when_a_published_marker_is_missing(self):
        changed = self.page.replace(
            b'data-claim-id="pages-port-diversion-decision"',
            b'data-claim-id="missing-decision-claim"',
        )
        with self.assertRaisesRegex(ValueError, "claim marker"):
            CANARY.run_canary(
                "https://example.test/glap/", fetcher=self.fetcher(changed)
            )

    def test_canary_fails_when_a_published_disclosure_is_missing(self):
        changed = self.page.replace(
            b"fixed illustrative cost model", b"undisclosed cost model"
        )
        with self.assertRaisesRegex(ValueError, "claim disclosure"):
            CANARY.run_canary(
                "https://example.test/glap/", fetcher=self.fetcher(changed)
            )

    def test_canary_fails_when_a_published_anchor_is_missing(self):
        changed = self.page.replace(b"Net modelled benefit", b"Model result")
        with self.assertRaisesRegex(ValueError, "claim anchor"):
            CANARY.run_canary(
                "https://example.test/glap/", fetcher=self.fetcher(changed)
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
                    "canary_public_claims.py",
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
