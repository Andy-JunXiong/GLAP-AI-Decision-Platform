"""Offline binding of private receipts, Git blobs, ZIP bytes and supplied configuration.

Never deploys, downloads, imports packaged source, extracts archives, or upgrades
supplied records to authenticated AWS evidence or human approval.
"""

from __future__ import annotations

import base64
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    from ops import read_generator_execution_receipt as reader
except ModuleNotFoundError:
    import read_generator_execution_receipt as reader


SCHEMA = "generator-release-binding-input.v1"
ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_ZIP_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
FILES = {
    "lambda_function.py": "lambda/glap_lifecycle_athena_adapter.py",
    "glap_stateful_lifecycle_generator.py": "lambda/glap_stateful_lifecycle_generator.py",
    "glap_temporal_boundary.py": "lambda/glap_temporal_boundary.py",
    "glap_governed_closed_loop.py": "lambda/glap_governed_closed_loop.py",
}
# Ordering is the producer's settings digest contract, not alphabetic order.
TABLE_ENV_DEFAULTS = {
    "SHIPMENT_TABLE": "fact_shipment_lifecycle_staging_v1",
    "SHIPMENT_EVENT_TABLE": "fact_shipment_lifecycle_event_staging_v1",
    "SHIPMENT_COST_TABLE": "fact_shipment_cost_staging_v1",
    "SHIPMENT_METRICS_TABLE": "fact_shipment_lifecycle_metrics_staging_v1",
    "SHIPMENT_SIGNAL_TABLE": "fact_shipment_signal_candidate_staging_v1",
    "LIFECYCLE_ALERT_TABLE": "fact_lifecycle_alert_staging_v1",
    "LIFECYCLE_ACTION_TABLE": "fact_lifecycle_action_staging_v1",
    "LIFECYCLE_ACTION_CURRENT_VIEW": "vw_lifecycle_action_current_staging_v1",
    "LIFECYCLE_OUTCOME_TABLE": "fact_lifecycle_outcome_staging_v1",
    "POLICY_PROPOSAL_TABLE": "fact_policy_proposal_staging_v1",
    "ROUTE_SERVICE_TABLE": "dim_route_service_v1",
    "LIFECYCLE_TARGET_TABLE": "dim_lifecycle_target_v1",
    "RATE_CARD_TABLE": "dim_rate_card_v1",
    "FX_RATE_TABLE": "dim_fx_rate_v1",
}
ENV_REQUIRED = {"ATHENA_SOURCE_DATABASE", "ATHENA_WORKGROUP", "ATHENA_OUTPUT",
                "PIPELINE_ENVIRONMENT", "ALLOW_FUTURE_SIMULATION"}
ENV_ALLOWED = set(TABLE_ENV_DEFAULTS) | ENV_REQUIRED | {"DEFAULT_REPORTING_CURRENCY"}
REQUEST_FIELDS = {"seed_population", "population_size", "new_count", "seed_version",
                  "retry_failed_run", "minimum_policy_outcomes", "policy_version"}
CONFIGURATION_FIELDS = {"FunctionName", "Version", "Runtime", "Handler", "MemorySize", "Timeout",
                        "PackageType", "Architectures", "Role", "Environment"}
require, exact, timestamp = reader.require, reader.exact, reader.timestamp


def object_digest(value: object) -> str:
    return hashlib.sha256(reader.evidence.canonical(value).encode()).hexdigest()


def report_base() -> dict:
    return {"schema_version": "generator-release-binding-report.v1", "status": "UNVERIFIED",
            "evidence_class": "LOCAL_BYTES_AND_SUPPLIED_RECORD_CONSISTENCY_ONLY",
            "reasons": [], "counts": None,
            "checks": {key: False for key in ("git_zip_bytes_equal", "zip_lambda_digest_equal",
                       "source_receipt_digest_equal", "configuration_digest_equal",
                       "settings_receipt_digest_equal", "request_receipt_digest_equal",
                       "configuration_records_bracket_run", "reader_bundle_consistent")},
            "runtime_verified": False, "aws_receipts_authenticated": False,
            "human_review_authenticated": False, "release_binding_verified": False,
            "mutable_revision_continuity_verified": False, "snapshot_lineage_verified": False,
            "net_new_rows_verified": False, "real_world_evidence": False,
            "execution_available": False, "authority": reader.evidence.empty_report()["authority"]}


def read_commit_sources(commit: str) -> dict[str, bytes]:
    """Read fixed Git blobs only, never checkout files, run hooks or fetch objects."""
    require(reader.matches(r"[a-f0-9]{40}", commit), "INVALID_SOURCE_COMMIT")
    git_environment = {**{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
                       "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
                       "GIT_TERMINAL_PROMPT": "0"}
    def git(*arguments: str) -> bytes:
        result = subprocess.run(["git", *arguments], cwd=ROOT, env=git_environment,
                                capture_output=True, timeout=10, check=False)
        require(result.returncode == 0, "GIT_SOURCE_UNAVAILABLE")
        return result.stdout
    require(git("rev-parse", "--verify", commit + "^{commit}").decode().strip() == commit,
            "SOURCE_COMMIT_RESOLUTION_MISMATCH")
    sources = {}
    for filename, path in FILES.items():
        ref = commit + ":" + path
        size = int(git("cat-file", "-s", ref).strip())
        require(0 < size <= MAX_SOURCE_BYTES, "GIT_SOURCE_SIZE_LIMIT")
        data = git("cat-file", "blob", ref)
        require(len(data) == size, "GIT_SOURCE_SIZE_MISMATCH")
        sources[filename] = data
    return sources


def decode_base64(value: object, maximum: int) -> bytes:
    require(type(value) is str and len(value) <= 4 * ((maximum + 2) // 3), "INVALID_BASE64_SIZE")
    decoded = base64.b64decode(value, validate=True)
    require(len(decoded) <= maximum and base64.b64encode(decoded).decode() == value, "INVALID_BASE64_VALUE")
    return decoded


def zip_sources(archive: bytes) -> dict[str, bytes]:
    require(0 < len(archive) <= MAX_ZIP_BYTES and archive.startswith(b"PK\x03\x04")
            and archive[-22:-18] == b"PK\x05\x06", "INVALID_ZIP_ENVELOPE")
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        entries = package.infolist()
        require(not package.comment and len(entries) == 4 and
                {entry.filename for entry in entries} == set(FILES), "INVALID_PACKAGE_FILES")
        data = {}
        for entry in entries:
            kind = stat.S_IFMT(entry.external_attr >> 16)
            require(not entry.is_dir() and not entry.flag_bits & 1 and kind in (0, stat.S_IFREG)
                    and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    and not entry.comment and 0 < entry.file_size <= MAX_SOURCE_BYTES,
                    "UNSAFE_OR_OVERSIZED_ZIP_MEMBER")
            data[entry.filename] = package.read(entry)  # CRC checked; never extract or import.
        return data


def configuration_projection(raw: dict) -> dict:
    """Bound selected config fields, not the entire AWS service response or IAM policy."""
    require(type(raw) is dict and CONFIGURATION_FIELDS <= set(raw), "MISSING_CONFIGURATION_FIELDS")
    require(raw["FunctionName"] == reader.GENERATOR and raw["Runtime"] == "python3.14"
            and raw["Handler"] == "lambda_function.lambda_handler" and raw["PackageType"] == "Zip"
            and type(raw["MemorySize"]) is int and raw["MemorySize"] == 512
            and type(raw["Timeout"]) is int and raw["Timeout"] == 900
            and raw["Architectures"] in (["x86_64"], ["arm64"])
            and raw.get("Layers", []) == [], "INVALID_STAGING_CONFIGURATION")
    require(reader.matches(r"arn:aws:iam::[0-9]{12}:role/glap-stateful-lifecycle-generator-staging-role", raw["Role"]),
            "INVALID_STAGING_ROLE_BINDING")
    exact(raw["Environment"], {"Variables"})
    env = raw["Environment"]["Variables"]
    require(type(env) is dict and ENV_REQUIRED <= set(env) <= ENV_ALLOWED and
            all(type(value) is str and len(value) <= 2048 for value in env.values()), "INVALID_ENVIRONMENT_FIELDS")
    require(env["ATHENA_SOURCE_DATABASE"] == "simulated_iceberg_m" and
            reader.matches(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}", env["ATHENA_WORKGROUP"])
            and reader.matches(r"s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]/[^\s]+/", env["ATHENA_OUTPUT"])
            and env["PIPELINE_ENVIRONMENT"] == "staging" and env["ALLOW_FUTURE_SIMULATION"] in ("true", "false")
            and env.get("DEFAULT_REPORTING_CURRENCY", "AUD") == "AUD", "INVALID_ENVIRONMENT_SCOPE")
    require(all(env.get(key, default) == default for key, default in TABLE_ENV_DEFAULTS.items()),
            "STAGING_TABLE_BINDING_CHANGED")
    return {**{key: raw[key] for key in sorted(CONFIGURATION_FIELDS)}, "Layers": []}


def require_receipt_source(source: bytes) -> None:
    """Reject legacy source lacking this producer; AST presence is not attestation."""
    tree = ast.parse(source.decode("utf-8-sig"))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    schemas = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
               and isinstance(node.value, ast.Constant) and any(isinstance(target, ast.Name)
               and target.id == "RECEIPT_SCHEMA" for target in node.targets)]
    require({"_source_bundle_sha256", "_new_execution_receipt", "_emit_execution_receipt",
             "_trace_query", "lambda_handler"} <= functions and
            schemas == ["generator-execution-receipt.v1"], "SOURCE_RECEIPT_CONTRACT_UNAVAILABLE")


def settings_digest(env: dict) -> str:
    return object_digest({"database": env["ATHENA_SOURCE_DATABASE"], "workgroup": env["ATHENA_WORKGROUP"],
        "output": env["ATHENA_OUTPUT"], "tables": [env.get(key, default) for key, default in TABLE_ENV_DEFAULTS.items()],
        "pipeline_environment": env["PIPELINE_ENVIRONMENT"], "allow_future_simulation": env["ALLOW_FUTURE_SIMULATION"]})


def validate_request(request: dict) -> None:
    exact(request, REQUEST_FIELDS)
    for key in ("seed_population", "retry_failed_run"):
        require(request[key] is None or type(request[key]) is bool, "INVALID_REQUEST_PARAMETERS")
    for key in ("population_size", "new_count"):
        require(request[key] is None or type(request[key]) is int and 0 <= request[key] <= 10000,
                "INVALID_REQUEST_PARAMETERS")
    for key in ("seed_version", "policy_version"):
        require(request[key] is None or reader.matches(r"[A-Za-z0-9_.-]{1,128}", request[key]), "INVALID_REQUEST_PARAMETERS")
    require(request["minimum_policy_outcomes"] is None or
            type(request["minimum_policy_outcomes"]) is int and request["minimum_policy_outcomes"] == 20,
            "POLICY_THRESHOLD_OUT_OF_SCOPE")


def validate_private_bundle(bundle: dict, config: dict) -> dict:
    exact(bundle, {"schema_version", "receipt", "bound_queries", "controller_records",
                   "release_binding_verified", "snapshot_lineage_verified"})
    require(bundle["schema_version"] == "generator-receipt-private-bundle.v1" and
            type(bundle["controller_records"]) is int and bundle["controller_records"] == 2 and
            bundle["release_binding_verified"] is bundle["snapshot_lineage_verified"] is False,
            "INVALID_PRIVATE_BUNDLE")
    start, end = reader.validate_config(config)
    receipt = bundle["receipt"]
    reader.validate_receipt(receipt, config, start, end)
    bound = bundle["bound_queries"]
    require(type(bound) is list and len(bound) == len(receipt["queries"]), "INCOMPLETE_BOUND_QUERIES")
    for query, binding in zip(receipt["queries"], bound):
        exact(binding, {"query_id", "purpose", "statement_sha256", "submitted_at", "completed_at"})
        require(all(binding[key] == query[key] for key in ("query_id", "purpose", "statement_sha256")),
                "BOUND_QUERY_MISMATCH")
        times = [timestamp(value) for value in (query["started_at"], binding["submitted_at"],
                                              binding["completed_at"], query["finished_at"])]
        millis = [int(value.timestamp() * 1000) for value in times]
        require(millis == sorted(millis), "BOUND_QUERY_TIME_MISMATCH")
    return receipt


def validate_binding(packet: object, source_reader=None) -> dict:
    report = report_base()
    try:
        exact(packet, {"schema_version", "input_kind", "expectation", "artifact_zip_base64", "reader_config",
                       "private_bundle", "configuration_before", "configuration_after"})
        require(packet["schema_version"] == SCHEMA and packet["input_kind"] in
                ("SYNTHETIC_FIXTURE", "SUPPLIED_STAGING_EXPORT"), "INVALID_BINDING_CONTRACT")
        expected = packet["expectation"]
        exact(expected, {"source_commit", "artifact_sha256", "configuration_sha256", "request_parameters"})
        require(reader.matches(r"[a-f0-9]{40}", expected["source_commit"]) and
                all(reader.matches(r"[a-f0-9]{64}", expected[key]) for key in
                    ("artifact_sha256", "configuration_sha256")), "INVALID_RELEASE_EXPECTATION")
        validate_request(expected["request_parameters"])
        receipt = validate_private_bundle(packet["private_bundle"], packet["reader_config"])
        archive = decode_base64(packet["artifact_zip_base64"], MAX_ZIP_BYTES)
        artifact_hash = hashlib.sha256(archive).digest()
        require(artifact_hash.hex() == expected["artifact_sha256"], "ARTIFACT_EXPECTATION_MISMATCH")
        files = zip_sources(archive)
        committed = (source_reader or read_commit_sources)(expected["source_commit"])
        exact(committed, set(FILES))
        require(all(type(value) is bytes and 0 < len(value) <= MAX_SOURCE_BYTES for value in committed.values()),
                "INVALID_COMMITTED_SOURCE_BYTES")
        require(files == committed, "GIT_ZIP_BYTES_MISMATCH")
        require_receipt_source(committed["lambda_function.py"])
        manifest = {name: hashlib.sha256(value).hexdigest() for name, value in sorted(files.items())}
        require(object_digest(manifest) == receipt["source_bundle_sha256"], "SOURCE_RECEIPT_DIGEST_MISMATCH")
        observations, projections = [], []
        for key in ("configuration_before", "configuration_after"):
            observation = packet[key]
            exact(observation, {"captured_at", "configuration"})
            captured = timestamp(observation["captured_at"])
            require(captured <= datetime.now(timezone.utc), "FUTURE_CONFIGURATION_OBSERVATION")
            raw = observation["configuration"]
            projected = configuration_projection(raw)
            require(raw["Version"] == receipt["function_version"] and
                    raw.get("State") == "Active" and raw.get("LastUpdateStatus") == "Successful",
                    "CONFIGURATION_NOT_STABLE_OR_WRONG_VERSION")
            require(reader.matches(reader.UUID, raw.get("RevisionId")), "INVALID_CONFIGURATION_REVISION")
            require(timestamp(raw["LastModified"]) <= captured, "CONFIGURATION_MODIFIED_AFTER_CAPTURE")
            require(decode_base64(raw["CodeSha256"], 32) == artifact_hash, "LAMBDA_ARTIFACT_DIGEST_MISMATCH")
            require(object_digest(projected) == expected["configuration_sha256"], "CONFIGURATION_EXPECTATION_MISMATCH")
            env = projected["Environment"]["Variables"]
            require(env["ATHENA_SOURCE_DATABASE"] == packet["reader_config"]["database"] and
                    env["ATHENA_WORKGROUP"] == packet["reader_config"]["workgroup"], "READER_CONFIGURATION_SCOPE_MISMATCH")
            require(settings_digest(env) == receipt["settings_sha256"], "SETTINGS_RECEIPT_DIGEST_MISMATCH")
            observations.append((captured, raw))
            projections.append(projected)
        before, after = observations
        require((after[0] - before[0]).total_seconds() <= reader.MAX_WINDOW_SECONDS and
                all(value[0].astimezone(ZoneInfo("Australia/Sydney")).date().isoformat() == receipt["logical_date"]
                    for value in observations), "CONFIGURATION_OBSERVATION_WINDOW_OUT_OF_SCOPE")
        require(before[0] <= timestamp(receipt["controller_link"]["run_started_at"]) <=
                timestamp(receipt["started_at"]) < timestamp(receipt["finished_at"]) <= after[0],
                "CONFIGURATION_RECORDS_DO_NOT_BRACKET_RUN")
        require(before[1]["RevisionId"] == after[1]["RevisionId"] and
                timestamp(before[1]["LastModified"]) == timestamp(after[1]["LastModified"])
                and projections[0] == projections[1], "CONFIGURATION_REVISION_CHANGED")
        require(object_digest(expected["request_parameters"]) == receipt["request_parameters_sha256"],
                "REQUEST_RECEIPT_DIGEST_MISMATCH")
        report.update(status="RELEASE_BINDING_RECORDS_CONSISTENT", counts={"source_files": 4,
            "configuration_observations": 2, "bound_queries": len(receipt["queries"])})
        report["checks"] = {key: True for key in report["checks"]}
    except reader.evidence.InvalidEvidence as error:
        report["reasons"] = [str(error)]
    except Exception:
        report["reasons"] = ["INVALID_BINDING_INPUT_OR_SOURCE_UNAVAILABLE"]
    return report


def validate_json(raw: bytes) -> dict:
    try:
        require(len(raw) <= MAX_INPUT_BYTES, "INPUT_TOO_LARGE")
        return validate_binding(reader.parse_json(raw))
    except reader.evidence.InvalidEvidence as error:
        report = report_base(); report["reasons"] = [str(error)]
    except Exception:
        report = report_base(); report["reasons"] = ["INVALID_BINDING_JSON"]
    return report


def main() -> int:
    if len(sys.argv) != 1:
        report = report_base(); report["reasons"] = ["INVALID_ARGUMENTS"]
    else:
        report = validate_json(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "RELEASE_BINDING_RECORDS_CONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
