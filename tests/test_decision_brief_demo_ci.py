import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "decision-brief-demo-ci.yml"
PACKAGE = ROOT / "decision-brief-demo" / "package.json"


class DecisionBriefDemoCiContractTests(unittest.TestCase):
    def test_browser_smoke_workflow_is_read_only_and_path_scoped(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('name: Decision brief demo CI', workflow)
        self.assertEqual(workflow.count('"decision-brief-demo/**"'), 2)
        self.assertEqual(
            workflow.count('".github/workflows/decision-brief-demo-ci.yml"'),
            2,
        )
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("working-directory: decision-brief-demo", workflow)
        self.assertIn("uses: actions/setup-node@v6", workflow)
        self.assertIn('node-version: "22.13.0"', workflow)
        self.assertIn("run: npm ci", workflow)
        self.assertIn("run: npx playwright install --with-deps chromium", workflow)
        self.assertIn("run: npm run lint", workflow)
        self.assertIn("run: npm run system-evidence:check", workflow)
        self.assertIn("run: npm test", workflow)

        for prohibited in (
            "aws-actions/",
            "wrangler deploy",
            "git push",
            "deploy-pages",
            "configure-aws-credentials",
        ):
            self.assertNotIn(prohibited, workflow)

    def test_standard_frontend_test_command_includes_browser_smoke(self) -> None:
        package = PACKAGE.read_text(encoding="utf-8")

        self.assertEqual(package.count('"@playwright/test"'), 1)
        self.assertIn(
            '"test": "npm run system-evidence:check && npm run build && node '
            '--experimental-strip-types --test tests/rendered-html.test.mjs '
            'tests/system-evidence-generator.test.mjs '
            'tests/system-evidence-snapshot.test.mjs '
            '&& playwright test --config '
            'playwright.config.mjs"',
            package,
        )
        self.assertIn(
            '"system-evidence:check": "node --experimental-strip-types '
            'scripts/build-system-evidence-snapshot.mjs --check"',
            package,
        )


if __name__ == "__main__":
    unittest.main()
