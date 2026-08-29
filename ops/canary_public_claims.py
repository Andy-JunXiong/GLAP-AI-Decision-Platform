"""Verify published Public Claim Truth markers using read-only HTTP."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PAGES_SURFACE = "PUBLIC_PAGES_SCENARIO_LAB"
PAGES_SOURCE = "offline/glap-demo.html"


def _load_validator(root: Path = ROOT) -> Any:
    path = root / "ops" / "validate_public_claims.py"
    spec = importlib.util.spec_from_file_location("public_claim_canary_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the Public Claim Truth validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fetch_bytes(url: str, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "text/html",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "GLAP-read-only-public-claim-canary/1",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"published resource returned HTTP {response.status}")
        return response.read()


def _page_url(base_url: str, cache_bust: str | None) -> str:
    url = urljoin(base_url.rstrip("/") + "/", "")
    if cache_bust:
        return f"{url}?public_claim_canary={quote(cache_bust, safe='')}"
    return url


def _pages_claims(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validator = _load_validator(root)
    manifest = validator.load_manifest(root)
    errors = validator.validate_manifest(manifest, root)
    if errors:
        raise ValueError("local Public Claim Truth validation failed: " + "; ".join(errors))
    claims = [
        claim for claim in manifest["claims"] if claim["surface"] == PAGES_SURFACE
    ]
    if not claims:
        raise ValueError("Public Claim Truth manifest has no Pages claims")
    if any(claim["source_file"] != PAGES_SOURCE for claim in claims):
        raise ValueError("Pages claims must bind to the published Pages source")
    return manifest, claims


def run_canary(
    base_url: str,
    *,
    cache_bust: str | None = None,
    timeout_seconds: float = 20,
    fetcher: Callable[[str, float], bytes] = _fetch_bytes,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Return an aggregate-only report or raise when published claims drift."""

    manifest, claims = _pages_claims(root)
    live_page_bytes = fetcher(_page_url(base_url, cache_bust), timeout_seconds)
    try:
        live_page = live_page_bytes.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        raise ValueError("published Public Claim Truth page is not UTF-8") from error

    for claim in claims:
        if live_page.count(claim["source_marker"]) != 1:
            raise ValueError("a published claim marker is missing or duplicated")
        if claim["required_anchor"] not in live_page:
            raise ValueError("a published claim anchor is missing")
        if claim["required_disclosure"] not in live_page:
            raise ValueError("a published claim disclosure is missing")

    classification_counts = {
        classification: sum(
            claim["classification"] == classification for claim in claims
        )
        for classification in sorted(manifest["classifications"])
    }
    authority = {
        "action_mutation_allowed": False,
        "external_writes_executed": False,
        "production_change_allowed": False,
    }
    return {
        "status": "PASS",
        "mode": "READ_ONLY",
        "schema_version": "public-claim-canary.v1",
        "scope": manifest["scope"],
        "checks": {
            "live_page_readable": True,
            "published_claim_markers_match_manifest": True,
            "required_anchors_present": True,
            "required_disclosures_present": True,
            "authority_all_false": True,
        },
        "aggregate": {
            "claim_count": len(claims),
            "classification_counts": classification_counts,
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
        print("FAIL: read-only Public Claim Truth canary: retry settings are invalid")
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
                print(f"FAIL: read-only Public Claim Truth canary: {error}")
                return 1
            print(
                f"WAIT: published Public Claim Truth surface is not ready "
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
