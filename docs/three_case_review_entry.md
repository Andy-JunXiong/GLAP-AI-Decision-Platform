# Ten-Story Mainland Review Entry

**Collection:** `glap-ten-story-review.v1`
**Status:** ten-story upgrade deployed; two complete submissions reconciled
**Evidence class:** compatible private review collection using the frozen ten-story display bundle
**Operational authority:** none

## Purpose and experience

This AWS Lambda Function URL gives an invited reviewer one link plus a supplied
username and password, without requiring a Tencent, Microsoft, OpenAI, or other
third-party account. After login it presents the same ten frozen decision
stories used by the formal story experience. Each story has three ordered
moments (`T0`, `T1`, `T2`), for 30 judgments in total.

At every moment the reviewer compares Plan A and Plan B on five questions,
records an overall preference and confidence, and may add notes. A committed
moment is saved to the server and becomes view-only. The next moment in that
story is not unlocked until the previous one is committed. The reviewer may
leave and resume, and may make the final immutable submission only after all 30
moments are complete.

The historical event facts are cutoff-bounded public evidence. Inventory,
priority, capacity, and cargo exposure are controlled synthetic state. Every
option remains proposal-only and grants no booking, rerouting, spending,
Action, production, or policy authority.

## Evidence boundary

The display bundle is generated from the repository's frozen ten-story,
30-package source. It preserves every source `review_id` and `package_digest`,
but this Lambda writes to collection `glap-ten-story-review.v1` and its own
export schema. It is therefore not automatically eligible for the existing
`human-evaluation-story.v2` Decision Quality gate.

On `2026-08-22`, the study owner approved combining the two content-equivalent
entry surfaces. A read-only export contained two complete submissions with 30
unique locked answers and all required attestations each. The governed local
reconciler verified the exact source bundle, display bundle, review IDs,
package digests, story positions, rubric dimensions, submission locks, and
distinct pseudonymous reviewer references. Both submissions passed and were
combined with two complete formal Sites submissions. This creates Decision
Quality evidence only; it cannot establish Business Outcome Effect, real
logistics performance, production readiness, or model readiness.

## Runtime design

```text
AWS Lambda Function URL
  -> same-origin login and HTTP-only signed session
  -> authenticated ten-story / 30-moment application
  -> immutable TEN_STORY_ANSWER row for every committed moment
  -> immutable TEN_STORY_SUBMISSION row after all 30 moments
  -> administrator-only pseudonymous JSON export
```

Implementation: [`glap_three_case_review.py`](../lambda/glap_three_case_review.py)
(the filename is retained to keep the existing Lambda handler and human
deployment steps stable). The generated display data is
[`ten_story_review_bundle.json`](../lambda/ten_story_review_bundle.json).

The unauthenticated response contains no story material. Passwords may use
PBKDF2-SHA256 account records, or the bounded direct-login recovery variables
`REVIEW_LOGIN_USERNAME`, `REVIEW_LOGIN_PASSWORD`, and
`REVIEW_LOGIN_REVIEWER_ID`. Direct mode is appropriate only for this isolated,
short-lived collection because anyone allowed to read Lambda environment
variables can read that password. Session cookies are HTTP-only, Secure,
SameSite=Strict, HMAC-signed, and expire after eight hours. Five failed logins
within 15 minutes cause a 15-minute source-and-username lockout. Mutation
requests require the exact same origin, and the Content Security Policy permits
no third-party scripts, frames, or network destinations.

The isolated DynamoDB table uses string partition key `pk` and stores:

- expiring `LOGIN_RATE` rows (`expires_at` is the TTL field);
- immutable `TEN_STORY_ANSWER` rows, one per reviewer and frozen review ID;
- immutable `TEN_STORY_SUBMISSION` rows, one per reviewer and collection.

## Package and validate

```powershell
node --experimental-strip-types ops/generate_ten_story_review_bundle.mjs
python -m compileall -q lambda ops examples tests
python -m unittest tests.test_three_case_review_lambda -v
python -m unittest discover -s tests -v
python ops/package_three_case_review_lambda.py
```

The package command creates `artifacts/glap-three-case-review.zip`, includes
both the Lambda module and generated story bundle, prints the ZIP SHA-256, and
uses handler `lambda_function.lambda_handler`.

## Human-owned AWS update

Repository agents are not authorised to modify Lambda, DynamoDB, IAM, Function
URLs, or deployed data. The existing isolated table and least-privilege role
remain sufficient; the required DynamoDB actions are `GetItem`, `PutItem`,
`DeleteItem`, and `Scan`. On 2026-08-18 a named human uploaded the new ZIP to
the existing Lambda. Keep memory at least 256 MB and timeout at least 10
seconds.

The existing account variables may remain unchanged. Changing the collection
ID invalidates old session cookies and prevents the earlier three-case test
submission keys from colliding with the new collection.

The post-upload read-only `/health` check reported:

- `build_id=ten-story-review-2026-08-18.1`;
- `collection_id=glap-ten-story-review.v1`;
- `case_count=10`;
- `moment_count=30`;
- bundle digest
  `b8a9d9fe86398f97d2a5023802dfa5bf0557c467c59f14db42fb3d7c9a8074ba`;
- `status=ok`.

The invited-account login flow was also confirmed by the user before private
credential delivery. Any future technical canary must sign in, confirm the
ten-card hub, and sign out without answering or submitting for a reviewer.

## Export and stop

After the reviewer finally submits, an authorised person uses the existing
private export bearer token against `/api/export`. The output contains only the
pseudonymous reviewer ID, frozen identifiers, 30 locked judgments, confidence,
optional notes, attestations, final timestamp, and the explicit claim boundary.
It contains no username, password hash, source address, or operational entity.

The exported file remains private and can be reconciled with a private formal
Sites export by [`reconcile_review_collections.py`](../ops/reconcile_review_collections.py).
The command writes only a local artifact and never writes Lambda, DynamoDB, or
Sites data. Any blind-key input is study-owner-only and must never be given to
reviewers or committed.

To stop collection, a named human disables the Function URL while retaining
the isolated table for evidence-preserving review. Disabling access does not
authorise deletion or alteration of committed answers.
