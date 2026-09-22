"""Plan pinned staging queries and validate supplied result pages offline.

No AWS client, execution option, credential lookup, or file output. Private
queries/rows exist only in the callable interface; the CLI prints aggregates.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    from ops import compare_learning_cardinality_evidence as comparison
except ModuleNotFoundError:
    import compare_learning_cardinality_evidence as comparison


SCHEMA = "learning-evidence-collection-plan.v1"
PACKET_SCHEMA = "learning-evidence-result-pages.v1"
MAX_PAGES = 32
MAX_BYTES = 16 * 1024 * 1024
TABLES = {
    "outcomes": "fact_lifecycle_outcome_staging_v1",
    "proposals": "fact_policy_proposal_staging_v1",
}
FIELDS = {"outcomes": comparison.OUTCOME_FIELDS, "proposals": comparison.PROPOSAL_FIELDS}
CONFIG_FIELDS = {"schema_version", "phase", "logical_date", "database",
                 "outcome_snapshot_id", "proposal_snapshot_id"}
require = comparison.require
exact = comparison.exact


def validate_config(config: dict) -> None:
    exact(config, CONFIG_FIELDS)
    require(config["schema_version"] == SCHEMA and config["phase"] in ("BEFORE", "AFTER"),
            "INVALID_COLLECTION_PLAN")
    cutoff = comparison.iso_date(config["logical_date"])
    require(cutoff <= datetime.now(ZoneInfo("Australia/Sydney")).date(), "FUTURE_LOGICAL_DATE")
    require(type(config["database"]) is str and
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", config["database"]) is not None,
            "INVALID_DATABASE")
    for field in ("outcome_snapshot_id", "proposal_snapshot_id"):
        value = config[field]
        require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None
                and int(value) <= 2**63 - 1, "INVALID_SNAPSHOT_ID")


def render_queries(config: dict) -> dict[str, str]:
    """Private in-memory SQL only. Never execute or log these returned values."""
    validate_config(config)
    queries = {}
    for kind, table in TABLES.items():
        columns = ", ".join(f"CAST({field} AS VARCHAR) AS {field}"
                            for field in sorted(FIELDS[kind]))
        snapshot = config["outcome_snapshot_id" if kind == "outcomes" else "proposal_snapshot_id"]
        ordering = "outcome_id, dt" if kind == "outcomes" else "proposal_id"
        queries[kind] = (
            f"SELECT {columns} FROM {config['database']}.{table} "
            f"FOR VERSION AS OF {snapshot} "
            "WHERE temporal_scope_id = 'OPERATIONAL' "
            f"ORDER BY {ordering}"
        )
    return queries


def plan_summary() -> dict:
    return {
        "schema_version": SCHEMA,
        "status": "LOCAL_PLAN_ONLY",
        "evidence_class": "OFFLINE_INPUT_CONSISTENCY_ONLY",
        "data_queries_per_phase": 2,
        "phases": ["BEFORE", "AFTER"],
        "max_rows_per_table": comparison.MAX_ROWS,
        "max_pages_per_query": MAX_PAGES,
        "query_result_reuse_allowed": False,
        "athena_result_object_creation_required_if_executed": True,
        "snapshot_ids_externally_verified": False,
        "snapshot_metadata_acquisition_implemented": False,
        "cross_table_consistency_verified": False,
        "exclusive_window_verified": False,
        "generator_path_verified": False,
        "runtime_verified": False,
        "execution_available": False,
        "authority": comparison.empty_report()["authority"],
    }


def cell_value(cell: object) -> str | None:
    require(type(cell) is dict and set(cell) in (set(), {"VarCharValue"}), "INVALID_CELL")
    if not cell:
        return None
    value = cell["VarCharValue"]
    require(type(value) is str and len(value) <= 4096, "INVALID_CELL")
    return value


def typed_value(field: str, value: str | None) -> object:
    if value is None:
        return None
    if field == "observed_outcome_count":
        require(re.fullmatch(r"[0-9]{1,10}", value) is not None, "INVALID_INTEGER_CELL")
        return int(value)
    if field == "simulation_config_change":
        require(value in ("true", "false"), "INVALID_BOOLEAN_CELL")
        return value == "true"
    if field in ("effect_pct", "success_rate_pct"):
        try:
            result = float(value)
        except ValueError:
            raise comparison.InvalidEvidence("INVALID_NUMBER_CELL") from None
        require(math.isfinite(result), "INVALID_NUMBER_CELL")
        return result
    return value


def decode_query(kind: str, query: str, receipt: dict) -> list[dict]:
    """Check the supplied query binding and every page; establish no authenticity."""
    exact(receipt, {"execution", "pages"})
    execution = receipt["execution"]
    exact(execution, {"query_id", "query", "state", "engine_version", "result_reused"})
    query_id = execution["query_id"]
    require(type(query_id) is str and re.fullmatch(r"\S{1,128}", query_id) is not None,
            "INVALID_QUERY_ID")
    require(execution["query"] == query and execution["state"] == "SUCCEEDED" and
            execution["engine_version"] == "Athena engine version 3" and
            execution["result_reused"] is False, "QUERY_BINDING_OR_STATE_MISMATCH")
    pages = receipt["pages"]
    require(type(pages) is list and 0 < len(pages) <= MAX_PAGES, "INVALID_PAGE_COLLECTION")
    columns = sorted(FIELDS[kind])
    expected_token, seen_tokens, records = None, set(), []
    for page_index, page in enumerate(pages):
        exact(page, {"query_id", "request_token", "response"})
        require(page["query_id"] == query_id and page["request_token"] == expected_token,
                "PAGE_QUERY_OR_TOKEN_MISMATCH")
        response = page["response"]
        require(type(response) is dict and "ResultSet" in response and
                not (set(response) - {"ResultSet", "NextToken", "ResponseMetadata", "UpdateCount"}),
                "INVALID_PAGE_RESPONSE")
        if "UpdateCount" in response:
            require(type(response["UpdateCount"]) is int and response["UpdateCount"] == 0,
                    "UNEXPECTED_QUERY_WRITE")
        result_set = response["ResultSet"]
        exact(result_set, {"ResultSetMetadata", "Rows"})
        exact(result_set["ResultSetMetadata"], {"ColumnInfo"})
        metadata = result_set["ResultSetMetadata"]["ColumnInfo"]
        require(type(metadata) is list and len(metadata) == len(columns), "COLUMN_MISMATCH")
        for field, info in zip(columns, metadata):
            require(type(info) is dict and info.get("Name") == field and info.get("Type") == "varchar",
                    "COLUMN_MISMATCH")
        rows = result_set["Rows"]
        require(type(rows) is list and len(rows) <= 1000, "INVALID_PAGE_ROWS")
        for row_index, row in enumerate(rows):
            exact(row, {"Data"})
            require(type(row["Data"]) is list and len(row["Data"]) == len(columns),
                    "ROW_WIDTH_MISMATCH")
            values = [cell_value(cell) for cell in row["Data"]]
            if page_index == 0 and row_index == 0:
                require(values == columns, "MISSING_OR_INVALID_HEADER")
                continue
            records.append({field: typed_value(field, value)
                            for field, value in zip(columns, values)})
            require(len(records) <= comparison.MAX_ROWS, "ROW_LIMIT_EXCEEDED")
        require(page_index != 0 or bool(rows), "MISSING_OR_INVALID_HEADER")
        if "NextToken" in response:
            token = response["NextToken"]
            require(type(token) is str and 0 < len(token) <= 1024 and token not in seen_tokens,
                    "INVALID_OR_REPEATED_TOKEN")
            seen_tokens.add(token)
            expected_token = token
            require(page_index < len(pages) - 1, "INCOMPLETE_PAGINATION")
        else:
            require(page_index == len(pages) - 1, "EXTRA_PAGE_AFTER_COMPLETION")
            expected_token = None
    return records


def assemble_snapshot(packet: dict) -> dict:
    """Return a private comparator-shaped candidate, not trusted runtime evidence."""
    exact(packet, {"schema_version", "config", "captured_at", "release", "queries"})
    require(packet["schema_version"] == PACKET_SCHEMA, "INVALID_RESULT_PACKET")
    config = packet["config"]
    queries = render_queries(config)
    exact(packet["queries"], {"outcomes", "proposals"})
    require(packet["queries"]["outcomes"]["execution"]["query_id"] !=
            packet["queries"]["proposals"]["execution"]["query_id"], "QUERY_ID_REUSED")
    captured = comparison.timestamp(packet["captured_at"])
    cutoff = comparison.iso_date(config["logical_date"])
    require(captured <= datetime.now(timezone.utc) and
            captured.astimezone(ZoneInfo("Australia/Sydney")).date() == cutoff,
            "INVALID_CAPTURE_TIME")
    candidate = {"captured_at": packet["captured_at"], "cutoff_date": config["logical_date"],
                 "complete": True, "release": packet["release"]}
    for kind, query in queries.items():
        candidate[kind] = decode_query(kind, query, packet["queries"][kind])
    comparison.snapshot(candidate, cutoff)
    return candidate


def validate_packet(packet: object) -> dict:
    report = plan_summary()
    report.update(status="UNVERIFIED", reasons=[], row_counts=None)
    try:
        snapshot = assemble_snapshot(packet)
        report["row_counts"] = {kind: len(snapshot[kind]) for kind in TABLES}
        report["status"] = "SUPPLIED_PAGES_VALIDATED_OFFLINE"
    except comparison.InvalidEvidence as error:
        report["reasons"] = [str(error)]
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        report["reasons"] = ["INVALID_PACKET"]
    return report


def validate_json(raw: bytes) -> dict:
    try:
        require(len(raw) <= MAX_BYTES, "INPUT_TOO_LARGE")
        def reject_constant(_: str) -> None:
            raise comparison.InvalidEvidence("NON_FINITE_JSON_NUMBER")
        packet = json.loads(raw, object_pairs_hook=comparison.unique_object,
                            parse_constant=reject_constant)
        return validate_packet(packet)
    except comparison.InvalidEvidence as error:
        report = validate_packet(None)
        report["reasons"] = [str(error)]
        return report
    except (ValueError, TypeError, RecursionError):
        report = validate_packet(None)
        report["reasons"] = ["INVALID_JSON"]
        return report


def main() -> int:
    class SafeParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            report = validate_packet(None)
            report["reasons"] = ["INVALID_ARGUMENTS"]
            print(json.dumps(report, sort_keys=True))
            raise SystemExit(2)
    parser = SafeParser(description=__doc__)
    parser.add_argument("--validate-pages", action="store_true",
                        help="Validate supplied private page receipts from stdin offline")
    args = parser.parse_args()
    report = (validate_json(sys.stdin.buffer.read(MAX_BYTES + 1))
              if args.validate_pages else plan_summary())
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 2 if report["status"] == "UNVERIFIED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
