import os
import re

import boto3


TARGET_FUNCTION = os.environ["TARGET_FUNCTION"]
TARGET_ALIAS = os.environ.get("TARGET_ALIAS", "staging")

if TARGET_ALIAS != "staging":
    raise RuntimeError("This function is locked to the staging alias")

lambda_client = boto3.client("lambda")


def find_version(version):
    marker = None
    while True:
        request = {"FunctionName": TARGET_FUNCTION}
        if marker:
            request["Marker"] = marker
        response = lambda_client.list_versions_by_function(**request)
        for candidate in response.get("Versions", []):
            if candidate.get("Version") == version:
                return candidate
        marker = response.get("NextMarker")
        if not marker:
            return None


def lambda_handler(event, context):
    if not isinstance(event, dict):
        raise ValueError("Event must be an object")

    version = str(event.get("version", ""))
    if not version.isdigit() or int(version) < 1:
        raise ValueError("version must be a positive immutable Lambda version")

    expected_git_sha = event.get("expected_git_sha")
    if expected_git_sha is not None:
        expected_git_sha = str(expected_git_sha).lower()
        if not re.fullmatch(r"[0-9a-f]{40}", expected_git_sha):
            raise ValueError("expected_git_sha must be a full 40-character SHA")

    candidate = find_version(version)
    if candidate is None:
        raise ValueError(f"Lambda version {version} does not exist")

    if expected_git_sha is not None:
        expected_description = f"GitHub {expected_git_sha}"
        if candidate.get("Description") != expected_description:
            raise ValueError("Lambda version description does not match Git commit")

    current = lambda_client.get_alias(
        FunctionName=TARGET_FUNCTION,
        Name="staging"
    )
    previous_version = current["FunctionVersion"]

    if previous_version == version:
        return {
            "status": "unchanged",
            "alias": "staging",
            "previous_version": previous_version,
            "new_version": version
        }

    updated = lambda_client.update_alias(
        FunctionName=TARGET_FUNCTION,
        Name="staging",
        FunctionVersion=version,
        RevisionId=current["RevisionId"]
    )
    return {
        "status": "promoted",
        "alias": "staging",
        "previous_version": previous_version,
        "new_version": updated["FunctionVersion"]
    }
