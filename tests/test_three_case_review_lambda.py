import base64
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambda"))

import glap_three_case_review as review  # noqa: E402


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class ConditionalFailure(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
        super().__init__("conditional check failed")


class FakeDynamoDB:
    def __init__(self):
        self.items = {}

    @staticmethod
    def _pk(key):
        return key["pk"]["S"]

    def get_item(self, *, Key, **_kwargs):
        item = self.items.get(self._pk(Key))
        return {"Item": item} if item else {}

    def put_item(self, *, Item, ConditionExpression=None, **_kwargs):
        key = self._pk(Item)
        if ConditionExpression == "attribute_not_exists(pk)" and key in self.items:
            raise ConditionalFailure()
        self.items[key] = Item
        return {}

    def delete_item(self, *, Key, **_kwargs):
        self.items.pop(self._pk(Key), None)
        return {}

    def scan(self, *, ExpressionAttributeValues=None, **_kwargs):
        values = ExpressionAttributeValues or {}
        kind = (values.get(":kind") or {}).get("S")
        reviewer = (values.get(":reviewer") or {}).get("S")
        collection = (values.get(":collection") or {}).get("S")
        matches = []
        for item in self.items.values():
            if kind and item.get("kind", {}).get("S") != kind:
                continue
            if reviewer and item.get("reviewer_id", {}).get("S") != reviewer:
                continue
            if collection and item.get("collection_id", {}).get("S") != collection:
                continue
            if "payload_json" in item:
                matches.append({"payload_json": item["payload_json"]})
        return {"Items": matches}


class TenStoryReviewLambdaTest(unittest.TestCase):
    password = "A-strong-review-password"
    username = "invited-reviewer"
    reviewer_id = "reviewer-ten-story-01"
    export_token = "export-token-with-enough-randomness"

    def setUp(self):
        salt = b"0123456789abcdef"
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", self.password.encode(), salt, review.PASSWORD_ITERATIONS, dklen=32
        )
        account = {
            "reviewer_id": self.reviewer_id,
            "username": self.username,
            "password_salt": b64url(salt),
            "password_hash": b64url(password_hash),
            "password_iterations": review.PASSWORD_ITERATIONS,
        }
        self.env = {
            "REVIEW_TABLE_NAME": "glap-three-case-review-test",
            "REVIEW_SESSION_SECRET": b64url(b"s" * 32),
            "REVIEW_EXPORT_TOKEN_SHA256": hashlib.sha256(self.export_token.encode()).hexdigest(),
            "REVIEW_ACCOUNTS_JSON": json.dumps([account]),
        }
        self.ddb = FakeDynamoDB()
        self.env_patch = patch.dict(os.environ, self.env, clear=False)
        self.ddb_patch = patch.object(review, "_ddb", return_value=self.ddb)
        self.time_patch = patch.object(review.time, "time", return_value=1_800_000_000)
        self.env_patch.start()
        self.ddb_patch.start()
        self.time_patch.start()
        review._config.cache_clear()

    def tearDown(self):
        review._config.cache_clear()
        self.time_patch.stop()
        self.ddb_patch.stop()
        self.env_patch.stop()

    def event(self, method="GET", path="/", body=None, *, cookies=None, origin=True, headers=None):
        event_headers = {"host": "review.example.test"}
        if origin:
            event_headers["origin"] = "https://review.example.test"
        if headers:
            event_headers.update(headers)
        event = {
            "version": "2.0",
            "rawPath": path,
            "headers": event_headers,
            "requestContext": {"http": {"method": method, "sourceIp": "203.0.113.10"}},
        }
        if body is not None:
            event["body"] = json.dumps(body)
        if cookies:
            event["cookies"] = cookies
        return event

    def login(self):
        response = review.lambda_handler(
            self.event("POST", "/api/login", {"username": self.username, "password": self.password}),
            None,
        )
        self.assertEqual(response["statusCode"], 200)
        return response["cookies"][0].split(";", 1)[0]

    @staticmethod
    def answer(review_id):
        _, _, stage = review.REVIEW_BY_ID[review_id]
        value = "TIE" if stage["shared_plan"] else "OPTION_A"
        return {
            "review_id": review_id,
            "package_digest": stage["package_digest"],
            "judgments": {dimension: value for dimension in review.DIMENSION_IDS},
            "preferred": value,
            "confidence": 4,
            "notes": "",
        }

    def commit(self, cookie, review_id):
        return review.lambda_handler(
            self.event("POST", "/api/answer", self.answer(review_id), cookies=[cookie]), None
        )

    def test_bundle_contains_ten_stories_and_thirty_frozen_moments(self):
        self.assertEqual(len(review.CASES), 10)
        self.assertEqual(len(review.REVIEW_IDS), 30)
        self.assertEqual(len(set(review.REVIEW_IDS)), 30)
        self.assertEqual(review.SOURCE_BUNDLE_ID, "35397ba1fb3d15d87ad7c071")

    def test_health_exposes_bounded_contract_metadata(self):
        response = review.lambda_handler(self.event(path="/health", origin=False), None)
        payload = json.loads(response["body"])
        self.assertEqual(payload["case_count"], 10)
        self.assertEqual(payload["moment_count"], 30)
        self.assertEqual(payload["collection_id"], review.COLLECTION_ID)

    def test_login_page_contains_no_case_material(self):
        response = review.lambda_handler(self.event(origin=False), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("十案例独立评审", response["body"])
        self.assertNotIn("Baltimore 港", response["body"])

    def test_authenticated_page_contains_story_hub_and_frozen_titles(self):
        cookie = self.login()
        response = review.lambda_handler(self.event(cookies=[cookie], origin=False), None)
        self.assertIn("10 DISTINCT DECISION STORIES", response["body"])
        self.assertIn("Baltimore 港", response["body"])
        self.assertIn("巴拿马运河", response["body"])

    def test_answer_is_locked_and_state_resumes_it(self):
        cookie = self.login()
        review_id = review.CASES[0]["stages"][0]["review_id"]
        self.assertEqual(self.commit(cookie, review_id)["statusCode"], 201)
        self.assertEqual(self.commit(cookie, review_id)["statusCode"], 409)
        state = review.lambda_handler(self.event(path="/api/state", cookies=[cookie], origin=False), None)
        payload = json.loads(state["body"])
        self.assertIn(review_id, payload["answers"])

    def test_later_moment_requires_previous_moment(self):
        cookie = self.login()
        review_id = review.CASES[0]["stages"][1]["review_id"]
        response = self.commit(cookie, review_id)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("previous moment", json.loads(response["body"])["error"])

    def test_shared_plan_requires_ties(self):
        shared = next(stage for stage in review.REVIEW_STAGES if stage["shared_plan"])
        payload = self.answer(shared["review_id"])
        payload["preferred"] = "OPTION_A"
        with self.assertRaisesRegex(ValueError, "shared-plan"):
            review._validate_answer(payload, self.reviewer_id, 1_800_000_000)

    def test_final_submission_requires_all_thirty_answers(self):
        cookie = self.login()
        request = {"attestations": {"independent": True, "no_conflict": True, "no_blind_key": True}}
        response = review.lambda_handler(self.event("POST", "/api/submit", request, cookies=[cookie]), None)
        self.assertEqual(response["statusCode"], 400)

    def test_complete_review_submits_once_and_exports_thirty_answers(self):
        cookie = self.login()
        for review_id in review.REVIEW_IDS:
            self.assertEqual(self.commit(cookie, review_id)["statusCode"], 201)
        request = {"attestations": {"independent": True, "no_conflict": True, "no_blind_key": True}}
        self.assertEqual(
            review.lambda_handler(self.event("POST", "/api/submit", request, cookies=[cookie]), None)["statusCode"],
            201,
        )
        self.assertEqual(
            review.lambda_handler(self.event("POST", "/api/submit", request, cookies=[cookie]), None)["statusCode"],
            409,
        )
        exported = review.lambda_handler(
            self.event(path="/api/export", origin=False, headers={"authorization": f"Bearer {self.export_token}"}),
            None,
        )
        payload = json.loads(exported["body"])
        self.assertEqual(len(payload["submissions"]), 1)
        self.assertEqual(len(payload["submissions"][0]["answers"]), 30)
        self.assertNotIn(self.username, exported["body"])
        self.assertIn("not automatically eligible", payload["submissions"][0]["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
