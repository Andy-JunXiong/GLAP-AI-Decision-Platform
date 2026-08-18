#!/usr/bin/env python3
"""Verify a reviewer password against REVIEW_ACCOUNTS_JSON without storing either."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json


def b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def credentials_match(accounts_json: str, username: str, password: str) -> bool:
    try:
        accounts = json.loads(accounts_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(accounts, list):
        return False
    account = next(
        (
            item
            for item in accounts
            if isinstance(item, dict)
            and str(item.get("username", "")).casefold() == username.strip().casefold()
        ),
        None,
    )
    if account is None:
        return False
    try:
        salt = b64url_decode(str(account["password_salt"]))
        expected = b64url_decode(str(account["password_hash"]))
        iterations = int(account["password_iterations"])
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations, dklen=32
        )
    except (KeyError, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def main() -> int:
    print("Nothing entered here is displayed, written to disk, or sent over the network.")
    accounts_json = getpass.getpass("Paste REVIEW_ACCOUNTS_JSON: ")
    username = input("Username: ").strip()
    password = getpass.getpass("Paste reviewer password: ")
    if credentials_match(accounts_json, username, password):
        print("LOCAL_CREDENTIAL_CHECK=PASS")
        return 0
    print("LOCAL_CREDENTIAL_CHECK=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
