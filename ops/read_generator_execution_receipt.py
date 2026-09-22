"""Bounded private log/query-metadata reader. Default CLI is plan-only.

No query execution, result-row download, Lambda invocation, file output or
snapshot attribution. Returned private bundles must never enter public status.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    from ops import compare_learning_cardinality_evidence as evidence
except ModuleNotFoundError:
    import compare_learning_cardinality_evidence as evidence


SCHEMA = "generator-receipt-reader-config.v1"
REGION = "us-east-1"
GENERATOR = "glap-stateful-lifecycle-generator-staging"
CONTROLLER = "glap-stateful-lifecycle-controller-staging"
ALLOWED_CALLS = ("logs:FilterLogEvents", "athena:GetQueryExecution")
MAX_PAGES = 20
MAX_EVENTS = 200
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 16384
MAX_QUERIES = 256
MAX_WINDOW_SECONDS = 7200
UUID = r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"
READS = {"READ_TARGETS", "READ_ROUTES", "READ_RATES", "READ_FX", "READ_ACTIVE",
         "READ_ALERTS", "READ_ACTIONS", "READ_OUTCOMES", "READ_PROPOSALS"}
DIGESTS = {"source_bundle_sha256", "settings_sha256", "request_parameters_sha256"}
CONFIG_FIELDS = {"schema_version", "region", "logical_date", "invocation_id", "function_version",
                 "window_start", "window_end", "database", "workgroup"} | DIGESTS
RECEIPT_FIELDS = {"schema_version", "invocation_id", "function_name", "function_version",
    "controller_link", "controller_link_trusted", "logical_date", "temporal_context",
    "started_at", "finished_at", "status", "dry_run", "generated_counts",
    "planned_write_statements", "completed_write_statements", "queries", "complete",
    "runtime_verified", "snapshot_lineage_verified", "real_world_evidence"} | DIGESTS
QUERY_FIELDS = {"sequence", "purpose", "query_id", "statement_sha256", "started_at",
                "finished_at", "status", "athena_state", "result_reused"}
require, exact, timestamp = evidence.require, evidence.exact, evidence.timestamp


def matches(pattern: str, value: object) -> bool:
    return type(value) is str and re.fullmatch(pattern, value) is not None


def parse_json(raw: str | bytes) -> object:
    def invalid_constant(_: str) -> None:
        raise evidence.InvalidEvidence("NON_FINITE_JSON_NUMBER")
    return json.loads(raw, object_pairs_hook=evidence.unique_object, parse_constant=invalid_constant)


def validate_config(config: dict) -> tuple[datetime, datetime]:
    exact(config, CONFIG_FIELDS)
    require(config["schema_version"] == SCHEMA and config["region"] == REGION, "INVALID_READER_SCOPE")
    require(matches(UUID, config["invocation_id"]) and
            matches(r"\$LATEST|[0-9]{1,20}", config["function_version"]), "INVALID_TARGET_IDENTITY")
    require(config["database"] == "simulated_iceberg_m" and
            matches(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}", config["workgroup"]), "INVALID_QUERY_SCOPE")
    require(all(matches(r"[a-f0-9]{64}", config[key]) for key in DIGESTS), "INVALID_EXPECTED_DIGEST")
    start, end = timestamp(config["window_start"]), timestamp(config["window_end"])
    cutoff = evidence.iso_date(config["logical_date"])
    now = datetime.now(timezone.utc)
    require(cutoff <= now.astimezone(ZoneInfo("Australia/Sydney")).date(), "FUTURE_LOGICAL_DATE")
    require(start < end <= now and (end - start).total_seconds() <= MAX_WINDOW_SECONDS,
            "INVALID_READ_WINDOW")
    # v1 only binds runs actually executed on their logical business date.
    require(all(value.astimezone(ZoneInfo("Australia/Sydney")).date() == cutoff
                for value in (start, end)), "CROSS_DATE_READ_WINDOW")
    return start, end


def report_base() -> dict:
    return {
        "schema_version": "generator-receipt-reader-report.v1", "status": "UNVERIFIED",
        "evidence_class": "READ_RESPONSE_CONSISTENCY_ONLY", "reasons": [], "counts": None,
        "read_attempted": False, "runtime_verified": False, "aws_receipts_authenticated": False,
        "release_binding_verified": False, "snapshot_lineage_verified": False,
        "net_new_rows_verified": False, "real_world_evidence": False,
        "authority": evidence.empty_report()["authority"],
    }


def plan_summary() -> dict:
    return {**report_base(), "status": "LOCAL_PLAN_ONLY", "allowed_calls": list(ALLOWED_CALLS),
            "read_executor_available": True, "log_groups": 2, "max_pages_per_group": MAX_PAGES,
            "max_events_per_group": MAX_EVENTS, "max_bytes_per_group": MAX_LOG_BYTES,
            "max_query_metadata_reads": MAX_QUERIES, "max_window_seconds": MAX_WINDOW_SECONDS}


def read_log_records(client, function: str, pattern: str, start: datetime, end: datetime) -> list[dict]:
    """Fully exhaust a bounded filtered window, including empty intermediate pages."""
    require(function in (GENERATOR, CONTROLLER), "INVALID_LOG_SCOPE")
    lower, upper = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    base = {"logGroupName": "/aws/lambda/" + function, "startTime": lower,
            "endTime": upper, "filterPattern": pattern, "limit": 100, "unmask": False}
    token, tokens, events, size, received = None, set(), {}, 0, 0
    for _ in range(MAX_PAGES):
        response = client.filter_log_events(**base, **({"nextToken": token} if token else {}))
        require(type(response) is dict and type(response.get("events")) is list, "INVALID_LOG_PAGE")
        for event in response["events"]:
            received += 1
            require(received <= MAX_EVENTS, "LOG_EVENT_LIMIT")
            require(type(event) is dict and {"eventId", "logStreamName", "timestamp", "ingestionTime", "message"}
                    <= set(event), "INVALID_LOG_EVENT")
            require(all(type(event[key]) is str and 0 < len(event[key]) <= 512
                        for key in ("eventId", "logStreamName")), "INVALID_LOG_IDENTITY")
            require(type(event["timestamp"]) is int and lower <= event["timestamp"] < upper
                    and type(event["ingestionTime"]) is int and
                    event["timestamp"] <= event["ingestionTime"] <= int(datetime.now(timezone.utc).timestamp() * 1000),
                    "LOG_TIME_OUTSIDE_WINDOW")
            message = event["message"]
            require(type(message) is str, "INVALID_LOG_MESSAGE")
            size += len(message.encode())
            require(size <= MAX_LOG_BYTES, "LOG_BYTE_LIMIT")
            # Identical delivery of the same service event is harmless; different
            # service event IDs carrying a second target receipt are ambiguous.
            key = event["eventId"]
            saved = {field: event[field] for field in
                     ("eventId", "logStreamName", "timestamp", "ingestionTime", "message")}
            if key in events:
                require(events[key] == saved, "CONFLICTING_LOG_EVENT")
            events[key] = saved
        token = response.get("nextToken")
        if token is None:
            break
        require(type(token) is str and 0 < len(token) <= 1024 and token not in tokens,
                "INVALID_OR_REPEATED_LOG_TOKEN")
        tokens.add(token)
    else:
        raise evidence.InvalidEvidence("INCOMPLETE_LOG_PAGINATION")
    records = []
    for event in events.values():
        record = parse_json(event["message"])
        # The producer emits plain JSON. Also accept a bounded standard Lambda
        # application-log envelope, never regex-extract JSON from arbitrary text.
        wrapper_request = None
        if type(record) is dict and "message" in record:
            exact(record, {"timestamp", "level", "message", "requestId"})
            require(matches(UUID, record["requestId"]) and record["level"] == "INFO", "INVALID_LOG_ENVELOPE")
            require(start <= timestamp(record["timestamp"]) < end, "INVALID_LOG_ENVELOPE_TIME")
            wrapper_request = record["requestId"]
            record = parse_json(record["message"]) if type(record["message"]) is str else record["message"]
        require(type(record) is dict, "INVALID_LOG_RECORD")
        records.append({"record": record, "event_time_ms": event["timestamp"],
                        "stream": event["logStreamName"], "wrapper_request": wrapper_request})
    return records


def validate_receipt(receipt: dict, config: dict, start: datetime, end: datetime) -> None:
    exact(receipt, RECEIPT_FIELDS)
    require(receipt["schema_version"] == "generator-execution-receipt.v1" and
            receipt["function_name"] == GENERATOR and all(receipt[key] == config[key]
            for key in DIGESTS | {"invocation_id", "function_version", "logical_date"}), "RECEIPT_TARGET_MISMATCH")
    require(receipt["status"] == "SUCCEEDED" and receipt["complete"] is True and
            all(receipt[key] is False for key in ("dry_run", "controller_link_trusted",
                "runtime_verified", "snapshot_lineage_verified", "real_world_evidence")), "INCOMPLETE_RECEIPT")
    require(receipt["temporal_context"] == {"execution_mode": "OPERATIONAL", "time_basis": "ACTUAL_CALENDAR",
            "as_of_date": config["logical_date"], "scenario_id": None}, "INVALID_RECEIPT_TEMPORAL_SCOPE")
    link = receipt["controller_link"]
    require(link is not None, "UNLINKED_RECEIPT")
    exact(link, {"link_id", "run_started_at", "stage_started_at"})
    require(matches(r"[a-f0-9]{32}", link["link_id"]), "INVALID_CONTROLLER_LINK")
    begun, finished = timestamp(receipt["started_at"]), timestamp(receipt["finished_at"])
    require(start <= timestamp(link["run_started_at"]) <= timestamp(link["stage_started_at"])
            <= begun < finished < end, "INVALID_RECEIPT_WINDOW")
    counts = receipt["generated_counts"]
    exact(counts, {"outcomes", "proposals"})
    require(all(type(n) is int and 0 <= n <= evidence.MAX_ROWS for n in counts.values()), "INVALID_GENERATED_COUNTS")
    require(type(receipt["planned_write_statements"]) is int and type(receipt["completed_write_statements"]) is int
            and 0 <= receipt["planned_write_statements"] == receipt["completed_write_statements"] <= MAX_QUERIES,
            "INVALID_WRITE_COUNTS")
    queries = receipt["queries"]
    require(type(queries) is list and 9 <= len(queries) <= MAX_QUERIES, "INVALID_QUERY_COUNT")
    seen, reads, writes, previous = set(), set(), 0, begun
    for index, query in enumerate(queries, 1):
        exact(query, QUERY_FIELDS)
        require(type(query["sequence"]) is int and query["sequence"] == index and
                matches(UUID, query["query_id"]) and query["query_id"] not in seen and
                matches(r"[a-f0-9]{64}", query["statement_sha256"]), "INVALID_QUERY_IDENTITY")
        seen.add(query["query_id"])
        require(query["status"] == query["athena_state"] == "SUCCEEDED" and
                query["result_reused"] is False, "QUERY_FAILED_OR_REUSE_UNVERIFIED")
        query_start, query_finish = timestamp(query["started_at"]), timestamp(query["finished_at"])
        require(previous <= query_start <= query_finish <= finished, "INVALID_QUERY_WINDOW")
        previous = query_finish
        purpose = query["purpose"]
        if purpose in READS and purpose not in reads and not writes:
            reads.add(purpose)
        else:
            require(purpose == "WRITE_MERGE" and reads == READS, "INVALID_QUERY_PURPOSE_ORDER")
            writes += 1
    require(reads == READS and writes == receipt["completed_write_statements"], "WRITE_QUERY_COUNT_MISMATCH")


def validate_controller(records: list[dict], receipt: dict) -> None:
    require(len(records) == 2, "MISSING_OR_AMBIGUOUS_CONTROLLER_RECORDS")
    by_state = {item["record"].get("state"): item for item in records}
    require(set(by_state) == {"REQUESTED", "RETURNED"}, "INVALID_CONTROLLER_STATES")
    require(len({item["stream"] for item in records}) == 1, "CONTROLLER_STREAM_MISMATCH")
    wrappers = {item["wrapper_request"] for item in records if item["wrapper_request"] is not None}
    require(len(wrappers) <= 1, "CONTROLLER_ENVELOPE_MISMATCH")
    common = {"schema_version", "link_id", "run_started_at", "stage_started_at", "state", "logical_date", "runtime_verified"}
    for state, item in by_state.items():
        row = item["record"]
        exact(row, common | ({"receipt_state", "invocation_id", "query_count", "generated_outcomes", "generated_proposals"}
                             if state == "RETURNED" else set()))
        require(row["schema_version"] == "generator-controller-link.v1" and row["runtime_verified"] is False
                and row["logical_date"] == receipt["logical_date"] and
                all(row[key] == value for key, value in receipt["controller_link"].items()), "CONTROLLER_LINK_MISMATCH")
        if state == "RETURNED":
            require(row["receipt_state"] == "PRESENT_LOCALLY_VALIDATED" and
                    row["invocation_id"] == receipt["invocation_id"], "CONTROLLER_RECEIPT_UNAVAILABLE")
            for key, expected in {"query_count": len(receipt["queries"]),
                                  "generated_outcomes": receipt["generated_counts"]["outcomes"],
                                  "generated_proposals": receipt["generated_counts"]["proposals"]}.items():
                require(type(row[key]) is int and row[key] == expected, "CONTROLLER_COUNT_MISMATCH")
    require(by_state["REQUESTED"]["event_time_ms"] <= int(timestamp(receipt["started_at"]).timestamp() * 1000)
            and by_state["RETURNED"]["event_time_ms"] >= int(timestamp(receipt["finished_at"]).timestamp() * 1000),
            "CONTROLLER_EVENT_ORDER_MISMATCH")


def service_time(value: object) -> datetime:
    if isinstance(value, datetime):
        require(value.utcoffset() is not None, "INVALID_QUERY_SERVICE_TIME")
        return value.astimezone(timezone.utc)
    return timestamp(value)


def read_and_correlate(config: dict, logs_client, athena_client) -> dict:
    """Private callable result contains identifiers; never print or persist it."""
    start, end = validate_config(config)
    records = read_log_records(logs_client, GENERATOR,
        '"generator-execution-receipt.v1" "' + config["invocation_id"] + '"', start, end)
    require(len(records) == 1, "MISSING_OR_AMBIGUOUS_GENERATOR_RECEIPT")
    receipt = records[0]["record"]
    validate_receipt(receipt, config, start, end)
    require(records[0]["wrapper_request"] in (None, receipt["invocation_id"]), "GENERATOR_ENVELOPE_MISMATCH")
    require(records[0]["event_time_ms"] >= int(timestamp(receipt["finished_at"]).timestamp() * 1000),
            "GENERATOR_EVENT_PRECEDES_FINISH")
    linked = read_log_records(logs_client, CONTROLLER,
        '"generator-controller-link.v1" "' + receipt["controller_link"]["link_id"] + '"', start, end)
    validate_controller(linked, receipt)
    requested, returned = ({item["record"]["state"]: item for item in linked}[key]
                           for key in ("REQUESTED", "RETURNED"))
    require(int(timestamp(receipt["controller_link"]["stage_started_at"]).timestamp() * 1000)
            <= requested["event_time_ms"] <= records[0]["event_time_ms"] <= returned["event_time_ms"],
            "LOG_CORRELATION_TIME_MISMATCH")
    bound = []
    for query in receipt["queries"]:
        raw = athena_client.get_query_execution(QueryExecutionId=query["query_id"])["QueryExecution"]
        require(raw["QueryExecutionId"] == query["query_id"] and raw["WorkGroup"] == config["workgroup"]
                and raw["QueryExecutionContext"]["Database"] == config["database"], "QUERY_METADATA_SCOPE_MISMATCH")
        sql = raw["Query"]
        require(type(sql) is str and len(sql.encode()) <= 512 * 1024 and
                hashlib.sha256(sql.encode()).hexdigest() == query["statement_sha256"], "QUERY_STATEMENT_MISMATCH")
        require(raw["Status"]["State"] == "SUCCEEDED" and
                raw.get("Statistics", {}).get("ResultReuseInformation", {}).get("ReusedPreviousResult") is False,
                "QUERY_METADATA_FAILED_OR_REUSED")
        submitted = service_time(raw["Status"]["SubmissionDateTime"])
        completed = service_time(raw["Status"]["CompletionDateTime"])
        # Service timestamps may have only millisecond precision. Compare at
        # that precision; no multi-second skew or guessed times are accepted.
        millis = lambda value: int(value.timestamp() * 1000)
        require(millis(timestamp(query["started_at"])) <= millis(submitted) <= millis(completed)
                <= millis(timestamp(query["finished_at"])), "QUERY_METADATA_TIME_MISMATCH")
        bound.append({"query_id": query["query_id"], "purpose": query["purpose"],
                      "statement_sha256": query["statement_sha256"],
                      "submitted_at": submitted.isoformat(), "completed_at": completed.isoformat()})
    return {"schema_version": "generator-receipt-private-bundle.v1", "receipt": receipt,
            "bound_queries": bound, "controller_records": len(linked),
            "release_binding_verified": False, "snapshot_lineage_verified": False}


def collect_receipts(config: dict, logs_client, athena_client) -> dict:
    report = report_base()
    try:
        validate_config(config)
        report["read_attempted"] = True
        private = read_and_correlate(config, logs_client, athena_client)
        receipt = private["receipt"]
        report.update(status="RECEIPT_QUERY_RECORDS_CONSISTENT", counts={
            "generator_receipts": 1, "controller_records": private["controller_records"],
            "bound_queries": len(private["bound_queries"]),
            "acknowledged_write_statements": receipt["completed_write_statements"],
            "generated_outcomes": receipt["generated_counts"]["outcomes"],
            "generated_proposals": receipt["generated_counts"]["proposals"]})
    except evidence.InvalidEvidence as error:
        report["reasons"] = [str(error)]
    except Exception:
        report["reasons"] = ["READ_OR_RECORD_VALIDATION_FAILED"]
    return report


def main() -> int:
    if len(sys.argv) == 1:
        print(json.dumps(plan_summary(), sort_keys=True))
        return 0
    report = report_base()
    if sys.argv[1:] != ["--read"]:
        report["reasons"] = ["INVALID_ARGUMENTS"]
    else:
        try:
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            require(len(raw) <= MAX_INPUT_BYTES, "INPUT_TOO_LARGE")
            config = parse_json(raw)
            validate_config(config)  # Before loading SDK or resolving credentials.
            import boto3
            from botocore.config import Config
            session = boto3.Session(region_name=REGION)
            client_config = Config(retries={"total_max_attempts": 1, "mode": "standard"},
                                   connect_timeout=5, read_timeout=10)
            report = collect_receipts(config,
                session.client("logs", config=client_config), session.client("athena", config=client_config))
        except evidence.InvalidEvidence as error:
            report["reasons"] = [str(error)]
        except Exception:
            report["reasons"] = ["READ_SETUP_OR_INPUT_FAILED"]
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "RECEIPT_QUERY_RECORDS_CONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
