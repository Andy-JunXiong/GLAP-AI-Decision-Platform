"""Mocked AWS interactions only; no deployment, invocation or runtime claim."""

import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import sys
import types
import unittest
import uuid
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout

from test_lifecycle_athena_adapter import adapter
from test_pipeline_controller import load_module, response


REQUEST_ID = "00000000-0000-0000-0000-000000000999"
CONTEXT = types.SimpleNamespace(aws_request_id=REQUEST_ID,
    function_name="glap-stateful-lifecycle-generator-staging", function_version="$LATEST")


class FakeAthena:
    def __init__(self, fail_at=None, fail_results_at=None):
        self.statements = []
        self.fail_at = fail_at
        self.fail_results_at = fail_results_at
        self.stopped = []

    def start_query_execution(self, **kwargs):
        self.statements.append(kwargs["QueryString"])
        return {"QueryExecutionId": str(uuid.UUID(int=len(self.statements)))}

    def get_query_execution(self, QueryExecutionId):
        index = uuid.UUID(QueryExecutionId).int
        return {"QueryExecution": {
            "Status": {"State": "FAILED" if index == self.fail_at else "SUCCEEDED"},
            "Statistics": {"ResultReuseInformation": {"ReusedPreviousResult": False}},
        }}

    def get_query_results(self, QueryExecutionId, **kwargs):
        if uuid.UUID(QueryExecutionId).int == self.fail_results_at:
            raise RuntimeError("protected-backend-error")
        return {"ResultSet": {"Rows": []}}

    def stop_query_execution(self, **kwargs):
        self.stopped.append(kwargs)


def event():
    return {"logical_run_date": datetime.now(timezone.utc).astimezone(
        __import__("zoneinfo").ZoneInfo("Australia/Sydney")).date().isoformat(),
        "execution_mode": "OPERATIONAL", "dry_run": False}


def handler_with_fakes(data, client, context=CONTEXT, outcomes=1):
    closed = {"alerts": [], "actions": [], "proposals": [], "outcomes": [
        {"outcome_id": f"protected-entity-{index}", "dt": data["logical_run_date"]}
        for index in range(outcomes)]}
    fake_boto = types.SimpleNamespace(client=lambda name, **kwargs: client)
    generated = {"status": "ok", "snapshots": [], "events": [], "metrics": [], "signals": []}
    with patch.dict(sys.modules, {"boto3": fake_boto}), patch.object(
            adapter.engine, "run_day", return_value=generated), patch.object(
            adapter, "build_closed_loop_rows", return_value=closed):
        return adapter.lambda_handler(data, context)


class GeneratorExecutionReceiptTests(unittest.TestCase):
    def test_handler_records_runtime_identity_query_hashes_and_counts(self):
        client, output = FakeAthena(), io.StringIO()
        data = event()
        data["aws_request_id"] = "client-spoof"
        data["execution_receipt"] = {"private": "must-not-escape"}
        with redirect_stdout(output):
            result = handler_with_fakes(data, client)
        receipt = result["execution_receipt"]
        self.assertEqual(json.loads(output.getvalue()), receipt)
        self.assertEqual(receipt["invocation_id"], REQUEST_ID)
        self.assertEqual(receipt["status"], "SUCCEEDED")
        self.assertTrue(receipt["complete"])
        self.assertEqual(receipt["generated_counts"], {"outcomes": 1, "proposals": 0})
        self.assertEqual(receipt["planned_write_statements"], 1)
        self.assertEqual(receipt["completed_write_statements"], 1)
        self.assertEqual(len(receipt["queries"]), 10)
        for index, row in enumerate(receipt["queries"]):
            self.assertEqual(row["sequence"], index + 1)
            self.assertEqual(row["statement_sha256"], hashlib.sha256(client.statements[index].encode()).hexdigest())
            self.assertEqual(row["status"], "SUCCEEDED")
            self.assertFalse(row["result_reused"])
        for marker in ("protected-entity", "client-spoof", "must-not-escape", "MERGE INTO", "s3://"):
            self.assertNotIn(marker, output.getvalue())
        self.assertFalse(receipt["runtime_verified"])
        self.assertFalse(receipt["snapshot_lineage_verified"])
        self.assertFalse(receipt["controller_link_trusted"])

    def test_runtime_context_is_required_before_any_aws_call(self):
        for context in (None, types.SimpleNamespace(aws_request_id="spoof"),
                        types.SimpleNamespace(**{**CONTEXT.__dict__, "function_name": "other-function"})):
            client = FakeAthena()
            with self.assertRaisesRegex(ValueError, "runtime context"):
                handler_with_fakes(event(), client, context)
            self.assertEqual(client.statements, [])

    def test_future_date_and_invalid_dry_run_fail_before_queries(self):
        for change in ({"logical_run_date": "2099-01-01"}, {"dry_run": "false"}):
            client = FakeAthena()
            with self.assertRaises(ValueError):
                handler_with_fakes({**event(), **change}, client)
            self.assertEqual(client.statements, [])

    def test_dry_run_has_read_queries_but_no_write_completion_claim(self):
        client, output = FakeAthena(), io.StringIO()
        with redirect_stdout(output):
            result = handler_with_fakes({**event(), "dry_run": True}, client)
        receipt = result["execution_receipt"]
        self.assertEqual(len(client.statements), 9)
        self.assertEqual(receipt["status"], "DRY_RUN")
        self.assertFalse(receipt["complete"])
        self.assertEqual(receipt["completed_write_statements"], 0)
        self.assertEqual(receipt["planned_write_statements"], 1)

    def test_partial_write_failure_retains_prior_queries_and_never_claims_completion(self):
        client, output = FakeAthena(fail_at=11), io.StringIO()
        with redirect_stdout(output), self.assertRaises(RuntimeError):
            handler_with_fakes(event(), client, outcomes=101)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["status"], "FAILED")
        self.assertFalse(receipt["complete"])
        self.assertEqual(receipt["completed_write_statements"], 1)
        self.assertEqual(receipt["planned_write_statements"], 2)
        self.assertEqual(receipt["queries"][-1]["athena_state"], "FAILED")
        self.assertEqual(receipt["queries"][-1]["status"], "FAILED")
        self.assertEqual(len(client.statements), 11)

    def test_result_fetch_failure_does_not_erase_acknowledged_write_success(self):
        client, output = FakeAthena(fail_results_at=10), io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "protected-backend-error"):
            handler_with_fakes(event(), client)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["completed_write_statements"], 1)
        self.assertFalse(receipt["complete"])
        self.assertEqual(receipt["queries"][-1]["athena_state"], "SUCCEEDED")
        self.assertEqual(receipt["queries"][-1]["status"], "FAILED")
        self.assertNotIn("protected-backend-error", output.getvalue())

    def test_query_bound_is_checked_before_first_write(self):
        client, output = FakeAthena(), io.StringIO()
        with patch.object(adapter, "MAX_RECEIPT_QUERIES", 9), redirect_stdout(output), self.assertRaises(RuntimeError):
            handler_with_fakes(event(), client)
        self.assertEqual(len(client.statements), 9)
        self.assertEqual(json.loads(output.getvalue())["completed_write_statements"], 0)

    def test_query_timeout_is_recorded_and_not_retried(self):
        client = FakeAthena()
        client.get_query_execution = lambda **kwargs: {"QueryExecution": {"Status": {"State": "RUNNING"}}}
        receipt = {"queries": [], "completed_write_statements": 0}
        with patch.object(adapter.time, "monotonic", side_effect=[0, 181]), self.assertRaises(TimeoutError):
            adapter._trace_query(client, "SELECT protected", receipt, "READ_TARGETS")
        self.assertEqual(receipt["queries"][0]["status"], "TIMED_OUT")
        self.assertEqual(len(client.statements), 1)
        self.assertEqual(len(client.stopped), 1)

    def test_repeated_query_identity_fails_receipt_closed(self):
        client = FakeAthena()
        receipt = {"queries": [], "completed_write_statements": 0}
        adapter._trace_query(client, "SELECT 1", receipt, "READ_TARGETS")
        client.start_query_execution = lambda **kwargs: {"QueryExecutionId": str(uuid.UUID(int=1))}
        with self.assertRaisesRegex(RuntimeError, "identity repeated"):
            adapter._trace_query(client, "SELECT 2", receipt, "READ_ROUTES")
        self.assertEqual(receipt["queries"][-1]["status"], "FAILED")

    def test_source_digest_is_deterministic_and_covers_all_four_files(self):
        first = adapter._source_bundle_sha256()
        self.assertEqual(first, adapter._source_bundle_sha256())
        original = adapter.Path.read_bytes
        visited = []
        def altered(path):
            visited.append(path.name)
            value = original(path)
            return value + b"# fixture" if path.name == "glap_temporal_boundary.py" else value
        with patch.object(adapter.Path, "read_bytes", altered):
            self.assertNotEqual(first, adapter._source_bundle_sha256())
        self.assertEqual(len(visited), 4)

    def test_missing_reuse_metadata_is_unknown_not_false(self):
        client = FakeAthena()
        client.get_query_execution = lambda **kwargs: {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        receipt = {"queries": [], "completed_write_statements": 0}
        adapter._trace_query(client, "SELECT 1", receipt, "READ_TARGETS")
        self.assertIsNone(receipt["queries"][0]["result_reused"])

    def test_failed_logging_preserves_original_failure(self):
        with patch.object(adapter, "_emit_execution_receipt", side_effect=OSError("log-failed")):
            with self.assertRaisesRegex(RuntimeError, "Athena lifecycle query failed"):
                handler_with_fakes(event(), FakeAthena(fail_at=1))

    def test_successful_execution_cannot_return_success_when_receipt_emission_fails(self):
        with patch.object(adapter, "_emit_execution_receipt", side_effect=OSError("log-failed")):
            with self.assertRaisesRegex(OSError, "log-failed"):
                handler_with_fakes(event(), FakeAthena())

    def test_malformed_controller_link_is_rejected_before_queries(self):
        data = event()
        data["execution_link"] = {"link_id": "unbounded-protected-marker"}
        client = FakeAthena()
        with self.assertRaisesRegex(ValueError, "execution link"):
            handler_with_fakes(data, client)
        self.assertEqual(client.statements, [])

    def test_controller_binds_private_receipt_without_changing_public_run_status(self):
        client = MagicMock()
        module = load_module(lambda_client=client)
        athena = FakeAthena()
        events = []
        def invoke(**kwargs):
            data = json.loads(kwargs["Payload"])
            events.append(data)
            return response(handler_with_fakes(data, athena) if len(events) == 1 else {"status": "ok"})
        client.invoke.side_effect = invoke
        stages = [{"name": "stateful_lifecycle_generation", "function_name": CONTEXT.function_name, "quality_gate": False},
                  {"name": "next_stage", "function_name": "fixture-next", "quality_gate": False}]
        output = io.StringIO()
        temporal = adapter.resolve_temporal_context(event()["logical_run_date"], event())
        with redirect_stdout(output), patch.object(module, "persist_run") as persist:
            result = module.execute_pipeline(stages, event()["logical_run_date"], "s3://fixture/status",
                                             temporal_context=temporal)
        self.assertEqual(result["status"], "succeeded")
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[-1]["receipt_state"], "PRESENT_LOCALLY_VALIDATED")
        self.assertEqual(records[-1]["invocation_id"], REQUEST_ID)
        self.assertEqual(records[1]["controller_link"], events[0]["execution_link"])
        self.assertNotIn("execution_link", events[1])
        serialized = json.dumps(result) + repr(persist.call_args_list)
        for marker in (REQUEST_ID, "execution_receipt", "query_id", "source_bundle_sha256", "link_id", "protected-entity"):
            self.assertNotIn(marker, serialized)

    def test_controller_legacy_response_remains_explicitly_unavailable(self):
        client = MagicMock()
        client.invoke.return_value = response({"status": "ok"})
        module = load_module(lambda_client=client)
        output = io.StringIO()
        with redirect_stdout(output):
            module.invoke_stage({"name": "stateful_lifecycle_generation", "function_name": CONTEXT.function_name,
                                 "quality_gate": False}, event())
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1])["receipt_state"], "UNAVAILABLE_LEGACY")

    def test_controller_rejects_tampered_receipt_and_wrong_count_types(self):
        data = event()
        timestamp = datetime.now(timezone.utc).isoformat()
        data["execution_link"] = {"link_id": "a" * 32, "run_started_at": timestamp, "stage_started_at": timestamp}
        with redirect_stdout(io.StringIO()):
            body = handler_with_fakes(data, FakeAthena())
        data.update(body["execution_receipt"]["temporal_context"])
        module = load_module()
        stage = {"function_name": CONTEXT.function_name}
        mutations = [lambda b: b["execution_receipt"].update(controller_link=None),
                     lambda b: b["execution_receipt"].update(runtime_verified=True),
                     lambda b: b["execution_receipt"]["queries"][0].update(status="FAILED"),
                     lambda b: b.update(outcome_rows_created=True),
                     lambda b: b["execution_receipt"].update(complete=False)]
        for mutate in mutations:
            changed = copy.deepcopy(body)
            mutate(changed)
            with self.assertRaises(module.StageFailure):
                module._validate_generator_receipt(changed, stage, data, data["execution_link"])


if __name__ == "__main__":
    unittest.main()
