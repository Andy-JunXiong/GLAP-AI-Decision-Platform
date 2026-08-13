import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_pre_commit_checks", ROOT / "ops" / "run_pre_commit_checks.py"
)
GATE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)


class PreCommitGateTests(unittest.TestCase):
    def test_hook_runs_staged_snapshot_gate_without_worktree_override(self):
        hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("ops/run_pre_commit_checks.py", hook)
        self.assertNotIn("--worktree", hook)

    def test_gate_materializes_the_git_index(self):
        source = (ROOT / "ops" / "run_pre_commit_checks.py").read_text(encoding="utf-8")
        self.assertIn('"checkout-index", "--all"', source)
        self.assertIn('"git", "diff", "--cached", "--check"', source)
        self.assertIn('"ops/audit_project_drift.py"', source)
        self.assertIn('"unittest", "discover"', source)

    def test_installer_is_plan_first_and_repository_scoped(self):
        installer = (ROOT / "ops" / "install_project_hooks.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$Apply", installer)
        self.assertIn("git config --local core.hooksPath .githooks", installer)
        self.assertIn("git config --local glap.pythonPath $pythonPath", installer)
        self.assertNotIn("--global", installer)

    def test_agent_guidance_requires_documentation_sync_before_commit_and_push(self):
        guidance = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("### Documentation and Fact Synchronization Gate", guidance)
        self.assertIn("documentation-impact audit", guidance)
        self.assertIn("origin/<branch>..HEAD", guidance)
        self.assertIn("If any tracked claim is stale, stop the push", guidance)


if __name__ == "__main__":
    unittest.main()
