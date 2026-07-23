import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "lambda" / "glap_staging_alias_promoter.py"


def load_module(lambda_client):
    fake_boto3 = types.SimpleNamespace(client=MagicMock(return_value=lambda_client))
    sys.modules["boto3"] = fake_boto3
    spec = importlib.util.spec_from_file_location("staging_alias_promoter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        os.environ,
        {"TARGET_FUNCTION": "glap-ai-agent-orchestrator", "TARGET_ALIAS": "staging"},
        clear=False,
    ):
        spec.loader.exec_module(module)
    return module


class StagingAliasPromoterTests(unittest.TestCase):
    def test_rejects_mutable_or_invalid_version(self):
        client = MagicMock()
        module = load_module(client)
        for invalid in ("", "$LATEST", "0", "prod"):
            with self.subTest(version=invalid), self.assertRaises(ValueError):
                module.lambda_handler({"version": invalid}, None)
        client.list_versions_by_function.assert_not_called()

    def test_rejects_version_from_another_commit(self):
        client = MagicMock()
        client.list_versions_by_function.return_value = {
            "Versions": [{"Version": "3", "Description": "GitHub deadbeef"}]
        }
        module = load_module(client)
        with self.assertRaisesRegex(ValueError, "does not match"):
            module.lambda_handler({"version": "3", "expected_git_sha": "a" * 40}, None)
        client.update_alias.assert_not_called()

    def test_promotes_only_staging_with_revision_guard(self):
        client = MagicMock()
        commit = "a" * 40
        client.list_versions_by_function.return_value = {
            "Versions": [{"Version": "3", "Description": f"GitHub {commit}"}]
        }
        client.get_alias.return_value = {
            "FunctionVersion": "2",
            "RevisionId": "revision-1",
        }
        client.update_alias.return_value = {"FunctionVersion": "3"}
        module = load_module(client)

        result = module.lambda_handler({"version": "3", "expected_git_sha": commit}, None)

        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["new_version"], "3")
        client.update_alias.assert_called_once_with(
            FunctionName="glap-ai-agent-orchestrator",
            Name="staging",
            FunctionVersion="3",
            RevisionId="revision-1",
        )


if __name__ == "__main__":
    unittest.main()
