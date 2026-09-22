"""All readers are injected synthetic mocks; no live service or credential access."""

import copy
import io
import json
import subprocess
import sys
import unittest
from datetime import timedelta
from unittest.mock import patch
from types import SimpleNamespace

from ops import read_snapshot_metadata as reader
from test_snapshot_metadata_normalizer import BASE, fixture, mutate


class Clock:
    def __init__(self):
        self.now = BASE

    def __call__(self):
        self.now += timedelta(milliseconds=1)
        return self.now


class Services:
    def __init__(self, packet):
        self.packet, self.calls, self.bodies = packet, [], []
        self.stage = "before"
        self.catalog_edit = self.object_edit = None

    def get_table(self, **kwargs):
        self.calls.append(("glue:GetTable", kwargs))
        kind = next(k for k, v in reader.normalizer.TABLES.items() if v == kwargs["Name"])
        value = {"Table": {"CatalogId": "123456789012", "DatabaseName": "simulated_iceberg_m",
                 "Name": kwargs["Name"], "TableType": "EXTERNAL_TABLE", "VersionId": "fixture-version",
                 "Parameters": {"table_type": "ICEBERG", "metadata_location":
                     self.packet["tables"][kind]["metadata_objects"][self.stage == "after"]["location"]}}}
        if self.catalog_edit:
            self.catalog_edit(value)
        return value

    def get_object(self, **kwargs):
        self.calls.append(("s3:GetObject", kwargs))
        location = "s3://" + kwargs["Bucket"] + "/" + kwargs["Key"]
        item = next(o for t in self.packet["tables"].values() for o in t["metadata_objects"] if o["location"] == location)
        raw = item["metadata_json"].encode()
        body = io.BytesIO(raw)
        self.bodies.append(body)
        response = {"Body": body, "ContentLength": len(raw), "ResponseMetadata": {"HTTPStatusCode": 200},
                    "ETag": "private-etag", "VersionId": "private-version"}
        if self.object_edit:
            self.object_edit(response)
        return response


def config():
    return {"schema_version": reader.SCHEMA, "region": "us-east-1", "database": "simulated_iceberg_m",
            "logical_date": "2026-09-01", "catalog_id": "123456789012", "tables": {
                k: {"metadata_prefix": "s3://fixture-metadata/" + k + "/", "bucket_owner": "123456789012"}
                for k in reader.normalizer.TABLES}}


class SnapshotMetadataReaderTests(unittest.TestCase):
    def setUp(self):
        self.packet, self.clock = fixture(), Clock()
        self.services = Services(self.packet)

    def start(self, cfg=None):
        return reader.start_capture(config() if cfg is None else cfg, glue=self.services, s3=self.services, clock=self.clock)

    def finish(self, session):
        self.clock.now = BASE + timedelta(seconds=100)
        self.services.stage = "after"
        return session.finish()

    def safe(self, report):
        self.assertFalse(any(report["authority"].values()))
        for key in ("runtime_verified", "history_complete", "writer_binding_verified", "snapshot_lineage_verified",
                    "net_new_rows_verified", "real_world_evidence", "execution_available"):
            self.assertIs(report[key], False)
        for marker in ("s3://", "fixture-metadata", "123456789012", "private-", "secret", "2026-09-01"):
            self.assertNotIn(marker, json.dumps(report))

    def test_complete_capture_normalizes_and_discards_without_closing_proof_gaps(self):
        before, session = self.start()
        self.assertEqual(before["status"], "BEFORE_CAPTURED_AFTER_PENDING")
        self.assertEqual(len(self.services.calls), 6)
        self.assertEqual(repr(session), "<MetadataSession private>")
        self.assertTrue(all(b.closed for b in self.services.bodies))
        self.assertTrue(all(r["immutable_identity_verified"] is False for r in session._records if r["kind"] == "object"))
        result = self.finish(session)
        self.assertEqual(result["status"], "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS")
        self.assertEqual(result["counts"]["metadata_objects"], 4)
        self.assertEqual([c[0] for c in self.services.calls].count("glue:GetTable"), 8)
        self.assertEqual([c[0] for c in self.services.calls].count("s3:GetObject"), 4)
        self.assertIsNone(session._packet)
        self.assertIsNone(session._records)
        self.safe(before); self.safe(result)

    def test_exact_owner_catalog_and_table_bindings_on_every_request(self):
        _, session = self.start()
        self.finish(session)
        for operation, args in self.services.calls:
            if operation == "glue:GetTable":
                self.assertEqual(set(args), {"CatalogId", "DatabaseName", "Name"})
                self.assertIn(args["Name"], reader.normalizer.TABLES.values())
            else:
                self.assertEqual(set(args), {"Bucket", "Key", "ExpectedBucketOwner"})
                self.assertEqual(args["ExpectedBucketOwner"], "123456789012")
                self.assertTrue(args["Key"].endswith(".json"))

    def test_config_frozen_after_start(self):
        cfg = config()
        _, session = self.start(cfg)
        cfg["tables"]["outcomes"]["metadata_prefix"] = "s3://secret/other/"
        self.assertEqual(self.finish(session)["status"], "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS")

    def test_invalid_config_is_rejected_before_client_factory(self):
        for key, value in (("region", "other"), ("database", "other"), ("logical_date", "2026-09-02"),
                           ("logical_date", "2026-08-31"), ("catalog_id", "secret"), ("extra", True)):
            cfg = config(); cfg[key] = value
            with patch.object(reader, "clients") as factory:
                report, session = reader.start_capture(cfg, clock=self.clock)
                self.assertIsNone(session); factory.assert_not_called(); self.safe(report)

    def test_prefix_must_be_narrow_nonoverlapping_and_unambiguous(self):
        for prefix in ("s3://fixture-metadata/", "s3://fixture-metadata/outcomes", "s3://fixture-metadata/proposals/",
                       "s3://fixture-metadata/outcomes/../", "s3://fixture-metadata/outcomes/%2e/",
                       "s3://fixture-metadata--x-s3/outcomes/"):
            cfg = config(); cfg["tables"]["outcomes"]["metadata_prefix"] = prefix
            report, session = self.start(cfg)
            self.assertIsNone(session); self.assertFalse(report["read_attempted"])
        self.assertEqual(self.services.calls, [])

    def test_partial_injected_client_pair_never_creates_real_client(self):
        with patch.object(reader, "clients") as factory:
            report, session = reader.start_capture(config(), glue=self.services, clock=self.clock)
            self.assertIsNone(session); factory.assert_not_called(); self.safe(report)

    def test_catalog_mismatch_never_downloads(self):
        for key, value in (("CatalogId", "000000000000"), ("Name", "other"), ("DatabaseName", "other"),
                           ("TargetTable", {"Name": "other"}), ("TableType", "VIRTUAL_VIEW")):
            self.services.calls.clear()
            self.services.catalog_edit = lambda r: r["Table"].update({key: value})
            _, session = self.start()
            self.assertIsNone(session)
            self.assertEqual([c[0] for c in self.services.calls], ["glue:GetTable"])

    def test_unallowlisted_catalog_pointer_never_downloads(self):
        for path in ("s3://secret/metadata.json", "s3://fixture-metadata/outcomes-extra/a.json",
                     "s3://fixture-metadata/proposals/a.json", "s3://fixture-metadata/outcomes/manifest.avro",
                     "s3://fixture-metadata/outcomes/%2fsecret.json"):
            self.services.calls.clear()
            self.services.catalog_edit = lambda r: r["Table"]["Parameters"].update(metadata_location=path)
            _, session = self.start()
            self.assertIsNone(session)
            self.assertFalse(any(c[0] == "s3:GetObject" for c in self.services.calls))

    def test_out_of_scope_history_rejected_before_following(self):
        mutate(self.packet, lambda d: d.update({"metadata-log": [{"timestamp-ms": 1, "metadata-file": "s3://secret/x.json"}]}), 0)
        _, session = self.start()
        self.assertIsNone(session)
        self.assertEqual([c[0] for c in self.services.calls].count("s3:GetObject"), 1)
        self.assertTrue(self.services.bodies[0].closed)

    def test_response_rejection_closes_body_and_returns_no_counts(self):
        for edit in (lambda r: r.update(ContentLength=reader.normalizer.MAX_OBJECT_BYTES + 1),
                     lambda r: r.update(ContentLength=True), lambda r: r.update(ContentLength=1),
                     lambda r: r.update(ContentLength=r["ContentLength"] + 1),
                     lambda r: r.update(ContentEncoding="gzip"), lambda r: r.update(ContentRange="bytes 0-1/2"),
                     lambda r: r.update(DeleteMarker=True),
                     lambda r: r.update(ResponseMetadata={"HTTPStatusCode": 206})):
            self.services.object_edit = edit
            report, session = self.start()
            self.assertIsNone(session); self.assertIsNone(report["counts"]); self.safe(report)
            self.assertTrue(all(b.closed for b in self.services.bodies))

    def test_total_bytes_limit_is_enforced_before_body_read(self):
        with patch.object(reader.normalizer, "MAX_TOTAL_BYTES", 1):
            _, session = self.start()
        self.assertIsNone(session)
        self.assertTrue(self.services.bodies[0].closed)

    def test_get_and_catalog_attempt_limits_stop_without_retry(self):
        for constant, maximum, operation in (("MAX_GET_ATTEMPTS", 1, "s3:GetObject"),
                                              ("MAX_GET_TABLE_CALLS", 1, "glue:GetTable")):
            self.services.calls.clear()
            with patch.object(reader, constant, maximum):
                _, session = self.start()
            self.assertIsNone(session)
            self.assertEqual([c[0] for c in self.services.calls].count(operation), 1)

    def test_distinct_object_limit_rejects_before_fetching_extra_history(self):
        mutate(self.packet, lambda d: d.update({"metadata-log": [{"timestamp-ms": 1,
               "metadata-file": "s3://fixture-metadata/outcomes/extra.json"}]}), 0)
        with patch.object(reader.normalizer, "MAX_OBJECTS_PER_TABLE", 1):
            _, session = self.start()
        self.assertIsNone(session)
        self.assertEqual([c[0] for c in self.services.calls].count("s3:GetObject"), 1)

    def test_invalid_utf8_json_and_format_fail_closed(self):
        for text in ('{"format-version":2,"format-version":2}', '{"format-version":true}', '{"format-version":3}', '[]', 'secret'):
            self.packet["tables"]["outcomes"]["metadata_objects"][0]["metadata_json"] = text
            report, session = self.start()
            self.assertIsNone(session); self.safe(report)

    def test_missing_version_is_not_invented(self):
        self.services.object_edit = lambda r: r.pop("VersionId")
        _, session = self.start()
        self.assertTrue(all(r["version_id"] is None for r in session._records if r["kind"] == "object"))
        self.safe(self.finish(session))

    def test_session_cannot_be_reused(self):
        _, session = self.start()
        self.finish(session)
        count = len(self.services.calls)
        self.assertEqual(session.finish()["status"], "UNVERIFIED")
        self.assertEqual(len(self.services.calls), count)

    def test_expired_cross_date_and_reversed_clock_stop_before_more_reads(self):
        for delta in (timedelta(seconds=7201), timedelta(days=1), timedelta(seconds=-1)):
            _, session = self.start()
            self.clock.now += delta
            count = len(self.services.calls)
            report = session.finish()
            self.assertEqual(report["status"], "UNVERIFIED")
            self.assertEqual(len(self.services.calls), count)
            self.assertIsNone(session._packet)
            self.clock.now = BASE

    def test_expiry_during_download_closes_body(self):
        self.services.object_edit = lambda r: setattr(self.clock, "now", BASE + timedelta(hours=3))
        report, session = self.start()
        self.assertIsNone(session); self.safe(report)
        self.assertTrue(self.services.bodies[0].closed)

    def test_service_exception_is_redacted_terminal_and_not_retried(self):
        def fail(**kwargs):
            raise RuntimeError("secret s3://private/token")
        with patch.object(self.services, "get_object", side_effect=fail) as get:
            report, session = self.start()
            self.assertIsNone(session); self.safe(report); self.assertEqual(get.call_count, 1)

    def test_structural_failure_from_normalizer_returns_no_partial_counts(self):
        mutate(self.packet, lambda d: d.update({"table-uuid": "secret"}))
        _, session = self.start()
        report = self.finish(session)
        self.assertEqual(report["status"], "UNVERIFIED"); self.assertIsNone(report["counts"]); self.safe(report)

    def test_changed_head_within_phase_is_rejected(self):
        _, session = self.start()
        session._packet["tables"]["outcomes"]["observations"]["before_close"]["metadata_location"] = \
            self.packet["tables"]["outcomes"]["metadata_objects"][1]["location"]
        report = self.finish(session)
        self.assertEqual(report["status"], "UNVERIFIED")

    def test_discard_abandons_before_state_without_external_actions(self):
        _, session = self.start()
        count = len(self.services.calls)
        session.discard()
        self.assertEqual(session.finish()["status"], "UNVERIFIED")
        self.assertEqual(len(self.services.calls), count)

    def test_cli_plan_and_execute_rejection_never_read_stdin_or_sdk(self):
        with patch.object(reader, "clients") as factory, patch.object(sys, "stdin", None), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(reader.main([]), 0)
            self.assertEqual(reader.main(["--execute"]), 2)
            factory.assert_not_called()
        process = subprocess.run([sys.executable, "ops/read_snapshot_metadata.py"], capture_output=True, text=True, check=True)
        report = json.loads(process.stdout)
        self.assertEqual(report["status"], "LOCAL_PLAN_ONLY"); self.safe(report)

    def test_wire_guard_blocks_redirect_retry_and_unapproved_endpoint(self):
        for service, operation, host in (("glue", "GetTable", "glue.us-east-1.amazonaws.com"),
                                         ("s3", "GetObject", "fixture-metadata.s3.us-east-1.amazonaws.com")):
            handlers = {}
            client = SimpleNamespace(meta=SimpleNamespace(events=SimpleNamespace(register=lambda k, v: handlers.update({k: v}))))
            reader.install_send_guard(client, service, operation)
            reset, send = handlers["before-call." + service + ".*"], handlers["before-send." + service + ".*"]
            reset(SimpleNamespace(name=operation)); send(SimpleNamespace(url="https://" + host + "/"))
            with self.assertRaises(ValueError):
                reset(SimpleNamespace(name="HeadBucket"))
            with self.assertRaises(ValueError):
                send(SimpleNamespace(url="https://" + host + "/"))
            for url in ("http://" + host, "https://secret.example", "https://" + host + ":444/", "https://user@" + host):
                reset(SimpleNamespace(name=operation))
                with self.assertRaises(ValueError):
                    send(SimpleNamespace(url=url))
            reset(SimpleNamespace(name=operation)); send(SimpleNamespace(url="https://" + host + "/"))

    def test_retained_history_is_fetched_once_and_cycles_rejected(self):
        # Before points to a retained older metadata file, independent of later roots.
        original = copy.deepcopy(self.packet["tables"]["outcomes"]["metadata_objects"][0])
        original["location"] = "s3://fixture-metadata/outcomes/older.json"
        self.packet["tables"]["outcomes"]["metadata_objects"].append(original)
        mutate(self.packet, lambda d: d.update({"metadata-log": [{"timestamp-ms": d["last-updated-ms"],
               "metadata-file": original["location"]}]}), 0)
        _, session = self.start()
        self.assertEqual(self.finish(session)["status"], "METADATA_STRUCTURES_CONSISTENT_WITH_GAPS")
        self.assertEqual(sum(c[1].get("Key") == "outcomes/older.json" for c in self.services.calls), 1)
        self.clock.now = BASE
        mutate(self.packet, lambda d: d.update({"metadata-log": [{"timestamp-ms": d["last-updated-ms"],
               "metadata-file": "s3://fixture-metadata/outcomes/before.json"}]}), 2)
        _, session = self.start()
        self.assertEqual(self.finish(session)["status"], "UNVERIFIED")

    def test_body_read_failure_is_terminal_and_closed(self):
        class BrokenBody(io.BytesIO):
            def read(self, amount):
                raise OSError("secret")
        broken = BrokenBody()
        def replace(response):
            response["Body"].close()
            response["Body"] = broken
        self.services.object_edit = replace
        report, session = self.start()
        self.assertIsNone(session); self.safe(report); self.assertTrue(broken.closed)

    def test_invalid_utf8_bytes_are_rejected(self):
        raw_body = io.BytesIO(b"\xff")
        def replace(response):
            response["Body"].close()
            response.update(Body=raw_body, ContentLength=1)
        self.services.object_edit = replace
        report, session = self.start()
        self.assertIsNone(session); self.safe(report); self.assertTrue(raw_body.closed)


if __name__ == "__main__":
    unittest.main()
