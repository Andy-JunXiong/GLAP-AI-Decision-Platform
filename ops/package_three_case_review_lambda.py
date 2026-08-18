#!/usr/bin/env python3
"""Create the dependency-free ten-story reviewer Lambda ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lambda" / "glap_three_case_review.py"
BUNDLE = ROOT / "lambda" / "ten_story_review_bundle.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "glap-three-case-review.zip",
        help="Output ZIP path (default: artifacts/glap-three-case-review.zip)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    source = SOURCE.read_bytes()
    compile(source, str(SOURCE), "exec")
    bundle = BUNDLE.read_bytes()
    parsed_bundle = json.loads(bundle)
    if len(parsed_bundle.get("cases", [])) != 10:
        raise ValueError("Ten-story display bundle must contain exactly 10 cases")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("lambda_function.py", source)
        archive.writestr("ten_story_review_bundle.json", bundle)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"created={output}")
    print(f"sha256={digest}")
    print("handler=lambda_function.lambda_handler")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
