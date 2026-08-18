import base64
import hashlib
import json
import unittest

from ops.verify_three_case_review_credentials import credentials_match


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class ThreeCaseReviewCredentialVerifierTest(unittest.TestCase):
    def test_matches_generated_contract_and_rejects_wrong_values(self):
        password = "correct-local-password"
        salt = b"0123456789abcdef"
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, 100_000, dklen=32
        )
        accounts_json = json.dumps(
            [
                {
                    "reviewer_id": "reviewer-local-check-01",
                    "username": "review03",
                    "password_salt": b64url(salt),
                    "password_hash": b64url(password_hash),
                    "password_iterations": 100_000,
                }
            ]
        )
        self.assertTrue(credentials_match(accounts_json, "review03", password))
        self.assertFalse(credentials_match(accounts_json, "review03", "wrong-password"))
        self.assertFalse(credentials_match(accounts_json, "review04", password))
        self.assertFalse(credentials_match("not-json", "review03", password))


if __name__ == "__main__":
    unittest.main()
