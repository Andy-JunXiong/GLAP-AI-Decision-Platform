import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


LAMBDA_DIR = Path(__file__).resolve().parents[1] / "lambda"
MODULE_PATH = LAMBDA_DIR / "glap_pipeline_controller.py"
if str(LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDA_DIR))


def load_module(lambda_client=None, s3_client=None):
    class NoSuchKey(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    resolved_s3_client = s3_client or MagicMock()
    if s3_client is None:
        resolved_s3_client.get_object.side_effect = NoSuchKey()
    clients = {
        "lambda": lambda_client or MagicMock(),
        "s3": resolved_s3_client,
    }
    fake_boto3 = types.SimpleNamespace(client=lambda name, **kwargs: clients[name])
    sys.modules["boto3"] = fake_boto3
    fake_config_module = types.ModuleType("botocore.config")
    fake_config_module.Config = lambda **kwargs: kwargs
    fake_botocore = types.ModuleType("botocore")
    fake_botocore.config = fake_config_module
    sys.modules["botocore"] = fake_botocore
    sys.modules["botocore.config"] = fake_config_module
    spec = importlib.util.spec_from_file_location("pipeline_controller", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def response(body, function_error=None):
    value = {"Payload": io.BytesIO(json.dumps(body).encode("utf-8"))}
    if function_error:
        value["FunctionError"] = function_error
    return value


STAGES = [
    {"name": "generation", "function_name": "generator", "quality_gate": False},
    {"name": "input_validation", "function_name": "validator", "quality_gate": True},
    {"name": "decision_flywheel", "function_name": "flywheel", "quality_gate": False},
]


PASSED_CHECKS = {
    "missing_dates": "passed",
    "empty_inputs": "passed",
    "duplicate_business_keys": "passed",
    "abnormal_volume_change": "passed",
    "stale_stage_outputs": "passed",
}


class PipelineControllerTests(unittest.TestCase):
    def test_rejects_duplicate_or_unsafe_stage_config(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.load_stage_config(json.dumps(STAGES + [STAGES[0]]))
        with self.assertRaises(ValueError):
            module.load_stage_config(json.dumps([{"name": "Bad Stage", "function_name": "x"}] * 2))
        with self.assertRaisesRegex(ValueError, "Unsupported quality contract"):
            module.load_stage_config(
                json.dumps(
                    [
                        {"name": "generation", "function_name": "x"},
                        {
                            "name": "gate",
                            "function_name": "y",
                            "quality_contract": "unknown_v1",
                        },
                    ]
                )
            )

    def test_lifecycle_contracts_are_forwarded_and_fail_closed(self):
        stages = [
            {"name": "stateful_lifecycle_generation", "function_name": "generator"},
            {
                "name": "lifecycle_validation",
                "function_name": "validator",
                "quality_contract": "lifecycle_v1",
            },
            {
                "name": "input_validation",
                "function_name": "validator",
                "quality_contract": "lifecycle_compat_v2",
            },
            {
                "name": "analytics_validation",
                "function_name": "validator",
                "quality_contract": "multimodal_analytics_v1",
            },
        ]
        module = load_module()
        validated = module.load_stage_config(json.dumps(stages))
        client = MagicMock()
        client.invoke.side_effect = [
            response({"status": "success"}),
            response(
                {
                    "status": "success",
                    "quality_checks": {
                        name: "passed"
                        for name in module.QUALITY_CONTRACTS["lifecycle_v1"]
                    },
                }
            ),
            response({"status": "success", "quality_checks": PASSED_CHECKS}),
            response(
                {
                    "status": "success",
                    "quality_checks": {
                        name: "passed"
                        for name in module.QUALITY_CONTRACTS[
                            "multimodal_analytics_v1"
                        ]
                    },
                }
            ),
        ]
        module.lambda_client = client
        with patch.object(module, "load_existing_run", return_value=None), patch.object(
            module, "persist_run"
        ):
            result = module.execute_pipeline(
                validated, "2026-09-01", "s3://safe/status.json"
            )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(result["stages"][1]["quality_checks"]), 19)
        self.assertEqual(len(result["stages"][2]["quality_checks"]), 5)
        self.assertEqual(len(result["stages"][3]["quality_checks"]), 8)
        lifecycle_payload = json.loads(client.invoke.call_args_list[1].kwargs["Payload"])
        compat_payload = json.loads(client.invoke.call_args_list[2].kwargs["Payload"])
        self.assertEqual(lifecycle_payload["quality_contract"], "lifecycle_v1")
        self.assertEqual(compat_payload["quality_contract"], "lifecycle_compat_v2")
        analytics_payload = json.loads(client.invoke.call_args_list[3].kwargs["Payload"])
        self.assertEqual(
            analytics_payload["quality_contract"], "multimodal_analytics_v1"
        )

    def test_failed_quality_gate_blocks_downstream_stage(self):
        client = MagicMock()
        failed_checks = dict(PASSED_CHECKS, duplicate_business_keys="failed")
        client.invoke.side_effect = [
            response({"status": "success"}),
            response({"status": "success", "quality_checks": failed_checks}),
        ]
        module = load_module(lambda_client=client)

        with patch.object(module, "persist_run") as persist:
            result = module.execute_pipeline(STAGES, "2026-08-04", "s3://safe/status.json")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_stage"], "input_validation")
        self.assertEqual(result["failure_category"], "quality_gate_failed")
        self.assertEqual(result["stages"][2]["status"], "blocked")
        self.assertEqual(client.invoke.call_count, 2)
        self.assertGreaterEqual(persist.call_count, 4)

    def test_invalid_quality_contract_fails_closed(self):
        client = MagicMock()
        client.invoke.side_effect = [
            response({"status": "success"}),
            response({"status": "success", "quality_checks": {"empty_inputs": "passed"}}),
        ]
        module = load_module(lambda_client=client)
        with patch.object(module, "persist_run"):
            result = module.execute_pipeline(STAGES, "2026-08-04", "s3://safe/status.json")
        self.assertEqual(result["failure_category"], "quality_contract_invalid")
        self.assertEqual(client.invoke.call_count, 2)

    def test_current_deployed_success_contracts_are_supported(self):
        module = load_module()
        self.assertEqual(module.parse_stage_payload(response({"status": "ok"})), {"status": "ok"})
        self.assertEqual(module.parse_stage_payload(response({"ok": True})), {"ok": True})
        with self.assertRaises(module.StageFailure):
            module.parse_stage_payload(response({"ok": False, "status": "ok"}))

    def test_success_records_duration_and_safe_quality_results(self):
        client = MagicMock()
        client.invoke.side_effect = [
            response({"status": "success", "private_detail": "do not publish"}),
            response({"status": "success", "quality_checks": PASSED_CHECKS}),
            response({"status": "success"}),
        ]
        module = load_module(lambda_client=client)
        with patch.object(module, "load_existing_run", return_value=None), patch.object(
            module, "persist_run"
        ):
            result = module.execute_pipeline(STAGES, "2026-08-04", "s3://safe/status.json")
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(all(stage["status"] == "succeeded" for stage in result["stages"]))
        self.assertTrue(all(stage["duration_ms"] is not None for stage in result["stages"]))
        self.assertNotIn("private_detail", json.dumps(result))
        self.assertNotIn("generator", json.dumps(result))
        self.assertNotIn("s3://", json.dumps(result))

    def test_same_day_success_is_reused_without_invoking_stages(self):
        client = MagicMock()
        module = load_module(lambda_client=client)
        existing = {
            "logical_run_date": "2026-08-04",
            "status": "succeeded",
            "stages": [],
        }
        with patch.object(module, "load_existing_run", return_value=existing), patch.object(
            module, "persist_run"
        ) as persist:
            result = module.execute_pipeline(STAGES, "2026-08-04", "s3://safe/status.json")
        self.assertIs(result, existing)
        client.invoke.assert_not_called()
        persist.assert_not_called()

    def test_same_day_failure_is_reused_fail_closed(self):
        client = MagicMock()
        module = load_module(lambda_client=client)
        existing = {
            "logical_run_date": "2026-08-04",
            "status": "failed",
            "failed_stage": "decision_pipeline",
            "failure_category": "dependency_failure",
            "stages": [],
        }
        with patch.object(module, "load_existing_run", return_value=existing), patch.object(
            module, "persist_run"
        ):
            with patch.dict(
                os.environ,
                {
                    "PIPELINE_STAGES_JSON": json.dumps(STAGES),
                    "PIPELINE_STATUS_S3_URI": "s3://safe/status.json",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "dependency_failure"):
                    module.lambda_handler({"logical_run_date": "2026-08-04"}, None)
        client.invoke.assert_not_called()

    def test_explicit_retry_recovers_only_first_stage_dependency_failure(self):
        client = MagicMock()
        client.invoke.side_effect = [
            response({"status": "success"}),
            response({"status": "success", "quality_checks": PASSED_CHECKS}),
            response({"status": "success"}),
        ]
        module = load_module(lambda_client=client)
        existing = {
            "logical_run_date": "2026-08-04",
            "status": "failed",
            "failed_stage": "generation",
            "failure_category": "dependency_failure",
            "stages": [],
        }
        with patch.object(module, "load_existing_run", return_value=existing), patch.object(
            module, "persist_run"
        ):
            result = module.execute_pipeline(
                STAGES,
                "2026-08-04",
                "s3://safe/status.json",
                retry_failed_run=True,
            )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(client.invoke.call_count, 3)

    def test_explicit_retry_rejects_non_retryable_same_day_failure(self):
        client = MagicMock()
        module = load_module(lambda_client=client)
        existing = {
            "logical_run_date": "2026-08-04",
            "status": "failed",
            "failed_stage": "input_validation",
            "failure_category": "quality_gate_failed",
            "stages": [],
        }
        with patch.object(module, "load_existing_run", return_value=existing), patch.object(
            module, "persist_run"
        ):
            with self.assertRaisesRegex(ValueError, "first-stage dependency failure"):
                module.execute_pipeline(
                    STAGES,
                    "2026-08-04",
                    "s3://safe/status.json",
                    retry_failed_run=True,
                )
        client.invoke.assert_not_called()

    def test_explicit_retry_requires_an_existing_failure_for_the_same_date(self):
        client = MagicMock()
        module = load_module(lambda_client=client)
        with patch.object(module, "load_existing_run", return_value=None), patch.object(
            module, "persist_run"
        ):
            with self.assertRaisesRegex(ValueError, "existing failed run for the same date"):
                module.execute_pipeline(
                    STAGES,
                    "2026-08-04",
                    "s3://safe/status.json",
                    retry_failed_run=True,
                )
        client.invoke.assert_not_called()

    def test_dry_run_does_not_overwrite_latest_status(self):
        client = MagicMock()
        module = load_module(lambda_client=client)
        with patch.object(module, "persist_run") as persist:
            result = module.execute_pipeline(
                STAGES, "2026-08-04", "s3://safe/status.json", dry_run=True
            )
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["dry_run"])
        self.assertTrue(all(stage["status"] == "not_invoked" for stage in result["stages"]))
        client.invoke.assert_not_called()
        persist.assert_not_called()

    def test_handler_requires_status_destination(self):
        module = load_module()
        with patch.dict(
            os.environ,
            {"PIPELINE_STAGES_JSON": json.dumps(STAGES)},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                module.lambda_handler({}, None)

    def test_handler_raises_after_persisted_failure_for_scheduler_retry(self):
        module = load_module()
        failed_run = {
            "status": "failed",
            "failed_stage": "input_validation",
            "failure_category": "quality_gate_failed",
        }
        with patch.dict(
            os.environ,
            {
                "PIPELINE_STAGES_JSON": json.dumps(STAGES),
                "PIPELINE_STATUS_S3_URI": "s3://safe/status.json",
            },
            clear=True,
        ), patch.object(module, "execute_pipeline", return_value=failed_run):
            with self.assertRaisesRegex(RuntimeError, "quality_gate_failed"):
                module.lambda_handler({"logical_run_date": "2026-08-04"}, None)


if __name__ == "__main__":
    unittest.main()
