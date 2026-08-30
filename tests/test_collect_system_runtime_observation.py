import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "collect_system_runtime_observation.py"
SPEC = importlib.util.spec_from_file_location(
    "collect_system_runtime_observation", MODULE_PATH
)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collector)


def valid_config() -> dict:
    return {
        "schema_version": "system-runtime-collector-config.v1",
        "region": "us-east-1",
        "storage_bucket": "private-storage",
        "glue_database": "private-catalog",
        "athena_workgroup": "private-workgroup",
        "production_function_name": "private-production-function",
        "production_schedule_name": "private-production-schedule",
        "dlq_url": "private-dlq-url",
        "alarm_names": ["private-alarm"],
        "alert_topic_arn": "private-topic",
        "staging_function_names": ["private-staging-function"],
        "staging_role_names": ["private-staging-role"],
        "staging_schedule_prefix": "private-staging-prefix",
        "staging_table_names": ["private-staging-table"],
        "staging_s3_write_prefixes": ["private-staging-prefix"],
    }


def fake_clients() -> dict:
    return {
        "s3": SimpleNamespace(
            head_bucket=lambda **_kwargs: {
                "ResponseMetadata": {"HTTPStatusCode": 200}
            }
        ),
        "glue": SimpleNamespace(
            get_database=lambda **_kwargs: {
                "Database": {"Name": "private-catalog"}
            }
        ),
        "athena": SimpleNamespace(
            get_work_group=lambda **_kwargs: {
                "WorkGroup": {"Name": "private-workgroup", "State": "ENABLED"}
            }
        ),
        "lambda": SimpleNamespace(
            get_alias=lambda **_kwargs: {"FunctionVersion": "7"},
            list_aliases=lambda **_kwargs: {
                "Aliases": [{"Name": "staging", "FunctionVersion": "7"}]
            },
        ),
        "scheduler": SimpleNamespace(
            get_schedule=lambda **_kwargs: {
                "State": "ENABLED",
                "Target": {
                    "Arn": "private-function:prod",
                    "RetryPolicy": {
                        "MaximumEventAgeInSeconds": 86400,
                        "MaximumRetryAttempts": 2,
                    },
                    "DeadLetterConfig": {"Arn": "private-dlq"},
                },
            },
            list_schedules=lambda **_kwargs: {"Schedules": []},
        ),
        "sqs": SimpleNamespace(
            get_queue_attributes=lambda **_kwargs: {
                "Attributes": {
                    "MessageRetentionPeriod": "1209600",
                    "SqsManagedSseEnabled": "true",
                }
            }
        ),
        "cloudwatch": SimpleNamespace(
            describe_alarms=lambda **_kwargs: {
                "MetricAlarms": [
                    {"AlarmName": "private-alarm", "ActionsEnabled": True}
                ]
            }
        ),
        "sns": SimpleNamespace(
            get_topic_attributes=lambda **_kwargs: {
                "Attributes": {"TopicArn": "private-topic"}
            }
        ),
        "iam": SimpleNamespace(
            list_attached_role_policies=lambda **_kwargs: {
                "AttachedPolicies": [],
                "IsTruncated": False,
            },
            list_role_policies=lambda **_kwargs: {
                "PolicyNames": ["private-inline-policy"],
                "IsTruncated": False,
            },
            get_role_policy=lambda **_kwargs: {
                "PolicyDocument": {
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "athena:StartQueryExecution",
                            "Resource": "private-workgroup",
                        },
                        {
                            "Effect": "Allow",
                            "Action": "glue:UpdateTable",
                            "Resource": "private:table/private-staging-table",
                        },
                        {
                            "Effect": "Allow",
                            "Action": "s3:PutObject",
                            "Resource": "private-staging-prefix/object",
                        },
                    ]
                }
            },
        ),
    }


class CollectSystemRuntimeObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)

    def test_plan_is_bounded_and_contains_no_private_config_value(self) -> None:
        config = valid_config()
        plan = collector.build_collection_plan(config)
        rendered = collector.canonical_json(plan)

        self.assertEqual(plan["mode"], "PLAN_ONLY")
        self.assertEqual(plan["planned_api_calls"], list(collector.ALLOWED_CALLS))
        self.assertFalse(plan["athena_query_started"])
        self.assertFalse(plan["lambda_invoked"])
        self.assertFalse(plan["external_write"])
        self.assertTrue(plan["private_config_validated"])
        self.assertEqual(
            plan["execution_requires_confirmation"], "AWS_CONTROL_PLANE_READS"
        )
        for key, value in config.items():
            if key in {"schema_version", "region"}:
                continue
            for private_value in value if isinstance(value, list) else [value]:
                self.assertNotIn(private_value, rendered)

    def test_collects_only_the_aggregate_observation_contract(self) -> None:
        clients = fake_clients()
        requested_services = []

        def client_factory(service: str):
            requested_services.append(service)
            return clients[service]

        observation = collector.collect_runtime_observation(
            valid_config(), client_factory, now=self.now
        )
        rendered = collector.canonical_json(observation)

        self.assertEqual(observation["as_of_date"], "2026-08-31")
        self.assertEqual(
            observation["evidence_class"], "AWS_CONTROL_PLANE_READS"
        )
        self.assertFalse(observation["athena_query_started"])
        self.assertFalse(observation["external_write"])
        self.assertFalse(observation["identifiers_retained"])
        self.assertEqual(set(observation["authority"].values()), {False})
        self.assertEqual(
            requested_services,
            [
                "s3",
                "glue",
                "athena",
                "lambda",
                "scheduler",
                "sqs",
                "cloudwatch",
                "sns",
                "iam",
            ],
        )
        for private_value in (
            "private-storage",
            "private-catalog",
            "private-workgroup",
            "private-production-function",
            "private-production-schedule",
            "private-dlq-url",
            "private-alarm",
            "private-topic",
            "private-staging-function",
            "private-staging-role",
            "private-staging-prefix",
            "private-staging-table",
        ):
            self.assertNotIn(private_value, rendered)

    def test_fails_closed_on_staging_alias_or_schedule(self) -> None:
        aliases = fake_clients()
        aliases["lambda"].list_aliases = lambda **_kwargs: {
            "Aliases": [{"Name": "prod", "FunctionVersion": "7"}]
        }
        with self.assertRaisesRegex(ValueError, "production alias"):
            collector.collect_runtime_observation(
                valid_config(), aliases.__getitem__, now=self.now
            )

        schedules = fake_clients()
        schedules["scheduler"].list_schedules = lambda **_kwargs: {
            "Schedules": [{"Name": "private-staging-schedule"}]
        }
        with self.assertRaisesRegex(ValueError, "staging schedule"):
            collector.collect_runtime_observation(
                valid_config(), schedules.__getitem__, now=self.now
            )

    def test_fails_closed_on_staging_iam_expansion(self) -> None:
        attached = fake_clients()
        attached["iam"].list_attached_role_policies = lambda **_kwargs: {
            "AttachedPolicies": [{"PolicyName": "expanded"}],
            "IsTruncated": False,
        }
        with self.assertRaisesRegex(ValueError, "managed policy"):
            collector.collect_runtime_observation(
                valid_config(), attached.__getitem__, now=self.now
            )

        production = fake_clients()
        production["iam"].get_role_policy = lambda **_kwargs: {
            "PolicyDocument": {
                "Statement": {
                    "Effect": "Allow",
                    "Action": "glue:UpdateTable",
                    "Resource": "private/fact_ai_actions_v2",
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "production analytics resource"):
            collector.collect_runtime_observation(
                valid_config(), production.__getitem__, now=self.now
            )

        mutation = fake_clients()
        mutation["iam"].get_role_policy = lambda **_kwargs: {
            "PolicyDocument": {
                "Statement": {
                    "Effect": "Allow",
                    "Action": "lambda:UpdateAlias",
                    "Resource": "private-staging-resource",
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "mutation authority"):
            collector.collect_runtime_observation(
                valid_config(), mutation.__getitem__, now=self.now
            )

        broad = fake_clients()
        broad["iam"].get_role_policy = lambda **_kwargs: {
            "PolicyDocument": {
                "Statement": {
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Resource": "private-staging-prefix/object",
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "broad service action"):
            collector.collect_runtime_observation(
                valid_config(), broad.__getitem__, now=self.now
            )

        write_scope = fake_clients()
        write_scope["iam"].get_role_policy = lambda **_kwargs: {
            "PolicyDocument": {
                "Statement": {
                    "Effect": "Allow",
                    "Action": "s3:PutObject",
                    "Resource": "different-prefix/object",
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "S3 write scope"):
            collector.collect_runtime_observation(
                valid_config(), write_scope.__getitem__, now=self.now
            )

    def test_fails_closed_on_production_reliability_drift(self) -> None:
        schedule = fake_clients()
        schedule["scheduler"].get_schedule = lambda **_kwargs: {
            "State": "ENABLED",
            "Target": {
                "Arn": "private-function:prod",
                "RetryPolicy": {
                    "MaximumEventAgeInSeconds": 86400,
                    "MaximumRetryAttempts": 3,
                },
                "DeadLetterConfig": {"Arn": "private-dlq"},
            },
        }
        with self.assertRaisesRegex(ValueError, "schedule reliability"):
            collector.collect_runtime_observation(
                valid_config(), schedule.__getitem__, now=self.now
            )

        queue = fake_clients()
        queue["sqs"].get_queue_attributes = lambda **_kwargs: {
            "Attributes": {
                "MessageRetentionPeriod": "86400",
                "SqsManagedSseEnabled": "true",
            }
        }
        with self.assertRaisesRegex(ValueError, "14 days"):
            collector.collect_runtime_observation(
                valid_config(), queue.__getitem__, now=self.now
            )

    def test_config_schema_and_source_preserve_plan_first_boundary(self) -> None:
        schema = json.loads(
            (
                ROOT / "docs/system_runtime_collector_config_v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "system-runtime-collector-config.v1",
        )
        self.assertIn("Populate outside the repository", schema["description"])
        self.assertIn('default="plan"', source)
        self.assertIn("execute requires the exact read-only confirmation", source)
        self.assertIn("private collector config must remain outside the repository", source)
        self.assertIn("runtime observation output must remain outside the repository", source)
        self.assertIn("--config-from-environment", source)
        for forbidden in (
            "start_query_execution(",
            ".invoke(",
            ".update_",
            ".delete_",
            ".create_",
        ):
            self.assertNotIn(forbidden, source.lower())

    def test_cli_defaults_to_plan_without_loading_an_aws_client(self) -> None:
        output = io.StringIO()
        with patch.object(sys, "argv", [str(MODULE_PATH)]), patch.object(
            collector.importlib,
            "import_module",
            side_effect=AssertionError("AWS client must not load in plan mode"),
        ), redirect_stdout(output):
            result = collector.main()

        self.assertEqual(result, 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["mode"], "PLAN_ONLY")
        self.assertFalse(plan["external_write"])
        self.assertFalse(plan["private_config_validated"])

    def test_protected_environment_config_is_exact_and_not_rendered(self) -> None:
        config = valid_config()
        environ = {}
        for key, environment_name in collector.ENV_SCALARS.items():
            environ[environment_name] = config[key]
        for key, environment_name in collector.ENV_LISTS.items():
            environ[environment_name] = json.dumps(config[key])

        loaded = collector.load_config_from_environment(environ)
        plan = collector.build_collection_plan(loaded)
        rendered = collector.canonical_json(plan)

        self.assertEqual(loaded, config)
        self.assertTrue(plan["private_config_validated"])
        for private_value in (
            value
            for key, configured in config.items()
            if key not in {"schema_version", "region"}
            for value in (configured if isinstance(configured, list) else [configured])
        ):
            self.assertNotIn(private_value, rendered)


if __name__ == "__main__":
    unittest.main()
