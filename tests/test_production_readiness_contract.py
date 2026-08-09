import copy
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_production_readiness_contract",
    ROOT / "ops" / "validate_production_readiness_contract.py",
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


class ProductionReadinessContractTests(unittest.TestCase):
    def test_repository_contract_is_valid_and_plan_only(self):
        self.assertEqual(VALIDATOR.validate_contract(VALIDATOR.load_contract()), [])

    def test_recurring_or_production_authority_fails_closed(self):
        contract = copy.deepcopy(VALIDATOR.load_contract())
        contract["authority"]["recurring_schedule_enabled"] = True
        contract["authority"]["production_alias_change_authorized"] = True
        errors = VALIDATOR.validate_contract(contract)
        self.assertTrue(any("recurring_schedule_enabled" in error for error in errors))
        self.assertTrue(any("production_alias_change_authorized" in error for error in errors))

    def test_unmeasured_query_class_cannot_claim_enforcement(self):
        contract = copy.deepcopy(VALIDATOR.load_contract())
        query_class = next(
            item for item in contract["athena"]["query_classes"]
            if item["id"] == "operations_api_read"
        )
        query_class["enforcement"] = "ENFORCED"
        errors = VALIDATOR.validate_contract(contract)
        self.assertTrue(any("measured-baseline" in error for error in errors))

    def test_incremental_view_inventory_is_exact(self):
        contract = copy.deepcopy(VALIDATOR.load_contract())
        contract["incremental_views"].pop()
        self.assertTrue(any("view inventory" in error for error in VALIDATOR.validate_contract(contract)))


if __name__ == "__main__":
    unittest.main()
