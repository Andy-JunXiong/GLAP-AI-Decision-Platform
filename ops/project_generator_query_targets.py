"""Offline source-bound MERGE target projection; no SQL or supplied-source execution."""

from __future__ import annotations

import ast
from datetime import date, datetime
import hashlib
import json
import math
import re
import sys

try:
    from ops import validate_generator_release_binding as binding
except ModuleNotFoundError:
    import validate_generator_release_binding as binding

SCHEMA = "generator-query-target-input.v1"
MAX_INPUT_BYTES = 24 * 1024 * 1024
MAX_SQL_BYTES = 512 * 1024
MAX_TOTAL_SQL_BYTES = 16 * 1024 * 1024
MAX_BATCH_ROWS = 100
# Full reviewed adapter bytes, with CRLF normalized only for this recipe check.
# Release binding still requires exact raw Git/ZIP bytes and the receipt digest.
REVIEWED_ADAPTER_SHA256 = "798e41080e378a3a4024e96035b1b73cf964c377c242241c89bde403f0d906dd"
FAMILIES = ("SNAPSHOT", "EVENT", "COST", "METRICS", "SIGNAL", "ALERT", "ACTION", "OUTCOME", "POLICY_PROPOSAL")
GAPS = ("SUPPLIED_RECORDS_NOT_AUTHENTICATED", "LIVE_QUERY_TARGET_COLLECTION_NOT_INTEGRATED",
        "QUERY_TO_COMMIT_BINDING_UNAVAILABLE", "COMPLETE_HISTORY_UNPROVEN", "WRITER_EXCLUSIVITY_UNPROVEN",
        "PINNED_ROWS_NOT_CHECKED", "ROW_VALUES_NOT_SEMANTICALLY_VALIDATED",
        "LEGACY_SOURCE_PIN_INCOMPATIBLE_WITH_RECEIPT_PRODUCER")
require, exact = binding.require, binding.exact


def report_base():
    return {"schema_version": "generator-query-target-report.v1", "status": "UNVERIFIED",
            "evidence_class": "OFFLINE_SOURCE_QUERY_SHAPE_CONSISTENCY_ONLY", "reasons": [], "counts": None,
            "gaps": list(GAPS), "runtime_verified": False, "release_binding_verified": False,
            "writer_binding_verified": False, "history_complete": False, "snapshot_lineage_verified": False,
            "net_new_rows_verified": False, "real_world_evidence": False, "execution_available": False,
            "authority": {**binding.report_base()["authority"], "aws_read": False,
                          "permission_change": False, "private_persistence": False, "source_pin_change": False}}


def plan_summary():
    return {**report_base(), "status": "LOCAL_PLAN_ONLY", "max_input_bytes": MAX_INPUT_BYTES,
            "max_sql_bytes": MAX_SQL_BYTES, "max_total_sql_bytes": MAX_TOTAL_SQL_BYTES,
            "max_queries": binding.reader.MAX_QUERIES, "max_batch_rows": MAX_BATCH_ROWS,
            "table_families": len(FAMILIES), "aws_calls": [], "source_execution_available": False}


def source_contract(source):
    """Parse the reviewed source as data only; never import, eval or compile it."""
    require(type(source) is bytes and len(source) <= binding.MAX_SOURCE_BYTES and
            hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest() == REVIEWED_ADAPTER_SHA256,
            "UNSUPPORTED_SOURCE_RECIPE")
    tree = ast.parse(source)
    assignments = {node.targets[0].id: node.value for node in tree.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}

    def columns(name):
        values = []
        for element in assignments[name].elts:
            if isinstance(element, ast.Starred):
                values.extend(columns(element.value.id))
            else:
                require(isinstance(element, ast.Constant) and type(element.value) is str, "INVALID_SOURCE_COLUMNS")
                values.append(element.value)
        return tuple(values)

    handler = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_execute_lifecycle")
    calls = {node.args[0].id: node for node in ast.walk(handler) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "build_merge_sql"}
    require(set(calls) == {family + "_TABLE" for family in FAMILIES}, "SOURCE_TARGET_INVENTORY_CHANGED")
    result = {}
    for family in FAMILIES:
        table_assignment = assignments[family + "_TABLE"]
        env_key, table = (arg.value for arg in table_assignment.args)
        call = calls[family + "_TABLE"]
        result[table] = {"columns": columns(call.args[1].id), "keys": tuple(item.value for item in call.args[2].elts),
                         "retry_updates": isinstance(call.args[4], ast.Name), "environment_key": env_key,
                         "family": "outcomes" if family == "OUTCOME" else "proposals" if family == "POLICY_PROPOSAL" else "other"}
    return result


NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:e[+-][0-9]+)?")


def literal_end(text, start):
    """Scan one generated literal; quoted SQL-like content is data, never syntax."""
    typed = next((prefix for prefix in ("DATE ", "TIMESTAMP ") if text.startswith(prefix, start)), "")
    pos = start + len(typed)
    if pos < len(text) and text[pos] == "'":
        first = pos
        pos += 1
        while pos < len(text):
            if text[pos] != "'":
                pos += 1
            elif pos + 1 < len(text) and text[pos + 1] == "'":
                pos += 2
            else:
                if typed:
                    value = text[first + 1:pos]
                    if typed == "DATE ":
                        require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value), "INVALID_TYPED_LITERAL")
                        date.fromisoformat(value)
                    else:
                        require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", value),
                                "INVALID_TYPED_LITERAL")
                        datetime.fromisoformat(value)
                return pos + 1
        require(False, "UNTERMINATED_LITERAL")
    require(not typed, "INVALID_TYPED_LITERAL")
    for keyword in ("NULL", "true", "false"):
        if text.startswith(keyword, start):
            return start + len(keyword)
    match = NUMBER.match(text, start)
    require(match is not None, "UNSUPPORTED_SQL_LITERAL")
    token = match.group()
    number = float(token) if "." in token or "e" in token else int(token)
    require((type(number) is int or math.isfinite(number)) and str(number) == token, "NONCANONICAL_NUMERIC_LITERAL")
    return match.end()


def batch_size(values, column_count):
    position, rows = 0, 0

    def consume(token):
        nonlocal position
        require(values.startswith(token, position), "MERGE_VALUES_SHAPE_MISMATCH")
        position += len(token)

    while position < len(values):
        require(rows < MAX_BATCH_ROWS, "MERGE_BATCH_LIMIT")
        consume("(")
        for column in range(column_count):
            if column:
                consume(", ")
            position = literal_end(values, position)
        consume(")")
        rows += 1
        if position == len(values):
            break
        consume(",\n")
        require(position < len(values), "MERGE_VALUES_SHAPE_MISMATCH")
    require(rows > 0, "EMPTY_MERGE_BATCH")
    return rows


def project_sql(sql, contract, retry):
    for table, rule in contract.items():
        prefix = f"MERGE INTO simulated_iceberg_m.{table} AS target\nUSING (VALUES\n"
        if not sql.startswith(prefix):
            continue
        columns, keys = rule["columns"], rule["keys"]
        names = ", ".join(columns)
        join = " AND ".join(f"target.{key} = source.{key}" for key in keys)
        update = ""
        if retry and rule["retry_updates"]:
            assignments = ", ".join(f"{column} = source.{column}" for column in columns if column not in keys)
            update = "\nWHEN MATCHED THEN UPDATE SET " + assignments
        suffix = (f"\n) AS source ({names})\nON {join}{update}\nWHEN NOT MATCHED THEN INSERT ({names}) VALUES ("
                  + ", ".join(f"source.{column}" for column in columns) + ")")
        require(sql.endswith(suffix), "MERGE_TEMPLATE_MISMATCH")
        count = batch_size(sql[len(prefix):-len(suffix)], len(columns))
        return {"database": "simulated_iceberg_m", "table": table, "family": rule["family"],
                "batch_row_count": count, "matched_update": bool(update)}
    require(False, "UNSUPPORTED_MERGE_TARGET_OR_HEADER")


def project_private(packet, source_reader=None):
    """Returns identifiers/hashes privately; callers must not log or persist them."""
    exact(packet, {"schema_version", "release_binding", "write_statements"})
    require(packet["schema_version"] == SCHEMA, "INVALID_TARGET_INPUT_CONTRACT")
    release = packet["release_binding"]
    require(len(json.dumps(release, ensure_ascii=False, allow_nan=False).encode()) <= binding.MAX_INPUT_BYTES,
            "RELEASE_PACKET_LIMIT")
    statements = packet["write_statements"]
    require(type(statements) is list and len(statements) <= binding.reader.MAX_QUERIES, "QUERY_LIMIT")
    sql_by_id, total = {}, 0
    for item in statements:
        exact(item, {"query_id", "sql"})
        require(binding.reader.matches(binding.reader.UUID, item["query_id"]) and item["query_id"] not in sql_by_id,
                "DUPLICATE_OR_INVALID_QUERY_ID")
        require(type(item["sql"]) is str and 0 < len(item["sql"].encode()) <= MAX_SQL_BYTES, "SQL_BYTE_LIMIT")
        total += len(item["sql"].encode())
        require(total <= MAX_TOTAL_SQL_BYTES, "TOTAL_SQL_BYTE_LIMIT")
        sql_by_id[item["query_id"]] = item["sql"]
    captured = {}

    def capture_sources(commit):
        sources = (source_reader or binding.read_commit_sources)(commit)
        captured.update(sources)
        return sources

    report = binding.validate_binding(release, source_reader=capture_sources)
    require(report["status"] == "RELEASE_BINDING_RECORDS_CONSISTENT", "RELEASE_RECORDS_UNVERIFIED")
    contract = source_contract(captured["lambda_function.py"])
    env = release["configuration_before"]["configuration"]["Environment"]["Variables"]
    require(env["ATHENA_SOURCE_DATABASE"] == "simulated_iceberg_m" and
            all(env.get(rule["environment_key"], table) == table for table, rule in contract.items()),
            "TARGET_CONFIGURATION_OUT_OF_SCOPE")
    receipt = release["private_bundle"]["receipt"]
    writes = [query for query in receipt["queries"] if query["purpose"] == "WRITE_MERGE"]
    require(set(sql_by_id) == {query["query_id"] for query in writes}, "INCOMPLETE_OR_EXTRA_WRITE_STATEMENTS")
    retry = release["expectation"]["request_parameters"]["retry_failed_run"] is True
    projected = []
    for query in writes:
        sql = sql_by_id[query["query_id"]]
        require(hashlib.sha256(sql.encode()).hexdigest() == query["statement_sha256"], "QUERY_STATEMENT_MISMATCH")
        target = project_sql(sql, contract, retry)
        projected.append({"query_id": query["query_id"], "statement_sha256": query["statement_sha256"], **target})
    order = [list(contract).index(item["table"]) for item in projected]
    require(order == sorted(order), "SOURCE_WRITE_ORDER_MISMATCH")
    for previous, following in zip(projected, projected[1:]):
        require(previous["table"] != following["table"] or previous["batch_row_count"] == MAX_BATCH_ROWS,
                "SOURCE_BATCH_BOUNDARY_MISMATCH")
    return {"schema_version": "generator-query-target-private.v1",
            "source_commit": release["expectation"]["source_commit"], "source_bundle_sha256": receipt["source_bundle_sha256"],
            "invocation_id": receipt["invocation_id"], "logical_date": receipt["logical_date"],
            "queries": projected, "gaps": list(GAPS), "runtime_verified": False,
            "writer_binding_verified": False, "history_complete": False, "snapshot_lineage_verified": False}


def project(packet, source_reader=None):
    report = report_base()
    try:
        private = project_private(packet, source_reader)
        queries = private["queries"]
        report.update(status="SOURCE_QUERY_TARGETS_CONSISTENT_WITH_GAPS", counts={
            "write_queries": len(queries), **{family + "_queries": sum(q["family"] == family for q in queries)
                                              for family in ("outcomes", "proposals", "other")}})
    except Exception:
        report["reasons"] = ["QUERY_TARGET_PROJECTION_REJECTED"]
    return report


def validate_json(raw):
    try:
        require(len(raw) <= MAX_INPUT_BYTES, "INPUT_BYTE_LIMIT")
        return project(binding.reader.parse_json(raw))
    except Exception:
        return {**report_base(), "reasons": ["QUERY_TARGET_INPUT_REJECTED"]}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        report = plan_summary()
    elif args == ["--project"]:
        try:
            report = validate_json(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
        except Exception:
            report = {**report_base(), "reasons": ["QUERY_TARGET_INPUT_REJECTED"]}
    else:
        report = {**report_base(), "reasons": ["INVALID_ARGUMENTS"]}
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] in ("LOCAL_PLAN_ONLY", "SOURCE_QUERY_TARGETS_CONSISTENT_WITH_GAPS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
