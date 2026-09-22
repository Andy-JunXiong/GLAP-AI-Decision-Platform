"""Private two-phase composition of existing readers; CLI only renders a plan.

No invocation callback, polling, persistence, retries, authority or source-pin change.
Callables may read AWS only under separately granted human scope.
"""

from __future__ import annotations

import copy
import json
import sys

try:
    from ops import read_generator_release_evidence as acquisition
except ModuleNotFoundError:
    import read_generator_release_evidence as acquisition

reader = acquisition.reader
ALLOWED_CALLS = acquisition.ALLOWED_CALLS + reader.ALLOWED_CALLS


def report_base():
    return {**acquisition.report_base(), "schema_version": "generator-evidence-collection-report.v1",
            "evidence_class": "COMPOSED_READ_RECORD_CONSISTENCY_ONLY"}


def summarize(result):
    return {**result, "schema_version": "generator-evidence-collection-report.v1",
            "evidence_class": "COMPOSED_READ_RECORD_CONSISTENCY_ONLY"}


def plan_summary():
    return {**summarize(acquisition.plan_summary()), "allowed_calls": list(ALLOWED_CALLS),
            "log_groups": 2, "max_pages_per_group": reader.MAX_PAGES,
            "max_events_per_group": reader.MAX_EVENTS, "max_log_bytes_per_group": reader.MAX_LOG_BYTES,
            "max_query_metadata_reads": reader.MAX_QUERIES,
            "business_invocation_available": False, "persistence_available": False}


def receipt_clients():
    """Existing credential chain, fixed region, no custom endpoint or application retry."""
    import boto3
    from botocore.config import Config
    session = boto3.Session(region_name=reader.REGION)
    config = Config(retries={"total_max_attempts": 1, "mode": "standard"},
                    connect_timeout=5, read_timeout=10, ignore_configured_endpoint_urls=True)
    return session.client("logs", config=config), session.client("athena", config=config)


class _BoundedLogs:
    def __init__(self, client, capture):
        self.client, self.capture = client, capture

    def filter_log_events(self, **kwargs):
        self.capture.check_open_window()
        response = self.client.filter_log_events(**kwargs)
        self.capture.check_open_window()
        return response


class _BoundedQueries:
    def __init__(self, client, capture):
        self.client, self.capture = client, capture

    def get_query_execution(self, **kwargs):
        self.capture.check_open_window()
        response = self.client.get_query_execution(**kwargs)
        self.capture.check_open_window()
        return response


class EvidenceCollectionSession:
    """Single-use private handle. Actual external run must occur between start and finish."""

    def __init__(self, capture):
        self._capture = capture

    def __repr__(self):
        return "<EvidenceCollectionSession private>"

    def discard(self):
        if self._capture is not None:
            self._capture.discard()
        self._capture = None

    def finish(self, reader_config, *, logs_client=None, athena_client=None):
        """Read one supplied invocation, then post-capture and validate; no bundle escapes."""
        report = report_base()
        capture, self._capture = self._capture, None
        try:
            acquisition.require(capture is not None, "COLLECTION_SESSION_CLOSED")
            acquisition.require((logs_client is None) == (athena_client is None), "INCOMPLETE_CLIENT_PAIR")
            config = copy.deepcopy(reader_config)
            # Check scope and independently derived digests BEFORE SDK setup or log calls.
            capture.check_reader_config(config)
            if logs_client is None:
                logs_client, athena_client = receipt_clients()
            capture.check_open_window()
            report["read_attempted"] = True
            bundle = reader.read_and_correlate(config, _BoundedLogs(logs_client, capture),
                                               _BoundedQueries(athena_client, capture))
            result = capture.finish(config, bundle)
            report = summarize(result)
            report["read_attempted"] = True  # Even if post-capture preflight rejected the bundle.
        except Exception:
            report["reasons"] = ["COLLECTION_OR_CORRELATION_FAILED"]
        finally:
            if capture is not None:
                capture.discard()
        return report


def start_collection(config, *, lambda_client=None, downloader=None, clock=None, source_reader=None):
    """Start only package/pre-run capture; injected dependencies are trusted test seams."""
    report, capture = acquisition.start_capture(config, client=lambda_client, downloader=downloader,
                                               clock=clock, source_reader=source_reader)
    return summarize(report), EvidenceCollectionSession(capture) if capture is not None else None


def main():
    report = plan_summary() if len(sys.argv) == 1 else report_base()
    if len(sys.argv) != 1:
        report["reasons"] = ["INVALID_ARGUMENTS"]
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "LOCAL_PLAN_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
