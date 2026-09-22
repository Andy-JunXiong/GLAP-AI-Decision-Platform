"""Offline consistency checks binding supplied snapshots, queries and a run.

This is not an AWS receipt authenticator or executor. All runtime/authority
claims remain false, even when the supplied evidence is internally consistent.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    from ops import compare_learning_cardinality_evidence as comparison
    from ops import prepare_learning_evidence_collection as collection
except ModuleNotFoundError:
    import compare_learning_cardinality_evidence as comparison
    import prepare_learning_evidence_collection as collection


SCHEMA = "learning-evidence-provenance-input.v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOTS = 100
FUNCTION_NAME = "glap-stateful-lifecycle-generator-staging"
RUN_FIELDS = {
    "run_id", "invocation_id", "function_name", "logical_date", "release",
    "started_at", "finished_at", "status", "dry_run", "write_statements",
    "outcome_rows_created", "policy_proposal_rows_created",
    "execution_mode", "time_basis", "scenario_id", "as_of_date",
}
TABLE_FIELDS = {
    "database", "table", "table_uuid_before", "table_uuid_after",
    "schema_sha256_before", "schema_sha256_after", "history_complete",
    "snapshots", "before", "after",
}
SNAPSHOT_FIELDS = {
    "snapshot_id", "parent_snapshot_id", "committed_at", "writer_invocation_id",
    "table_uuid", "schema_sha256",
}
FENCE_FIELDS = {
    "opened_at", "closed_at", "head_at_open", "head_at_close",
    "query_started_at", "query_finished_at", "query_id",
}
require = comparison.require
exact = comparison.exact


def private_id(value: object) -> None:
    require(type(value) is str and re.fullmatch(r"\S{1,128}", value) is not None,
            "INVALID_PRIVATE_BINDING")


def snapshot_id(value: object) -> None:
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None
            and int(value) <= 2**63 - 1, "INVALID_SNAPSHOT_ID")


def digest(value: object) -> None:
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
            "INVALID_SCHEMA_DIGEST")


def report_base() -> dict:
    return {
        "schema_version": "learning-evidence-provenance-report.v1",
        "status": "UNVERIFIED",
        "evidence_class": "OFFLINE_INPUT_CONSISTENCY_ONLY",
        "reasons": [],
        "counts": None,
        "comparison": None,
        "aws_receipts_authenticated": False,
        "snapshot_ids_externally_verified": False,
        "cross_table_consistency_verified": False,
        "exclusive_window_verified": False,
        "generator_path_verified": False,
        "runtime_verified": False,
        "historical_anomaly_resolved": False,
        "real_world_evidence": False,
        "execution_available": False,
        "authority": comparison.empty_report()["authority"],
    }


def validate_table(kind: str, table: dict, before: dict, after: dict, run: dict) -> dict:
    exact(table, TABLE_FIELDS)
    require(table["history_complete"] is True, "INCOMPLETE_SNAPSHOT_HISTORY")
    require(table["database"] == before["config"]["database"] == after["config"]["database"]
            and table["table"] == collection.TABLES[kind], "TABLE_BINDING_MISMATCH")
    for suffix in ("before", "after"):
        private_id(table["table_uuid_" + suffix])
        digest(table["schema_sha256_" + suffix])
    require(table["table_uuid_before"] == table["table_uuid_after"] and
            table["schema_sha256_before"] == table["schema_sha256_after"],
            "TABLE_IDENTITY_OR_SCHEMA_CHANGED")
    start = comparison.timestamp(run["started_at"])
    finish = comparison.timestamp(run["finished_at"])
    field = "outcome_snapshot_id" if kind == "outcomes" else "proposal_snapshot_id"
    heads, times = {}, {}
    for phase, packet in (("before", before), ("after", after)):
        fence = table[phase]
        exact(fence, FENCE_FIELDS)
        head = packet["config"][field]
        require(fence["head_at_open"] == fence["head_at_close"] == head,
                "COLLECTION_HEAD_CHANGED_OR_UNBOUND")
        require(fence["query_id"] == packet["queries"][kind]["execution"]["query_id"],
                "QUERY_RECEIPT_UNBOUND")
        opened = comparison.timestamp(fence["opened_at"])
        closed = comparison.timestamp(fence["closed_at"])
        query_start = comparison.timestamp(fence["query_started_at"])
        query_end = comparison.timestamp(fence["query_finished_at"])
        captured = comparison.timestamp(packet["captured_at"])
        require(opened <= query_start < query_end <= closed <= captured,
                "INVALID_COLLECTION_WINDOW")
        require(all(value.astimezone(ZoneInfo("Australia/Sydney")).date() ==
                    comparison.iso_date(run["logical_date"])
                    for value in (opened, query_start, query_end, closed)),
                "CROSS_DATE_COLLECTION_WINDOW")
        if phase == "before":
            require(captured < start, "BASELINE_OVERLAPS_RUN")
        else:
            require(finish < opened, "AFTER_COLLECTION_OVERLAPS_RUN")
        heads[phase] = head
        times[phase] = (opened, query_start, query_end, closed)
    history = table["snapshots"]
    require(type(history) is list and 0 < len(history) <= MAX_SNAPSHOTS,
            "INVALID_SNAPSHOT_HISTORY")
    seen, prior = set(), None
    for index, node in enumerate(history):
        exact(node, SNAPSHOT_FIELDS)
        snapshot_id(node["snapshot_id"])
        if node["parent_snapshot_id"] is not None:
            snapshot_id(node["parent_snapshot_id"])
        require(node["snapshot_id"] not in seen and
                node["parent_snapshot_id"] != node["snapshot_id"], "DUPLICATE_OR_CYCLIC_SNAPSHOT")
        seen.add(node["snapshot_id"])
        committed = comparison.timestamp(node["committed_at"])
        require(node["table_uuid"] == table["table_uuid_before"] and
                node["schema_sha256"] == table["schema_sha256_before"],
                "SNAPSHOT_IDENTITY_OR_SCHEMA_MISMATCH")
        if node["writer_invocation_id"] is not None:
            private_id(node["writer_invocation_id"])
        if index == 0:
            require(node["snapshot_id"] == heads["before"] and
                    committed <= times["before"][0], "BASELINE_SNAPSHOT_UNBOUND")
        else:
            require(node["parent_snapshot_id"] == prior["snapshot_id"],
                    "SNAPSHOT_LINEAGE_GAP_OR_BRANCH")
            require(comparison.timestamp(prior["committed_at"]) <= committed and
                    start <= committed <= finish, "COMMIT_OUTSIDE_TARGET_RUN")
            require(node["writer_invocation_id"] == run["invocation_id"],
                    "UNATTRIBUTED_OR_OTHER_WRITER")
        prior = node
    require(history[0]["parent_snapshot_id"] not in seen, "DUPLICATE_OR_CYCLIC_SNAPSHOT")
    require(history[-1]["snapshot_id"] == heads["after"], "AFTER_SNAPSHOT_UNBOUND")
    # Returning to the original head cannot conceal supplied intervening commits.
    require(heads["before"] != heads["after"] or len(history) == 1, "SNAPSHOT_ROLLBACK")
    return {"times": times, "new_snapshots": len(history) - 1}


def validate_evidence(evidence: object) -> dict:
    report = report_base()
    try:
        exact(evidence, {"schema_version", "input_kind", "before", "after", "run", "tables"})
        require(evidence["schema_version"] == SCHEMA and
                evidence["input_kind"] in ("SYNTHETIC_FIXTURE", "SUPPLIED_STAGING_EXPORT"),
                "INVALID_PROVENANCE_CONTRACT")
        before, after, run = evidence["before"], evidence["after"], evidence["run"]
        exact(run, RUN_FIELDS)
        for field in ("run_id", "invocation_id"):
            private_id(run[field])
        require(run["function_name"] == FUNCTION_NAME and run["status"] == "SUCCEEDED"
                and run["dry_run"] is False, "INVALID_TARGET_INVOCATION")
        require(run["execution_mode"] == "OPERATIONAL" and
                run["time_basis"] == "ACTUAL_CALENDAR" and run["scenario_id"] is None and
                run["as_of_date"] == run["logical_date"], "INVALID_INVOCATION_SCOPE")
        comparison.release(run["release"])
        start, finish = comparison.timestamp(run["started_at"]), comparison.timestamp(run["finished_at"])
        require(start < finish <= datetime.now(timezone.utc), "INVALID_RUN_WINDOW")
        for field in ("write_statements", "outcome_rows_created", "policy_proposal_rows_created"):
            require(type(run[field]) is int and 0 <= run[field] <= comparison.MAX_ROWS,
                    "INVALID_RUN_COUNTS")
        require(run["write_statements"] > 0, "MISSING_WRITE_PATH_EVIDENCE")
        snapshots = {}
        query_ids = set()
        for phase, packet in (("before", before), ("after", after)):
            snapshots[phase] = collection.assemble_snapshot(packet)
            require(packet["config"]["phase"] == phase.upper() and
                    packet["config"]["logical_date"] == run["logical_date"] and
                    packet["release"] == run["release"], "PHASE_DATE_OR_RELEASE_MISMATCH")
            for receipt in packet["queries"].values():
                query_id = receipt["execution"]["query_id"]
                require(query_id not in query_ids, "QUERY_REUSED_ACROSS_PHASES")
                query_ids.add(query_id)
        exact(evidence["tables"], {"outcomes", "proposals"})
        tables = evidence["tables"]
        require(tables["outcomes"]["table_uuid_before"] != tables["proposals"]["table_uuid_before"],
                "TABLE_IDENTITIES_COLLIDE")
        checked = {kind: validate_table(kind, table, before, after, run)
                   for kind, table in tables.items()}
        for phase in ("before", "after"):
            windows = [value["times"][phase] for value in checked.values()]
            require(max(t[0] for t in windows) <= min(t[1] for t in windows) and
                    max(t[2] for t in windows) <= min(t[3] for t in windows),
                    "NO_SHARED_COLLECTION_FENCE")
        candidate = {
            "schema_version": comparison.SCHEMA, "input_kind": evidence["input_kind"],
            "before": snapshots["before"], "after": snapshots["after"],
            "run": {field: run[field] for field in
                    ("started_at", "finished_at", "logical_date", "release")},
        }
        # These flags mean the supplied receipts passed the local checks above.
        # The nested and outer reports still explicitly deny runtime verification.
        candidate["run"].update(generator_path_completed=True, exclusive_window=True)
        comparison_report = comparison.compare_evidence(candidate)
        require(comparison_report["status"] != "UNVERIFIED", "COMPARISON_UNVERIFIED")
        old_versions = {(row["outcome_id"], row["dt"]) for row in snapshots["before"]["outcomes"]}
        new_versions = {(row["outcome_id"], row["dt"]) for row in snapshots["after"]["outcomes"]}
        created = len(new_versions - old_versions)
        old_proposals = {row["proposal_id"] for row in snapshots["before"]["proposals"]}
        for row in snapshots["after"]["outcomes"]:
            if (row["outcome_id"], row["dt"]) not in old_versions:
                require(row["dt"] == row["as_of_date"] == run["logical_date"],
                        "NEW_ROW_DATE_MISMATCH")
        for row in snapshots["after"]["proposals"]:
            if row["proposal_id"] not in old_proposals:
                require(row["created_date"] == row["as_of_date"] == run["logical_date"],
                        "NEW_ROW_DATE_MISMATCH")
        require(run["outcome_rows_created"] == created and
                run["policy_proposal_rows_created"] == comparison_report["counts"]["new_proposals"],
                "RUN_COUNTS_DISAGREE_WITH_ROWS")
        # Identical snapshot IDs must yield identical full rows, including order-independent duplicates.
        for kind in collection.TABLES:
            field = "outcome_snapshot_id" if kind == "outcomes" else "proposal_snapshot_id"
            if before["config"][field] == after["config"][field]:
                require(sorted(comparison.canonical(row) for row in snapshots["before"][kind]) ==
                        sorted(comparison.canonical(row) for row in snapshots["after"][kind]),
                        "SAME_SNAPSHOT_DIFFERENT_ROWS")
        report["comparison"] = comparison_report
        report["counts"] = {"bound_queries": len(query_ids), "bound_tables": len(checked),
                            "new_snapshots": sum(v["new_snapshots"] for v in checked.values()),
                            "new_outcome_versions": created}
        report["status"] = (
            "RECEIPTS_CONSISTENT_COMPARISON_VIOLATION"
            if comparison_report["status"] == "VIOLATION_IN_SUPPLIED_EVIDENCE"
            else "RECEIPTS_AND_COMPARISON_CONSISTENT")
    except comparison.InvalidEvidence as error:
        report["reasons"] = [str(error)]
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        report["reasons"] = ["INVALID_PROVENANCE_INPUT"]
    return report


def validate_json(raw: bytes) -> dict:
    try:
        require(len(raw) <= MAX_BYTES, "INPUT_TOO_LARGE")
        def reject_constant(_: str) -> None:
            raise comparison.InvalidEvidence("NON_FINITE_JSON_NUMBER")
        return validate_evidence(json.loads(raw, object_pairs_hook=comparison.unique_object,
                                           parse_constant=reject_constant))
    except comparison.InvalidEvidence as error:
        report = report_base()
        report["reasons"] = [str(error)]
        return report
    except (ValueError, TypeError, RecursionError):
        report = report_base()
        report["reasons"] = ["INVALID_JSON"]
        return report


def main() -> int:
    if len(sys.argv) != 1:
        report = report_base()
        report["reasons"] = ["INVALID_ARGUMENTS"]
    else:
        report = validate_json(sys.stdin.buffer.read(MAX_BYTES + 1))
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return {"RECEIPTS_AND_COMPARISON_CONSISTENT": 0,
            "RECEIPTS_CONSISTENT_COMPARISON_VIOLATION": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
