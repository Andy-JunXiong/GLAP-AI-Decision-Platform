import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "lambda" / "glap_pipeline_stage_stub.py"
SPEC = importlib.util.spec_from_file_location("pipeline_stage_stub", MODULE_PATH)
stub = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(stub)


class PipelineStageStubTests(unittest.TestCase):
    def test_returns_current_success_contract_without_writes(self):
        result = stub.lambda_handler(
            {
                "logical_run_date": "2026-08-04",
                "pipeline_stage": "generation",
            },
            None,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["writes_performed"], 0)
        self.assertTrue(result["stub"])

    def test_requires_logical_date(self):
        with self.assertRaises(ValueError):
            stub.lambda_handler({}, None)


if __name__ == "__main__":
    unittest.main()
