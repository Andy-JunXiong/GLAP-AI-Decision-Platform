"""Plan-only CLI and two-phase private callable acquisition; never invokes Lambda.

Live callable use needs separate read authority. No persistence, log/query reads,
package execution, retries, or reconstruction of a missing pre-run capture.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import json
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

try:
    from ops import validate_generator_release_binding as binding
except ModuleNotFoundError:
    import validate_generator_release_binding as binding

reader = binding.reader
require, exact, timestamp = reader.require, reader.exact, reader.timestamp
SCHEMA = "generator-release-acquisition-config.v1"
ALLOWED_CALLS = ("lambda:GetFunction", "lambda:GetFunctionConfiguration")
MAX_DOWNLOAD_SECONDS = 30


def utc_now():
    return datetime.now(timezone.utc)


def report_base():
    report = binding.report_base()
    report.update(schema_version="generator-release-acquisition-report.v1",
                  evidence_class="LOCAL_ACQUISITION_RECORD_CONSISTENCY_ONLY",
                  read_attempted=False)
    return report


def plan_summary():
    return {**report_base(), "status": "LOCAL_PLAN_ONLY",
            "allowed_calls": list(ALLOWED_CALLS), "max_get_function_calls": 1,
            "max_configuration_calls": 2, "max_package_downloads": 1,
            "max_zip_bytes": binding.MAX_ZIP_BYTES,
            "max_window_seconds": reader.MAX_WINDOW_SECONDS,
            "callable_reader_available": True, "cli_read_available": False}


def validate_config(config, now):
    exact(config, {"schema_version", "region", "logical_date", "function_version", "expectation"})
    require(config["schema_version"] == SCHEMA and config["region"] == reader.REGION,
            "INVALID_ACQUISITION_SCOPE")
    require(reader.matches(r"\$LATEST|[0-9]{1,20}", config["function_version"]), "INVALID_TARGET_VERSION")
    require(reader.evidence.iso_date(config["logical_date"]) ==
            now.astimezone(ZoneInfo("Australia/Sydney")).date(), "NOT_CURRENT_SYDNEY_DATE")
    expected = config["expectation"]
    exact(expected, {"source_commit", "artifact_sha256", "configuration_sha256", "request_parameters"})
    require(reader.matches(r"[a-f0-9]{40}", expected["source_commit"]) and
            all(reader.matches(r"[a-f0-9]{64}", expected[key]) for key in
                ("artifact_sha256", "configuration_sha256")), "INVALID_RELEASE_EXPECTATION")
    binding.validate_request(expected["request_parameters"])


def package_location(location):
    """Only regional AWS S3 HTTPS URLs returned by GetFunction; never caller URLs."""
    require(type(location) is str and 0 < len(location) <= 16384 and
            not re.search(r"[\s\\\x00-\x1f\x7f]", location), "INVALID_PACKAGE_LOCATION")
    url = urlsplit(location)
    require(url.scheme == "https" and url.username is None and url.password is None and
            url.port is None and not url.fragment and url.path.startswith("/") and url.query and
            reader.matches(r"(?:[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\.)?s3\.us-east-1\.amazonaws\.com",
                           url.netloc), "INVALID_PACKAGE_LOCATION")
    return url


def download_package(location):
    """One direct TLS GET; no redirects, proxies, decompression or credential headers."""
    url = package_location(location)
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    connection = http.client.HTTPSConnection(url.hostname, timeout=5)
    response = None
    try:
        connection.connect()
        transport = connection.sock
        transport.settimeout(10)
        connection.request("GET", url.path + "?" + url.query, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        require(response.status == 200, "PACKAGE_HTTP_STATUS_REJECTED")
        require(response.getheader("Content-Encoding") in (None, "identity") and
                response.getheader("Transfer-Encoding") is None, "PACKAGE_ENCODING_REJECTED")
        length = response.getheader("Content-Length")
        require(reader.matches(r"[0-9]{1,10}", length) and
                0 < int(length) <= binding.MAX_ZIP_BYTES, "PACKAGE_SIZE_REJECTED")
        chunks, received = [], 0
        while received < int(length):
            remaining = deadline - time.monotonic()
            require(remaining > 0, "PACKAGE_DOWNLOAD_DEADLINE")
            transport.settimeout(min(10, remaining))
            chunk = response.read1(min(65536, int(length) - received))
            require(bool(chunk), "PACKAGE_TRUNCATED")
            chunks.append(chunk)
            received += len(chunk)
        require(time.monotonic() <= deadline, "PACKAGE_DOWNLOAD_DEADLINE")
        return b"".join(chunks)
    finally:
        if response is not None:
            response.close()
        connection.close()


def lambda_client():
    import boto3
    from botocore.config import Config
    session = boto3.Session(region_name=reader.REGION)
    return session.client("lambda", config=Config(
        retries={"total_max_attempts": 1, "mode": "standard"}, connect_timeout=5, read_timeout=10,
        ignore_configured_endpoint_urls=True))


def selected_configuration(raw, config, captured):
    projected = binding.configuration_projection(raw)
    require(raw["Version"] == config["function_version"] and raw.get("State") == "Active" and
            raw.get("LastUpdateStatus") == "Successful", "CONFIGURATION_NOT_STABLE_OR_WRONG_VERSION")
    require(reader.matches(reader.UUID, raw.get("RevisionId")), "INVALID_CONFIGURATION_REVISION")
    require(timestamp(raw["LastModified"]) <= captured, "CONFIGURATION_MODIFIED_AFTER_CAPTURE")
    require(binding.decode_base64(raw["CodeSha256"], 32).hex() == config["expectation"]["artifact_sha256"],
            "LAMBDA_ARTIFACT_DIGEST_MISMATCH")
    require(binding.object_digest(projected) == config["expectation"]["configuration_sha256"],
            "CONFIGURATION_EXPECTATION_MISMATCH")
    # Discard non-projected AWS fields and raw errors; retain strict validator inputs only.
    return copy.deepcopy({**projected, **{key: raw[key] for key in
        ("CodeSha256", "RevisionId", "LastModified", "State", "LastUpdateStatus")}})


class CaptureSession:
    """Private, single-use in-memory state. Construct via start_capture, never serialize."""

    def __init__(self, config, client, clock, source_reader, archive, before, started):
        self._config, self._client, self._clock = config, client, clock
        self._source_reader, self._archive, self._before = source_reader, archive, before
        self._started, self._used = started, False

    def __repr__(self):
        return "<CaptureSession private>"

    def discard(self):
        self._used = True
        self._archive = self._before = self._config = None
        self._client = self._source_reader = self._clock = None

    def check_open_window(self):
        """Local preflight for composition; never reads AWS or returns private values."""
        require(not self._used, "CAPTURE_SESSION_CLOSED")
        now = self._clock()
        validate_config(self._config, now)
        require(timestamp(self._before["captured_at"]) <= now and
                (now - timestamp(self._before["captured_at"])).total_seconds() <= reader.MAX_WINDOW_SECONDS,
                "CAPTURE_WINDOW_EXPIRED")
        return now

    def check_reader_config(self, config):
        """Bind receipt read expectations to the frozen package/config BEFORE log access."""
        now = self.check_open_window()
        start, end = reader.validate_config(config)
        require(timestamp(self._before["captured_at"]) <= start < end <= now,
                "READER_WINDOW_NOT_WITHIN_CAPTURE")
        require(config["logical_date"] == self._config["logical_date"] and
                config["function_version"] == self._config["function_version"], "RECEIPT_TARGET_MISMATCH")
        env = self._before["configuration"]["Environment"]["Variables"]
        require(config["database"] == env["ATHENA_SOURCE_DATABASE"] and
                config["workgroup"] == env["ATHENA_WORKGROUP"], "READER_CONFIGURATION_SCOPE_MISMATCH")
        manifest = {name: hashlib.sha256(data).hexdigest()
                    for name, data in binding.zip_sources(self._archive).items()}
        expected = {"source_bundle_sha256": binding.object_digest(manifest),
                    "settings_sha256": binding.settings_digest(env),
                    "request_parameters_sha256": binding.object_digest(self._config["expectation"]["request_parameters"])}
        require(all(config[key] == value for key, value in expected.items()), "READER_EXPECTATION_MISMATCH")

    def finish(self, reader_config, private_bundle):
        """After the external run, capture once and validate; always destroy session state."""
        report = report_base()
        try:
            require(not self._used, "CAPTURE_SESSION_CLOSED")
            self._used = True  # Any failed finish is terminal; no retries.
            now = self._clock()
            validate_config(self._config, now)
            require(self._started <= now and
                    (now - timestamp(self._before["captured_at"])).total_seconds() <= reader.MAX_WINDOW_SECONDS,
                    "CAPTURE_WINDOW_EXPIRED")
            receipt = binding.validate_private_bundle(private_bundle, reader_config)
            require(receipt["logical_date"] == self._config["logical_date"] and
                    receipt["function_version"] == self._config["function_version"], "RECEIPT_TARGET_MISMATCH")
            require(timestamp(self._before["captured_at"]) <= timestamp(receipt["controller_link"]["run_started_at"])
                    and timestamp(receipt["finished_at"]) <= now, "RUN_NOT_BRACKETED")
            report["read_attempted"] = True
            # Only the post-run configuration read; no polling, invocation or receipt read.
            raw = self._client.get_function_configuration(
                FunctionName=reader.GENERATOR, Qualifier=self._config["function_version"])
            captured = self._clock()
            require(captured >= now, "CAPTURE_CLOCK_REVERSED")
            validate_config(self._config, captured)
            after = {"captured_at": captured.isoformat(),
                     "configuration": selected_configuration(raw, self._config, captured)}
            packet = {"schema_version": binding.SCHEMA, "input_kind": "SUPPLIED_STAGING_EXPORT",
                      "expectation": self._config["expectation"],
                      "artifact_zip_base64": base64.b64encode(self._archive).decode(),
                      "reader_config": reader_config, "private_bundle": private_bundle,
                      "configuration_before": self._before, "configuration_after": after}
            require(len(json.dumps(packet, allow_nan=False).encode()) <= binding.MAX_INPUT_BYTES,
                    "INPUT_TOO_LARGE")
            result = binding.validate_binding(packet, source_reader=self._source_reader)
            report.update({key: value for key, value in result.items() if key not in
                           ("schema_version", "evidence_class")})
        except Exception:
            # Never relay exception messages from SDK, HTTP, Git or caller objects.
            report["reasons"] = ["ACQUISITION_OR_BINDING_FAILED"]
        finally:
            self.discard()
        return report


def start_capture(config, *, client=None, downloader=None, clock=None, source_reader=None):
    """Acquire package and pre-run configuration. Returns (aggregate report, private session).

    Injection points are for trusted in-process tests/integration, never JSON input.
    The caller separately arranges the business run and existing receipt reader.
    """
    report = report_base()
    try:
        clock = clock or utc_now
        started = clock()
        config = copy.deepcopy(config)
        validate_config(config, started)  # Before SDK import, credentials or network.
        source_reader = source_reader or binding.read_commit_sources
        sources = source_reader(config["expectation"]["source_commit"])
        exact(sources, set(binding.FILES))
        require(all(type(data) is bytes and 0 < len(data) <= binding.MAX_SOURCE_BYTES
                    for data in sources.values()), "INVALID_COMMITTED_SOURCE_BYTES")
        binding.require_receipt_source(sources["lambda_function.py"])
        client = client if client is not None else lambda_client()
        target = {"FunctionName": reader.GENERATOR, "Qualifier": config["function_version"]}
        report["read_attempted"] = True
        response = client.get_function(**target)
        observed = clock()
        require(observed >= started, "CAPTURE_CLOCK_REVERSED")
        initial = selected_configuration(response["Configuration"], config, observed)
        require(type(response["Code"]) is dict and "Error" not in response["Code"], "PACKAGE_UNAVAILABLE")
        location = response["Code"]["Location"]
        package_location(location)
        archive = (downloader or download_package)(location)
        require(type(archive) is bytes and 0 < len(archive) <= binding.MAX_ZIP_BYTES,
                "PACKAGE_SIZE_REJECTED")
        require(hashlib.sha256(archive).hexdigest() == config["expectation"]["artifact_sha256"],
                "ARTIFACT_EXPECTATION_MISMATCH")
        require(binding.zip_sources(archive) == sources, "GIT_ZIP_BYTES_MISMATCH")
        pre_started = clock()
        require(observed <= pre_started and (pre_started - observed).total_seconds() <= MAX_DOWNLOAD_SECONDS,
                "PACKAGE_DOWNLOAD_DEADLINE")
        raw = client.get_function_configuration(**target)
        captured = clock()
        require(pre_started <= captured, "CAPTURE_CLOCK_REVERSED")
        validate_config(config, captured)
        before = {"captured_at": captured.isoformat(),
                  "configuration": selected_configuration(raw, config, captured)}
        require(before["configuration"] == initial, "CONFIGURATION_CHANGED_DURING_ACQUISITION")
        session = CaptureSession(config, client, clock, source_reader, archive, before, started)
        report.update(status="PRE_RUN_CAPTURE_READY", counts={"source_files": 4, "configuration_observations": 1})
        return report, session
    except Exception:
        report["reasons"] = ["PRE_RUN_ACQUISITION_FAILED"]
        return report, None


def main():
    report = plan_summary() if len(sys.argv) == 1 else report_base()
    if len(sys.argv) != 1:
        report["reasons"] = ["INVALID_ARGUMENTS"]
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "LOCAL_PLAN_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
