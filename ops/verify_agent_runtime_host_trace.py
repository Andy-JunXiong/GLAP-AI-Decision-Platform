"""Replay-verify an Agent Runtime host trace against its frozen input bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from ops.run_governed_agent_runtime import verify_host_trace
except ModuleNotFoundError:
    from run_governed_agent_runtime import verify_host_trace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--expected-trace-sha256")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    verify_host_trace(bundle, trace, args.expected_trace_sha256)
    print(json.dumps({"status": "PASS", "trace_sha256": trace["trace_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
