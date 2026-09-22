"""Composition tests with real producers/validators and synthetic AWS transports."""

import base64
import copy
from datetime import timedelta
import io
import json
import os
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from ops import collect_generator_release_evidence as collection
from test_generator_release_binding import fixture, BASE
from test_generator_receipt_reader import fixture as receipt_fixture, mutate_receipt


class GeneratorEvidenceCollectionTests(unittest.TestCase):
    def setUp(self):
        self.packet, self.sources = fixture()
        with patch.dict(os.environ, {"PIPELINE_ENVIRONMENT": "staging", "ALLOW_FUTURE_SIMULATION": "false"}):
            self.reader_config, self.logs, self.queries = receipt_fixture()
        self.config = {"schema_version": collection.acquisition.SCHEMA,
                       "region": collection.reader.REGION, "logical_date": self.reader_config["logical_date"],
                       "function_version": "$LATEST", "expectation": copy.deepcopy(self.packet["expectation"])}
        raw = self.packet["configuration_before"]["configuration"]
        self.lambda_client = Mock(spec=["get_function", "get_function_configuration"])
        self.location = "https://fixture-bucket.s3.us-east-1.amazonaws.com/package?signature=private"
        self.lambda_client.get_function.return_value = {"Code": {"Location": self.location},
                                                       "Configuration": copy.deepcopy(raw)}
        self.lambda_client.get_function_configuration.return_value = copy.deepcopy(raw)
        self.downloader = Mock(return_value=base64.b64decode(self.packet["artifact_zip_base64"]))
        self.moment = BASE
        self.clock = lambda: self.moment

    def start(self):
        return collection.start_collection(self.config, lambda_client=self.lambda_client,
                                           downloader=self.downloader, clock=self.clock,
                                           source_reader=lambda _: self.sources)

    def finish(self, session):
        self.moment = BASE + timedelta(seconds=150)
        return session.finish(self.reader_config, logs_client=self.logs, athena_client=self.queries)

    def assert_safe(self, report):
        for key in ("runtime_verified", "aws_receipts_authenticated", "human_review_authenticated",
                    "release_binding_verified", "mutable_revision_continuity_verified", "snapshot_lineage_verified",
                    "net_new_rows_verified", "real_world_evidence", "execution_available"):
            self.assertIs(report[key], False)
        self.assertFalse(any(report["authority"].values()))
        output = json.dumps(report)
        for marker in (self.location, self.reader_config["invocation_id"], "arn:", "s3://",
                       "MERGE INTO", "secret-detail", self.config["expectation"]["source_commit"]):
            self.assertNotIn(marker, output)

    def assert_unverified(self, report):
        self.assertEqual(report["status"], "UNVERIFIED", report)
        self.assertIsNone(report["counts"])
        self.assertFalse(any(report["checks"].values()))
        self.assert_safe(report)

    def test_complete_composition_uses_real_readers_and_one_external_run(self):
        report, session = self.start()
        capture = session._capture
        self.assertEqual(report["status"], "PRE_RUN_CAPTURE_READY")
        self.assertEqual(self.logs.calls, [])
        self.assertEqual(self.queries.calls, [])
        self.assert_safe(report)
        result = self.finish(session)
        self.assertEqual(result["schema_version"], "generator-evidence-collection-report.v1")
        self.assertEqual(result["status"], "RELEASE_BINDING_RECORDS_CONSISTENT", result)
        self.assertEqual(result["counts"], {"source_files": 4, "configuration_observations": 2, "bound_queries": 10})
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(len(self.logs.calls), 2)
        self.assertEqual(len(self.queries.calls), 10)
        self.assertEqual(self.lambda_client.get_function.call_count, 1)
        self.assertEqual(self.lambda_client.get_function_configuration.call_count, 2)
        self.assertIsNone(session._capture)
        self.assertIsNone(capture._archive)
        self.assertEqual(repr(session), "<EvidenceCollectionSession private>")
        self.assert_safe(result)

    def test_pre_capture_failure_never_creates_a_finish_handle(self):
        self.downloader.side_effect = RuntimeError("secret-detail")
        result, session = self.start()
        self.assert_unverified(result)
        self.assertIsNone(session)
        self.assertEqual(self.logs.calls, [])
        self.assertEqual(self.queries.calls, [])

    def test_all_digest_and_scope_mismatches_stop_before_client_factory(self):
        changes = {"source_bundle_sha256": "0" * 64, "settings_sha256": "0" * 64,
                   "request_parameters_sha256": "0" * 64, "workgroup": "other",
                   "function_version": "1", "logical_date": "2026-08-31",
                   "region": "other", "database": "other", "invocation_id": "not-a-uuid"}
        for key, value in changes.items():
            with self.subTest(key=key):
                self.setUp()
                _, session = self.start()
                self.moment = BASE + timedelta(seconds=150)
                self.reader_config[key] = value
                with patch.object(collection, "receipt_clients") as factory:
                    result = session.finish(self.reader_config)
                self.assert_unverified(result)
                self.assertFalse(result["read_attempted"])
                factory.assert_not_called()
                self.assertEqual(self.lambda_client.get_function_configuration.call_count, 1)

    def test_old_future_unfinished_or_expired_windows_cannot_read(self):
        for mode in ("old", "future", "unfinished", "expired", "cross_day"):
            with self.subTest(mode=mode):
                self.setUp()
                _, session = self.start()
                self.moment = BASE + timedelta(seconds=150)
                if mode == "old":
                    self.reader_config["window_start"] = (BASE - timedelta(seconds=1)).isoformat()
                elif mode == "future":
                    self.reader_config["window_end"] = "2099-01-01T00:00:00+00:00"
                elif mode == "unfinished":
                    self.moment = BASE + timedelta(seconds=50)
                elif mode == "expired":
                    self.moment = BASE + timedelta(hours=3)
                else:
                    self.moment = BASE + timedelta(days=1)
                result = session.finish(self.reader_config, logs_client=self.logs, athena_client=self.queries)
                self.assert_unverified(result)
                self.assertEqual(self.logs.calls, [])

    def test_missing_or_ambiguous_receipt_blocks_query_and_post_capture(self):
        for mode in ("missing", "duplicate"):
            self.setUp()
            _, session = self.start()
            events = self.logs.pages[collection.reader.GENERATOR][0]["events"]
            if mode == "missing":
                events.clear()
            else:
                events.append({**events[0], "eventId": "other-event"})
            result = self.finish(session)
            self.assert_unverified(result)
            self.assertTrue(result["read_attempted"])
            self.assertEqual(self.queries.calls, [])
            self.assertEqual(self.lambda_client.get_function_configuration.call_count, 1)

    def test_controller_disagreement_blocks_query_and_post_capture(self):
        _, session = self.start()
        self.logs.pages[collection.reader.CONTROLLER][0]["events"].pop()
        self.assert_unverified(self.finish(session))
        self.assertEqual(self.queries.calls, [])
        self.assertEqual(self.lambda_client.get_function_configuration.call_count, 1)

    def test_receipt_for_wrong_invocation_is_not_silently_substituted(self):
        _, session = self.start()
        mutate_receipt(self.logs, lambda receipt: receipt.update(invocation_id="00000000-0000-0000-0000-000000000099"))
        self.assert_unverified(self.finish(session))
        self.assertEqual(self.queries.calls, [])

    def test_query_hash_failure_blocks_post_capture_and_retry(self):
        _, session = self.start()
        next(iter(self.queries.queries.values()))["Query"] = "secret-detail"
        self.assert_unverified(self.finish(session))
        self.assertEqual(len(self.queries.calls), 1)
        self.assertEqual(self.lambda_client.get_function_configuration.call_count, 1)
        calls = (len(self.logs.calls), len(self.queries.calls))
        self.assert_unverified(self.finish(session))
        self.assertEqual((len(self.logs.calls), len(self.queries.calls)), calls)

    def test_post_configuration_drift_withholds_all_consistency_checks(self):
        _, session = self.start()
        self.lambda_client.get_function_configuration.return_value["RevisionId"] = "00000000-0000-0000-0000-000000000099"
        result = self.finish(session)
        self.assert_unverified(result)
        self.assertEqual(result["reasons"], ["CONFIGURATION_REVISION_CHANGED"])

    def test_mid_read_expiry_stops_before_more_calls(self):
        _, session = self.start()
        real_read = self.logs.filter_log_events
        def slow_read(**kwargs):
            response = real_read(**kwargs)
            self.moment = BASE + timedelta(hours=3)
            return response
        self.logs.filter_log_events = slow_read
        self.assert_unverified(self.finish(session))
        self.assertEqual(len(self.logs.calls), 1)
        self.assertEqual(self.queries.calls, [])
        self.assertEqual(self.lambda_client.get_function_configuration.call_count, 1)

    def test_service_errors_are_redacted_and_close_session(self):
        _, session = self.start()
        capture = session._capture
        self.logs.filter_log_events = Mock(side_effect=RuntimeError("secret-detail " + self.location))
        result = self.finish(session)
        self.assert_unverified(result)
        self.logs.filter_log_events.assert_called_once()
        self.assertIsNone(capture._archive)
        self.assertEqual(result["reasons"], ["COLLECTION_OR_CORRELATION_FAILED"])

    def test_client_setup_failure_or_incomplete_pair_does_not_read(self):
        for mode in ("setup", "pair"):
            self.setUp()
            _, session = self.start()
            self.moment = BASE + timedelta(seconds=150)
            with patch.object(collection, "receipt_clients", side_effect=RuntimeError("secret-detail")) as factory:
                if mode == "setup":
                    result = session.finish(self.reader_config)
                    factory.assert_called_once()
                else:
                    result = session.finish(self.reader_config, logs_client=self.logs)
                    factory.assert_not_called()
            self.assert_unverified(result)
            self.assertFalse(result["read_attempted"])
            self.assertEqual(self.logs.calls, [])

    def test_discard_releases_capture_and_never_reads_receipts(self):
        _, session = self.start()
        capture = session._capture
        session.discard()
        session.discard()
        self.assertIsNone(capture._archive)
        self.assert_unverified(self.finish(session))
        self.assertEqual(self.logs.calls, [])

    def test_caller_changes_cannot_replace_frozen_expectations(self):
        _, session = self.start()
        self.config["expectation"]["request_parameters"]["new_count"] = 999
        self.assertEqual(self.finish(session)["status"], "RELEASE_BINDING_RECORDS_CONSISTENT")

    def test_finish_config_is_copied_before_external_reader_runs(self):
        _, session = self.start()
        real_read = self.logs.filter_log_events
        def read_and_change_caller(**kwargs):
            self.reader_config["workgroup"] = "caller-mutated"
            return real_read(**kwargs)
        self.logs.filter_log_events = read_and_change_caller
        self.assertEqual(self.finish(session)["status"], "RELEASE_BINDING_RECORDS_CONSISTENT")

    def test_reentrant_finish_cannot_reuse_active_capture(self):
        _, session = self.start()
        real_read = self.logs.filter_log_events
        rejected = []
        def reentrant_read(**kwargs):
            rejected.append(session.finish(self.reader_config, logs_client=self.logs, athena_client=self.queries))
            return real_read(**kwargs)
        self.logs.filter_log_events = reentrant_read
        self.assertEqual(self.finish(session)["status"], "RELEASE_BINDING_RECORDS_CONSISTENT")
        self.assertEqual(len(rejected), 2)
        for result in rejected:
            self.assert_unverified(result)
            self.assertFalse(result["read_attempted"])
        self.assertEqual(self.lambda_client.get_function_configuration.call_count, 2)

    def test_receipt_clients_use_fixed_region_endpoints_and_one_attempt(self):
        factory = Mock()
        with patch.dict(sys.modules, {"boto3": types.SimpleNamespace(Session=factory),
                                      "botocore.config": types.SimpleNamespace(Config=types.SimpleNamespace)}):
            collection.receipt_clients()
        factory.assert_called_once_with(region_name=collection.reader.REGION)
        self.assertEqual([call.args for call in factory.return_value.client.call_args_list], [("logs",), ("athena",)])
        for call in factory.return_value.client.call_args_list:
            config = call.kwargs["config"]
            self.assertEqual(config.retries["total_max_attempts"], 1)
            self.assertEqual((config.connect_timeout, config.read_timeout), (5, 10))
            self.assertIs(config.ignore_configured_endpoint_urls, True)

    def test_plan_and_rejected_cli_flags_never_start_collection(self):
        for flags in ([], ["--read"], ["--invoke"]):
            with patch.object(sys, "argv", ["collector", *flags]), patch.object(collection, "start_collection") as start:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = collection.main()
            start.assert_not_called()
            result = json.loads(output.getvalue())
            self.assertEqual(code, 2 if flags else 0)
            self.assertEqual(result["status"], "UNVERIFIED" if flags else "LOCAL_PLAN_ONLY")
            self.assert_safe(result)
        result = subprocess.run([sys.executable, "ops/collect_generator_release_evidence.py"],
                                input="secret-detail", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("secret-detail", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
