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
        self.assertIn("Operational data snapshot", self.html)
        for marker in (
            'id="opsGenerated"',
            'id="opsAtRisk"',
            'id="opsAlerts"',
            'id="opsDecisions"',
            'id="opsActions"',
            'id="opsOutcomes"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_ops_snapshot_loads_with_explicit_fallback(self):
        self.assertIn('fetch("data/ops-snapshot.json"', self.html)
        self.assertIn("SYNTHETIC OPS FALLBACK", self.html)
        self.assertIn("SCHEDULED AWS OPS ANALYTICS", self.html)
        self.assertIn("is_connected:false", self.html)

    def test_live_analytics_and_forecast_are_rendered_from_the_snapshot(self):
        for marker in (
            'id="analytics"',
            'id="analyticsForecastTotal"',
            'id="forecastChart"',
            'id="stageFreshness"',
            'id="riskHotspotsTracked"',
            'id="alertDistribution"',
            'id="actionDistribution"',
            'id="rootCauseDistribution"',
            "AWS EXISTING ASSETS",
            "ordinary_least_squares_28d",
            "renderAnalytics(snapshot)",
            "Simulated average improvement",
        ):
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
        self.assertIn("offline/data/ops-snapshot.json", workflow)
        self.assertIn("ops/export_ops_snapshot.py", workflow)
        self.assertIn("AWS_OPS_READ_ROLE_ARN", workflow)
        self.assertIn("actions/configure-pages@v5", workflow)
        self.assertIn("actions/upload-pages-artifact@v4", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)



if __name__ == "__main__":
    unittest.main()
