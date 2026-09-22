"""Plan-only CLI; separately authorized two-phase Glue/S3 callable, memory only."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

try:
    from ops import normalize_snapshot_metadata as normalizer
except ModuleNotFoundError:
    import normalize_snapshot_metadata as normalizer

SCHEMA = "snapshot-metadata-acquisition-config.v1"
ALLOWED_CALLS = ("glue:GetTable", "s3:GetObject")
MAX_GET_TABLE_CALLS = 8
MAX_GET_ATTEMPTS = 64
require, exact = normalizer.require, normalizer.exact


def report_base():
    return {**normalizer.report_base(), "schema_version": "snapshot-metadata-acquisition-report.v1",
            "evidence_class": "LOCAL_METADATA_ACQUISITION_CONSISTENCY_ONLY", "read_attempted": False,
            "gaps": [*normalizer.GAPS, "CACHED_OBJECT_LOCATIONS_NOT_REVALIDATED",
                     "IMMUTABLE_OBJECT_IDENTITY_NOT_GUARANTEED"]}


def plan_summary():
    return {**report_base(), "status": "LOCAL_PLAN_ONLY", "allowed_calls": list(ALLOWED_CALLS),
            "max_get_table_calls": MAX_GET_TABLE_CALLS, "max_metadata_get_attempts": MAX_GET_ATTEMPTS,
            "max_objects_per_table": normalizer.MAX_OBJECTS_PER_TABLE,
            "max_object_bytes": normalizer.MAX_OBJECT_BYTES, "max_total_bytes": normalizer.MAX_TOTAL_BYTES,
            "max_window_seconds": normalizer.MAX_WINDOW_SECONDS,
            "callable_reader_available": True, "cli_read_available": False,
            "row_query_available": False, "persistence_available": False}


def utc_now():
    return datetime.now(timezone.utc)


def validate_config(config, now):
    exact(config, {"schema_version", "region", "database", "logical_date", "catalog_id", "tables"})
    require(config["schema_version"] == SCHEMA and config["region"] == "us-east-1" and
            config["database"] == "simulated_iceberg_m", "INVALID_SCOPE")
    require(now.tzinfo is not None and normalizer.evidence.iso_date(config["logical_date"]) ==
            now.astimezone(ZoneInfo("Australia/Sydney")).date(), "NOT_CURRENT_SYDNEY_DATE")
    require(type(config["catalog_id"]) is str and re.fullmatch(r"[0-9]{12}", config["catalog_id"]),
            "INVALID_CATALOG_BINDING")
    exact(config["tables"], set(normalizer.TABLES))
    prefixes = []
    for scope in config["tables"].values():
        exact(scope, {"metadata_prefix", "bucket_owner"})
        prefix = normalizer.location(scope["metadata_prefix"])
        bucket = prefix.split("/")[2]
        require(prefix.endswith("/") and len(prefix.split("/")) >= 5 and
                all(prefix.split("/")[3:-1]) and "%" not in prefix and
                not bucket.endswith(("--x-s3", "-s3alias", "--ol-s3")) and
                not re.fullmatch(r"[0-9.]+", bucket), "INVALID_METADATA_PREFIX")
        require(type(scope["bucket_owner"]) is str and re.fullmatch(r"[0-9]{12}", scope["bucket_owner"]),
                "INVALID_BUCKET_OWNER")
        require(not any(prefix.startswith(p) or p.startswith(prefix) for p in prefixes), "OVERLAPPING_PREFIXES")
        prefixes.append(prefix)


def clients():
    import boto3
    from botocore.config import Config
    session = boto3.Session(region_name="us-east-1")
    config = Config(retries={"total_max_attempts": 1, "mode": "standard"},
                    connect_timeout=5, read_timeout=10, ignore_configured_endpoint_urls=True,
                    use_dualstack_endpoint=False, use_fips_endpoint=False,
                    s3={"addressing_style": "virtual", "use_accelerate_endpoint": False,
                        "us_east_1_regional_endpoint": "regional"})
    glue, s3 = session.client("glue", config=config), session.client("s3", config=config)
    install_send_guard(glue, "glue", "GetTable")
    install_send_guard(s3, "s3", "GetObject")
    return glue, s3


def install_send_guard(client, service, operation):
    """Block SDK retries/region redirects before a second wire send, including S3 redirects."""
    sends = [0]

    def reset(model, **kwargs):
        require(model.name == operation, "UNAPPROVED_SDK_OPERATION")
        sends[0] = 0

    def before_send(request, **kwargs):
        url = urlsplit(request.url)
        host = url.netloc
        valid_host = (host == "glue.us-east-1.amazonaws.com" if service == "glue" else
                      host == "s3.us-east-1.amazonaws.com" or
                      re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\.s3\.us-east-1\.amazonaws\.com", host))
        require(sends[0] == 0 and url.scheme == "https" and valid_host, "EXTRA_OR_NONREGIONAL_SEND_REJECTED")
        sends[0] += 1

    client.meta.events.register("before-call." + service + ".*", reset)
    client.meta.events.register("before-send." + service + ".*", before_send)


class MetadataSession:
    """Private single-use capture. Not thread-safe; never serialize its attributes."""

    def __init__(self, config, glue, s3, clock, started):
        self._config, self._glue, self._s3, self._clock = config, glue, s3, clock
        self._started = self._last = started
        self._busy = self._closed = False
        self._gets = self._catalogs = self._bytes = 0
        self._records = []
        self._packet = {"schema_version": normalizer.SCHEMA, "input_kind": "SUPPLIED_STAGING_EXPORT",
                        **{key: config[key] for key in ("region", "database", "logical_date")},
                        "tables": {kind: {"metadata_objects": [], "observations": {}} for kind in normalizer.TABLES}}

    def __repr__(self):
        return "<MetadataSession private>"

    def discard(self):
        self._closed = True
        self._config = self._glue = self._s3 = self._clock = self._packet = self._records = None

    def _check(self):
        require(not self._closed, "SESSION_CLOSED")
        now = self._clock()
        validate_config(self._config, now)
        require(self._last <= now and (now - self._started).total_seconds() <= normalizer.MAX_WINDOW_SECONDS,
                "CLOCK_OR_WINDOW_REJECTED")
        self._last = now
        return now

    def _location(self, kind, value):
        value = normalizer.location(value)
        require(value.startswith(self._config["tables"][kind]["metadata_prefix"]) and
                value.endswith(".json") and "%" not in value and
                all(value.split("/")[3:]), "OBJECT_OUTSIDE_METADATA_SCOPE")
        return value

    def _observe(self, kind, phase):
        start = self._check()
        require(self._catalogs < MAX_GET_TABLE_CALLS, "CATALOG_CALL_LIMIT")
        self._catalogs += 1
        response = self._glue.get_table(CatalogId=self._config["catalog_id"],
                                       DatabaseName=self._config["database"], Name=normalizer.TABLES[kind])
        finish = self._check()
        table = response["Table"]
        require(table.get("CatalogId") == self._config["catalog_id"] and
                table.get("DatabaseName") == self._config["database"] and table.get("Name") == normalizer.TABLES[kind]
                and table.get("TableType") == "EXTERNAL_TABLE" and not table.get("TargetTable") and
                table.get("Parameters", {}).get("table_type", "").upper() == "ICEBERG", "CATALOG_BINDING_REJECTED")
        pointer = self._location(kind, table["Parameters"].get("metadata_location"))
        self._packet["tables"][kind]["observations"][phase] = {
            "database": self._config["database"], "table": normalizer.TABLES[kind],
            "metadata_location": pointer, "started_at": start.isoformat(), "finished_at": finish.isoformat()}
        self._records.append({"kind": "catalog", "started_at": start, "finished_at": finish,
                              "version_id": table.get("VersionId"), "metadata_location": pointer})
        return pointer

    def _fetch(self, kind, root):
        objects = self._packet["tables"][kind]["metadata_objects"]
        known = {item["location"] for item in objects}
        pending = [root]
        while pending:
            location = self._location(kind, pending.pop())
            if location in known:
                continue
            require(len(known) < normalizer.MAX_OBJECTS_PER_TABLE and self._gets < MAX_GET_ATTEMPTS,
                    "METADATA_OBJECT_LIMIT")
            start = self._check()
            self._gets += 1
            bucket, key = location[5:].split("/", 1)
            response = self._s3.get_object(Bucket=bucket, Key=key,
                                         ExpectedBucketOwner=self._config["tables"][kind]["bucket_owner"])
            body = response.get("Body")
            try:
                self._check()
                length = response.get("ContentLength")
                require(type(length) is int and 0 < length <= normalizer.MAX_OBJECT_BYTES,
                        "METADATA_OBJECT_BYTE_LIMIT")
                require(self._bytes + length <= normalizer.MAX_TOTAL_BYTES, "TOTAL_METADATA_BYTE_LIMIT")
                require(response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 200 and
                        "ContentRange" not in response and response.get("ContentEncoding") in (None, "identity") and
                        not response.get("DeleteMarker"), "OBJECT_RESPONSE_REJECTED")
                chunks, received = [], 0
                while received < length:
                    self._check()
                    chunk = body.read(min(65536, length - received))
                    self._check()
                    require(type(chunk) is bytes and 0 < len(chunk) <= min(65536, length - received),
                            "OBJECT_TRUNCATED_OR_OVERSIZED")
                    chunks.append(chunk)
                    received += len(chunk)
                require(body.read(1) == b"", "OBJECT_LENGTH_MISMATCH")
                finish = self._check()
            finally:
                if body is not None:
                    body.close()
            raw = b"".join(chunks)
            text = raw.decode("utf-8")
            doc = normalizer.parse_json(text)
            require(type(doc) is dict and type(doc.get("format-version")) is int and doc["format-version"] == 2,
                    "UNSUPPORTED_METADATA_FORMAT")
            history = doc.get("metadata-log", [])
            require(type(history) is list and len(history) <= normalizer.MAX_OBJECTS_PER_TABLE, "METADATA_HISTORY_LIMIT")
            targets = []
            for entry in history:
                exact(entry, {"timestamp-ms", "metadata-file"})
                targets.append(self._location(kind, entry["metadata-file"]))
            require(len(known | set(pending) | set(targets) | {location}) <= normalizer.MAX_OBJECTS_PER_TABLE,
                    "METADATA_OBJECT_LIMIT")
            self._bytes += len(raw)
            objects.append({"location": location, "metadata_json": text})
            known.add(location)
            self._records.append({"kind": "object", "location": location, "started_at": start, "finished_at": finish,
                                  "sha256": hashlib.sha256(raw).hexdigest(), "version_id": response.get("VersionId"),
                                  "etag": response.get("ETag"), "immutable_identity_verified": False})
            pending.extend(target for target in targets if target not in known and target not in pending)

    def _phase(self, phase):
        # Both openings precede either closing. No row-query or business callback is executed.
        roots = {kind: self._observe(kind, phase + "_open") for kind in normalizer.TABLES}
        for kind, root in roots.items():
            self._fetch(kind, root)
        roots = {kind: self._observe(kind, phase + "_close") for kind in normalizer.TABLES}
        for kind, root in roots.items():
            self._fetch(kind, root)

    def finish(self):
        report = report_base()
        if self._closed or self._busy:
            return {**report, "reasons": ["SESSION_CLOSED_OR_BUSY"]}
        self._busy = True
        try:
            now = self._check()
            require(all(normalizer.evidence.timestamp(t["observations"]["before_close"]["finished_at"]) < now
                        for t in self._packet["tables"].values()), "PHASE_OBSERVATIONS_OVERLAP")
            report["read_attempted"] = True
            self._phase("after")
            self._check()
            result = normalizer.normalize(self._packet)
            report.update(status=result["status"], counts=result["counts"], reasons=result["reasons"])
            return report
        except Exception:
            return {**report, "status": "UNVERIFIED", "counts": None, "reasons": ["METADATA_CAPTURE_REJECTED"]}
        finally:
            self.discard()


def start_capture(config, *, glue=None, s3=None, clock=None):
    """Capture before fences. Calling this is a read attempt, never an authorization."""
    report, session = report_base(), None
    try:
        clock = clock or utc_now
        started = clock()
        config = copy.deepcopy(config)
        validate_config(config, started)
        require((glue is None) == (s3 is None), "INCOMPLETE_CLIENT_PAIR")
        if glue is None:
            glue, s3 = clients()
        session = MetadataSession(config, glue, s3, clock, started)
        report["read_attempted"] = True
        session._phase("before")
        return {**report, "status": "BEFORE_CAPTURED_AFTER_PENDING"}, session
    except Exception:
        if session is not None:
            session.discard()
        return {**report, "reasons": ["METADATA_CAPTURE_REJECTED"]}, None


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    report = plan_summary() if not args else {**report_base(), "reasons": ["CLI_READ_NOT_AVAILABLE"]}
    print(json.dumps(report, sort_keys=True))
    return 0 if not args else 2


if __name__ == "__main__":
    raise SystemExit(main())
