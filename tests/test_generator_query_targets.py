"""Synthetic source/release/SQL records only; no AWS, SQL or packaged-source execution."""

import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from ops import project_generator_query_targets as targets
from test_generator_release_binding import fixture as release_fixture, replace_archive, zip_bytes
from test_generator_receipt_reader import fixture as receipt_fixture, BASE
from test_generator_execution_receipt import adapter


def fixture():
    release, sources = release_fixture()
    _, _, client = receipt_fixture()
    writes = [{"query_id": q["query_id"], "sql": client.queries[q["query_id"]]["Query"]}
              for q in release["private_bundle"]["receipt"]["queries"] if q["purpose"] == "WRITE_MERGE"]
    return {"schema_version": targets.SCHEMA, "release_binding": release, "write_statements": writes}, sources


def replace_statements(packet, sqls, retry=False):
    release = packet["release_binding"]
    receipt = release["private_bundle"]["receipt"]
    prototype = copy.deepcopy(receipt["queries"][-1])
    receipt["queries"] = receipt["queries"][:9]
    release["private_bundle"]["bound_queries"] = release["private_bundle"]["bound_queries"][:9]
    receipt["planned_write_statements"] = receipt["completed_write_statements"] = len(sqls)
    receipt["finished_at"] = (BASE + timedelta(seconds=90)).isoformat()
    release["expectation"]["request_parameters"]["retry_failed_run"] = retry
    digest = targets.binding.object_digest(release["expectation"]["request_parameters"])
    receipt["request_parameters_sha256"] = release["reader_config"]["request_parameters_sha256"] = digest
    packet["write_statements"] = []
    for index, sql in enumerate(sqls):
        start = BASE + timedelta(seconds=70, milliseconds=index * 100)
        end = start + timedelta(milliseconds=100)
        query = {**prototype, "sequence": index + 10, "query_id": str(uuid.UUID(int=index + 10)),
                 "statement_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                 "started_at": start.isoformat(), "finished_at": end.isoformat()}
        receipt["queries"].append(query)
        release["private_bundle"]["bound_queries"].append({
            **{key: query[key] for key in ("query_id", "purpose", "statement_sha256")},
            "submitted_at": start.isoformat(), "completed_at": end.isoformat()})
        packet["write_statements"].append({"query_id": query["query_id"], "sql": sql})


def sql_for(family, rows=None, retry=False):
    table = getattr(adapter, family + "_TABLE")
    rule = targets.source_contract((targets.binding.ROOT / "lambda/glap_lifecycle_athena_adapter.py").read_bytes())[table]
    return adapter.build_merge_sql(table, getattr(adapter, family + "_COLUMNS"), rule["keys"],
                                   [{}] if rows is None else rows, retry and rule["retry_updates"])


class GeneratorQueryTargetTests(unittest.TestCase):
    def setUp(self):
        self.packet, self.sources = fixture()

    def report(self):
        return targets.project(self.packet, source_reader=lambda commit: self.sources)

    def safe(self, report):
        self.assertFalse(any(report["authority"].values()))
        for key in ("runtime_verified", "release_binding_verified", "history_complete", "writer_binding_verified",
                    "snapshot_lineage_verified", "net_new_rows_verified", "real_world_evidence", "execution_available"):
            self.assertIs(report[key], False)
        for marker in ("protected-entity", "s3://", "arn:", "MERGE INTO", "lambda_function", "statement_sha256",
                       "invocation_id", "source_commit", "secret"):
            self.assertNotIn(marker, json.dumps(report))

    def rejected(self):
        report = self.report()
        self.assertEqual(report["status"], "UNVERIFIED", report)
        self.assertIsNone(report["counts"]); self.safe(report)

    def test_real_generated_sql_receipt_and_release_records_project_privately(self):
        calls = []
        private = targets.project_private(self.packet, source_reader=lambda commit: calls.append(commit) or self.sources)
        self.assertEqual(calls, [self.packet["release_binding"]["expectation"]["source_commit"]])
        self.assertEqual(private["queries"][0]["table"], adapter.OUTCOME_TABLE)
        self.assertEqual(private["queries"][0]["statement_sha256"], hashlib.sha256(self.packet["write_statements"][0]["sql"].encode()).hexdigest())
        self.assertNotIn("sql", private["queries"][0]); self.assertNotIn("snapshot_id", private["queries"][0])
        report = self.report()
        self.assertEqual(report["status"], "SOURCE_QUERY_TARGETS_CONSISTENT_WITH_GAPS")
        self.assertEqual(report["counts"], {"write_queries": 1, "outcomes_queries": 1, "proposals_queries": 0, "other_queries": 0})
        self.safe(report)

    def test_all_nine_families_are_accounted_for(self):
        replace_statements(self.packet, [sql_for(family)[0] for family in targets.FAMILIES])
        report = self.report()
        self.assertEqual(report["counts"], {"write_queries": 9, "outcomes_queries": 1, "proposals_queries": 1, "other_queries": 7})
        self.safe(report)

    def test_retry_shape_matches_request_and_keeps_actions_proposals_insert_only(self):
        replace_statements(self.packet, [sql_for(family, retry=True)[0] for family in targets.FAMILIES], retry=True)
        private = targets.project_private(self.packet, lambda commit: self.sources)
        self.assertEqual([q["matched_update"] for q in private["queries"]], [True] * 6 + [False, True, False])

    def test_unexpected_update_and_missing_retry_update_are_rejected(self):
        for sql, retry in ((sql_for("OUTCOME", retry=True)[0], False), (sql_for("OUTCOME")[0], True)):
            replace_statements(self.packet, [sql], retry=retry)
            self.rejected()

    def test_real_batch_boundaries_and_statement_input_order(self):
        sqls = sql_for("OUTCOME", [{}] * 101)
        replace_statements(self.packet, sqls)
        self.packet["write_statements"].reverse()
        private = targets.project_private(self.packet, lambda commit: self.sources)
        self.assertEqual([q["batch_row_count"] for q in private["queries"]], [100, 1])

    def test_short_intermediate_batch_and_reordered_family_are_rejected(self):
        for sqls in ([sql_for("OUTCOME")[0]] * 2, [sql_for("OUTCOME")[0], sql_for("EVENT")[0]]):
            replace_statements(self.packet, sqls)
            self.rejected()

    def test_zero_writes_stays_consistent_without_inventing_outputs(self):
        replace_statements(self.packet, [])
        self.packet["release_binding"]["private_bundle"]["receipt"]["generated_counts"] = {"outcomes": 0, "proposals": 0}
        report = self.report()
        self.assertEqual(report["counts"]["write_queries"], 0); self.safe(report)

    def test_literals_with_sql_keywords_quotes_and_newlines_are_data(self):
        literals = (None, True, False, 123, -1, 1.25, -0.0, 1e+30, 1e-09, date(2026, 9, 1),
                    datetime(2026, 9, 1, tzinfo=timezone.utc), "", "中文", "'", "x'); DROP TABLE secret; --\nMERGE INTO x", "\\")
        sqls = sql_for("OUTCOME", [{"outcome_id": value} for value in literals])
        replace_statements(self.packet, sqls)
        report = self.report()
        self.assertEqual(report["status"], "SOURCE_QUERY_TARGETS_CONSISTENT_WITH_GAPS"); self.safe(report)

    def test_sql_byte_hash_is_not_whitespace_normalized(self):
        self.packet["write_statements"][0]["sql"] += "\n"
        self.rejected()

    def test_trailing_statements_comments_and_whitespace_fail_full_template(self):
        sql = sql_for("OUTCOME")[0]
        for suffix in (";", "; DROP TABLE secret", " -- comment", "\n", "/* comment */"):
            replace_statements(self.packet, [sql + suffix]); self.rejected()

    def test_target_database_quoting_and_nonmerge_fail_even_with_matching_hash(self):
        sql = sql_for("OUTCOME")[0]
        for changed in (sql.replace("simulated_iceberg_m", "production"), sql.replace(adapter.OUTCOME_TABLE, "unknown"),
                        sql.replace(adapter.OUTCOME_TABLE, '"' + adapter.OUTCOME_TABLE + '"'),
                        sql.lower(), "SELECT 'MERGE INTO secret'", "DELETE FROM secret"):
            replace_statements(self.packet, [changed]); self.rejected()

    def test_column_join_and_insert_mutations_fail_even_with_matching_hash(self):
        sql = sql_for("OUTCOME")[0]
        for changed in (sql.replace("ON target.", "ON other."), sql.replace(" = source.", " <> source.", 1),
                        sql.replace("AS source (outcome_id", "AS source (wrong"),
                        sql.replace("WHEN NOT MATCHED", "WHEN MATCHED"), sql.replace("VALUES (source.outcome_id", "VALUES (NULL")):
            replace_statements(self.packet, [changed]); self.rejected()

    def test_values_expressions_comments_and_nonfinite_numbers_fail(self):
        sql = sql_for("OUTCOME")[0]
        for literal in ("now()", "NULL /* secret */", "NaN", "inf", "1e+999", "1e+0004", "-0", "1 + 1", "CAST(NULL AS varchar)", "DATE '2026-02-30'",
                        "TIMESTAMP '2026-09-01 25:00:00'", "'unclosed", "NULL, NULL"):
            replace_statements(self.packet, [sql.replace("(NULL, ", "(" + literal + ", ", 1)])
            self.rejected()

    def test_empty_and_oversized_batches_are_rejected(self):
        rule = next(iter(targets.source_contract(self.sources["lambda_function.py"]).values()))
        for values in ("", "(" + ", ".join(["NULL"] * len(rule["columns"])) + "),\n"):
            with self.assertRaises(ValueError):
                targets.batch_size(values, len(rule["columns"]))
        with self.assertRaises(ValueError):
            targets.batch_size(",\n".join(["(NULL)"] * 101), 1)

    def test_missing_duplicate_extra_and_read_query_statements_are_rejected(self):
        original = copy.deepcopy(self.packet["write_statements"])
        for statements in ([], original * 2, original + [{"query_id": str(uuid.UUID(int=999)), "sql": "secret"}],
                           [{"query_id": str(uuid.UUID(int=1)), "sql": original[0]["sql"]}]):
            self.packet["write_statements"] = statements; self.rejected()

    def test_statement_input_cannot_supply_guessed_target_or_snapshot(self):
        self.packet["write_statements"][0]["target_table"] = adapter.OUTCOME_TABLE
        self.rejected()

    def test_release_or_receipt_disagreement_blocks_projection(self):
        self.packet["release_binding"]["private_bundle"]["bound_queries"][-1]["statement_sha256"] = "0" * 64
        self.rejected()

    def test_unavailable_source_is_redacted(self):
        def unavailable(commit):
            raise RuntimeError("secret arn:private")
        report = targets.project(self.packet, unavailable)
        self.assertEqual(report["status"], "UNVERIFIED"); self.safe(report)

    def test_recipe_source_change_is_rejected_without_executing_it(self):
        with patch("builtins.exec") as execute:
            with self.assertRaises(ValueError):
                targets.source_contract(self.sources["lambda_function.py"] + b"\nraise Exception('secret')\n")
            execute.assert_not_called()

    def test_git_zip_byte_equality_is_still_required(self):
        changed = {**self.sources, "lambda_function.py": self.sources["lambda_function.py"] + b"\n# changed\n"}
        replace_archive(self.packet["release_binding"], zip_bytes(changed))
        self.rejected()

    def test_consistent_release_with_unreviewed_adapter_still_fails_recipe_gate(self):
        self.sources["lambda_function.py"] += b"\n# unreviewed recipe change\n"
        release = self.packet["release_binding"]
        replace_archive(release, zip_bytes(self.sources))
        manifest = {name: hashlib.sha256(value).hexdigest() for name, value in self.sources.items()}
        digest = targets.binding.object_digest(manifest)
        release["private_bundle"]["receipt"]["source_bundle_sha256"] = release["reader_config"]["source_bundle_sha256"] = digest
        self.assertEqual(targets.binding.validate_binding(release, lambda commit: self.sources)["status"],
                         "RELEASE_BINDING_RECORDS_CONSISTENT")
        self.rejected()

    def test_reviewed_recipe_allows_crlf_but_not_a_new_source_pin_claim(self):
        lf = self.sources["lambda_function.py"].replace(b"\r\n", b"\n")
        self.assertEqual(targets.source_contract(lf), targets.source_contract(lf.replace(b"\n", b"\r\n")))
        self.assertIn("LEGACY_SOURCE_PIN_INCOMPATIBLE_WITH_RECEIPT_PRODUCER", self.report()["gaps"])

    def test_configuration_target_override_is_rejected_by_release_boundary(self):
        release = self.packet["release_binding"]
        for key in ("configuration_before", "configuration_after"):
            release[key]["configuration"]["Environment"]["Variables"]["LIFECYCLE_OUTCOME_TABLE"] = "different"
        self.rejected()

    def test_sql_limits_reject_before_source_read(self):
        for name, value in (("MAX_SQL_BYTES", 1), ("MAX_TOTAL_SQL_BYTES", 1)):
            with patch.object(targets, name, value), patch.object(targets.binding, "read_commit_sources") as read:
                self.assertEqual(targets.project(self.packet)["status"], "UNVERIFIED")
                read.assert_not_called()

    def test_future_receipt_and_forged_proof_flags_are_rejected(self):
        self.packet["release_binding"]["reader_config"]["logical_date"] = "9999-12-31"
        self.rejected()
        self.packet, self.sources = fixture()
        self.packet["release_binding"]["private_bundle"]["release_binding_verified"] = True
        self.rejected()

    def test_json_limits_duplicate_keys_and_nonfinite_are_rejected(self):
        for raw in (b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', b'[]'):
            self.safe(targets.validate_json(raw))
            self.assertEqual(targets.validate_json(raw)["status"], "UNVERIFIED")
        with patch.object(targets, "MAX_INPUT_BYTES", 1):
            self.assertEqual(targets.validate_json(b'{}')["status"], "UNVERIFIED")

    def test_plan_cli_never_reads_stdin_sources_or_sdk(self):
        with patch.object(sys, "stdin", None), patch.object(targets.binding, "read_commit_sources") as read, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(targets.main([]), 0)
            self.assertEqual(targets.main(["--execute"]), 2)
            read.assert_not_called()
        result = subprocess.run([sys.executable, "ops/project_generator_query_targets.py"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["status"], "LOCAL_PLAN_ONLY")

    def test_project_cli_only_emits_aggregate_results(self):
        incoming = io.TextIOWrapper(io.BytesIO(json.dumps(self.packet).encode()))
        with patch.object(sys, "stdin", incoming), patch.object(targets.binding, "read_commit_sources", return_value=self.sources), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(targets.main(["--project"]), 0)
            self.safe(json.loads(output.getvalue()))
        with patch.object(sys, "stdin", None), patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(targets.main(["--project"]), 2)
            self.safe(json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
