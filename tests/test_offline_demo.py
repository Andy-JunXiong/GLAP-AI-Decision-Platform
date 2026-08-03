from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "offline" / "glap-demo.html"
README = ROOT / "README.md"
HERO = ROOT / "docs" / "glap-decision-intelligence-hero.png"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
LIVE_DEMO_URL = "https://andy-junxiong.github.io/GLAP-AI-Decision-Platform/"


class OfflineDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = DEMO.read_text(encoding="utf-8")

    def test_demo_is_self_contained(self):
        self.assertIn("<style>", self.html)
        self.assertIn("<script>", self.html)
        self.assertNotIn('<script src="http', self.html)
        self.assertNotIn('<link rel="stylesheet" href="http', self.html)

    def test_customer_journey_is_present(self):
        for label in (
            "Control Tower",
            "Signal monitoring",
            "Decision queue",
            "Shipments & inventory",
            "Outcomes & value",
            "Decision Brief",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.html)

    def test_control_tower_summarises_daily_operational_flow(self):
        self.assertIn("Today's operational flow", self.html)
        for marker in ('id="opsPending"', 'id="opsActions"', 'id="opsOutcomes"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_human_review_and_audit_controls_are_present(self):
        for marker in (
            'id="divertRange"',
            'id="approve"',
            'id="reject"',
            'id="reasonModal"',
            'id="ledgerRows"',
            "Prior approval invalidated",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_expected_and_observed_value_are_distinguished(self):
        self.assertIn("Expected impact compared with observed result", self.html)
        self.assertIn("awaiting observed outcome", self.html)
        self.assertIn("Expected benefit", self.html)

    def test_system_evidence_views_are_present(self):
        for view in (
            "AWS Overview",
            "Data Catalog",
            "Logic & SQL",
            "OPS Dashboard",
            "Release & Lineage",
        ):
            with self.subTest(view=view):
                self.assertIn(view, self.html)


class RepositoryShowcaseTests(unittest.TestCase):
    def test_readme_has_a_complete_showcase_hero(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn("docs/glap-decision-intelligence-hero.png", readme)
        self.assertIn("Open the interactive product demo", readme)
        self.assertIn(LIVE_DEMO_URL, readme)
        self.assertIn("Follow the three-minute walkthrough", readme)
        self.assertIn("Inspect AWS evidence", readme)
        self.assertIn("Read the decision case", readme)

    def test_showcase_hero_is_present_and_nonempty(self):
        self.assertTrue(HERO.is_file())
        self.assertGreater(HERO.stat().st_size, 100_000)

    def test_live_demo_has_a_pages_deployment_workflow(self):
        workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("offline/glap-demo.html", workflow)
        self.assertIn("actions/configure-pages@v5", workflow)
        self.assertIn("actions/upload-pages-artifact@v4", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)



if __name__ == "__main__":
    unittest.main()
