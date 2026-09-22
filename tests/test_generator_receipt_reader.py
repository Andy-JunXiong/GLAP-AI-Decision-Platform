"""Synthetic service-response scenarios; never connects to AWS."""

import copy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

from ops import read_generator_execution_receipt as reader
from test_generator_execution_receipt import adapter, handler_with_fakes, FakeAthena, CONTEXT
from test_pipeline_controller import load_module


BASE = datetime(2026, 9, 1, 1, tzinfo=timezone.utc)


def log_event(record, identity, moment, stream="fixture-stream"):
    return {"eventId": identity, "logStreamName": stream, "timestamp": int(moment.timestamp() * 1000),
            "ingestionTime": int((moment + timedelta(seconds=1)).timestamp() * 1000),
            "message": json.dumps(record)}


class LogClient:
    def __init__(self, generator, controller):
        self.pages = {reader.GENERATOR: [{"events": generator}], reader.CONTROLLER: [{"events": controller}]}
        self.calls = []
        self.positions = {reader.GENERATOR: 0, reader.CONTROLLER: 0}

    def filter_log_events(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["logGroupName"].rsplit("/", 1)[-1]
        index = self.positions[name]
        self.positions[name] += 1
        return copy.deepcopy(self.pages[name][index])


class QueryClient:
    def __init__(self, queries):
        self.queries, self.calls = queries, []

    def get_query_execution(self, **kwargs):
        self.calls.append(kwargs)
        return {"QueryExecution": copy.deepcopy(self.queries[kwargs["QueryExecutionId"]])}


def fixture():
    data = {"logical_run_date": "2026-09-01", "dry_run": False,
            "execution_mode": "OPERATIONAL", "time_basis": "ACTUAL_CALENDAR",
            "as_of_date": "2026-09-01", "scenario_id": None,
            "execution_link": {"link_id": "a" * 32, "run_started_at": BASE.isoformat(),
                               "stage_started_at": (BASE + timedelta(seconds=2)).isoformat()}}
    ticks = iter((BASE + timedelta(seconds=5 + index * 3)).isoformat() for index in range(30))
    client = FakeAthena()
    temporal = {key: data[key] for key in ("execution_mode", "time_basis", "as_of_date", "scenario_id")}
    with patch.object(adapter, "_receipt_timestamp", side_effect=lambda: next(ticks)), patch.object(
            adapter, "resolve_temporal_context", return_value=temporal), redirect_stdout(io.StringIO()):
        body = handler_with_fakes(data, client)
    receipt = body["execution_receipt"]
    module = load_module()
    summary = module._validate_generator_receipt(body, {"function_name": CONTEXT.function_name}, data, data["execution_link"])
    common = {"schema_version": "generator-controller-link.v1", **data["execution_link"],
              "logical_date": data["logical_run_date"], "runtime_verified": False}
    finish = reader.timestamp(receipt["finished_at"])
    logs = LogClient([log_event(receipt, "fixture-generator", finish + timedelta(milliseconds=100))], [
        log_event({**common, "state": "REQUESTED"}, "fixture-request", BASE + timedelta(seconds=3)),
        log_event({**common, "state": "RETURNED", **summary}, "fixture-return", finish + timedelta(milliseconds=200))])
    queries = {}
    for query, sql in zip(receipt["queries"], client.statements):
        queries[query["query_id"]] = {
            "QueryExecutionId": query["query_id"], "Query": sql, "WorkGroup": "primary",
            "QueryExecutionContext": {"Database": "simulated_iceberg_m"},
            "Status": {"State": "SUCCEEDED",
                       "SubmissionDateTime": reader.timestamp(query["started_at"]) + timedelta(seconds=1),
                       "CompletionDateTime": reader.timestamp(query["finished_at"]) - timedelta(seconds=1)},
            "Statistics": {"ResultReuseInformation": {"ReusedPreviousResult": False}},
            "ResultConfiguration": {"OutputLocation": "s3://protected-fixture/must-not-escape"}}
    config = {"schema_version": reader.SCHEMA, "region": reader.REGION, "logical_date": data["logical_run_date"],
              "invocation_id": receipt["invocation_id"], "function_version": receipt["function_version"],
              "window_start": BASE.isoformat(), "window_end": (BASE + timedelta(seconds=120)).isoformat(),
              "database": "simulated_iceberg_m", "workgroup": "primary",
              **{key: receipt[key] for key in reader.DIGESTS}}
    return config, logs, QueryClient(queries)


def mutate_receipt(logs, mutation):
    event = logs.pages[reader.GENERATOR][0]["events"][0]
    receipt = json.loads(event["message"])
    mutation(receipt)
    event["message"] = json.dumps(receipt)


class GeneratorReceiptReaderTests(unittest.TestCase):
    def assert_unverified(self, report, reason=None):
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertIsNone(report["counts"])
        if reason:
            self.assertEqual(report["reasons"], [reason])

    def test_real_producer_and_controller_receipt_correlates_with_query_metadata(self):
        config, logs, queries = fixture()
        report = reader.collect_receipts(config, logs, queries)
        self.assertEqual(report["status"], "RECEIPT_QUERY_RECORDS_CONSISTENT", report)
        self.assertEqual(report["counts"]["bound_queries"], 10)
        self.assertEqual(report["counts"]["acknowledged_write_statements"], 1)
        self.assertEqual(len(logs.calls), 2)
        self.assertEqual(len(queries.calls), 10)
        for call in logs.calls:
            self.assertFalse(call["unmask"])
            self.assertEqual(call["limit"], 100)
        for key in ("runtime_verified", "aws_receipts_authenticated", "release_binding_verified",
                    "snapshot_lineage_verified", "net_new_rows_verified", "real_world_evidence"):
            self.assertIs(report[key], False)
        self.assertFalse(any(report["authority"].values()))
        rendered = json.dumps(report)
        for marker in (config["invocation_id"], config["source_bundle_sha256"], reader.GENERATOR,
                       "fixture", "s3://", "MERGE INTO", "protected-entity"):
            self.assertNotIn(marker, rendered)

    def test_private_bundle_omits_sql_and_storage_paths(self):
        config, logs, queries = fixture()
        bundle = reader.read_and_correlate(config, logs, queries)
        self.assertEqual(len(bundle["bound_queries"]), 10)
        self.assertIn(config["invocation_id"], json.dumps(bundle))
        self.assertNotIn("MERGE INTO", json.dumps(bundle))
        self.assertNotIn("s3://", json.dumps(bundle))

    def test_empty_intermediate_page_and_duplicate_delivery_are_handled(self):
        config, logs, queries = fixture()
        final = logs.pages[reader.GENERATOR][0]
        logs.pages[reader.GENERATOR] = [
            {"events": [], "nextToken": "page-two"},
            {"events": final["events"], "nextToken": "page-three"}, final]
        self.assertEqual(reader.collect_receipts(config, logs, queries)["status"], "RECEIPT_QUERY_RECORDS_CONSISTENT")
        self.assertEqual(logs.calls[1]["nextToken"], "page-two")
        self.assertEqual(logs.calls[2]["nextToken"], "page-three")

    def test_repeated_token_never_loops_or_reaches_metadata(self):
        config, logs, queries = fixture()
        logs.pages[reader.GENERATOR] = [{"events": [], "nextToken": "repeat"}] * 2
        self.assert_unverified(reader.collect_receipts(config, logs, queries), "INVALID_OR_REPEATED_LOG_TOKEN")
        self.assertEqual(len(logs.calls), 2)
        self.assertFalse(queries.calls)

    def test_page_event_and_byte_bounds_fail_closed(self):
        for bound, value, reason in (("MAX_PAGES", 1, "INCOMPLETE_LOG_PAGINATION"),
                                     ("MAX_EVENTS", 0, "LOG_EVENT_LIMIT"),
                                     ("MAX_LOG_BYTES", 1, "LOG_BYTE_LIMIT")):
            with self.subTest(bound=bound):
                config, logs, queries = fixture()
                if bound == "MAX_PAGES":
                    logs.pages[reader.GENERATOR][0]["nextToken"] = "more"
                with patch.object(reader, bound, value):
                    self.assert_unverified(reader.collect_receipts(config, logs, queries), reason)
                self.assertFalse(queries.calls)

    def test_distinct_duplicate_receipts_and_conflicting_event_identity_are_rejected(self):
        for same_identity in (False, True):
            config, logs, queries = fixture()
            events = logs.pages[reader.GENERATOR][0]["events"]
            duplicate = copy.deepcopy(events[0])
            if same_identity:
                duplicate["message"] += " "
            else:
                duplicate["eventId"] = "second-event"
            events.append(duplicate)
            expected = "CONFLICTING_LOG_EVENT" if same_identity else "MISSING_OR_AMBIGUOUS_GENERATOR_RECEIPT"
            self.assert_unverified(reader.collect_receipts(config, logs, queries), expected)

    def test_absent_legacy_receipt_remains_unverified(self):
        config, logs, queries = fixture()
        logs.pages[reader.GENERATOR] = [{"events": []}]
        self.assert_unverified(reader.collect_receipts(config, logs, queries), "MISSING_OR_AMBIGUOUS_GENERATOR_RECEIPT")
        self.assertFalse(queries.calls)

    def test_invalid_configuration_prevents_all_calls(self):
        for field, value in (("region", "other"), ("database", "production"),
                             ("logical_date", "2099-01-01"), ("invocation_id", '" escape'),
                             ("window_end", "2099-01-01T00:00:00Z"),
                             ("window_start", "2026-08-31T00:00:00Z"),
                             ("source_bundle_sha256", "not-a-digest")):
            with self.subTest(field=field):
                config, logs, queries = fixture()
                config[field] = value
                report = reader.collect_receipts(config, logs, queries)
                self.assert_unverified(report)
                self.assertFalse(report["read_attempted"])
                self.assertFalse(logs.calls or queries.calls)

    def test_log_outside_window_is_rejected(self):
        config, logs, queries = fixture()
        logs.pages[reader.GENERATOR][0]["events"][0]["timestamp"] = 0
        self.assert_unverified(reader.collect_receipts(config, logs, queries), "LOG_TIME_OUTSIDE_WINDOW")

    def test_receipt_identity_digest_and_scope_must_match(self):
        for field, value in (("source_bundle_sha256", "0" * 64), ("settings_sha256", "0" * 64),
                             ("function_version", "99"), ("invocation_id", "00000000-0000-0000-0000-000000000001"),
                             ("logical_date", "2026-09-02")):
            config, logs, queries = fixture()
            mutate_receipt(logs, lambda r: r.update({field: value}))
            self.assert_unverified(reader.collect_receipts(config, logs, queries), "RECEIPT_TARGET_MISMATCH")

    def test_failed_dry_unlinked_and_falsely_trusted_receipts_fail(self):
        for field, value in (("status", "FAILED"), ("dry_run", True), ("runtime_verified", True),
                             ("complete", False), ("controller_link", None)):
            config, logs, queries = fixture()
            mutate_receipt(logs, lambda r: r.update({field: value}))
            self.assert_unverified(reader.collect_receipts(config, logs, queries))
            self.assertFalse(queries.calls)

    def test_duplicate_out_of_order_and_reused_queries_fail(self):
        mutations = [lambda r: r["queries"][1].update(query_id=r["queries"][0]["query_id"]),
                     lambda r: r["queries"][0].update(purpose="WRITE_MERGE"),
                     lambda r: r["queries"][0].update(result_reused=None),
                     lambda r: r["queries"][0].update(result_reused=True),
                     lambda r: r.update(completed_write_statements=True)]
        for mutate in mutations:
            config, logs, queries = fixture()
            mutate_receipt(logs, mutate)
            self.assert_unverified(reader.collect_receipts(config, logs, queries))
            self.assertFalse(queries.calls)

    def test_missing_ambiguous_and_wrong_controller_links_fail(self):
        for mode in ("missing", "duplicate", "link", "count", "stream", "order"):
            config, logs, queries = fixture()
            events = logs.pages[reader.CONTROLLER][0]["events"]
            if mode == "missing":
                events.pop()
            elif mode == "duplicate":
                extra = copy.deepcopy(events[-1]); extra["eventId"] = "extra"
                events.append(extra)
            elif mode in ("link", "count"):
                row = json.loads(events[-1]["message"])
                row.update({"link_id": "b" * 32} if mode == "link" else {"generated_outcomes": True})
                events[-1]["message"] = json.dumps(row)
            elif mode == "stream":
                events[-1]["logStreamName"] = "different-stream"
            else:
                events[-1]["timestamp"] = events[0]["timestamp"]
            self.assert_unverified(reader.collect_receipts(config, logs, queries))
            self.assertFalse(queries.calls)

    def test_standard_json_log_envelope_and_request_binding(self):
        for wrong_request in (False, True):
            config, logs, queries = fixture()
            event = logs.pages[reader.GENERATOR][0]["events"][0]
            event["message"] = json.dumps({"timestamp": datetime.fromtimestamp(event["timestamp"] / 1000, timezone.utc).isoformat(),
                "level": "INFO", "message": event["message"],
                "requestId": "00000000-0000-0000-0000-000000000001" if wrong_request else config["invocation_id"]})
            result = reader.collect_receipts(config, logs, queries)
            if wrong_request:
                self.assert_unverified(result, "GENERATOR_ENVELOPE_MISMATCH")
            else:
                self.assertEqual(result["status"], "RECEIPT_QUERY_RECORDS_CONSISTENT")

    def test_truncated_json_and_duplicate_keys_fail_without_exposing_log(self):
        for message in ('{"private":"secret",', '{"schema_version":"one","schema_version":"two"}'):
            config, logs, queries = fixture()
            logs.pages[reader.GENERATOR][0]["events"][0]["message"] = message
            report = reader.collect_receipts(config, logs, queries)
            self.assert_unverified(report)
            self.assertNotIn("secret", json.dumps(report))

    def test_changed_sql_scope_or_query_identity_fails_metadata_binding(self):
        for field, value in (("Query", "SELECT protected-secret"), ("WorkGroup", "different"),
                             ("QueryExecutionId", "other"), ("QueryExecutionContext", {"Database": "other"})):
            config, logs, queries = fixture()
            next(iter(queries.queries.values()))[field] = value
            report = reader.collect_receipts(config, logs, queries)
            self.assert_unverified(report)
            self.assertEqual(len(queries.calls), 1)
            self.assertNotIn("protected-secret", json.dumps(report))

    def test_missing_reuse_and_failed_service_state_are_unverified(self):
        for mode in ("reuse", "missing", "failed"):
            config, logs, queries = fixture()
            query = next(iter(queries.queries.values()))
            if mode == "failed":
                query["Status"]["State"] = "FAILED"
            else:
                query["Statistics"] = {} if mode == "missing" else {"ResultReuseInformation": {"ReusedPreviousResult": True}}
            self.assert_unverified(reader.collect_receipts(config, logs, queries), "QUERY_METADATA_FAILED_OR_REUSED")

    def test_service_times_must_fit_actual_query_window(self):
        config, logs, queries = fixture()
        next(iter(queries.queries.values()))["Status"]["SubmissionDateTime"] = BASE
        self.assert_unverified(reader.collect_receipts(config, logs, queries), "QUERY_METADATA_TIME_MISMATCH")

    def test_millisecond_service_precision_is_supported(self):
        config, logs, queries = fixture()
        for query in queries.queries.values():
            for key in ("SubmissionDateTime", "CompletionDateTime"):
                query["Status"][key] = query["Status"][key].isoformat(timespec="milliseconds")
        self.assertEqual(reader.collect_receipts(config, logs, queries)["status"], "RECEIPT_QUERY_RECORDS_CONSISTENT")

    def test_service_error_is_sanitized_without_retry(self):
        config, logs, queries = fixture()
        with patch.object(logs, "filter_log_events", side_effect=RuntimeError("s3://protected-error")) as call:
            report = reader.collect_receipts(config, logs, queries)
        self.assert_unverified(report, "READ_OR_RECORD_VALIDATION_FAILED")
        self.assertEqual(call.call_count, 1)
        self.assertNotIn("protected", json.dumps(report))

    def test_cli_defaults_to_redacted_plan_without_aws_sdk(self):
        result = subprocess.run([sys.executable, "ops/read_generator_execution_receipt.py"],
                                capture_output=True, text=True, check=True)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "LOCAL_PLAN_ONLY")
        self.assertFalse(plan["read_attempted"])
        self.assertEqual(set(plan["allowed_calls"]), {"logs:FilterLogEvents", "athena:GetQueryExecution"})
        self.assertNotIn(reader.GENERATOR, result.stdout)

    def test_cli_rejects_extra_flags_and_bad_input_without_echoing_it(self):
        for args, data in ((["--execute"], ""), (["--read"], '{"secret":"must-not-escape"}')):
            result = subprocess.run([sys.executable, "ops/read_generator_execution_receipt.py", *args],
                                    input=data, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assert_unverified(json.loads(result.stdout))
            self.assertNotIn("must-not-escape", result.stdout + result.stderr)

    def test_read_cli_uses_existing_sdk_session_only_for_two_bounded_clients(self):
        config, logs, queries = fixture()
        created, options = [], []
        class Session:
            def __init__(self, **kwargs):
                options.append(kwargs)

            def client(self, service, **kwargs):
                created.append(service)
                return {"logs": logs, "athena": queries}[service]
        def sdk_config(**kwargs):
            options.append(kwargs)
            return object()
        modules = {"boto3": types.SimpleNamespace(Session=Session),
                   "botocore.config": types.SimpleNamespace(Config=sdk_config)}
        stdin = types.SimpleNamespace(buffer=io.BytesIO(json.dumps(config).encode()))
        output = io.StringIO()
        with patch.dict(sys.modules, modules), patch.object(sys, "argv", ["reader", "--read"]), \
                patch.object(sys, "stdin", stdin), redirect_stdout(output):
            self.assertEqual(reader.main(), 0)
        self.assertEqual(created, ["logs", "athena"])
        self.assertEqual(options[0], {"region_name": "us-east-1"})
        self.assertEqual(options[1]["retries"]["total_max_attempts"], 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "RECEIPT_QUERY_RECORDS_CONSISTENT")
        self.assertNotIn(config["invocation_id"], output.getvalue())


if __name__ == "__main__":
    unittest.main()
