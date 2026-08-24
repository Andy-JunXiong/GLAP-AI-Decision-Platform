#!/usr/bin/env python3
"""Read live review sources and emit only an identity-free corpus summary."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
RECONCILER_PATH = ROOT / "ops" / "reconcile_review_collections.py"
DEFAULT_REVIEW_BUNDLE = ROOT / "blinded-review-survey" / "data" / "review-bundle.json"
DEFAULT_DISPLAY_BUNDLE = ROOT / "lambda" / "ten_story_review_bundle.json"
DEFAULT_RUBRIC = ROOT / "docs" / "decision_quality_rubric_v1.json"
FORBIDDEN_OUTPUT_KEYS = {
    "answers",
    "notes",
    "reviewer_id",
    "reviewer_ref",
    "reviews",
    "reviews_by_package",
    "submissions",
    "user_id",
    "username",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_reconciler():
    spec = importlib.util.spec_from_file_location("review_reconciler", RECONCILER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("cannot load review reconciler")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_mainland_submissions(profile: str, region: str, table_name: str) -> list[dict[str, Any]]:
    import boto3

    client = boto3.Session(profile_name=profile, region_name=region).client("dynamodb")
    submissions: list[dict[str, Any]] = []
    start_key: dict[str, Any] | None = None
    while True:
        request: dict[str, Any] = {
            "TableName": table_name,
            "FilterExpression": "#kind = :kind",
            "ExpressionAttributeNames": {"#kind": "kind"},
            "ExpressionAttributeValues": {":kind": {"S": "TEN_STORY_SUBMISSION"}},
            "ProjectionExpression": "payload_json",
            "ConsistentRead": True,
        }
        if start_key:
            request["ExclusiveStartKey"] = start_key
        response = client.scan(**request)
        for item in response.get("Items", []):
            raw = (item.get("payload_json") or {}).get("S")
            if raw:
                submissions.append(json.loads(raw))
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            break
    return submissions


def build_mainland_export(
    submissions: list[dict[str, Any]], display_bundle: dict[str, Any]
) -> dict[str, Any]:
    eligible = [
        item
        for item in submissions
        if item.get("collection_id") == "glap-ten-story-review.v1"
        and item.get("bundle_digest") == display_bundle.get("bundle_digest")
        and item.get("source_bundle_id") == display_bundle.get("source_bundle_id")
        and item.get("source_bundle_digest") == display_bundle.get("source_bundle_digest")
    ]
    return {
        "schema_version": "glap-ten-story-review-export.v1",
        "collection_id": "glap-ten-story-review.v1",
        "bundle_digest": display_bundle["bundle_digest"],
        "source_bundle_id": display_bundle["source_bundle_id"],
        "source_bundle_digest": display_bundle["source_bundle_digest"],
        "submissions": sorted(
            eligible,
            key=lambda item: (str(item.get("submitted_at")), str(item.get("reviewer_id"))),
        ),
    }


def assert_aggregate_safe(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                raise ValueError(f"private review field reached aggregate output: {path}.{key}")
            if key == "reviewer_identifiers_retained" and item is not False:
                raise ValueError("aggregate output must discard reviewer identifiers")
            assert_aggregate_safe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_aggregate_safe(item, f"{path}[{index}]")
    elif isinstance(value, str) and value.startswith("reviewer-"):
        raise ValueError(f"pseudonymous reviewer identifier reached aggregate output: {path}")


def canonical_digest(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "artifact_digest"}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--formal-export",
        required=True,
        help="Formal export path, or - to read the private export from stdin",
    )
    parser.add_argument("--key-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", default="codex-readonly")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--table-name", default="glap-three-case-review")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reconciler = load_reconciler()
    review_bundle = load_json(DEFAULT_REVIEW_BUNDLE)
    display_bundle = load_json(DEFAULT_DISPLAY_BUNDLE)
    rubric = load_json(DEFAULT_RUBRIC)
    key_bundle = load_json(args.key_bundle)
    formal_export = (
        json.loads(sys.stdin.readline())
        if args.formal_export == "-"
        else load_json(Path(args.formal_export))
    )
    mainland_export = build_mainland_export(
        read_mainland_submissions(args.profile, args.region, args.table_name),
        display_bundle,
    )

    submissions = reconciler.normalize_formal_export(formal_export, review_bundle)
    submissions.extend(
        reconciler.normalize_mainland_export(
            mainland_export, review_bundle, display_bundle
        )
    )
    combined = reconciler.reconcile_collections(review_bundle, submissions)
    summary = reconciler.aggregate_corpus(combined, review_bundle, key_bundle, rubric)
    artifact = {
        "schema_version": "decision-quality-five-review-corpus-artifact.v1",
        "generated_on_sydney_date": datetime.now(
            ZoneInfo("Australia/Sydney")
        ).date().isoformat(),
        "reviewer_count": combined["reviewer_count"],
        "review_record_count": combined["review_record_count"],
        "source_collections": combined["source_collections"],
        "corpus_summary": summary,
        "privacy": {
            "reviewer_identifiers_retained": False,
            "credentials_retained": False,
            "answer_content_retained": False,
            "raw_exports_retained": False,
        },
        "claim_boundary": {
            "supports": ["FIVE_REVIEW_CONTROLLED_POINT_IN_TIME_DECISION_QUALITY"],
            "does_not_support": [
                "BUSINESS_OUTCOME_EFFECT",
                "REAL_LOGISTICS_PERFORMANCE",
                "A303_REACTIVATION",
                "MODEL_PROMOTION",
                "PRODUCTION_READINESS",
                "OPERATIONAL_AUTHORITY",
            ],
        },
        "operational_mutations": [],
    }
    assert_aggregate_safe(artifact)
    artifact["artifact_digest"] = canonical_digest(artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS: five-review corpus reconciled in memory; "
        f"reviewers={artifact['reviewer_count']} "
        f"records={artifact['review_record_count']} "
        f"results={json.dumps(summary['result_counts'], sort_keys=True)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
