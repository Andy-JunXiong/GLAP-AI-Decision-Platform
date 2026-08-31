import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github/workflows/collect-system-runtime-observation.yml"
)
COLLECTOR_PATH = ROOT / "ops/collect_system_runtime_observation.py"
REQUIREMENTS_PATH = ROOT / "ops/requirements-system-runtime-observation.txt"
SPEC = importlib.util.spec_from_file_location(
    "collect_system_runtime_workflow_contract", COLLECTOR_PATH
)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collector)


class CollectSystemRuntimeWorkflowTests(unittest.TestCase):
    def test_workflow_is_manual_plan_first_and_non_publishing(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertNotIn("\n  schedule:", workflow)
        self.assertIn("default: plan", workflow)
        self.assertIn("if: inputs.action == 'plan'", workflow)
        self.assertIn("if: inputs.action == 'execute'", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("actions/upload-artifact", workflow)
        self.assertNotIn("actions/deploy-pages", workflow)
        self.assertNotIn("git push", workflow)
        self.assertNotIn("aws athena", workflow.lower())
        self.assertNotIn("start-query-execution", workflow.lower())

    def test_plan_job_has_no_environment_oidc_or_private_config(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        plan = workflow.split("  plan:\n", 1)[1].split("  execute:\n", 1)[0]

        self.assertIn("--action plan", plan)
        self.assertIn("without private configuration or AWS credentials", plan)
        self.assertNotIn("environment:", plan)
        self.assertNotIn("id-token: write", plan)
        self.assertNotIn("configure-aws-credentials", plan)
        self.assertNotIn("secrets.", plan)
        self.assertNotIn("--config-from-environment", plan)
        self.assertNotIn("requirements-system-runtime-observation.txt", plan)

    def test_execute_dependency_is_pinned_and_verified_before_authentication(
        self,
    ) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        execute = workflow.split("  execute:\n", 1)[1]
        requirements = [
            line.strip()
            for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        self.assertEqual(
            requirements,
            [
                "boto3==1.43.83",
                "botocore==1.43.83",
                "jmespath==1.1.0",
                "python-dateutil==2.9.0.post0",
                "s3transfer==0.19.2",
                "six==1.17.0",
                "urllib3==2.7.0",
            ],
        )
        self.assertIn("-r ops/requirements-system-runtime-observation.txt", execute)
        self.assertIn("import boto3", execute)
        self.assertLess(
            execute.index("Verify collector contracts before AWS authentication"),
            execute.index("Install pinned System observation dependency"),
        )
        self.assertLess(
            execute.index("Install pinned System observation dependency"),
            execute.index("Verify runtime dependency before AWS authentication"),
        )
        self.assertLess(
            execute.index("Verify runtime dependency before AWS authentication"),
            execute.index("aws-actions/configure-aws-credentials@v6"),
        )

    def test_execute_job_is_protected_read_only_and_transient(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        execute = workflow.split("  execute:\n", 1)[1]

        self.assertIn("environment: system-observation-read", execute)
        self.assertIn("id-token: write", execute)
        self.assertEqual(execute.count("aws-actions/configure-aws-credentials@v6"), 1)
        self.assertIn("mask-aws-account-id: true", execute)
        self.assertIn("--config-from-environment", execute)
        self.assertIn("--confirm-read-only AWS_CONTROL_PLANE_READS", execute)
        self.assertIn("--check-output", execute)
        self.assertIn("if: always()", execute)
        self.assertIn('rm -f -- "$observation" "$candidate"', execute)
        self.assertNotIn("upload-artifact", execute)
        self.assertNotIn("public/data/system-evidence-snapshot.json", execute)

    def test_every_private_environment_field_is_secret_backed(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        environment_names = tuple(collector.ENV_SCALARS.values()) + tuple(
            collector.ENV_LISTS.values()
        )

        for environment_name in environment_names:
            secret_name = environment_name.removeprefix("GLAP_SYSTEM_")
            self.assertIn(
                f"{environment_name}: ${{{{ secrets.SYSTEM_{secret_name} }}}}",
                workflow,
            )
        self.assertIn(
            "role-to-assume: ${{ secrets.SYSTEM_OBSERVATION_ROLE_ARN }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
