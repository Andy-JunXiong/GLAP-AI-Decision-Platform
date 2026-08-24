"""Verify the published Evaluation page and snapshot without mutating state."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PAGE_PATH = ROOT / "offline" / "glap-demo.html"
SNAPSHOT_PATH = ROOT / "offline" / "data" / "evaluation-snapshot.json"
EXPORTER_PATH = ROOT / "ops" / "export_public_evaluation_snapshot.py"

PAGE_LOADER_MARKERS = (
    'const EVALUATION_SCHEMA_VERSION="public-evaluation-snapshot.v1"',
    'fetch("data/evaluation-snapshot.json",{cache:"no-store"})',
    "validateEvaluationSnapshot",
    "applyEvaluationSnapshot(await response.json())",
)
FAIL_CLOSED_MARKERS = (
    'id="evaluationState">UNAVAILABLE',
    "function renderEvaluationUnavailable()",
    "async function loadEvaluationSnapshot(){\n    renderEvaluationUnavailable();",
    'catch(error){console.warn("Evaluation snapshot unavailable; result withheld",error)}',
)


def _load_exporter() -> Any:
    spec = importlib.util.spec_from_file_location(
        "public_evaluation_canary_exporter", EXPORTER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the public Evaluation exporter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fetch_bytes(url: str, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/html;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "GLAP-read-only-evaluation-canary/1",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"published resource returned HTTP {response.status}")
        return response.read()


def _resource_url(base_url: str, path: str, cache_bust: str | None) -> str:
    url = urljoin(base_url.rstrip("/") + "/", path)
    if cache_bust:
        return f"{url}?evaluation_canary={quote(cache_bust, safe='')}"
    return url


def run_canary(
    base_url: str,
    *,
    today: date | None = None,
    cache_bust: str | None = None,
    timeout_seconds: float = 20,
    fetcher: Callable[[str, float], bytes] = _fetch_bytes,
) -> dict[str, Any]:
    """Return an aggregate-only report or raise when the live surface drifts."""

    exporter = _load_exporter()
    page_url = _resource_url(base_url, "", cache_bust)
    snapshot_url = _resource_url(base_url, "data/evaluation-snapshot.json", cache_bust)
    live_page_bytes = fetcher(page_url, timeout_seconds)
    live_snapshot_bytes = fetcher(snapshot_url, timeout_seconds)

    try:
        live_page = live_page_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("published Evaluation page is not UTF-8") from error
    try:
        live_snapshot = json.loads(live_snapshot_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("published Evaluation snapshot is not valid UTF-8 JSON") from error

    live_page_normalized = live_page.replace("\r\n", "\n")
    expected_page = PAGE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    if live_page_normalized != expected_page:
        raise ValueError("published page differs from the locally validated Pages source")

    expected_snapshot = exporter.build_public_snapshot(
        exporter.load_json(exporter.SOURCE_PATH),
        exporter.load_json(exporter.BUNDLE_PATH),
        exporter.load_json(exporter.RUBRIC_PATH),
    )
    if live_snapshot != expected_snapshot:
        raise ValueError("published Evaluation snapshot differs from the governed source projection")
    errors = exporter.validate_public_snapshot(live_snapshot, today=today)
    if errors:
        raise ValueError("published Evaluation snapshot is invalid: " + "; ".join(errors))

    missing_loader = [
        marker for marker in PAGE_LOADER_MARKERS if marker not in live_page_normalized
    ]
    if missing_loader:
        raise ValueError("published page no longer contains the validated Evaluation loader")
    missing_fail_closed = [
        marker for marker in FAIL_CLOSED_MARKERS if marker not in live_page_normalized
    ]
    if missing_fail_closed:
        raise ValueError("published page no longer contains the fail-closed Evaluation state")

    corpus = live_snapshot["corpus"]
    quality = live_snapshot["decision_quality"]
    authority = live_snapshot["authority"]
    if any(authority.values()):
        raise ValueError("published Evaluation snapshot has non-false authority")

    return {
        "status": "PASS",
        "mode": "READ_ONLY",
        "schema_version": live_snapshot["schema_version"],
        "evaluation_as_of_date": live_snapshot["evaluation_as_of_date"],
        "checks": {
            "live_page_matches_validated_source": True,
            "live_snapshot_matches_governed_projection": True,
            "aggregate_counts_reconcile": (
                corpus["locked_review_record_count"]
                == corpus["cutoff_count"] * corpus["complete_review_count"]
                and quality["favors_a303_on_count"] + quality["no_winner_count"]
                == corpus["cutoff_count"]
            ),
            "authority_all_false": True,
            "page_loader_present": True,
            "fail_closed_state_present": True,
        },
        "aggregate": {
            "case_count": corpus["case_count"],
            "cutoff_count": corpus["cutoff_count"],
            "complete_review_count": corpus["complete_review_count"],
            "locked_review_record_count": corpus["locked_review_record_count"],
            "favors_a303_on_count": quality["favors_a303_on_count"],
            "no_winner_count": quality["no_winner_count"],
        },
        "authority": authority,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cache-bust")
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--retry-seconds", type=float, default=3)
    args = parser.parse_args()
    if args.attempts < 1 or args.retry_seconds < 0 or args.timeout_seconds <= 0:
        print("FAIL: read-only public Evaluation canary: retry settings are invalid")
        return 1
    for attempt in range(1, args.attempts + 1):
        try:
            report = run_canary(
                args.base_url,
                cache_bust=args.cache_bust,
                timeout_seconds=args.timeout_seconds,
            )
        except Exception as error:
            if attempt == args.attempts:
                print(f"FAIL: read-only public Evaluation canary: {error}")
                return 1
            print(
                f"WAIT: published Evaluation surface is not ready "
                f"({attempt}/{args.attempts}): {error}",
                file=sys.stderr,
            )
            time.sleep(args.retry_seconds)
            continue
        print(json.dumps(report, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
