"""Plan or execute a bounded AWS control-plane System observation.

Execution is deliberately separate from public projection and publication. It
uses fixed read-only control-plane calls, never starts Athena, never invokes a
Lambda, never changes AWS, and emits no configured resource identifier.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "ops/export_public_system_evidence_snapshot.py"
CONFIG_SCHEMA_VERSION = "system-runtime-collector-config.v1"
OBSERVATION_SCHEMA_VERSION = "system-runtime-observation.v1"
EXECUTION_CONFIRMATION = "AWS_CONTROL_PLANE_READS"
REGION = "us-east-1"

CONFIG_KEYS = {
    "schema_version",
    "region",
    "storage_bucket",
    "glue_database",
    "athena_workgroup",
    "production_function_name",
    "production_schedule_name",
    "dlq_url",
    "alarm_names",
    "alert_topic_arn",
    "staging_function_names",
    "staging_role_names",
    "staging_schedule_prefix",
    "staging_table_names",
    "staging_s3_write_prefixes",
}
ALLOWED_CALLS = (
    "s3:HeadBucket",
    "glue:GetDatabase",
    "athena:GetWorkGroup",
    "lambda:GetAlias",
    "lambda:ListAliases",
    "scheduler:GetSchedule",
    "scheduler:ListSchedules",
    "sqs:GetQueueAttributes",
    "cloudwatch:DescribeAlarms",
    "sns:GetTopicAttributes",
    "iam:ListAttachedRolePolicies",
    "iam:ListRolePolicies",
    "iam:GetRolePolicy",
)
PRODUCTION_RESOURCE_MARKERS = (
    "fact_shipment_events_extended_iceberg",
    "fact_ai_alerts_v3",
    "fact_ai_root_causes_v1",
    "fact_ai_insights_v3",
    "fact_ai_decisions_v3",
    "fact_ai_actions_v2",
    "fact_ai_outcomes_v2",
    "fact_ai_learning_feedback_v1",
    "fact_ai_learning_v1",
    "ai_decision_trace_v1",
    "v_ai_latest_decision_trace",
)
FORBIDDEN_STAGING_ACTIONS = (
    "lambda:updatealias",
    "lambda:createalias",
    "lambda:deletealias",
    "scheduler:create",
    "scheduler:update",
    "scheduler:delete",
    "events:putrule",
    "events:puttargets",
)
ENV_SCALARS = {
    "storage_bucket": "GLAP_SYSTEM_STORAGE_BUCKET",
    "glue_database": "GLAP_SYSTEM_GLUE_DATABASE",
    "athena_workgroup": "GLAP_SYSTEM_ATHENA_WORKGROUP",
    "production_function_name": "GLAP_SYSTEM_PRODUCTION_FUNCTION_NAME",
    "production_schedule_name": "GLAP_SYSTEM_PRODUCTION_SCHEDULE_NAME",
    "dlq_url": "GLAP_SYSTEM_DLQ_URL",
    "alert_topic_arn": "GLAP_SYSTEM_ALERT_TOPIC_ARN",
    "staging_schedule_prefix": "GLAP_SYSTEM_STAGING_SCHEDULE_PREFIX",
}
ENV_LISTS = {
    "alarm_names": "GLAP_SYSTEM_ALARM_NAMES_JSON",
    "staging_function_names": "GLAP_SYSTEM_STAGING_FUNCTION_NAMES_JSON",
    "staging_role_names": "GLAP_SYSTEM_STAGING_ROLE_NAMES_JSON",
    "staging_table_names": "GLAP_SYSTEM_STAGING_TABLE_NAMES_JSON",
    "staging_s3_write_prefixes": "GLAP_SYSTEM_STAGING_S3_WRITE_PREFIXES_JSON",
}


def _load_exporter() -> Any:
    spec = importlib.util.spec_from_file_location(
        "system_runtime_observation_exporter", EXPORTER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the System observation contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("collector config must contain one JSON object")
    return value


def validate_collector_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(config) != CONFIG_KEYS:
        errors.append("collector config envelope has drifted")
    if config.get("schema_version") != CONFIG_SCHEMA_VERSION:
        errors.append("collector config schema is unsupported")
    if config.get("region") != REGION:
        errors.append("collector region must remain us-east-1")
    scalar_keys = (
        "storage_bucket",
        "glue_database",
        "athena_workgroup",
        "production_function_name",
        "production_schedule_name",
        "dlq_url",
        "alert_topic_arn",
        "staging_schedule_prefix",
    )
    if any(
        not isinstance(config.get(key), str) or not config[key].strip()
        for key in scalar_keys
    ):
        errors.append("collector private resource locators are incomplete")
    for key in (
        "alarm_names",
        "staging_function_names",
        "staging_role_names",
        "staging_table_names",
        "staging_s3_write_prefixes",
    ):
        values = config.get(key)
        if (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(values))
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            errors.append(f"collector {key} must contain unique non-empty values")
    if isinstance(config.get("alarm_names"), list) and len(config["alarm_names"]) > 100:
        errors.append("collector alarm_names exceeds the bounded API limit")
    return errors


def load_config_from_environment(environ: Mapping[str, str]) -> dict[str, Any]:
    config: dict[str, Any] = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "region": REGION,
    }
    for key, environment_name in ENV_SCALARS.items():
        config[key] = environ.get(environment_name, "")
    for key, environment_name in ENV_LISTS.items():
        raw = environ.get(environment_name, "")
        try:
            config[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{environment_name} must contain a JSON array"
            ) from exc
    errors = validate_collector_config(config)
    if errors:
        raise ValueError("invalid protected collector environment: " + "; ".join(errors))
    return config


def build_collection_plan(config: dict[str, Any] | None = None) -> dict[str, Any]:
    if config is not None:
        errors = validate_collector_config(config)
        if errors:
            raise ValueError("invalid collector config: " + "; ".join(errors))
    return {
        "schema_version": "system-runtime-collection-plan.v1",
        "mode": "PLAN_ONLY",
        "region": REGION,
        "planned_api_calls": list(ALLOWED_CALLS),
        "athena_query_started": False,
        "lambda_invoked": False,
        "external_write": False,
        "private_values_logged": False,
        "private_config_validated": config is not None,
        "output_contract": OBSERVATION_SCHEMA_VERSION,
        "execution_requires_confirmation": EXECUTION_CONFIRMATION,
    }


def _client(client_factory: Callable[[str], Any], service: str) -> Any:
    return client_factory(service)


def _require_response_name(response: dict[str, Any], container: str, expected: str) -> None:
    value = response.get(container)
    if not isinstance(value, dict) or value.get("Name") != expected:
        raise ValueError(f"{container} control-plane response did not reconcile")


def _list_aliases(lambda_client: Any, function_name: str) -> list[dict[str, Any]]:
    aliases: list[dict[str, Any]] = []
    marker: str | None = None
    while True:
        request = {"FunctionName": function_name}
        if marker:
            request["Marker"] = marker
        response = lambda_client.list_aliases(**request)
        page = response.get("Aliases", [])
        if not isinstance(page, list):
            raise ValueError("Lambda alias response is malformed")
        aliases.extend(page)
        marker = response.get("NextMarker")
        if not marker:
            return aliases


def _list_staging_schedules(scheduler_client: Any, prefix: str) -> list[dict[str, Any]]:
    schedules: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        request = {"NamePrefix": prefix}
        if token:
            request["NextToken"] = token
        response = scheduler_client.list_schedules(**request)
        page = response.get("Schedules", [])
        if not isinstance(page, list):
            raise ValueError("Scheduler list response is malformed")
        schedules.extend(page)
        token = response.get("NextToken")
        if not token:
            return schedules


def _list_inline_policies(iam_client: Any, role_name: str) -> list[str]:
    names: list[str] = []
    marker: str | None = None
    while True:
        request = {"RoleName": role_name}
        if marker:
            request["Marker"] = marker
        response = iam_client.list_role_policies(**request)
        page = response.get("PolicyNames", [])
        if not isinstance(page, list):
            raise ValueError("IAM inline policy response is malformed")
        names.extend(page)
        if not response.get("IsTruncated"):
            return names
        marker = response.get("Marker")
        if not marker:
            raise ValueError("IAM inline policy pagination is incomplete")


def _has_attached_policies(iam_client: Any, role_name: str) -> bool:
    marker: str | None = None
    while True:
        request = {"RoleName": role_name}
        if marker:
            request["Marker"] = marker
        response = iam_client.list_attached_role_policies(**request)
        page = response.get("AttachedPolicies", [])
        if not isinstance(page, list):
            raise ValueError("IAM attached policy response is malformed")
        if page:
            return True
        if not response.get("IsTruncated"):
            return False
        marker = response.get("Marker")
        if not marker:
            raise ValueError("IAM attached policy pagination is incomplete")


def _allow_statements(policy: dict[str, Any]) -> list[dict[str, Any]]:
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        raise ValueError("IAM policy statements are malformed")
    allowed: list[dict[str, Any]] = []
    for statement in statements:
        if not isinstance(statement, dict):
            raise ValueError("IAM policy statement is malformed")
        if statement.get("Effect") != "Allow":
            continue
        if "NotAction" in statement:
            raise ValueError("staging inline policy uses an unbounded NotAction")
        allowed.append(statement)
    return allowed


def _policy_actions(policy: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for statement in _allow_statements(policy):
        value = statement.get("Action", [])
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("IAM policy actions are malformed")
        actions.extend(item.lower() for item in value)
    return actions


def _statement_resources(statement: dict[str, Any]) -> list[str]:
    resources = statement.get("Resource", [])
    if isinstance(resources, str):
        resources = [resources]
    if not isinstance(resources, list) or any(
        not isinstance(resource, str) for resource in resources
    ):
        raise ValueError("IAM policy resources are malformed")
    return resources


def _validate_staging_roles(
    iam_client: Any,
    role_names: list[str],
    staging_table_names: list[str],
    staging_s3_write_prefixes: list[str],
) -> None:
    for role_name in role_names:
        if _has_attached_policies(iam_client, role_name):
            raise ValueError("staging role has an unbounded managed policy")
        policy_names = _list_inline_policies(iam_client, role_name)
        if not policy_names:
            raise ValueError("staging role has no inspectable inline policy")
        for policy_name in policy_names:
            response = iam_client.get_role_policy(
                RoleName=role_name, PolicyName=policy_name
            )
            policy = response.get("PolicyDocument")
            if not isinstance(policy, dict):
                raise ValueError("staging inline policy document is missing")
            serialized = json.dumps(policy, sort_keys=True).lower()
            if any(marker in serialized for marker in PRODUCTION_RESOURCE_MARKERS):
                raise ValueError("staging role references a production analytics resource")
            actions = _policy_actions(policy)
            if any(
                action in {"*", "lambda:*", "scheduler:*", "events:*", "glue:*", "s3:*"}
                for action in actions
            ):
                raise ValueError("staging role has a broad service action")
            if any(
                action.startswith(forbidden)
                for action in actions
                for forbidden in FORBIDDEN_STAGING_ACTIONS
            ):
                raise ValueError("staging role has alias or schedule mutation authority")
            for statement in _allow_statements(policy):
                statement_actions = _policy_actions({"Statement": [statement]})
                resources = _statement_resources(statement)
                if "glue:updatetable" in statement_actions:
                    table_resources = [
                        resource for resource in resources if ":table/" in resource.lower()
                    ]
                    if not table_resources or any(
                        not any(
                            resource.lower().endswith("/" + table_name.lower())
                            for table_name in staging_table_names
                        )
                        for resource in table_resources
                    ):
                        raise ValueError("staging Glue write scope is outside the allowlist")
                if any(
                    action
                    in {
                        "s3:putobject",
                        "s3:deleteobject",
                        "s3:abortmultipartupload",
                    }
                    for action in statement_actions
                ) and any(
                    not any(
                        resource.startswith(prefix)
                        for prefix in staging_s3_write_prefixes
                    )
                    for resource in resources
                ):
                    raise ValueError("staging S3 write scope is outside the allowlist")


def collect_runtime_observation(
    config: dict[str, Any],
    client_factory: Callable[[str], Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    errors = validate_collector_config(config)
    if errors:
        raise ValueError("invalid collector config: " + "; ".join(errors))
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("collector time must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc).replace(microsecond=0)
    as_of_date = observed_at.astimezone(ZoneInfo("Australia/Sydney")).date()

    s3 = _client(client_factory, "s3")
    head = s3.head_bucket(Bucket=config["storage_bucket"])
    status = head.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if status != 200:
        raise ValueError("storage control-plane check did not return HTTP 200")

    glue = _client(client_factory, "glue")
    _require_response_name(
        glue.get_database(Name=config["glue_database"]),
        "Database",
        config["glue_database"],
    )

    athena = _client(client_factory, "athena")
    workgroup = athena.get_work_group(WorkGroup=config["athena_workgroup"]).get(
        "WorkGroup"
    )
    if (
        not isinstance(workgroup, dict)
        or workgroup.get("Name") != config["athena_workgroup"]
        or workgroup.get("State") != "ENABLED"
    ):
        raise ValueError("Athena workgroup control-plane state is not enabled")

    lambda_client = _client(client_factory, "lambda")
    prod_alias = lambda_client.get_alias(
        FunctionName=config["production_function_name"], Name="prod"
    )
    version = str(prod_alias.get("FunctionVersion", ""))
    if not version.isdigit() or int(version) < 1:
        raise ValueError("production alias does not target an immutable version")
    for function_name in config["staging_function_names"]:
        aliases = _list_aliases(lambda_client, function_name)
        if any(alias.get("Name") == "prod" for alias in aliases if isinstance(alias, dict)):
            raise ValueError("a staging function exposes a production alias")

    scheduler = _client(client_factory, "scheduler")
    schedule = scheduler.get_schedule(Name=config["production_schedule_name"])
    target = schedule.get("Target")
    retry = target.get("RetryPolicy") if isinstance(target, dict) else None
    dead_letter = target.get("DeadLetterConfig") if isinstance(target, dict) else None
    if (
        schedule.get("State") != "ENABLED"
        or not isinstance(target, dict)
        or not str(target.get("Arn", "")).endswith(":prod")
        or retry
        != {"MaximumEventAgeInSeconds": 86400, "MaximumRetryAttempts": 2}
        or not isinstance(dead_letter, dict)
        or not dead_letter.get("Arn")
    ):
        raise ValueError("production schedule reliability boundary has drifted")
    if _list_staging_schedules(scheduler, config["staging_schedule_prefix"]):
        raise ValueError("a staging schedule is present")

    sqs = _client(client_factory, "sqs")
    attributes = sqs.get_queue_attributes(
        QueueUrl=config["dlq_url"],
        AttributeNames=[
            "MessageRetentionPeriod",
            "SqsManagedSseEnabled",
            "KmsMasterKeyId",
        ],
    ).get("Attributes")
    if not isinstance(attributes, dict) or attributes.get("MessageRetentionPeriod") != "1209600":
        raise ValueError("dead-letter retention is not 14 days")
    if attributes.get("SqsManagedSseEnabled") != "true" and not attributes.get(
        "KmsMasterKeyId"
    ):
        raise ValueError("dead-letter encryption is not enabled")

    cloudwatch = _client(client_factory, "cloudwatch")
    alarm_response = cloudwatch.describe_alarms(AlarmNames=config["alarm_names"])
    alarms = alarm_response.get("MetricAlarms", [])
    if alarm_response.get("NextToken") or not isinstance(alarms, list):
        raise ValueError("CloudWatch alarm response is incomplete")
    observed_alarm_names = {
        alarm.get("AlarmName") for alarm in alarms if isinstance(alarm, dict)
    }
    if observed_alarm_names != set(config["alarm_names"]) or any(
        alarm.get("ActionsEnabled") is not True
        for alarm in alarms
        if isinstance(alarm, dict)
    ):
        raise ValueError("CloudWatch alarm coverage has drifted")

    sns = _client(client_factory, "sns")
    topic_attributes = sns.get_topic_attributes(
        TopicArn=config["alert_topic_arn"]
    ).get("Attributes")
    if (
        not isinstance(topic_attributes, dict)
        or topic_attributes.get("TopicArn") != config["alert_topic_arn"]
    ):
        raise ValueError("SNS alert topic did not reconcile")

    iam = _client(client_factory, "iam")
    _validate_staging_roles(
        iam,
        config["staging_role_names"],
        config["staging_table_names"],
        config["staging_s3_write_prefixes"],
    )

    observation = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "as_of_date": as_of_date.isoformat(),
        "observed_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
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
            {"key": key, "verified": True}
            for key in (
                "storage",
                "catalog",
                "analytics",
                "compute",
                "reliability",
                "observability",
            )
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
    exporter = _load_exporter()
    validation = exporter.validate_runtime_observation(
        observation, today=as_of_date
    )
    if validation:
        raise ValueError("collected observation failed its public contract")
    return observation


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _path_is_inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument("--config", type=Path)
    config_group.add_argument("--config-from-environment", action="store_true")
    parser.add_argument("--action", choices=("plan", "execute"), default="plan")
    parser.add_argument("--confirm-read-only")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile")
    args = parser.parse_args()

    config = None
    if args.config:
        if _path_is_inside_repository(args.config):
            parser.error("private collector config must remain outside the repository")
        config = load_json(args.config)
    elif args.config_from_environment:
        config = load_config_from_environment(os.environ)
    plan = build_collection_plan(config)
    if args.action == "plan":
        print(canonical_json(plan), end="")
        return 0
    if args.confirm_read_only != EXECUTION_CONFIRMATION:
        parser.error("execute requires the exact read-only confirmation")
    if config is None:
        parser.error("execute requires protected collector configuration")
    if args.output is None:
        parser.error("execute requires an output path")
    if _path_is_inside_repository(args.output):
        parser.error("runtime observation output must remain outside the repository")

    boto3 = importlib.import_module("boto3")
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    observation = collect_runtime_observation(config, session.client)
    args.output.write_text(canonical_json(observation), encoding="utf-8")
    print("PASS: aggregate System runtime observation written outside the repository")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
