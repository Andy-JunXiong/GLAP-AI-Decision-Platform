"""Validate high-risk public decision, execution, outcome, and value claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = "docs/public_claim_manifest_v1.json"
SCHEMA_VERSION = "public-claim-manifest.v1"
SCOPE = "HIGH_RISK_DECISION_EXECUTION_OUTCOME_VALUE_CLAIMS_V1"
CLASSIFICATIONS = {"RUNTIME_BACKED", "MODELLED_SYNTHETIC", "ILLUSTRATIVE"}
SEMANTICS = {
    "DECISION_RECOMMENDATION",
    "BUSINESS_VALUE_MODELLED",
    "EXECUTION_OUTCOME_VALUE_SUMMARY",
    "DECISION_BRIEF_SCENARIO",
}
CLAIM_KEYS = {
    "claim_id",
    "surface",
    "semantic",
    "classification",
    "source_file",
    "source_marker",
    "required_anchor",
    "required_disclosure",
    "backing_source_path",
}
LEGACY_UNQUALIFIED_CLAIMS = {
    "decision-brief-demo/app/page.tsx": (
        'title="Value delivered"',
        'label="Decisions executed"',
        'title="Cumulative value delivered"',
        'title="Recent decision outcomes"',
        'copy="80% model confidence"',
    ),
    "offline/glap-demo.html": ("80% model confidence",),
}


def load_manifest(root: Path = ROOT) -> dict[str, Any]:
    return json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))


def _safe_repository_file(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = root / relative
    return path if path.is_file() and path.stat().st_size > 0 else None


def validate_manifest(manifest: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if manifest.get("scope") != SCOPE:
        errors.append("unsupported or expanded scope")
    if set(manifest.get("classifications", [])) != CLASSIFICATIONS:
        errors.append("classification vocabulary must contain exactly the three governed classes")

    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims:
        return errors + ["claims must be a non-empty list"]

    claim_ids = [claim.get("claim_id") for claim in claims if isinstance(claim, dict)]
    if len(claim_ids) != len(claims) or len(claim_ids) != len(set(claim_ids)):
        errors.append("claim_id values must be present and unique")

    for index, claim in enumerate(claims):
        prefix = f"claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if set(claim) != CLAIM_KEYS:
            errors.append(f"{prefix} must use the exact v1 claim fields")
            continue
        classification = claim["classification"]
        if classification not in CLASSIFICATIONS:
            errors.append(f"{prefix} has an unsupported classification")
        if claim["semantic"] not in SEMANTICS:
            errors.append(f"{prefix} has an unsupported semantic")
        source_path = _safe_repository_file(root, claim["source_file"])
        if source_path is None:
            errors.append(f"{prefix} source_file is unsafe, missing, or empty")
            continue
        source = source_path.read_text(encoding="utf-8")
        marker = claim["source_marker"]
        if not isinstance(marker, str) or not marker or source.count(marker) != 1:
            errors.append(f"{prefix} source_marker must occur exactly once in its source surface")
        for field in ("required_anchor", "required_disclosure"):
            value = claim[field]
            if not isinstance(value, str) or not value or value not in source:
                errors.append(f"{prefix} {field} is missing from its source surface")

        backing = claim["backing_source_path"]
        if classification == "ILLUSTRATIVE" and backing is not None:
            errors.append(f"{prefix} illustrative claims cannot cite a backing source")
        if classification in {"RUNTIME_BACKED", "MODELLED_SYNTHETIC"}:
            if _safe_repository_file(root, backing) is None:
                errors.append(f"{prefix} requires a repository backing source")

    for relative_path, forbidden in LEGACY_UNQUALIFIED_CLAIMS.items():
        path = _safe_repository_file(root, relative_path)
        if path is None:
            errors.append(f"required claim surface is missing: {relative_path}")
            continue
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            if phrase in source:
                errors.append(f"legacy unqualified public claim remains in {relative_path}: {phrase}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_manifest(load_manifest(args.root), args.root)
    if errors:
        print("Public claim validation: DRIFT")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Public claim validation: PASS")
    print("Scope: HIGH_RISK_DECISION_EXECUTION_OUTCOME_VALUE_CLAIMS_V1")
    print("Claim classes: RUNTIME_BACKED, MODELLED_SYNTHETIC, ILLUSTRATIVE")
    print("External writes executed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
