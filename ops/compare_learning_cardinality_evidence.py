"""Offline, aggregate-only comparison of supplied staging evidence via stdin.

No collector, network client, file output, runtime attestation, or authority.
Even consistent inputs are unverified supplied evidence, never a runtime PASS.
"""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


SCHEMA = "learning-cardinality-comparison-input.v1"
SOURCE_COMMIT = "a10678bc324f62731a021b33d9919f39fcba7731"
MINIMUM_OUTCOMES = 20
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
CLOSED = {"SUCCESSFUL", "PARTIALLY_SUCCESSFUL", "FAILED", "INCONCLUSIVE"}
TEMPORAL = {"temporal_scope_id", "execution_mode", "time_basis", "as_of_date",
            "execution_scenario_id"}
OUTCOME_FIELDS = TEMPORAL | {
    "outcome_id", "action_id", "alert_fingerprint", "shipment_id", "dt",
    "observation_due_date", "status", "observed_date", "effect_pct",
    "outcome_version", "provenance",
}
PROPOSAL_FIELDS = TEMPORAL | {
    "proposal_id", "source_policy_version", "status", "observed_outcome_count",
    "success_rate_pct", "proposed_change", "simulation_config_change",
    "effective_date", "approved_by", "approved_policy_version",
    "rollback_policy_version", "provenance", "created_date",
}
RELEASE_FIELDS = {"source_commit", "artifact_sha256", "configuration_sha256"}
SNAPSHOT_FIELDS = {"captured_at", "cutoff_date", "complete", "release",
                   "outcomes", "proposals"}
RUN_FIELDS = {"started_at", "finished_at", "logical_date", "release",
              "generator_path_completed", "exclusive_window"}


class InvalidEvidence(ValueError):
    """Only fixed, identifier-free reason codes may cross the output boundary."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise InvalidEvidence(reason)


def exact(value: object, keys: set[str]) -> None:
    require(type(value) is dict and set(value) == keys, "INVALID_SHAPE")


def iso_date(value: object) -> date:
    require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
            "INVALID_DATE")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidEvidence("INVALID_DATE") from None


def timestamp(value: object) -> datetime:
    require(type(value) is str, "INVALID_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.utcoffset() is not None, "INVALID_TIMESTAMP")
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise InvalidEvidence("INVALID_TIMESTAMP") from None


def text_value(value: object) -> None:
    require(type(value) is str and bool(value.strip()) and len(value) <= 4096,
            "INVALID_FIELD")


def number(value: object) -> None:
    require(type(value) in (int, float) and math.isfinite(value), "INVALID_NUMBER")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def release(value: dict) -> None:
    exact(value, RELEASE_FIELDS)
    require(value["source_commit"] == SOURCE_COMMIT, "UNBOUND_SOURCE")
    for field in ("artifact_sha256", "configuration_sha256"):
        require(type(value[field]) is str and
                re.fullmatch(r"[a-f0-9]{64}", value[field]) is not None,
                "INVALID_RELEASE_BINDING")


def temporal(row: dict, cutoff: date) -> date:
    require(row["temporal_scope_id"] == "OPERATIONAL" and
            row["execution_mode"] == "OPERATIONAL" and
            row["time_basis"] == "ACTUAL_CALENDAR" and
            row["execution_scenario_id"] is None, "TEMPORAL_SCOPE_MISMATCH")
    as_of = iso_date(row["as_of_date"])
    require(as_of <= cutoff, "FUTURE_OR_POST_CUTOFF_ROW")
    return as_of


def snapshot(value: dict, cutoff: date) -> tuple[dict, dict, int, int]:
    exact(value, SNAPSHOT_FIELDS)
    require(value["complete"] is True, "INCOMPLETE_SNAPSHOT")
    require(iso_date(value["cutoff_date"]) == cutoff, "CUTOFF_MISMATCH")
    release(value["release"])
    for field in ("outcomes", "proposals"):
        require(type(value[field]) is list and len(value[field]) <= MAX_ROWS,
                "INVALID_ROW_COLLECTION")
    versions, latest = {}, {}
    for row in value["outcomes"]:
        exact(row, OUTCOME_FIELDS)
        as_of = temporal(row, cutoff)
        version_date = iso_date(row["dt"])
        require(version_date <= as_of, "FUTURE_OR_POST_CUTOFF_ROW")
        for field in ("outcome_id", "action_id", "alert_fingerprint", "shipment_id",
                      "outcome_version"):
            text_value(row[field])
        require(type(row["status"]) is str and row["status"] in CLOSED | {"PENDING"}
                and row["provenance"] == "SIMULATED", "INVALID_OUTCOME_STATE")
        due = iso_date(row["observation_due_date"])
        if row["status"] == "PENDING":
            require(row["observed_date"] is None and row["effect_pct"] is None,
                    "INVALID_PENDING_OUTCOME")
        else:
            observed = iso_date(row["observed_date"])
            require(due <= observed <= version_date, "INVALID_OBSERVATION_WINDOW")
            number(row["effect_pct"])
        key = (row["outcome_id"], version_date)
        payload = canonical(row)
        require(key not in versions or versions[key] == payload,
                "CONFLICTING_OUTCOME_VERSIONS")
        versions[key] = payload
        prior = latest.get(row["outcome_id"])
        if prior is None or version_date > prior[0]:
            latest[row["outcome_id"]] = (version_date, row)
    eligible = sum(row["status"] in CLOSED for _, row in latest.values())
    proposals, activated = {}, 0
    for row in value["proposals"]:
        exact(row, PROPOSAL_FIELDS)
        as_of = temporal(row, cutoff)
        require(iso_date(row["created_date"]) <= as_of, "FUTURE_OR_POST_CUTOFF_ROW")
        for field in ("proposal_id", "source_policy_version", "proposed_change",
                      "rollback_policy_version"):
            text_value(row[field])
        require(type(row["status"]) is str and
                row["status"] in {"PENDING_HUMAN_REVIEW", "APPROVED"} and
                row["provenance"] == "SIMULATED_LEARNING_EVIDENCE" and
                row["simulation_config_change"] is False, "INVALID_PROPOSAL_STATE")
        require(type(row["observed_outcome_count"]) is int and
                row["observed_outcome_count"] >= 0, "INVALID_PROPOSAL_COUNT")
        number(row["success_rate_pct"])
        require(0 <= row["success_rate_pct"] <= 100, "INVALID_SUCCESS_RATE")
        for field in ("approved_by", "approved_policy_version"):
            if row[field] is not None:
                text_value(row[field])
        if row["effective_date"] is not None:
            iso_date(row["effective_date"])
        activated += int(row["status"] == "APPROVED" or any(
            row[field] is not None for field in
            ("approved_by", "approved_policy_version", "effective_date")))
        require(row["proposal_id"] not in proposals, "DUPLICATE_PROPOSAL")
        proposals[row["proposal_id"]] = canonical(row)
    return versions, proposals, eligible, activated


def empty_report() -> dict:
    return {
        "schema_version": "learning-cardinality-comparison-report.v1",
        "evidence_class": "OFFLINE_INPUT_CONSISTENCY_ONLY",
        "status": "UNVERIFIED",
        "reasons": [],
        "historical_proposals": "UNVERIFIED",
        "counts": None,
        "runtime_verified": False,
        "historical_anomaly_resolved": False,
        "real_world_evidence": False,
        "authority": {key: False for key in (
            "aws_query", "lifecycle_continuation", "proposal_mutation",
            "policy_activation", "deployment", "production", "model_promotion")},
    }


def compare_evidence(evidence: object) -> dict:
    """Validate supplied assertions and compare exact rows; echo no input values."""
    report = empty_report()
    try:
        exact(evidence, {"schema_version", "input_kind", "before", "run", "after"})
        require(evidence["schema_version"] == SCHEMA and
                evidence["input_kind"] in ("SYNTHETIC_FIXTURE", "SUPPLIED_STAGING_EXPORT"),
                "INVALID_CONTRACT")
        run, before, after = evidence["run"], evidence["before"], evidence["after"]
        exact(run, RUN_FIELDS)
        require(run["generator_path_completed"] is True, "MISSING_PATH_EVIDENCE")
        require(run["exclusive_window"] is True, "AMBIGUOUS_RUN_WINDOW")
        release(run["release"])
        cutoff = iso_date(run["logical_date"])
        zone = ZoneInfo("Australia/Sydney")
        now = datetime.now(timezone.utc)
        require(cutoff <= now.astimezone(zone).date(), "FUTURE_LOGICAL_DATE")
        old_versions, old, before_count, before_activated = snapshot(before, cutoff)
        new_versions, new, after_count, after_activated = snapshot(after, cutoff)
        times = [timestamp(before["captured_at"]), timestamp(run["started_at"]),
                 timestamp(run["finished_at"]), timestamp(after["captured_at"])]
        require(times[0] < times[1] < times[2] < times[3] <= now and
                all(t.astimezone(zone).date() == cutoff for t in times),
                "INVALID_OBSERVATION_ORDER")
        require(before["release"] == run["release"] == after["release"],
                "RELEASE_BINDING_CHANGED")
        require(before_count < MINIMUM_OUTCOMES and after_count < MINIMUM_OUTCOMES,
                "OUTSIDE_BELOW_THRESHOLD_SCOPE")
        added = len(new.keys() - old.keys())
        removed = len(old.keys() - new.keys())
        changed = sum(old[key] != new[key] for key in old.keys() & new.keys())
        history_changed = sum(new_versions.get(key) != payload
                              for key, payload in old_versions.items())
        report["counts"] = {
            "eligible_before": before_count, "eligible_after": after_count,
            "proposals_before": len(old), "proposals_after": len(new),
            "new_proposals": added, "removed_proposals": removed,
            "changed_proposals": changed, "activated_before": before_activated,
            "activated_after": after_activated,
            "missing_or_changed_outcome_versions": history_changed,
        }
        report["historical_proposals"] = (
            "CHANGED_OR_MISSING" if removed or changed else
            "PRESERVED_REVIEW_STILL_REQUIRED" if old else "NONE_IN_SUPPLIED_BASELINE")
        for flag, reason in (
            (added, "NEW_PROPOSAL_BELOW_THRESHOLD"),
            (removed or changed, "HISTORICAL_PROPOSAL_CHANGED_OR_MISSING"),
            (before_activated or after_activated, "ACTIVATION_PRESENT"),
            (history_changed, "OUTCOME_HISTORY_CHANGED_OR_MISSING"),
        ):
            if flag:
                report["reasons"].append(reason)
        report["status"] = ("VIOLATION_IN_SUPPLIED_EVIDENCE" if report["reasons"] else
                            "CONSISTENT_WITH_BELOW_THRESHOLD_RULE")
    except InvalidEvidence as error:
        report["reasons"] = [str(error)]
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        report["reasons"] = ["INVALID_INPUT"]
    return report


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def compare_json(raw: bytes) -> dict:
    try:
        require(len(raw) <= MAX_BYTES, "INPUT_TOO_LARGE")
        def reject_constant(_: str) -> None:
            raise InvalidEvidence("NON_FINITE_JSON_NUMBER")
        value = json.loads(raw, object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
        return compare_evidence(value)
    except InvalidEvidence as error:
        result = empty_report()
        result["reasons"] = [str(error)]
        return result
    except (ValueError, TypeError, RecursionError):
        result = empty_report()
        result["reasons"] = ["INVALID_JSON"]
        return result


def main() -> int:
    report = compare_json(sys.stdin.buffer.read(MAX_BYTES + 1))
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return {"CONSISTENT_WITH_BELOW_THRESHOLD_RULE": 0,
            "VIOLATION_IN_SUPPLIED_EVIDENCE": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
