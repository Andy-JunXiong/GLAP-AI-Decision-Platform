"""Offline projection of supplied Iceberg v2 metadata; never attests writer/history.

No SDK, network, credentials, file output or provenance-validator invocation.
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
    from ops.prepare_learning_evidence_collection import TABLES
except ModuleNotFoundError:
    import compare_learning_cardinality_evidence as evidence
    from prepare_learning_evidence_collection import TABLES

SCHEMA = "snapshot-metadata-input.v1"
MAX_INPUT_BYTES = 40 * 1024 * 1024
MAX_OBJECT_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_OBJECTS_PER_TABLE = 32
MAX_SNAPSHOTS = 100
MAX_WINDOW_SECONDS = 7200
PHASES = ("before_open", "before_close", "after_open", "after_close")
GAPS = ("SUPPLIED_RECORDS_NOT_AUTHENTICATED", "COMMIT_TIMES_UNAVAILABLE",
        "QUERY_TARGET_BINDING_UNAVAILABLE", "QUERY_TO_COMMIT_BINDING_UNAVAILABLE",
        "COMPLETE_HISTORY_UNPROVEN", "WRITER_EXCLUSIVITY_UNPROVEN",
        "PINNED_ROWS_NOT_CHECKED", "LEGACY_SOURCE_PIN_INCOMPATIBLE_WITH_RECEIPT_PRODUCER")
require, exact = evidence.require, evidence.exact


def report_base():
    return {"schema_version": "snapshot-metadata-report.v1", "status": "UNVERIFIED",
            "evidence_class": "OFFLINE_METADATA_STRUCTURE_ONLY", "reasons": [], "gaps": list(GAPS),
            "counts": None, "runtime_verified": False, "history_complete": False,
            "writer_binding_verified": False, "snapshot_lineage_verified": False,
            "net_new_rows_verified": False, "real_world_evidence": False, "execution_available": False,
            "authority": {**evidence.empty_report()["authority"], "aws_read": False,
                          "permission_change": False, "private_persistence": False, "source_pin_change": False}}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def parse_json(raw):
    def invalid(_):
        raise evidence.InvalidEvidence("NON_FINITE_JSON_NUMBER")
    return json.loads(raw, object_pairs_hook=evidence.unique_object, parse_constant=invalid)


def integer(value, minimum=0, maximum=2**63 - 1):
    require(type(value) is int and minimum <= value <= maximum, "INVALID_METADATA_INTEGER")
    return value


def millis(value):
    integer(value)
    return datetime.fromtimestamp(value / 1000, timezone.utc)


def location(value):
    require(type(value) is str and len(value) <= 4096 and
            re.fullmatch(r"s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]/[^\s?#\\]+", value) is not None,
            "INVALID_METADATA_LOCATION")
    require(all(part not in (".", "..") for part in value.split("/")[3:]), "INVALID_METADATA_LOCATION")
    return value


def schema_digest(schema):
    """Check supported type structure; hash the FULL schema including extension fields."""
    require(type(schema) is dict and schema.get("type") == "struct", "INVALID_SCHEMA")
    integer(schema.get("schema-id"), maximum=2**31 - 1)
    ids = set()
    def add_id(value):
        integer(value, 1, 2147483447)
        require(value not in ids, "DUPLICATE_SCHEMA_FIELD_ID")
        ids.add(value)
    def visit(value, depth=0):
        require(depth <= 32, "SCHEMA_DEPTH_LIMIT")
        if type(value) is str:
            require(value in {"boolean", "int", "long", "float", "double", "date", "time",
                              "timestamp", "timestamptz", "string", "uuid", "binary"}
                    or re.fullmatch(r"fixed\[[1-9][0-9]{0,8}\]", value) is not None
                    or re.fullmatch(r"decimal\([1-9][0-9]?,[0-9]{1,2}\)", value) is not None,
                    "UNSUPPORTED_SCHEMA_TYPE")
            if value.startswith("decimal"):
                precision, scale = map(int, value[8:-1].split(","))
                require(scale <= precision <= 38, "INVALID_DECIMAL_TYPE")
            return
        require(type(value) is dict, "INVALID_SCHEMA_TYPE")
        if value.get("type") == "struct":
            fields = value.get("fields")
            require(type(fields) is list and len(fields) <= 1000, "INVALID_SCHEMA_FIELDS")
            names = set()
            for field in fields:
                require(type(field) is dict and type(field.get("name")) is str and field["name"]
                        and field["name"] not in names and type(field.get("required")) is bool, "INVALID_SCHEMA_FIELD")
                names.add(field["name"])
                add_id(field.get("id"))
                visit(field.get("type"), depth + 1)
        elif value.get("type") == "list":
            add_id(value.get("element-id"))
            require(type(value.get("element-required")) is bool, "INVALID_SCHEMA_FIELD")
            visit(value.get("element"), depth + 1)
        elif value.get("type") == "map":
            add_id(value.get("key-id")); add_id(value.get("value-id"))
            require(type(value.get("value-required")) is bool, "INVALID_SCHEMA_FIELD")
            visit(value.get("key"), depth + 1); visit(value.get("value"), depth + 1)
        else:
            require(False, "UNSUPPORTED_SCHEMA_TYPE")
    visit(schema)
    identifiers = schema.get("identifier-field-ids", [])
    require(type(identifiers) is list and all(type(v) is int and v in ids for v in identifiers)
            and len(set(identifiers)) == len(identifiers), "INVALID_SCHEMA_IDENTIFIERS")
    return digest(schema)


def normalize_table(kind, packet, logical_date, now):
    exact(packet, {"metadata_objects", "observations"})
    objects = packet["metadata_objects"]
    require(type(objects) is list and 0 < len(objects) <= MAX_OBJECTS_PER_TABLE, "METADATA_OBJECT_LIMIT")
    docs, hashes, total = {}, {}, 0
    for item in objects:
        exact(item, {"location", "metadata_json"})
        name = location(item["location"])
        require(name not in docs, "DUPLICATE_METADATA_LOCATION")
        require(type(item["metadata_json"]) is str, "INVALID_METADATA_JSON")
        raw = item["metadata_json"].encode("utf-8")
        require(0 < len(raw) <= MAX_OBJECT_BYTES, "METADATA_OBJECT_BYTE_LIMIT")
        total += len(raw)
        docs[name], hashes[name] = parse_json(raw), hashlib.sha256(raw).hexdigest()
    exact(packet["observations"], set(PHASES))
    windows, roots = {}, {}
    for phase in PHASES:
        observation = packet["observations"][phase]
        exact(observation, {"database", "table", "metadata_location", "started_at", "finished_at"})
        require(observation["database"] == "simulated_iceberg_m" and observation["table"] == TABLES[kind],
                "CATALOG_TABLE_MISMATCH")
        start, finish = (evidence.timestamp(observation[k]) for k in ("started_at", "finished_at"))
        require(start <= finish <= now and all(t.astimezone(ZoneInfo("Australia/Sydney")).date() == logical_date
                for t in (start, finish)), "INVALID_OBSERVATION_WINDOW")
        root = observation["metadata_location"]
        require(type(root) is str and root in docs, "CATALOG_METADATA_UNAVAILABLE")
        windows[phase], roots[phase] = (start, finish), root
    ordered = [time for phase in PHASES for time in windows[phase]]
    require(ordered == sorted(ordered), "OBSERVATION_ORDER_MISMATCH")
    nodes, fingerprints, doc_heads, doc_schemas, edges = {}, {}, {}, {}, {}
    uuids, table_locations = set(), set()
    for name, metadata in docs.items():
        require(type(metadata) is dict and type(metadata.get("format-version")) is int and
                metadata["format-version"] == 2, "UNSUPPORTED_METADATA_FORMAT")
        uuid = metadata.get("table-uuid")
        require(type(uuid) is str and re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", uuid),
                "INVALID_TABLE_UUID")
        uuids.add(uuid.lower()); table_locations.add(location(metadata.get("location")))
        updated = millis(metadata.get("last-updated-ms"))
        require(updated <= now, "FUTURE_METADATA_TIME")
        last_sequence = integer(metadata.get("last-sequence-number"))
        schemas = metadata.get("schemas")
        require(type(schemas) is list and 0 < len(schemas) <= 100, "INVALID_SCHEMAS")
        schema_map = {}
        for schema in schemas:
            hashed = schema_digest(schema)
            require(schema["schema-id"] not in schema_map, "DUPLICATE_SCHEMA_ID")
            schema_map[schema["schema-id"]] = hashed
        current_schema = integer(metadata.get("current-schema-id"), maximum=2**31 - 1)
        require(current_schema in schema_map, "SCHEMA_CONTEXT_UNAVAILABLE")
        doc_schemas[name] = schema_map[current_schema]
        snapshots = metadata.get("snapshots")
        require(type(snapshots) is list and 0 < len(snapshots) <= MAX_SNAPSHOTS, "SNAPSHOT_LIMIT_OR_EMPTY")
        local_ids, local_sequences = set(), set()
        for snapshot in snapshots:
            require(type(snapshot) is dict, "INVALID_SNAPSHOT")
            sid = integer(snapshot.get("snapshot-id"), 1)
            require(sid not in local_ids, "DUPLICATE_SNAPSHOT_ID")
            local_ids.add(sid)
            parent = snapshot.get("parent-snapshot-id")
            if parent is not None:
                integer(parent, 1)
            require(parent != sid, "CYCLIC_SNAPSHOT")
            sequence = integer(snapshot.get("sequence-number"), 1)
            require(sequence <= last_sequence and sequence not in local_sequences, "INVALID_SNAPSHOT_SEQUENCE")
            local_sequences.add(sequence)
            created = millis(snapshot.get("timestamp-ms"))
            require(created <= updated, "SNAPSHOT_AFTER_METADATA")
            schema_id = snapshot.get("schema-id")
            require(type(schema_id) is int and schema_id in schema_map, "SCHEMA_CONTEXT_UNAVAILABLE")
            summary = snapshot.get("summary")
            require(type(summary) is dict and summary.get("operation") in {"append", "replace", "overwrite", "delete"}
                    and all(type(k) is str and type(v) is str for k, v in summary.items()), "INVALID_SNAPSHOT_SUMMARY")
            location(snapshot.get("manifest-list"))  # Validate syntax only; never follow or read it.
            fingerprint = digest({"snapshot": snapshot, "schema_sha256": schema_map[schema_id]})
            require(sid not in fingerprints or fingerprints[sid] == fingerprint, "CONFLICTING_SNAPSHOT_ID")
            fingerprints[sid] = fingerprint
            nodes[sid] = {"snapshot_id": str(sid), "parent_snapshot_id": str(parent) if parent is not None else None,
                          "sequence_number": sequence, "created_at": created.isoformat(),
                          "schema_sha256": schema_map[schema_id]}
        head = integer(metadata.get("current-snapshot-id"), 1)
        require(head in local_ids, "CURRENT_SNAPSHOT_UNAVAILABLE")
        doc_heads[name] = head
        refs = metadata.get("refs", {})
        require(type(refs) is dict and set(refs) <= {"main"}, "UNSUPPORTED_SNAPSHOT_REFS")
        if "main" in refs:
            require(type(refs["main"]) is dict and refs["main"].get("type") == "branch" and
                    type(refs["main"].get("snapshot-id")) is int and refs["main"]["snapshot-id"] == head,
                    "MAIN_REFERENCE_MISMATCH")
        log = metadata.get("snapshot-log", [])
        require(type(log) is list and len(log) <= MAX_SNAPSHOTS, "INVALID_SNAPSHOT_LOG")
        prior, prior_sequence = None, None
        for entry in log:
            exact(entry, {"timestamp-ms", "snapshot-id"})
            moment, log_id = millis(entry["timestamp-ms"]), integer(entry["snapshot-id"], 1)
            require(log_id in local_ids, "SNAPSHOT_LOG_CONTEXT_UNAVAILABLE")
            require((prior is None or prior <= moment) and moment <= updated and
                    moment >= evidence.timestamp(nodes[log_id]["created_at"]), "INVALID_SNAPSHOT_LOG_TIME")
            sequence = nodes[log_id]["sequence_number"]
            require(prior_sequence is None or sequence > prior_sequence, "ROLLBACK_OR_REPEATED_HEAD")
            prior, prior_sequence = moment, sequence
        require(not log or log[-1]["snapshot-id"] == head, "SNAPSHOT_LOG_HEAD_MISMATCH")
        history = metadata.get("metadata-log", [])
        require(type(history) is list and len(history) <= MAX_OBJECTS_PER_TABLE, "METADATA_HISTORY_LIMIT")
        edges[name], prior = [], None
        for entry in history:
            exact(entry, {"timestamp-ms", "metadata-file"})
            moment, target = millis(entry["timestamp-ms"]), location(entry["metadata-file"])
            require(target in docs, "METADATA_HISTORY_REFERENCE_UNAVAILABLE")
            require(target not in edges[name] and (prior is None or prior <= moment) and moment <= updated,
                    "INVALID_METADATA_HISTORY")
            edges[name].append(target); prior = moment
        for phase in PHASES:
            if roots[phase] == name:
                require(updated <= windows[phase][1], "METADATA_AFTER_OBSERVATION")
    require(len(uuids) == len(table_locations) == 1, "TABLE_IDENTITY_OR_LOCATION_CHANGED")
    require(len(nodes) <= MAX_SNAPSHOTS, "SNAPSHOT_UNION_LIMIT")
    visited, active = set(), set()
    def walk(name):
        require(name not in active, "CYCLIC_METADATA_HISTORY")
        if name in visited:
            return
        active.add(name)
        for target in edges[name]:
            require(docs[target]["last-updated-ms"] <= docs[name]["last-updated-ms"], "METADATA_HISTORY_TIME_REVERSED")
            walk(target)
        active.remove(name); visited.add(name)
    for name in roots.values():
        walk(name)
    require(visited == set(docs), "UNREFERENCED_METADATA_OBJECT")
    heads = {phase: doc_heads[name] for phase, name in roots.items()}
    require(heads["before_open"] == heads["before_close"] and heads["after_open"] == heads["after_close"],
            "OBSERVATION_HEAD_CHANGED")
    schema_hashes = {doc_schemas[name] for name in roots.values()}
    require(len(schema_hashes) == 1, "OBSERVATION_SCHEMA_CHANGED")
    baseline, after = heads["before_open"], heads["after_close"]
    children, seqs = {}, set()
    for sid, node in nodes.items():
        sequence = node["sequence_number"]
        require(sequence not in seqs, "CONFLICTING_SNAPSHOT_SEQUENCE")
        seqs.add(sequence)
        parent = int(node["parent_snapshot_id"]) if node["parent_snapshot_id"] else None
        if parent is not None:
            require(parent in nodes or sid == baseline, "SNAPSHOT_PARENT_UNAVAILABLE")
            require(parent not in children or children[parent] == sid, "UNSUPPORTED_SNAPSHOT_BRANCH")
            children[parent] = sid
        if parent in nodes:
            require(nodes[parent]["sequence_number"] < sequence and
                    evidence.timestamp(nodes[parent]["created_at"]) <= evidence.timestamp(node["created_at"]),
                    "SNAPSHOT_ORDER_OR_CYCLE")
    segment, cursor = [], after
    while True:
        require(cursor in nodes and cursor not in segment, "SNAPSHOT_LINEAGE_GAP_OR_CYCLE")
        segment.append(cursor)
        if cursor == baseline:
            break
        parent = nodes[cursor]["parent_snapshot_id"]
        require(parent is not None, "BEFORE_HEAD_NOT_ANCESTOR")
        cursor = int(parent)
    require(all(nodes[sid]["schema_sha256"] in schema_hashes for sid in segment), "SEGMENT_SCHEMA_CHANGED")
    require(all(node["sequence_number"] <= nodes[after]["sequence_number"] for node in nodes.values()),
            "DISCARDED_OR_UNBOUND_SNAPSHOT")
    ancestors, cursor = set(), after
    while cursor in nodes:
        require(cursor not in ancestors, "SNAPSHOT_LINEAGE_GAP_OR_CYCLE")
        ancestors.add(cursor)
        parent = nodes[cursor]["parent_snapshot_id"]
        cursor = int(parent) if parent is not None else None
    require(ancestors == set(nodes), "DISCONNECTED_SNAPSHOT_HISTORY")
    return {"table_uuid": next(iter(uuids)), "table_location": next(iter(table_locations)), "metadata_sha256": hashes,
            "snapshots": [nodes[sid] for sid in reversed(segment)], "windows": windows,
            "metadata_objects": len(docs), "metadata_bytes": total, "supplied_snapshots": len(nodes)}


def normalize_private(packet):
    exact(packet, {"schema_version", "input_kind", "logical_date", "region", "database", "tables"})
    require(packet["schema_version"] == SCHEMA and packet["input_kind"] in
            ("SYNTHETIC_FIXTURE", "SUPPLIED_STAGING_EXPORT"), "INVALID_INPUT_CONTRACT")
    require(packet["region"] == "us-east-1" and packet["database"] == "simulated_iceberg_m", "INVALID_STAGING_SCOPE")
    now = datetime.now(timezone.utc)
    logical_date = evidence.iso_date(packet["logical_date"])
    require(logical_date <= now.astimezone(ZoneInfo("Australia/Sydney")).date(), "FUTURE_LOGICAL_DATE")
    exact(packet["tables"], set(TABLES))
    tables = {kind: normalize_table(kind, value, logical_date, now) for kind, value in packet["tables"].items()}
    require(tables["outcomes"]["table_uuid"] != tables["proposals"]["table_uuid"], "TABLE_IDENTITIES_COLLIDE")
    require(tables["outcomes"]["table_location"] != tables["proposals"]["table_location"] and
            not set(tables["outcomes"]["metadata_sha256"]) & set(tables["proposals"]["metadata_sha256"]),
            "TABLE_STORAGE_BINDINGS_COLLIDE")
    require(sum(v["metadata_bytes"] for v in tables.values()) <= MAX_TOTAL_BYTES, "TOTAL_METADATA_BYTE_LIMIT")
    windows = [t["windows"] for t in tables.values()]
    require((max(w["after_close"][1] for w in windows) - min(w["before_open"][0] for w in windows)).total_seconds()
            <= MAX_WINDOW_SECONDS, "COLLECTION_WINDOW_LIMIT")
    for phase in ("before", "after"):
        require(max(w[phase + "_open"][1] for w in windows) <= min(w[phase + "_close"][0] for w in windows),
                "NO_SHARED_OBSERVATION_INTERVAL")
    require(max(w["before_close"][1] for w in windows) < min(w["after_open"][0] for w in windows),
            "PHASE_OBSERVATIONS_OVERLAP")
    return {"schema_version": "snapshot-metadata-private.v1", "tables": tables, "gaps": list(GAPS),
            "history_complete": False, "writer_binding_verified": False, "runtime_verified": False}


def normalize(packet):
    report = report_base()
    try:
        private = normalize_private(packet)
        report.update(status="METADATA_STRUCTURES_CONSISTENT_WITH_GAPS", counts={"tables": 2,
                      "observations": 8, "metadata_objects": sum(v["metadata_objects"] for v in private["tables"].values()),
                      "supplied_snapshots": sum(v["supplied_snapshots"] for v in private["tables"].values())})
    except evidence.InvalidEvidence as error:
        report["reasons"] = [str(error)]
    except Exception:
        report["reasons"] = ["INVALID_METADATA_INPUT"]
    return report


def validate_json(raw):
    try:
        require(len(raw) <= MAX_INPUT_BYTES, "INPUT_TOO_LARGE")
        return normalize(parse_json(raw))
    except evidence.InvalidEvidence as error:
        report = report_base(); report["reasons"] = [str(error)]
    except Exception:
        report = report_base(); report["reasons"] = ["INVALID_METADATA_JSON"]
    return report


def plan_summary():
    return {**report_base(), "status": "LOCAL_PLAN_ONLY", "supported_format_versions": [2],
            "max_objects_per_table": MAX_OBJECTS_PER_TABLE, "max_object_bytes": MAX_OBJECT_BYTES,
            "max_total_metadata_bytes": MAX_TOTAL_BYTES, "max_input_bytes": MAX_INPUT_BYTES,
            "max_snapshots_per_table": MAX_SNAPSHOTS, "max_window_seconds": MAX_WINDOW_SECONDS}


def main():
    if len(sys.argv) == 1:
        report = plan_summary()
    elif sys.argv[1:] == ["--normalize"]:
        report = validate_json(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
    else:
        report = report_base(); report["reasons"] = ["INVALID_ARGUMENTS"]
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] in ("LOCAL_PLAN_ONLY", "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
