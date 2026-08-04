from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PipelineCutoverScriptTests(unittest.TestCase):
    def test_cutover_is_plan_only_by_default_and_has_rollback(self):
        script = (ROOT / "ops" / "cutover_pipeline_reliability.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$Apply", script)
        self.assertIn("if (-not $Apply)", script)
        self.assertIn("cutover-backups", script)
        self.assertIn('Set-ScheduleState -Schedule $replacement -State "DISABLED"', script)
        self.assertIn('Set-ScheduleState -Schedule $schedule -State $schedule.State', script)
        for schedule in (
            "glap_daily_generator",
            "glap_daily_orchestrator",
            "glap-ai-orchestrator-daily",
            "glap-ai-flywheel-orchestrator-daily",
            "glap-generator-daily",
        ):
            self.assertIn(schedule, script)


if __name__ == "__main__":
    unittest.main()
