"""Local byte and synthetic-record tests; no AWS access or repository mutation."""

import base64
import copy
from datetime import timedelta
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import unittest
import warnings
import zipfile
from unittest.mock import patch

from ops import validate_generator_release_binding as binding
from test_generator_receipt_reader import fixture as reader_fixture, BASE
from test_generator_execution_receipt import adapter


def zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in files.items():
            package.writestr(name, data)
    return stream.getvalue()


def fixture():
    with patch.dict(os.environ, {"PIPELINE_ENVIRONMENT": "staging", "ALLOW_FUTURE_SIMULATION": "false"}):
        config, logs, queries = reader_fixture()
        private = binding.reader.read_and_correlate(config, logs, queries)
    sources = {name: (binding.ROOT / path).read_bytes() for name, path in binding.FILES.items()}
    archive = zip_bytes(sources)
    environment = {**binding.TABLE_ENV_DEFAULTS, "ATHENA_SOURCE_DATABASE": adapter.DATABASE,
        "ATHENA_WORKGROUP": adapter.WORKGROUP, "ATHENA_OUTPUT": adapter.OUTPUT,
        "PIPELINE_ENVIRONMENT": "staging", "ALLOW_FUTURE_SIMULATION": "false",
        "DEFAULT_REPORTING_CURRENCY": "AUD"}
    configuration = {"FunctionName": binding.reader.GENERATOR, "Version": "$LATEST",
        "Runtime": "python3.14", "Handler": "lambda_function.lambda_handler", "PackageType": "Zip",
        "MemorySize": 512, "Timeout": 900, "Architectures": ["x86_64"],
        "Role": "arn:aws:iam::000000000000:role/glap-stateful-lifecycle-generator-staging-role",
        "Environment": {"Variables": environment}, "State": "Active", "LastUpdateStatus": "Successful",
        "RevisionId": "00000000-0000-0000-0000-000000000001",
        "LastModified": (BASE - timedelta(minutes=1)).isoformat(),
        "CodeSha256": base64.b64encode(hashlib.sha256(archive).digest()).decode()}
    packet = {"schema_version": binding.SCHEMA, "input_kind": "SYNTHETIC_FIXTURE",
        "expectation": {"source_commit": "1" * 40, "artifact_sha256": hashlib.sha256(archive).hexdigest(),
                        "configuration_sha256": binding.object_digest(binding.configuration_projection(configuration)),
                        "request_parameters": dict.fromkeys(binding.REQUEST_FIELDS)},
        "artifact_zip_base64": base64.b64encode(archive).decode(), "reader_config": config, "private_bundle": private,
        "configuration_before": {"captured_at": BASE.isoformat(), "configuration": copy.deepcopy(configuration)},
        "configuration_after": {"captured_at": (BASE + timedelta(seconds=100)).isoformat(), "configuration": copy.deepcopy(configuration)}}
    return packet, sources


def replace_archive(packet, archive):
    packet["artifact_zip_base64"] = base64.b64encode(archive).decode()
    packet["expectation"]["artifact_sha256"] = hashlib.sha256(archive).hexdigest()
    for key in ("configuration_before", "configuration_after"):
        packet[key]["configuration"]["CodeSha256"] = base64.b64encode(hashlib.sha256(archive).digest()).decode()


class GeneratorReleaseBindingTests(unittest.TestCase):
    def assert_unverified(self, report, reason=None):
        self.assertEqual(report["status"], "UNVERIFIED", report)
        self.assertIsNone(report["counts"])
        self.assertFalse(any(report["checks"].values()))
        if reason:
            self.assertEqual(report["reasons"], [reason])

    def validate(self, packet, sources):
        return binding.validate_binding(packet, source_reader=lambda commit: sources)

    def test_real_producer_reader_bundle_matches_zip_source_and_configuration_recipe(self):
        packet, sources = fixture()
        report = self.validate(packet, sources)
        self.assertEqual(report["status"], "RELEASE_BINDING_RECORDS_CONSISTENT", report)
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["counts"], {"source_files": 4, "configuration_observations": 2, "bound_queries": 10})
        for key in ("runtime_verified", "aws_receipts_authenticated", "human_review_authenticated",
                    "release_binding_verified", "mutable_revision_continuity_verified", "snapshot_lineage_verified",
                    "net_new_rows_verified", "real_world_evidence", "execution_available"):
            self.assertIs(report[key], False)
        self.assertFalse(any(report["authority"].values()))
        for private in (packet["expectation"]["source_commit"], packet["reader_config"]["invocation_id"],
                        packet["reader_config"]["source_bundle_sha256"], "arn:", "s3://", "lambda_function.py"):
            self.assertNotIn(private, json.dumps(report))

    def test_zip_bytes_must_equal_each_committed_file(self):
        packet, sources = fixture()
        altered = {**sources, "glap_temporal_boundary.py": sources["glap_temporal_boundary.py"] + b"\n# change"}
        replace_archive(packet, zip_bytes(altered))
        self.assert_unverified(self.validate(packet, sources), "GIT_ZIP_BYTES_MISMATCH")

    def test_line_endings_are_not_normalized_for_source_comparison(self):
        packet, sources = fixture()
        altered = {**sources, "lambda_function.py": sources["lambda_function.py"].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")}
        if altered == sources:
            altered["lambda_function.py"] = altered["lambda_function.py"].replace(b"\r\n", b"\n")
        replace_archive(packet, zip_bytes(altered))
        self.assert_unverified(self.validate(packet, sources), "GIT_ZIP_BYTES_MISMATCH")

    def test_artifact_expectation_and_lambda_base64_digest_are_distinct_checks(self):
        for field in ("expectation", "lambda"):
            packet, sources = fixture()
            if field == "expectation":
                packet["expectation"]["artifact_sha256"] = "0" * 64
            else:
                packet["configuration_after"]["configuration"]["CodeSha256"] = base64.b64encode(b"0" * 32).decode()
            reason = "ARTIFACT_EXPECTATION_MISMATCH" if field == "expectation" else "LAMBDA_ARTIFACT_DIGEST_MISMATCH"
            self.assert_unverified(self.validate(packet, sources), reason)

    def test_extra_missing_nested_and_duplicate_zip_entries_are_rejected(self):
        for mode in ("extra", "missing", "nested", "duplicate"):
            packet, sources = fixture()
            altered = dict(sources)
            if mode == "extra":
                altered["extra.py"] = b"pass"
            elif mode == "missing":
                altered.pop("glap_temporal_boundary.py")
            elif mode == "nested":
                altered["../lambda_function.py"] = altered.pop("lambda_function.py")
            archive = zip_bytes(altered)
            if mode == "duplicate":
                stream = io.BytesIO(archive)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(stream, "a") as package:
                        package.writestr("lambda_function.py", b"duplicate")
                archive = stream.getvalue()
            replace_archive(packet, archive)
            self.assert_unverified(self.validate(packet, sources), "INVALID_PACKAGE_FILES")

    def test_symlinks_archive_comments_and_oversize_members_are_rejected(self):
        packet, sources = fixture()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as package:
            for name, data in sources.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                package.writestr(info, data)
        replace_archive(packet, stream.getvalue())
        self.assert_unverified(self.validate(packet, sources), "UNSAFE_OR_OVERSIZED_ZIP_MEMBER")
        packet, sources = fixture()
        with patch.object(binding, "MAX_SOURCE_BYTES", 1):
            self.assert_unverified(self.validate(packet, sources), "UNSAFE_OR_OVERSIZED_ZIP_MEMBER")
        packet, sources = fixture()
        stream = io.BytesIO(base64.b64decode(packet["artifact_zip_base64"]))
        with zipfile.ZipFile(stream, "a") as package:
            package.comment = b"unexpected"
        replace_archive(packet, stream.getvalue())
        self.assert_unverified(self.validate(packet, sources), "INVALID_ZIP_ENVELOPE")

    def test_invalid_base64_and_nonzip_fail_closed(self):
        for value in ("@invalid", base64.b64encode(b"not-a-zip").decode()):
            packet, sources = fixture()
            packet["artifact_zip_base64"] = value
            self.assert_unverified(self.validate(packet, sources))

    def test_zip_source_is_never_extracted_or_executed(self):
        packet, sources = fixture()
        with patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("no extraction")), \
                patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("no extraction")):
            self.assertEqual(self.validate(packet, sources)["status"], "RELEASE_BINDING_RECORDS_CONSISTENT")

    def test_changed_source_manifest_cannot_be_hidden_by_matching_git_and_zip(self):
        packet, sources = fixture()
        sources["lambda_function.py"] += b"\n# new source"
        replace_archive(packet, zip_bytes(sources))
        self.assert_unverified(self.validate(packet, sources), "SOURCE_RECEIPT_DIGEST_MISMATCH")

    def test_legacy_source_cannot_claim_new_receipt_even_with_matching_hashes(self):
        packet, sources = fixture()
        sources["lambda_function.py"] = sources["lambda_function.py"].replace(
            b"def _new_execution_receipt(", b"def _legacy_execution_receipt(")
        replace_archive(packet, zip_bytes(sources))
        digest = binding.object_digest({name: hashlib.sha256(data).hexdigest() for name, data in sources.items()})
        packet["reader_config"]["source_bundle_sha256"] = digest
        packet["private_bundle"]["receipt"]["source_bundle_sha256"] = digest
        self.assert_unverified(self.validate(packet, sources), "SOURCE_RECEIPT_CONTRACT_UNAVAILABLE")

    def test_configuration_digest_includes_role_environment_and_runtime(self):
        packet, sources = fixture()
        packet["expectation"]["configuration_sha256"] = "0" * 64
        self.assert_unverified(self.validate(packet, sources), "CONFIGURATION_EXPECTATION_MISMATCH")
        baseline = packet["configuration_before"]["configuration"]
        original = binding.object_digest(binding.configuration_projection(baseline))
        changed = copy.deepcopy(baseline)
        changed["Role"] = changed["Role"].replace("000000000000", "111111111111")
        self.assertNotEqual(original, binding.object_digest(binding.configuration_projection(changed)))

    def test_wrong_function_version_state_or_runtime_fails(self):
        for field, value in (("Version", "99"), ("State", "Pending"), ("LastUpdateStatus", "InProgress"),
                             ("Runtime", "python3.13"), ("MemorySize", True), ("Handler", "other.handler"),
                             ("Layers", [{"Arn": "protected-layer"}])):
            with self.subTest(field=field):
                packet, sources = fixture()
                packet["configuration_after"]["configuration"][field] = value
                self.assert_unverified(self.validate(packet, sources))

    def test_unknown_environment_or_production_table_is_rejected(self):
        for change in ({"PRIVATE_SECRET": "must-not-escape"}, {"SHIPMENT_TABLE": "fact_production"},
                       {"PIPELINE_ENVIRONMENT": "production"}):
            packet, sources = fixture()
            packet["configuration_after"]["configuration"]["Environment"]["Variables"].update(change)
            report = self.validate(packet, sources)
            self.assert_unverified(report)
            self.assertNotIn("must-not-escape", json.dumps(report))

    def test_omitted_default_table_settings_resolve_like_producer(self):
        packet, sources = fixture()
        for field in ("configuration_before", "configuration_after"):
            env = packet[field]["configuration"]["Environment"]["Variables"]
            for key in binding.TABLE_ENV_DEFAULTS:
                env.pop(key)
        packet["expectation"]["configuration_sha256"] = binding.object_digest(
            binding.configuration_projection(packet["configuration_before"]["configuration"]))
        self.assertEqual(self.validate(packet, sources)["status"], "RELEASE_BINDING_RECORDS_CONSISTENT")

    def test_settings_hash_is_not_substituted_for_full_projection_hash(self):
        packet, sources = fixture()
        packet["expectation"]["configuration_sha256"] = packet["reader_config"]["settings_sha256"]
        self.assert_unverified(self.validate(packet, sources), "CONFIGURATION_EXPECTATION_MISMATCH")

    def test_changed_settings_fail_even_if_configuration_expectation_is_updated(self):
        packet, sources = fixture()
        for key in ("configuration_before", "configuration_after"):
            packet[key]["configuration"]["Environment"]["Variables"]["ATHENA_OUTPUT"] = "s3://fixture-other/results/"
        packet["expectation"]["configuration_sha256"] = binding.object_digest(
            binding.configuration_projection(packet["configuration_before"]["configuration"]))
        self.assert_unverified(self.validate(packet, sources), "SETTINGS_RECEIPT_DIGEST_MISMATCH")

    def test_changed_request_and_threshold_do_not_match_receipt(self):
        for field, value, reason in (("seed_population", True, "REQUEST_RECEIPT_DIGEST_MISMATCH"),
                                     ("minimum_policy_outcomes", 19, "POLICY_THRESHOLD_OUT_OF_SCOPE"),
                                     ("population_size", True, "INVALID_REQUEST_PARAMETERS")):
            packet, sources = fixture()
            packet["expectation"]["request_parameters"][field] = value
            self.assert_unverified(self.validate(packet, sources), reason)

    def test_changed_revision_or_last_modified_is_not_continuity(self):
        for field, value in (("RevisionId", "00000000-0000-0000-0000-000000000002"),
                             ("LastModified", (BASE - timedelta(seconds=30)).isoformat())):
            packet, sources = fixture()
            packet["configuration_after"]["configuration"][field] = value
            self.assert_unverified(self.validate(packet, sources), "CONFIGURATION_REVISION_CHANGED")

    def test_configuration_observations_must_bracket_run_and_not_be_stale_or_future(self):
        for field, value in (("configuration_before", (BASE + timedelta(seconds=4)).isoformat()),
                             ("configuration_after", (BASE + timedelta(seconds=20)).isoformat()),
                             ("configuration_after", (BASE + timedelta(hours=3)).isoformat()),
                             ("configuration_after", "2099-01-01T00:00:00+00:00")):
            packet, sources = fixture()
            packet[field]["captured_at"] = value
            self.assert_unverified(self.validate(packet, sources))

    def test_opaque_bundle_counts_and_query_bindings_are_revalidated(self):
        for mode in ("missing", "query", "timestamp", "trueflag", "boolean"):
            packet, sources = fixture()
            bundle = packet["private_bundle"]
            if mode == "missing":
                bundle["bound_queries"].pop()
            elif mode == "query":
                bundle["bound_queries"][0]["query_id"] = "other"
            elif mode == "timestamp":
                bundle["bound_queries"][0]["submitted_at"] = BASE.isoformat()
            elif mode == "trueflag":
                bundle["release_binding_verified"] = True
            else:
                bundle["controller_records"] = True
            self.assert_unverified(self.validate(packet, sources))

    def test_malformed_source_commit_is_rejected_before_git(self):
        packet, sources = fixture()
        packet["expectation"]["source_commit"] = "HEAD; echo private"
        with patch.object(binding, "read_commit_sources") as loader:
            self.assert_unverified(binding.validate_binding(packet), "INVALID_RELEASE_EXPECTATION")
        loader.assert_not_called()

    def test_git_loader_reads_fixed_blobs_disables_replace_fetch_and_ignores_git_environment(self):
        commit = "1" * 40
        blobs = {path: ("# " + path).encode() for path in binding.FILES.values()}
        calls = []
        def git_run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[1] == "rev-parse":
                output = (commit + "\n").encode()
            else:
                path = argv[-1].split(":", 1)[1]
                output = str(len(blobs[path])).encode() if argv[2] == "-s" else blobs[path]
            return subprocess.CompletedProcess(argv, 0, stdout=output, stderr=b"")
        with patch.dict(os.environ, {"GIT_DIR": "unrelated-repository"}), patch.object(binding.subprocess, "run", side_effect=git_run):
            result = binding.read_commit_sources(commit)
        self.assertEqual(len(calls), 9)
        self.assertEqual(result, {name: blobs[path] for name, path in binding.FILES.items()})
        for argv, options in calls:
            self.assertNotIn("GIT_DIR", options["env"])
            self.assertEqual(options["env"]["GIT_NO_REPLACE_OBJECTS"], "1")
            self.assertEqual(options["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(options["cwd"], binding.ROOT)
            self.assertNotIn("shell", options)

    def test_git_failure_is_sanitized(self):
        packet, sources = fixture()
        result = subprocess.CompletedProcess([], 128, stdout=b"", stderr=b"protected-git-error")
        with patch.object(binding.subprocess, "run", return_value=result):
            report = binding.validate_binding(packet)
        self.assert_unverified(report, "GIT_SOURCE_UNAVAILABLE")
        self.assertNotIn("protected", json.dumps(report))

    def test_cli_json_size_duplicates_and_arguments_fail_without_private_output(self):
        self.assert_unverified(binding.validate_json(b"x" * (binding.MAX_INPUT_BYTES + 1)), "INPUT_TOO_LARGE")
        self.assert_unverified(binding.validate_json(b'{"key":1,"key":2}'))
        for args in ([], ["--read"], ["--deploy"]):
            result = subprocess.run([sys.executable, "ops/validate_generator_release_binding.py", *args],
                                    input='{"private":"must-not-escape"}', capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assert_unverified(json.loads(result.stdout))
            self.assertNotIn("must-not-escape", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
