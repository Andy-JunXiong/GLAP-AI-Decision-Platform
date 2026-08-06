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
            "Decisions",
            "Shipment baseline",
            "Outcome maturity",
            "Decision Brief",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.html)

    def test_control_tower_summarises_daily_operational_flow(self):
        self.assertIn("Decision flywheel snapshot", self.html)
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

    def test_control_tower_separates_stateful_baseline_and_maturity(self):
        self.assertIn("Stateful operational baseline", self.html)
        for marker in (
            'id="baselineShipments"',
            'id="baselineBookings"',
            'id="baselineDelivered"',
            'id="baselineSlaRate"',
            'id="baselineSignals"',
            'id="baselineHighSignals"',
            'id="baselineMaturity"',
            "Synthetic engineering evidence only",
            "renderOperationalBaseline(snapshot)",
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
            'id="analyticsLaneProfile"',
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
            "Prior scenario approval invalidated",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_every_page_separates_governed_and_scenario_evidence(self):
        for marker in (
            'id="signalLaneTable"',
            'id="publishedDecisionCount"',
            'id="shipmentLaneTable"',
            'id="outcomeReadiness"',
            'id="analyticsLaneProfile"',
            "scenario approvals stay in browser",
            "No measured savings or production performance claim",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_stale_claims_and_fake_actions_do_not_return(self):
        for forbidden in (
            "12 min ago",
            "Validated storage avoided",
            "Stockouts prevented",
            "Rolling 90-day accuracy",
            "23 Jul · 09:30 AEST",
            "Shipment and outcome records have been updated",
            "data-demo-action",
            'id="shipmentTable"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.html)

    def test_schema_16_breakdowns_are_rendered(self):
        for marker in (
            'schema_version:"1.6"',
            "breakdowns.market_lanes",
            "population_profile",
            "outcome_labels",
            'id="analyticsModeCount"',
            'id="analyticsProviderCount"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_readability_scale_covers_core_and_dense_views(self):
        for marker in (
            "Readability scale: keep every explanatory label legible",
            "body{font-size:18px;line-height:1.55}",
            ".page{max-width:1450px",
            ".metric span{font-size:15px",
            ".row{font-size:16px",
            ".system-nav button{font-size:15px",
            ".flow-step p,.flow-step small{font-size:14px",
            ".resource-row{grid-template-columns:220px 125px 1fr 110px",
            ".contract-row.header,.contract-row code,.contract-row p,.contract-row span{font-size:14px}",
            ".mapping-grid{grid-template-columns:repeat(3,1fr)",
            "@media(max-width:720px){body{font-size:16px}",
            ".nav button{height:62px;font-size:12px}",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

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
        for marker in (
            "15 Lambda",
            "127 objects",
            "4 enabled and 5 disabled",
            "fact_shipment_lifecycle_staging_v1",
            "vw_multimodal_operational_baseline_v1",
            "6 OK and 1 insufficient data",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)


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
        self.assertIn("sql/13_operational_baseline.sql", workflow)
        self.assertIn("AWS_OPS_READ_ROLE_ARN", workflow)
        self.assertIn("actions/configure-pages@v5", workflow)
        self.assertIn("actions/upload-pages-artifact@v4", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)



if __name__ == "__main__":
    unittest.main()
