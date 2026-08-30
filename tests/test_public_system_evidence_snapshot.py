import importlib.util
import json
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "export_public_system_evidence_snapshot.py"
SPEC = importlib.util.spec_from_file_location(
    "export_public_system_evidence_snapshot", MODULE_PATH
)
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(exporter)


def valid_observation() -> dict:
    return {
        "schema_version": "system-runtime-observation.v1",
        "as_of_date": "2026-08-31",
        "observed_at_utc": "2026-08-30T15:00:00Z",
        "evidence_class": "AWS_CONTROL_PLANE_READS",
        "aggregate_only": True,
        "read_only": True,
        "athena_query_started": False,
        "external_write": False,
        "identifiers_retained": False,
        "production_track": {
            "scheduler_targets_prod_alias": True,
            "immutable_alias": True,
        },
        "staging_track": {
            "manual_only": True,
            "scheduler_present": False,
            "production_alias_present": False,
            "production_table_write": False,
        },
        "reliability": {
            "stage_count": 6,
            "quality_check_count": 10,
            "retry_count": 2,
            "max_event_age_hours": 24,
            "dlq_retention_days": 14,
        },
        "services": [
            {"key": "storage", "verified": True},
            {"key": "catalog", "verified": True},
            {"key": "analytics", "verified": True},
            {"key": "compute", "verified": True},
            {"key": "reliability", "verified": True},
            {"key": "observability", "verified": True},
        ],
        "authority": {
            "aws_write": False,
            "infrastructure_change": False,
            "production_alias_move": False,
            "schedule_change": False,
            "action_mutation": False,
            "policy_activation": False,
            "model_promotion": False,
        },
    }


class PublicSystemEvidenceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 8, 31)

    def test_builds_deterministic_public_runtime_candidate(self) -> None:
        observation = valid_observation()
        snapshot = exporter.build_public_runtime_snapshot(
            observation, today=self.today
        )

        self.assertEqual(
            snapshot["schema_version"], "public-system-evidence-snapshot.v2"
        )
        self.assertEqual(snapshot["evidence_class"], "AWS_RUNTIME_INSPECTION")
        self.assertTrue(snapshot["live_aws_inspection"])
        self.assertEqual(
            snapshot["source_provenance"]["observation_contract"],
            "system-runtime-observation.v1",
        )
        self.assertEqual(
            [service["status"] for service in snapshot["services"]],
            ["RUNTIME_VERIFIED"] * 6,
        )
        self.assertEqual(set(snapshot["authority"].values()), {False})
        self.assertEqual(
            exporter.canonical_json(snapshot),
            exporter.canonical_json(
                exporter.build_public_runtime_snapshot(
                    deepcopy(observation), today=self.today
                )
            ),
        )
        self.assertEqual(
            exporter.validate_public_runtime_snapshot(snapshot, today=self.today),
            [],
        )

    def test_rejects_temporal_and_provenance_drift(self) -> None:
        future = valid_observation()
        future["as_of_date"] = "2026-09-01"
        future["observed_at_utc"] = "2026-08-31T15:00:00Z"
        self.assertIn(
            "runtime observation must use the current Sydney date",
            exporter.validate_runtime_observation(future, today=self.today),
        )

        mismatched = valid_observation()
        mismatched["observed_at_utc"] = "2026-08-29T15:00:00Z"
        self.assertIn(
            "observed_at_utc does not reconcile to as_of_date in Sydney",
            exporter.validate_runtime_observation(mismatched, today=self.today),
        )

    def test_rejects_athena_write_identifier_and_authority_drift(self) -> None:
        mutations = (
            ("athena", lambda value: value.__setitem__("athena_query_started", True)),
            ("write", lambda value: value.__setitem__("external_write", True)),
            (
                "identifier",
                lambda value: value.__setitem__(
                    "private_resource", "arn" + ":aws"
                ),
            ),
            (
                "authority",
                lambda value: value["authority"].__setitem__("schedule_change", True),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                observation = valid_observation()
                mutate(observation)
                self.assertTrue(
                    exporter.validate_runtime_observation(
                        observation, today=self.today
                    )
                )

    def test_rejects_staging_reliability_and_service_drift(self) -> None:
        staging = valid_observation()
        staging["staging_track"]["scheduler_present"] = True
        self.assertIn(
            "staging isolation is not verified",
            exporter.validate_runtime_observation(staging, today=self.today),
        )

        reliability = valid_observation()
        reliability["reliability"]["retry_count"] = 3
        self.assertIn(
            "runtime reliability controls have drifted",
            exporter.validate_runtime_observation(reliability, today=self.today),
        )

        services = valid_observation()
        services["services"].reverse()
        self.assertIn(
            "runtime service verification order or state has drifted",
            exporter.validate_runtime_observation(services, today=self.today),
        )

        public_snapshot = exporter.build_public_runtime_snapshot(
            valid_observation(), today=self.today
        )
        public_snapshot["services"][0]["label"] = "Unexpected storage label"
        self.assertIn(
            "public System service copy has drifted",
            exporter.validate_public_runtime_snapshot(
                public_snapshot, today=self.today
            ),
        )

    def test_contract_is_machine_readable_and_exporter_has_no_aws_client(self) -> None:
        schema = json.loads(
            (
                ROOT / "docs/public_system_runtime_observation_v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertEqual(schema["properties"]["schema_version"]["const"], "system-runtime-observation.v1")
        self.assertFalse(schema["properties"]["athena_query_started"]["const"])
        self.assertFalse(schema["properties"]["external_write"]["const"])
        self.assertNotIn("boto3", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn(".client(", source)
        self.assertIn("the exporter cannot overwrite the tracked Sites snapshot", source)


if __name__ == "__main__":
    unittest.main()
