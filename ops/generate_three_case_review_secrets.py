#!/usr/bin/env python3
"""Generate one pseudonymous reviewer account and service secrets.

The script writes nothing to disk. Copy the account JSON, session secret, and
export-token hash into the Lambda environment through an approved secret path.
Store the plaintext reviewer password and export token outside the repository.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import re
import secrets


PASSWORD_ITERATIONS = 100_000


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-id", required=True, help="Pseudonymous ID such as reviewer-three-case-01")
    parser.add_argument("--username", required=True, help="Dedicated login username; do not use an email address")
    parser.add_argument(
        "--generate-password",
        action="store_true",
        help="Generate and print a strong one-time reviewer password instead of prompting",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reviewer_id = args.reviewer_id.strip()
    username = args.username.strip()
    if not re.fullmatch(r"reviewer-[a-z0-9][a-z0-9-]{2,63}", reviewer_id):
        raise SystemExit("--reviewer-id must start with reviewer- and contain only lowercase letters, digits, or hyphens")
    if not username or len(username) > 80 or "@" in username:
        raise SystemExit("--username must be 1-80 characters and must not be an email address")
    if args.generate_password:
        password = secrets.token_urlsafe(18)
    else:
        password = getpass.getpass("Reviewer password: ")
        confirmation = getpass.getpass("Repeat reviewer password: ")
        if password != confirmation:
            raise SystemExit("Passwords do not match")
    if len(password) < 16 or len(password) > 128:
        raise SystemExit("Reviewer password must contain 16-128 characters")

    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS, dklen=32
    )
    account = {
        "reviewer_id": reviewer_id,
        "username": username,
        "password_salt": b64url(salt),
        "password_hash": b64url(password_hash),
        "password_iterations": PASSWORD_ITERATIONS,
    }
    session_secret = b64url(secrets.token_bytes(32))
    export_token = b64url(secrets.token_bytes(32))

    print("\nREVIEW_ACCOUNTS_JSON")
    print(json.dumps([account], ensure_ascii=False, separators=(",", ":")))
    print("\nREVIEW_SESSION_SECRET")
    print(session_secret)
    print("\nREVIEW_EXPORT_TOKEN_SHA256")
    print(hashlib.sha256(export_token.encode("utf-8")).hexdigest())
    print("\nPLAINTEXT_EXPORT_TOKEN (store outside the repository)")
    print(export_token)
    if args.generate_password:
        print("\nPLAINTEXT_REVIEWER_PASSWORD (store outside the repository)")
        print(password)
    else:
        print("\nThe plaintext reviewer password is not printed or stored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
