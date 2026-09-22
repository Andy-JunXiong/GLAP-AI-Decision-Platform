"""Supplied synthetic metadata only; no AWS or file acquisition."""

import copy
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from ops import normalize_snapshot_metadata as normalizer

BASE = datetime(2026, 9, 1, 1, tzinfo=timezone.utc)


def ms(value):
    return int(value.timestamp() * 1000)


def fixture():
    tables = {}
    for index, (kind, table) in enumerate(normalizer.TABLES.items(), 1):
        path = "s3://fixture-metadata/" + kind
        before_name, after_name = path + "/before.json", path + "/after.json"
        schema = {"schema-id": 0, "type": "struct", "fields": [
            {"id": 1, "name": "private_business_key", "required": True, "type": "string"}]}
        snapshot = {"snapshot-id": 100, "sequence-number": 1, "timestamp-ms": ms(BASE - timedelta(days=1)),
                    "schema-id": 0, "manifest-list": path + "/manifest.avro", "summary": {"operation": "append"}}
        before = {"format-version": 2, "table-uuid": f"00000000-0000-0000-0000-{index:012d}",
                  "location": path, "last-sequence-number": 1, "last-updated-ms": ms(BASE - timedelta(seconds=1)),
                  "last-column-id": 1, "schemas": [schema], "current-schema-id": 0,
                  "partition-specs": [{"spec-id": 0, "fields": []}], "default-spec-id": 0,
                  "last-partition-id": 999, "sort-orders": [{"order-id": 0, "fields": []}],
                  "default-sort-order-id": 0, "current-snapshot-id": 100, "snapshots": [snapshot],
                  "snapshot-log": [{"timestamp-ms": snapshot["timestamp-ms"], "snapshot-id": 100}],
                  "refs": {"main": {"type": "branch", "snapshot-id": 100}}}
        after = copy.deepcopy(before)
        after.update({"last-sequence-number": 2, "last-updated-ms": ms(BASE + timedelta(seconds=51)),
                      "current-snapshot-id": 200, "refs": {"main": {"type": "branch", "snapshot-id": 200}},
                      "metadata-log": [{"timestamp-ms": before["last-updated-ms"], "metadata-file": before_name}]})
        after["snapshots"].append({**copy.deepcopy(snapshot), "snapshot-id": 200, "parent-snapshot-id": 100,
                                   "sequence-number": 2, "timestamp-ms": ms(BASE + timedelta(seconds=50))})
        after["snapshot-log"].append({"timestamp-ms": ms(BASE + timedelta(seconds=50)), "snapshot-id": 200})
        observations = {}
        for phase, second in zip(normalizer.PHASES, (0, 10, 100, 110)):
            observations[phase] = {"database": "simulated_iceberg_m", "table": table,
                                   "metadata_location": before_name if phase.startswith("before") else after_name,
                                   "started_at": (BASE + timedelta(seconds=second)).isoformat(),
                                   "finished_at": (BASE + timedelta(seconds=second + 1)).isoformat()}
        tables[kind] = {"metadata_objects": [{"location": before_name, "metadata_json": json.dumps(before)},
                                             {"location": after_name, "metadata_json": json.dumps(after)}],
                        "observations": observations}
    return {"schema_version": normalizer.SCHEMA, "input_kind": "SYNTHETIC_FIXTURE", "logical_date": "2026-09-01",
            "region": "us-east-1", "database": "simulated_iceberg_m", "tables": tables}


def mutate(packet, change, index=1, kind="outcomes"):
    item = packet["tables"][kind]["metadata_objects"][index]
    doc = json.loads(item["metadata_json"])
    change(doc)
    item["metadata_json"] = json.dumps(doc)


class SnapshotMetadataNormalizerTests(unittest.TestCase):
    def assert_safe(self, report):
        self.assertFalse(any(report["authority"].values()))
        for key in ("runtime_verified", "history_complete", "writer_binding_verified", "snapshot_lineage_verified",
                    "net_new_rows_verified", "real_world_evidence", "execution_available"):
            self.assertIs(report[key], False)
        self.assertEqual(report["gaps"], list(normalizer.GAPS))
        for marker in ("s3://", "fixture-metadata", "private_business_key", "00000000-0000", "2026-09-01", "secret-detail"):
            self.assertNotIn(marker, json.dumps(report))

    def rejected(self, packet, reason=None):
        report = normalizer.normalize(packet)
        self.assertEqual(report["status"], "UNVERIFIED", report)
        self.assertIsNone(report["counts"])
        if reason:
            self.assertEqual(report["reasons"], [reason])
        self.assert_safe(report)

    def test_linear_supplied_history_normalizes_with_all_proof_gaps(self):
        packet = fixture()
        report = normalizer.normalize(packet)
        self.assertEqual(report["status"], "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS", report)
        self.assertEqual(report["counts"], {"tables": 2, "observations": 8, "metadata_objects": 4, "supplied_snapshots": 4})
        self.assert_safe(report)
        private = normalizer.normalize_private(packet)
        for table in private["tables"].values():
            for snapshot in table["snapshots"]:
                self.assertIn("created_at", snapshot)
                self.assertNotIn("committed_at", snapshot)
                self.assertNotIn("writer_invocation_id", snapshot)

    def test_unchanged_heads_do_not_prove_zero_writes_or_complete_history(self):
        packet = fixture()
        for table in packet["tables"].values():
            table["metadata_objects"].pop()
            for observation in table["observations"].values():
                observation["metadata_location"] = table["metadata_objects"][0]["location"]
        report = normalizer.normalize(packet)
        self.assertEqual(report["status"], "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS", report)
        self.assert_safe(report)

    def test_metadata_format_and_integer_types_are_strict(self):
        for key, value in (("format-version", 3), ("format-version", True), ("last-sequence-number", True),
                           ("current-snapshot-id", "200"), ("current-schema-id", True)):
            packet = fixture()
            mutate(packet, lambda d: d.update({key: value}))
            self.rejected(packet)

    def test_catalog_scope_and_missing_pointer_fail_closed(self):
        for key, value in (("table", "other"), ("database", "other"), ("metadata_location", "s3://missing/other.json")):
            packet = fixture()
            packet["tables"]["outcomes"]["observations"]["before_open"][key] = value
            self.rejected(packet)

    def test_uuid_changes_and_cross_table_identity_collision_fail(self):
        packet = fixture()
        mutate(packet, lambda d: d.update({"table-uuid": "00000000-0000-0000-0000-000000000099"}))
        self.rejected(packet, "TABLE_IDENTITY_OR_LOCATION_CHANGED")
        packet = fixture()
        for index in (0, 1):
            mutate(packet, lambda d: d.update({"table-uuid": "00000000-0000-0000-0000-000000000001"}), index, "proposals")
        self.rejected(packet, "TABLE_IDENTITIES_COLLIDE")

    def test_changed_full_schema_is_not_hidden(self):
        packet = fixture()
        mutate(packet, lambda d: d["schemas"][0].update({"private-extension": "changed"}))
        self.rejected(packet, "CONFLICTING_SNAPSHOT_ID")

    def test_distinct_uuids_cannot_share_metadata_storage(self):
        packet = fixture()
        packet["tables"]["proposals"] = json.loads(json.dumps(packet["tables"]["proposals"]).replace(
            'fixture-metadata/proposals', 'fixture-metadata/outcomes'))
        self.rejected(packet, "TABLE_STORAGE_BINDINGS_COLLIDE")

    def test_missing_prebaseline_parent_keeps_history_unverified(self):
        packet = fixture()
        for kind in normalizer.TABLES:
            for index in (0, 1):
                mutate(packet, lambda d: d["snapshots"][0].update({"parent-snapshot-id": 99}), index, kind)
        report = normalizer.normalize(packet)
        self.assertEqual(report["status"], "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS", report)
        self.assert_safe(report)

    def test_schema_digest_preserves_extensions_unicode_and_array_order(self):
        schema = json.loads(fixture()["tables"]["outcomes"]["metadata_objects"][0]["metadata_json"])["schemas"][0]
        reordered = dict(reversed(list(schema.items())))
        self.assertEqual(normalizer.schema_digest(schema), normalizer.schema_digest(reordered))
        extended = {**schema, "comment": "供应链"}
        self.assertNotEqual(normalizer.schema_digest(schema), normalizer.schema_digest(extended))
        with patch.object(normalizer.hashlib, "sha256", wraps=normalizer.hashlib.sha256) as hashing:
            normalizer.schema_digest(extended)
        self.assertIn("供应链".encode(), hashing.call_args.args[0])

    def test_nested_schema_types_duplicate_ids_and_unknown_types(self):
        schema = {"schema-id": 0, "type": "struct", "fields": [
            {"id": 1, "name": "items", "required": True,
             "type": {"type": "list", "element-id": 2, "element-required": False, "element": "decimal(10,2)"}}]}
        self.assertEqual(len(normalizer.schema_digest(schema)), 64)
        for value in ("unknown", "decimal(39,2)", "decimal(2,3)"):
            schema["fields"][0]["type"]["element"] = value
            with self.assertRaises(normalizer.evidence.InvalidEvidence):
                normalizer.schema_digest(schema)
        schema["fields"][0]["type"].update({"element-id": 1, "element": "string"})
        with self.assertRaises(normalizer.evidence.InvalidEvidence):
            normalizer.schema_digest(schema)

    def test_missing_snapshot_schema_never_uses_current_schema(self):
        packet = fixture()
        mutate(packet, lambda d: d["snapshots"][1].pop("schema-id"))
        self.rejected(packet, "SCHEMA_CONTEXT_UNAVAILABLE")

    def test_duplicate_and_conflicting_snapshot_ids_fail(self):
        packet = fixture()
        mutate(packet, lambda d: d["snapshots"].append(copy.deepcopy(d["snapshots"][0])))
        self.rejected(packet, "DUPLICATE_SNAPSHOT_ID")
        packet = fixture()
        mutate(packet, lambda d: d["snapshots"][0]["summary"].update({"extra": "secret-detail"}))
        self.rejected(packet, "CONFLICTING_SNAPSHOT_ID")

    def test_missing_parent_cycle_and_branches_fail(self):
        for parent in (999, 200):
            packet = fixture()
            mutate(packet, lambda d: d["snapshots"][1].update({"parent-snapshot-id": parent}))
            self.rejected(packet)
        packet = fixture()
        def branch(d):
            d["last-sequence-number"] = 3
            d["snapshots"].append({**d["snapshots"][1], "snapshot-id": 300, "sequence-number": 3})
        mutate(packet, branch)
        self.rejected(packet, "UNSUPPORTED_SNAPSHOT_BRANCH")

    def test_disconnected_supplied_nodes_cannot_be_discarded(self):
        packet = fixture()
        def disconnected(d):
            d["snapshots"].append({**d["snapshots"][0], "snapshot-id": 999, "sequence-number": 3})
            d["last-sequence-number"] = 3
        mutate(packet, disconnected)
        self.rejected(packet, "DISCARDED_OR_UNBOUND_SNAPSHOT")

    def test_missing_and_cyclic_metadata_history_is_not_complete(self):
        packet = fixture()
        mutate(packet, lambda d: d["metadata-log"][0].update({"metadata-file": "s3://missing-bucket/old.json"}))
        self.rejected(packet, "METADATA_HISTORY_REFERENCE_UNAVAILABLE")
        packet = fixture()
        after_name = packet["tables"]["outcomes"]["metadata_objects"][1]["location"]
        mutate(packet, lambda d: d["metadata-log"][0].update({"metadata-file": after_name}))
        self.rejected(packet, "CYCLIC_METADATA_HISTORY")

    def test_main_refs_and_visible_rollback_fail(self):
        packet = fixture()
        mutate(packet, lambda d: d["refs"]["main"].update({"snapshot-id": 100}))
        self.rejected(packet, "MAIN_REFERENCE_MISMATCH")
        packet = fixture()
        def rollback(d):
            d["snapshot-log"].append({"timestamp-ms": d["last-updated-ms"], "snapshot-id": 100})
            d["current-snapshot-id"] = 100
            d["refs"]["main"]["snapshot-id"] = 100
        mutate(packet, rollback)
        self.rejected(packet, "ROLLBACK_OR_REPEATED_HEAD")

    def test_empty_tables_and_secondary_refs_are_explicitly_unsupported(self):
        packet = fixture()
        mutate(packet, lambda d: d.update({"snapshots": []}))
        self.rejected(packet, "SNAPSHOT_LIMIT_OR_EMPTY")
        packet = fixture()
        mutate(packet, lambda d: d["refs"].update({"audit": {"type": "tag", "snapshot-id": 100}}))
        self.rejected(packet, "UNSUPPORTED_SNAPSHOT_REFS")

    def test_future_and_cross_date_observations_fail(self):
        for value in ("2099-01-01T00:00:00+00:00", "2026-09-02T01:00:00+00:00", "2026-09-01T01:00:00"):
            packet = fixture()
            packet["tables"]["outcomes"]["observations"]["after_close"]["finished_at"] = value
            self.rejected(packet)
        packet = fixture()
        packet["logical_date"] = "2099-01-01"
        self.rejected(packet, "FUTURE_LOGICAL_DATE")

    def test_shared_observation_window_is_required(self):
        packet = fixture()
        observation = packet["tables"]["proposals"]["observations"]["before_open"]
        observation["started_at"] = (BASE + timedelta(seconds=10)).isoformat()
        observation["finished_at"] = (BASE + timedelta(seconds=10)).isoformat()
        packet["tables"]["outcomes"]["observations"]["before_close"]["started_at"] = (BASE + timedelta(seconds=9)).isoformat()
        self.rejected(packet, "NO_SHARED_OBSERVATION_INTERVAL")

    def test_metadata_after_observation_and_snapshot_after_metadata_fail(self):
        packet = fixture()
        mutate(packet, lambda d: d.update({"last-updated-ms": ms(BASE + timedelta(seconds=200))}))
        self.rejected(packet, "METADATA_AFTER_OBSERVATION")
        packet = fixture()
        mutate(packet, lambda d: d["snapshots"][1].update({"timestamp-ms": ms(BASE + timedelta(seconds=200))}))
        self.rejected(packet, "SNAPSHOT_AFTER_METADATA")

    def test_optional_absent_logs_do_not_clear_history_gap(self):
        packet = fixture()
        for kind in normalizer.TABLES:
            for index in (0, 1):
                mutate(packet, lambda d: d.pop("snapshot-log"), index, kind)
        report = normalizer.normalize(packet)
        self.assertEqual(report["status"], "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS")
        self.assert_safe(report)

    def test_raw_writer_hints_are_never_projected_or_trusted(self):
        packet = fixture()
        for kind in normalizer.TABLES:
            for index in (0, 1):
                mutate(packet, lambda d: [s["summary"].update({"writer_invocation_id": "secret-detail"}) for s in d["snapshots"]], index, kind)
        self.assert_safe(normalizer.normalize(packet))
        self.assertNotIn("secret-detail", str(normalizer.normalize_private(packet)))
        packet["history_complete"] = True
        self.rejected(packet, "INVALID_SHAPE")

    def test_object_snapshot_byte_and_window_bounds(self):
        for field, limit in (("MAX_OBJECTS_PER_TABLE", 1), ("MAX_OBJECT_BYTES", 1),
                             ("MAX_TOTAL_BYTES", 1), ("MAX_SNAPSHOTS", 1), ("MAX_WINDOW_SECONDS", 1)):
            with self.subTest(field=field), patch.object(normalizer, field, limit):
                self.rejected(fixture())

    def test_duplicate_json_keys_nonfinite_invalid_unicode_and_oversize(self):
        for raw in (b'{"schema_version":1,"schema_version":2}', b'{"bad":NaN}', b'\xff', b'[]'):
            report = normalizer.validate_json(raw)
            self.assertEqual(report["status"], "UNVERIFIED")
            self.assert_safe(report)
        with patch.object(normalizer, "MAX_INPUT_BYTES", 1):
            self.assertEqual(normalizer.validate_json(b'{}')["reasons"], ["INPUT_TOO_LARGE"])
        packet = fixture()
        packet["tables"]["outcomes"]["metadata_objects"][0]["metadata_json"] = '{"private":"secret-detail","private":2}'
        self.rejected(packet)

    def test_default_and_normalize_cli_and_unknown_flags_are_redacted(self):
        for args, data, code, status in (([], "secret-detail", 0, "LOCAL_PLAN_ONLY"),
                (["--normalize"], json.dumps(fixture()), 0, "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS"),
                (["--normalize"], '{"bad":"secret-detail"}', 2, "UNVERIFIED"),
                (["--execute"], "secret-detail", 2, "UNVERIFIED")):
            run = subprocess.run([sys.executable, "ops/normalize_snapshot_metadata.py", *args],
                                 input=data, capture_output=True, text=True)
            self.assertEqual(run.returncode, code, run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(report["status"], status)
            self.assert_safe(report)
            self.assertEqual(run.stderr, "")


if __name__ == "__main__":
    unittest.main()
