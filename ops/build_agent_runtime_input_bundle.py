"""Build and verify a content-addressed Agent Runtime v1 input bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from ops.run_governed_agent_runtime import build_input_bundle
except ModuleNotFoundError:
    from run_governed_agent_runtime import build_input_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    bundle = build_input_bundle(manifest)
    rendered = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
