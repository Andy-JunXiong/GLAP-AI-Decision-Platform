"""Offline acquisition tests. All service and HTTP calls are synthetic."""

import base64
import copy
from datetime import timedelta
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from ops import read_generator_release_evidence as acquisition
from test_generator_release_binding import fixture, BASE


LOCATION = "https://fixture-bucket.s3.us-east-1.amazonaws.com/package?X-Amz-Signature=private"


class GeneratorReleaseAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.packet, self.sources = fixture()
        self.config = {"schema_version": acquisition.SCHEMA, "region": acquisition.reader.REGION,
                       "logical_date": self.packet["reader_config"]["logical_date"],
                       "function_version": "$LATEST", "expectation": copy.deepcopy(self.packet["expectation"])}
        self.raw = self.packet["configuration_before"]["configuration"]
        self.client = Mock(spec=["get_function", "get_function_configuration"])
        self.client.get_function.return_value = {"Code": {"Location": LOCATION}, "Configuration": copy.deepcopy(self.raw)}
        self.client.get_function_configuration.return_value = copy.deepcopy(self.raw)
        self.archive = base64.b64decode(self.packet["artifact_zip_base64"])
        self.downloader = Mock(return_value=self.archive)
        self.moment = BASE
        self.clock = lambda: self.moment
        self.loader = Mock(return_value=self.sources)

    def start(self):
        return acquisition.start_capture(self.config, client=self.client, downloader=self.downloader,
                                         clock=self.clock, source_reader=self.loader)

    def finish(self, session):
        self.moment = BASE + timedelta(seconds=100)
        return session.finish(self.packet["reader_config"], self.packet["private_bundle"])

    def assert_private(self, report):
        output = json.dumps(report)
        for value in (LOCATION, "arn:", "s3://", self.config["expectation"]["source_commit"],
                      self.packet["reader_config"]["invocation_id"], "secret-detail"):
            self.assertNotIn(value, output)
        self.assertFalse(any(report["authority"].values()))
        for key in ("runtime_verified", "aws_receipts_authenticated", "human_review_authenticated",
                    "release_binding_verified", "mutable_revision_continuity_verified", "snapshot_lineage_verified",
                    "net_new_rows_verified", "real_world_evidence", "execution_available"):
            self.assertIs(report[key], False)

    def test_two_phase_capture_composes_real_binding_without_invocation(self):
        report, session = self.start()
        self.assertEqual(report["status"], "PRE_RUN_CAPTURE_READY", report)
        self.assertFalse(any(report["checks"].values()))
        self.assertEqual(self.client.get_function_configuration.call_count, 1)
        self.assert_private(report)
        result = self.finish(session)
        self.assertEqual(result["status"], "RELEASE_BINDING_RECORDS_CONSISTENT", result)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(self.client.get_function.call_count, 1)
        self.assertEqual(self.client.get_function_configuration.call_count, 2)
        for call in self.client.method_calls:
            self.assertEqual(call.kwargs, {"FunctionName": acquisition.reader.GENERATOR, "Qualifier": "$LATEST"})
        self.downloader.assert_called_once_with(LOCATION)
        self.assert_private(result)
        self.assertIsNone(session._archive)
        self.assertEqual(repr(session), "<CaptureSession private>")

    def test_invalid_input_and_non_current_dates_fail_before_source_or_network(self):
        for key, value in (("region", "other"), ("logical_date", "2099-01-01"),
                           ("logical_date", "2026-08-31"), ("function_version", "prod"), ("url", LOCATION)):
            with self.subTest(key=key, value=value):
                config = copy.deepcopy(self.config)
                config[key] = value
                with patch.object(acquisition, "lambda_client") as factory:
                    result, session = acquisition.start_capture(config, clock=self.clock, source_reader=self.loader)
                self.assertEqual(result["status"], "UNVERIFIED")
                self.assertIsNone(session)
                self.assertFalse(result["read_attempted"])
                factory.assert_not_called()
                self.loader.assert_not_called()

    def test_missing_git_or_legacy_source_stops_before_aws(self):
        for failure in (True, False):
            if failure:
                self.loader.side_effect = RuntimeError("secret-detail")
            else:
                self.loader.side_effect = None
                self.loader.return_value = {**self.sources, "lambda_function.py": b"pass"}
            result, session = self.start()
            self.assertIsNone(session)
            self.client.get_function.assert_not_called()
            self.assert_private(result)

    def test_service_and_download_failures_are_sanitized_without_retry(self):
        for target in (self.client.get_function, self.downloader, self.client.get_function_configuration):
            with self.subTest(target=target):
                target.side_effect = RuntimeError("secret-detail " + LOCATION)
                result, session = self.start()
                self.assertIsNone(session)
                self.assertEqual(result["reasons"], ["PRE_RUN_ACQUISITION_FAILED"])
                self.assert_private(result)
                target.side_effect = None

    def test_invalid_location_is_rejected_before_downloader(self):
        for url in ("http://example.com/p?q=1", "https://127.0.0.1/p?q=1",
                    "https://s3.us-east-1.amazonaws.com.evil.test/p?q=1",
                    "https://user@s3.us-east-1.amazonaws.com/p?q=1", LOCATION + "#fragment",
                    "https://s3.us-east-1.amazonaws.com:443/p?q=1", LOCATION + "\n",
                    "https://fixture-bucket.s3.eu-west-1.amazonaws.com/p?q=1"):
            self.client.get_function.return_value["Code"]["Location"] = url
            result, session = self.start()
            self.assertIsNone(session)
            self.downloader.assert_not_called()
            self.assert_private(result)

    def test_artifact_mismatch_and_oversize_stop_before_configuration(self):
        for data in (b"wrong", self.archive + b"x", b"x" * (acquisition.binding.MAX_ZIP_BYTES + 1)):
            self.downloader.return_value = data
            result, session = self.start()
            self.assertIsNone(session)
            self.client.get_function_configuration.assert_not_called()
            self.assert_private(result)

    def test_unstable_or_wrong_configuration_stops_before_download(self):
        for field, value in (("State", "Pending"), ("Version", "1"), ("CodeSha256", "bad"),
                             ("MemorySize", 256), ("LastModified", "2099-01-01T00:00:00+00:00")):
            self.client.get_function.return_value["Configuration"] = {**self.raw, field: value}
            result, session = self.start()
            self.assertIsNone(session)
            self.downloader.assert_not_called()
            self.assert_private(result)

    def test_revision_changes_during_package_acquisition_are_rejected(self):
        self.client.get_function_configuration.return_value["RevisionId"] = "00000000-0000-0000-0000-000000000002"
        result, session = self.start()
        self.assertIsNone(session)
        self.assert_private(result)

    def test_changed_post_revision_fails_and_session_cannot_retry(self):
        _, session = self.start()
        self.client.get_function_configuration.return_value["RevisionId"] = "00000000-0000-0000-0000-000000000002"
        result = self.finish(session)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["reasons"], ["CONFIGURATION_REVISION_CHANGED"])
        self.assertIsNone(result["counts"])
        self.assertFalse(any(result["checks"].values()))
        result = self.finish(session)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(self.client.get_function_configuration.call_count, 2)
        self.assert_private(result)

    def test_missing_receipt_or_old_run_cannot_trigger_post_read(self):
        for mode in ("missing", "old", "unfinished", "expired", "cross_day"):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == "old":
                    self.moment = BASE + timedelta(seconds=50)
                _, session = self.start()
                self.moment = BASE + timedelta(seconds=100)
                if mode == "missing":
                    self.packet["private_bundle"] = {}
                elif mode == "unfinished":
                    self.moment = BASE + timedelta(seconds=4)
                elif mode == "expired":
                    self.moment = BASE + timedelta(hours=3)
                elif mode == "cross_day":
                    self.moment = BASE + timedelta(days=1)
                result = session.finish(self.packet["reader_config"], self.packet["private_bundle"])
                self.assertEqual(result["status"], "UNVERIFIED")
                self.assertEqual(self.client.get_function_configuration.call_count, 1)
                self.assertIsNone(session._archive)

    def test_clock_reversal_during_pre_capture_is_rejected(self):
        self.clock = Mock(side_effect=[BASE, BASE, BASE, BASE - timedelta(seconds=1)])
        result, session = self.start()
        self.assertIsNone(session)
        self.assertEqual(result["status"], "UNVERIFIED")

    def test_expectations_are_frozen_against_caller_mutation(self):
        _, session = self.start()
        self.config["expectation"]["artifact_sha256"] = "0" * 64
        self.assertEqual(self.finish(session)["status"], "RELEASE_BINDING_RECORDS_CONSISTENT")

    def test_discard_and_post_read_error_destroy_private_state(self):
        _, session = self.start()
        session.discard()
        self.assertEqual(self.finish(session)["status"], "UNVERIFIED")
        self.assertEqual(self.client.get_function_configuration.call_count, 1)
        _, session = self.start()
        self.client.get_function_configuration.side_effect = RuntimeError("secret-detail")
        result = self.finish(session)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIsNone(session._archive)
        self.assert_private(result)

    def test_cli_plan_and_invalid_flags_never_create_client_or_read_stdin(self):
        for flags, expected in (([], "LOCAL_PLAN_ONLY"), (["--read"], "UNVERIFIED"), (["--deploy"], "UNVERIFIED")):
            with patch.object(sys, "argv", ["reader", *flags]), patch.object(acquisition, "lambda_client") as factory:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = acquisition.main()
                report = json.loads(output.getvalue())
                self.assertEqual(report["status"], expected)
                self.assertEqual(code, 0 if not flags else 2)
                factory.assert_not_called()
                self.assert_private(report)

    def test_http_download_is_bounded_and_closes_transport(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda key: {"Content-Length": "3"}.get(key)
        response.read1.side_effect = [b"ab", b"c"]
        with patch.object(acquisition.http.client, "HTTPSConnection", return_value=connection) as factory:
            self.assertEqual(acquisition.download_package(LOCATION), b"abc")
        factory.assert_called_once_with("fixture-bucket.s3.us-east-1.amazonaws.com", timeout=5)
        self.assertEqual(connection.request.call_count, 1)
        connection.close.assert_called_once()
        response.close.assert_called_once()

    def test_redirect_error_encoding_oversize_and_truncation_are_not_retried(self):
        for mode in ("redirect", "error", "encoding", "chunked", "oversize", "missing_length", "truncated"):
            connection = Mock()
            response = connection.getresponse.return_value
            response.status = {"redirect": 302, "error": 403}.get(mode, 200)
            headers = {"Content-Length": "3"}
            if mode == "encoding":
                headers["Content-Encoding"] = "gzip"
            if mode == "chunked":
                headers["Transfer-Encoding"] = "chunked"
            if mode == "oversize":
                headers["Content-Length"] = str(acquisition.binding.MAX_ZIP_BYTES + 1)
            if mode == "missing_length":
                headers.clear()
            response.getheader.side_effect = headers.get
            response.read1.return_value = b""
            with patch.object(acquisition.http.client, "HTTPSConnection", return_value=connection):
                with self.assertRaises(acquisition.reader.evidence.InvalidEvidence):
                    acquisition.download_package(LOCATION)
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()

    def test_download_deadline_stops_before_reading_more_body(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda key: {"Content-Length": "3"}.get(key)
        with patch.object(acquisition.http.client, "HTTPSConnection", return_value=connection), \
                patch.object(acquisition.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaises(acquisition.reader.evidence.InvalidEvidence):
                acquisition.download_package(LOCATION)
        response.read1.assert_not_called()
        connection.close.assert_called_once()

    def test_sdk_factory_keeps_region_attempt_timeouts_and_service_endpoint(self):
        factory = Mock()
        with patch.dict(sys.modules, {"boto3": types.SimpleNamespace(Session=factory),
                                      "botocore.config": types.SimpleNamespace(Config=types.SimpleNamespace)}):
            acquisition.lambda_client()
        factory.assert_called_once_with(region_name=acquisition.reader.REGION)
        args, kwargs = factory.return_value.client.call_args
        self.assertEqual(args, ("lambda",))
        config = kwargs["config"]
        self.assertEqual(config.retries["total_max_attempts"], 1)
        self.assertEqual((config.connect_timeout, config.read_timeout), (5, 10))
        self.assertIs(config.ignore_configured_endpoint_urls, True)

    def test_oversized_composed_packet_fails_without_partial_positive(self):
        _, session = self.start()
        with patch.object(acquisition.binding, "MAX_INPUT_BYTES", 1):
            result = self.finish(session)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIsNone(result["counts"])
        self.assertFalse(any(result["checks"].values()))
        self.assertIsNone(session._archive)

    def test_changed_original_request_cannot_be_accepted_from_receipt(self):
        self.config["expectation"]["request_parameters"]["new_count"] = 3
        _, session = self.start()
        result = self.finish(session)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["reasons"], ["REQUEST_RECEIPT_DIGEST_MISMATCH"])
        self.assert_private(result)


if __name__ == "__main__":
    unittest.main()
