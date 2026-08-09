"""Run fail-closed checks against the exact Git index snapshot before commit."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = "decision-brief-demo/"


def _run(command: list[str], cwd: Path) -> int:
    print(f"\n[pre-commit] {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def _staged_files(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def _materialize_staged_snapshot(root: Path, destination: Path) -> None:
    prefix = destination.resolve().as_posix().rstrip("/") + "/"
    completed = subprocess.run(
        ["git", "checkout-index", "--all", f"--prefix={prefix}"],
        cwd=root,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("Unable to materialize the staged Git snapshot")


def _run_snapshot_checks(snapshot: Path) -> int:
    commands = (
        [sys.executable, "-m", "compileall", "-q", "lambda", "ops", "examples", "tests"],
        [sys.executable, "ops/audit_project_drift.py", "--format", "markdown"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    )
    for command in commands:
        if not (snapshot / "ops/audit_project_drift.py").is_file():
            print(
                "[pre-commit] The staged snapshot does not contain the drift audit. "
                "Stage the hook, audit, contract, and tests together.",
                file=sys.stderr,
            )
            return 1
        if _run(command, snapshot):
            return 1
    return 0


def _run_frontend_checks_if_needed(root: Path, staged_files: list[str]) -> int:
    if not any(path.startswith(FRONTEND_ROOT) for path in staged_files):
        return 0
    npm = "npm.cmd" if os.name == "nt" else "npm"
    frontend = root / "decision-brief-demo"
    for command in ([npm, "run", "lint"], [npm, "test"]):
        if _run(command, frontend):
            return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worktree",
        action="store_true",
        help="Validate the working tree for installation diagnostics; hooks must omit this flag.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = REPOSITORY_ROOT
    if _run(["git", "diff", "--cached", "--check"], root):
        return 1
    staged_files = _staged_files(root)

    if args.worktree:
        if _run_snapshot_checks(root):
            return 1
    else:
        with tempfile.TemporaryDirectory(prefix="glap-staged-") as directory:
            snapshot = Path(directory)
            _materialize_staged_snapshot(root, snapshot)
            if _run_snapshot_checks(snapshot):
                return 1

    if _run_frontend_checks_if_needed(root, staged_files):
        return 1
    print("\n[pre-commit] PASS: staged snapshot satisfies the GLAP drift and quality gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
