import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_public_claims", ROOT / "ops" / "validate_public_claims.py"
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


class PublicClaimManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = VALIDATOR.load_manifest(ROOT)

    def test_repository_claim_manifest_passes(self):
        self.assertEqual(VALIDATOR.validate_manifest(self.manifest, ROOT), [])

    def test_unknown_classification_fails(self):
        drifted = copy.deepcopy(self.manifest)
        drifted["claims"][0]["classification"] = "OBSERVED"
        errors = VALIDATOR.validate_manifest(drifted, ROOT)
        self.assertTrue(any("unsupported classification" in error for error in errors))

    def test_illustrative_claim_cannot_gain_a_backing_source(self):
        drifted = copy.deepcopy(self.manifest)
        drifted["claims"][0]["backing_source_path"] = "README.md"
        errors = VALIDATOR.validate_manifest(drifted, ROOT)
        self.assertTrue(any("cannot cite a backing source" in error for error in errors))

    def test_modelled_claim_requires_a_real_backing_source(self):
        drifted = copy.deepcopy(self.manifest)
        modelled = next(
            claim for claim in drifted["claims"]
            if claim["classification"] == "MODELLED_SYNTHETIC"
        )
        modelled["backing_source_path"] = "docs/missing-calculation.md"
        errors = VALIDATOR.validate_manifest(drifted, ROOT)
        self.assertTrue(any("requires a repository backing source" in error for error in errors))

    def test_source_annotation_drift_fails(self):
        paths = {
            VALIDATOR.MANIFEST_PATH,
            "decision-brief-demo/app/page.tsx",
            "offline/glap-demo.html",
            "README.md",
            "docs/case_study_port_disruption.md",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in paths:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            page = root / "decision-brief-demo/app/page.tsx"
            page.write_text(
                page.read_text(encoding="utf-8").replace(
                    'data-claim-id="next-decision-recommendation"',
                    'data-claim-id="unregistered-recommendation"',
                ),
                encoding="utf-8",
            )
            errors = VALIDATOR.validate_manifest(VALIDATOR.load_manifest(root), root)
        self.assertTrue(any("source_marker" in error for error in errors))

    def test_duplicate_source_annotation_fails(self):
        paths = {
            VALIDATOR.MANIFEST_PATH,
            "decision-brief-demo/app/page.tsx",
            "offline/glap-demo.html",
            "README.md",
            "docs/case_study_port_disruption.md",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in paths:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            page = root / "decision-brief-demo/app/page.tsx"
            marker = 'data-claim-id="next-decision-recommendation" data-claim-classification="ILLUSTRATIVE"'
            page.write_text(
                page.read_text(encoding="utf-8") + f"\n// {marker}\n",
                encoding="utf-8",
            )
            errors = VALIDATOR.validate_manifest(VALIDATOR.load_manifest(root), root)
        self.assertTrue(any("must occur exactly once" in error for error in errors))

    def test_legacy_executed_value_wording_fails(self):
        paths = {
            VALIDATOR.MANIFEST_PATH,
            "decision-brief-demo/app/page.tsx",
            "offline/glap-demo.html",
            "README.md",
            "docs/case_study_port_disruption.md",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in paths:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            page = root / "decision-brief-demo/app/page.tsx"
            page.write_text(
                page.read_text(encoding="utf-8").replace(
                    'title="Illustrative scenario value"', 'title="Value delivered"'
                ),
                encoding="utf-8",
            )
            errors = VALIDATOR.validate_manifest(VALIDATOR.load_manifest(root), root)
        self.assertTrue(any("legacy unqualified public claim" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
