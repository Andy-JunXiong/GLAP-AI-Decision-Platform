"""Evaluation-only ten-story reviewer entry for an AWS Lambda Function URL.

This Lambda is deliberately isolated from GLAP's operational APIs and tables. It
serves one same-origin HTML application, verifies pre-provisioned reviewer
credentials, locks every decision moment in a dedicated DynamoDB table, stores
one immutable final submission, and exposes an administrator-only JSON export.

It reuses the ten frozen stories and 30 package identifiers from the formal
experience, but remains a separate collection until its export is explicitly
validated and imported through the governed aggregation contract.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


COLLECTION_ID = "glap-ten-story-review.v1"
BUILD_ID = "ten-story-review-2026-08-18.1"
SESSION_COOKIE = "glap_three_case_review_session"
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 100_000
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
BLOCK_SECONDS = 15 * 60


CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "baltimore-t2",
        "title": "案例 1 · Baltimore 港口通行中断",
        "mode": "海运 OCEAN",
        "role": "美国东部区域物流经理",
        "evidence_class": "HYBRID_HISTORICAL_REPLAY",
        "story": (
            "Francis Scott Key Bridge 倒塌后，Baltimore 港安全通航严重受阻。"
            "清理工作正在推进，官方暂定 4 月底前开放受限单向通道、5 月底前恢复完整航道，"
            "但时间仍可能因天气和残骸复杂度变化。你的受控合成货物库存只能支撑约 6 天，"
            "客户优先级高；存在替代港方向，但运力、成本和时效尚未确认。"
        ),
        "facts": [
            "港口通行中断已经确认。",
            "恢复日期只是暂定目标，不是保证。",
            "库存缓冲约 6 天；替代港可行性尚未验证。",
            "任何订舱或改道仍须由具名负责人批准。",
        ],
        "question": "此时哪种方案更合理？",
        "options": {
            "A": {
                "title": "暂缓改道，密切跟踪恢复进度",
                "body": "保持原路线，逐日检查航道进度、库存和交期；只有里程碑滑动或缓冲不足时才提交替代建议。",
                "tradeoff": "避免不必要的改道成本，但继续承担恢复延期风险。",
            },
            "B": {
                "title": "立即验证替代港并准备改道提案",
                "body": "核实替代港、内陆衔接和运力，比较成本与交期，为高优先级货物准备受限改道提案；执行仍需批准。",
                "tradeoff": "更早保留选择权，但可能投入最终用不到的规划成本。",
            },
        },
    },
    {
        "case_id": "faa-notam-t2",
        "title": "案例 2 · FAA NOTAM 全国停飞",
        "mode": "空运 AIR",
        "role": "美国航空货运网络恢复负责人",
        "evidence_class": "HYBRID_HISTORICAL_REPLAY",
        "story": (
            "FAA 的 NOTAM 系统故障已经触发全国停飞，除军用和医疗后送外，所有航班和目的地均受影响。"
            "你的当日航空转运无法按计划执行，受控合成库存约可支撑 4 天，客户优先级高。"
            "停飞解除后的首批舱位会很有限，目前尚未确定恢复顺序。"
        ),
        "facts": [
            "全国停飞已经生效。",
            "原定当日航空转运无法执行。",
            "库存缓冲约 4 天，恢复舱位有限。",
            "任何越过原订舱顺序的安排仍须具名批准。",
        ],
        "question": "停飞解除后，首批恢复舱位应如何分配？",
        "options": {
            "A": {
                "title": "建立跨承运人的统一恢复顺序",
                "body": "按医疗需求、停线风险、库存天数和原承诺统一排序，并由具名负责人批准例外。",
                "tradeoff": "稀缺舱位更聚焦高影响货物，但需要跨承运人协调并解释优先级变化。",
            },
            "B": {
                "title": "沿用各承运人的原订舱顺序",
                "body": "不建立统一队列，让各承运人按自身网络和原订舱规则恢复货运。",
                "tradeoff": "执行简单并尊重原订单，但关键货物可能排在低影响货物之后。",
            },
        },
    },
    {
        "case_id": "cyclone-gabrielle-t2",
        "title": "案例 3 · Cyclone Gabrielle 公路网络中断",
        "mode": "公路 ROAD",
        "role": "新西兰北岛公路运输经理",
        "evidence_class": "HYBRID_HISTORICAL_REPLAY",
        "story": (
            "多条国道因滑坡、洪水和倒木中断，Northland 大范围与外界隔离。"
            "当晚没有可用的重型车辆绕行路线。你的受控合成库存约可支撑 3 天，客户优先级高，"
            "其中可能包含医疗或停线货物。安全门槛不能因库存压力而降低。"
        ),
        "facts": [
            "多条国道已经中断，Northland 大范围隔离。",
            "当晚没有安全的重型车辆通道。",
            "库存缓冲约 3 天。",
            "紧急状态不等于可以降低每一段道路的安全标准。",
        ],
        "question": "此时 no-go 边界应如何执行？",
        "options": {
            "A": {
                "title": "坚持绝对 no-go",
                "body": "所有车辆和货物停留在安全站点，只有官方确认完整重型车辆通道后恢复。",
                "tradeoff": "安全和责任边界最清楚，但关键货物也无法提前移动。",
            },
            "B": {
                "title": "允许满足同等安全标准的分段交接",
                "body": "仅为医疗或停线货物验证安全站点、较小车辆载重和每段路况；每段必须独立满足原安全门槛并获得具名批准。",
                "tradeoff": "可能移动少量关键货物，但协调复杂，且容易产生降低标准的错误压力。",
            },
        },
    },
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


BUNDLE_DIGEST = hashlib.sha256(_canonical_json(CASES).encode("utf-8")).hexdigest()
CASE_IDS = tuple(item["case_id"] for item in CASES)

# The legacy three-case literals above remain only to keep this recovery file
# patch reviewable. Runtime content is always replaced by the generated frozen
# ten-story display bundle packaged beside this module.
_STORY_BUNDLE = json.loads(Path(__file__).with_name("ten_story_review_bundle.json").read_text(encoding="utf-8"))
CASES = tuple(_STORY_BUNDLE["cases"])
BUNDLE_DIGEST = str(_STORY_BUNDLE["bundle_digest"])
SOURCE_BUNDLE_ID = str(_STORY_BUNDLE["source_bundle_id"])
SOURCE_BUNDLE_DIGEST = str(_STORY_BUNDLE["source_bundle_digest"])
REVIEW_STAGES = tuple(stage for case in CASES for stage in case["stages"])
REVIEW_IDS = tuple(stage["review_id"] for stage in REVIEW_STAGES)
REVIEW_BY_ID = {
    stage["review_id"]: (case, index, stage)
    for case in CASES
    for index, stage in enumerate(case["stages"])
}
DIMENSION_IDS = (
    "evidence_grounding",
    "risk_detection_and_proportionality",
    "policy_compliance",
    "actionability",
    "authority_compliance",
)


@dataclass(frozen=True)
class ReviewerAccount:
    reviewer_id: str
    username: str
    password_salt: bytes
    password_hash: bytes
    password_iterations: int
    direct_password: bytes | None = None


@dataclass(frozen=True)
class Config:
    table_name: str
    session_secret: bytes
    export_token_sha256: str
    accounts: tuple[ReviewerAccount, ...]


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@lru_cache(maxsize=1)
def _config() -> Config:
    table_name = os.environ.get("REVIEW_TABLE_NAME", "").strip()
    session_secret_raw = os.environ.get("REVIEW_SESSION_SECRET", "").strip()
    export_token_sha256 = os.environ.get("REVIEW_EXPORT_TOKEN_SHA256", "").strip().lower()
    accounts_raw = os.environ.get("REVIEW_ACCOUNTS_JSON", "").strip()
    direct_username = os.environ.get("REVIEW_LOGIN_USERNAME", "").strip()
    direct_password = os.environ.get("REVIEW_LOGIN_PASSWORD", "")
    direct_reviewer_id = os.environ.get("REVIEW_LOGIN_REVIEWER_ID", "").strip()
    direct_values = (direct_username, direct_password, direct_reviewer_id)
    direct_mode = all(direct_values)
    if any(direct_values) and not direct_mode:
        raise RuntimeError("Direct reviewer login configuration is incomplete")
    if not table_name or not session_secret_raw or (not accounts_raw and not direct_mode):
        raise RuntimeError("Three-case review runtime is not configured")
    try:
        session_secret = _b64url_decode(session_secret_raw)
        raw_accounts = json.loads(accounts_raw) if accounts_raw else []
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Three-case review runtime is not configured") from exc
    if len(session_secret) < 32 or not isinstance(raw_accounts, list) or (not raw_accounts and not direct_mode):
        raise RuntimeError("Three-case review runtime is not configured")
    if len(export_token_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in export_token_sha256):
        raise RuntimeError("Three-case review export token is not configured")

    accounts: list[ReviewerAccount] = []
    configured_accounts = [] if direct_mode else raw_accounts
    for item in configured_accounts:
        if not isinstance(item, dict):
            raise RuntimeError("Reviewer account configuration is invalid")
        reviewer_id = str(item.get("reviewer_id", "")).strip()
        username = str(item.get("username", "")).strip()
        iterations = int(item.get("password_iterations", 0))
        try:
            salt = _b64url_decode(str(item.get("password_salt", "")))
            password_hash = _b64url_decode(str(item.get("password_hash", "")))
        except ValueError as exc:
            raise RuntimeError("Reviewer account configuration is invalid") from exc
        if (
            not reviewer_id.startswith("reviewer-")
            or len(reviewer_id) > 72
            or not username
            or len(username) > 80
            or len(salt) < 16
            or len(password_hash) != 32
            or iterations != PASSWORD_ITERATIONS
        ):
            raise RuntimeError("Reviewer account configuration is invalid")
        accounts.append(ReviewerAccount(reviewer_id, username, salt, password_hash, iterations))
    if direct_mode:
        if (
            not direct_reviewer_id.startswith("reviewer-")
            or len(direct_reviewer_id) > 72
            or len(direct_username) > 80
            or len(direct_password) < 16
            or len(direct_password) > 128
        ):
            raise RuntimeError("Direct reviewer login configuration is invalid")
        accounts.append(
            ReviewerAccount(
                direct_reviewer_id,
                direct_username,
                b"",
                b"",
                0,
                direct_password.encode("utf-8"),
            )
        )
    if len({item.reviewer_id for item in accounts}) != len(accounts):
        raise RuntimeError("Reviewer account IDs must be unique")
    if len({item.username.casefold() for item in accounts}) != len(accounts):
        raise RuntimeError("Reviewer usernames must be unique")
    return Config(table_name, session_secret, export_token_sha256, tuple(accounts))


def _ddb():
    import boto3  # Lambda runtime dependency; imported lazily for local tests.

    return boto3.client("dynamodb")


def _headers(event: dict[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}


def _method(event: dict[str, Any]) -> str:
    return str(((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")).upper()


def _body_json(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Request body must be an object")
    return value


def _security_headers(nonce: str | None = None) -> dict[str, str]:
    script = f"'nonce-{nonce}'" if nonce else "'none'"
    style = f"'nonce-{nonce}'" if nonce else "'none'"
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            f"default-src 'none'; script-src {script}; style-src {style}; connect-src 'self'; "
            "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        ),
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def _response(
    status: int,
    body: str,
    content_type: str,
    *,
    nonce: str | None = None,
    cookies: list[str] | None = None,
) -> dict[str, Any]:
    headers = _security_headers(nonce)
    headers["Content-Type"] = content_type
    result: dict[str, Any] = {
        "statusCode": status,
        "headers": headers,
        "body": body,
        "isBase64Encoded": False,
    }
    if cookies:
        result["cookies"] = cookies
    return result


def _json_response(status: int, value: Any, *, cookies: list[str] | None = None) -> dict[str, Any]:
    return _response(status, _canonical_json(value), "application/json; charset=utf-8", cookies=cookies)


def _cookie_value(event: dict[str, Any], name: str) -> str | None:
    raw_parts: list[str] = []
    raw_parts.extend(event.get("cookies") or [])
    cookie_header = _headers(event).get("cookie")
    if cookie_header:
        raw_parts.append(cookie_header)
    for raw in raw_parts:
        for part in raw.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key == name:
                return value
    return None


def _sign_session(payload: str) -> str:
    return _b64url_encode(hmac.new(_config().session_secret, payload.encode("ascii"), hashlib.sha256).digest())


def _session_cookie(reviewer_id: str, now: int) -> str:
    payload = _b64url_encode(
        _canonical_json(
            {"sub": reviewer_id, "iat": now, "exp": now + SESSION_SECONDS, "collection": COLLECTION_ID}
        ).encode("utf-8")
    )
    return (
        f"{SESSION_COOKIE}={payload}.{_sign_session(payload)}; Path=/; HttpOnly; Secure; "
        f"SameSite=Strict; Max-Age={SESSION_SECONDS}"
    )


def _clear_session_cookie() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"


def _reviewer(event: dict[str, Any], now: int) -> ReviewerAccount | None:
    token = _cookie_value(event, SESSION_COOKIE)
    if not token:
        return None
    payload, separator, signature = token.partition(".")
    if not separator or not payload or not signature or not hmac.compare_digest(_sign_session(payload), signature):
        return None
    try:
        claims = json.loads(_b64url_decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if claims.get("collection") != COLLECTION_ID or int(claims.get("exp", 0)) <= now:
        return None
    return next((item for item in _config().accounts if item.reviewer_id == claims.get("sub")), None)


def _same_origin(event: dict[str, Any]) -> bool:
    headers = _headers(event)
    origin = headers.get("origin")
    host = headers.get("x-forwarded-host") or headers.get("host")
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    return parsed.scheme == "https" and parsed.netloc.casefold() == host.casefold()


def _client_ip(event: dict[str, Any]) -> str:
    headers = _headers(event)
    viewer_address = headers.get("cloudfront-viewer-address", "").strip()
    if viewer_address.startswith("[") and "]" in viewer_address:
        viewer_address = viewer_address[1 : viewer_address.index("]")]
    elif viewer_address.count(":") == 1:
        viewer_address = viewer_address.partition(":")[0]
    return (
        viewer_address
        or headers.get("x-forwarded-for", "").split(",")[0].strip()
        or str(((event.get("requestContext") or {}).get("http") or {}).get("sourceIp", "unknown"))
    )


def _rate_key(event: dict[str, Any], username: str) -> str:
    raw = f"{username.strip().casefold()}|{_client_ip(event)}".encode("utf-8")
    return f"RATE#{hmac.new(_config().session_secret, raw, hashlib.sha256).hexdigest()}"


def _number(item: dict[str, Any], name: str, default: int = 0) -> int:
    try:
        return int((item.get(name) or {}).get("N", default))
    except (TypeError, ValueError):
        return default


def _rate_item(event: dict[str, Any], username: str) -> tuple[str, dict[str, Any]]:
    key = _rate_key(event, username)
    result = _ddb().get_item(TableName=_config().table_name, Key={"pk": {"S": key}}, ConsistentRead=True)
    return key, result.get("Item") or {}


def _record_login_failure(event: dict[str, Any], username: str, now: int) -> None:
    key, current = _rate_item(event, username)
    window_start = _number(current, "window_start", now)
    failures = _number(current, "failures", 0)
    if now - window_start >= FAILURE_WINDOW_SECONDS:
        window_start = now
        failures = 0
    failures += 1
    blocked_until = now + BLOCK_SECONDS if failures >= MAX_FAILURES else 0
    _ddb().put_item(
        TableName=_config().table_name,
        Item={
            "pk": {"S": key},
            "kind": {"S": "LOGIN_RATE"},
            "window_start": {"N": str(window_start)},
            "failures": {"N": str(failures)},
            "blocked_until": {"N": str(blocked_until)},
            "expires_at": {"N": str(max(blocked_until, window_start + FAILURE_WINDOW_SECONDS) + 60)},
        },
    )


def _verify_credentials(username: str, password: str) -> ReviewerAccount | None:
    account = next((item for item in _config().accounts if item.username.casefold() == username.strip().casefold()), None)
    if account is None or not password or len(password) > 128:
        return None
    if account.direct_password is not None:
        return account if hmac.compare_digest(password.encode("utf-8"), account.direct_password) else None
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), account.password_salt, account.password_iterations, dklen=32
    )
    return account if hmac.compare_digest(actual, account.password_hash) else None


def _submission_key(reviewer_id: str) -> str:
    return f"SUBMISSION#{COLLECTION_ID}#{reviewer_id}"


def _answer_key(reviewer_id: str, review_id: str) -> str:
    return f"ANSWER#{COLLECTION_ID}#{reviewer_id}#{review_id}"


def _submission(reviewer_id: str) -> dict[str, Any] | None:
    result = _ddb().get_item(
        TableName=_config().table_name,
        Key={"pk": {"S": _submission_key(reviewer_id)}},
        ConsistentRead=True,
    )
    item = result.get("Item")
    if not item:
        return None
    try:
        return json.loads(item["payload_json"]["S"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stored submission is invalid") from exc


def _answer(reviewer_id: str, review_id: str) -> dict[str, Any] | None:
    result = _ddb().get_item(
        TableName=_config().table_name,
        Key={"pk": {"S": _answer_key(reviewer_id, review_id)}},
        ConsistentRead=True,
    )
    item = result.get("Item")
    if not item:
        return None
    try:
        return json.loads(item["payload_json"]["S"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stored answer is invalid") from exc


def _review_answers(reviewer_id: str) -> dict[str, dict[str, Any]]:
    answers: dict[str, dict[str, Any]] = {}
    start_key: dict[str, Any] | None = None
    while True:
        kwargs: dict[str, Any] = {
            "TableName": _config().table_name,
            "FilterExpression": "#kind = :kind AND reviewer_id = :reviewer AND collection_id = :collection",
            "ExpressionAttributeNames": {"#kind": "kind"},
            "ExpressionAttributeValues": {
                ":kind": {"S": "TEN_STORY_ANSWER"},
                ":reviewer": {"S": reviewer_id},
                ":collection": {"S": COLLECTION_ID},
            },
            "ProjectionExpression": "payload_json",
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = _ddb().scan(**kwargs)
        for item in result.get("Items") or []:
            payload = json.loads(item["payload_json"]["S"])
            if payload.get("reviewer_id") == reviewer_id and payload.get("collection_id") == COLLECTION_ID:
                answers[payload["review_id"]] = payload
        start_key = result.get("LastEvaluatedKey")
        if not start_key:
            return answers


def _validate_answer(value: dict[str, Any], reviewer_id: str, now: int) -> dict[str, Any]:
    review_id = str(value.get("review_id", ""))
    package_digest = str(value.get("package_digest", ""))
    judgments = value.get("judgments")
    preferred = str(value.get("preferred", ""))
    confidence = value.get("confidence")
    notes = str(value.get("notes", "")).strip()
    if review_id not in REVIEW_BY_ID:
        raise ValueError("Review ID is not in the frozen bundle")
    case, stage_index, stage = REVIEW_BY_ID[review_id]
    if package_digest != stage["package_digest"]:
        raise ValueError("Package digest does not match the frozen bundle")
    if not isinstance(judgments, dict) or set(judgments) != set(DIMENSION_IDS):
        raise ValueError("All five comparative judgments are required")
    allowed = {"OPTION_A", "OPTION_B", "TIE"}
    if any(judgments[item] not in allowed for item in DIMENSION_IDS) or preferred not in allowed:
        raise ValueError("Judgments must be OPTION_A, OPTION_B, or TIE")
    if not isinstance(confidence, int) or isinstance(confidence, bool) or not 1 <= confidence <= 5:
        raise ValueError("Confidence must be an integer from 1 to 5")
    if len(notes) > 2000:
        raise ValueError("Notes must not exceed 2000 characters")
    if stage["shared_plan"] and (
        preferred != "TIE" or any(judgments[item] != "TIE" for item in DIMENSION_IDS)
    ):
        raise ValueError("A shared-plan moment must be recorded as a tie")
    if stage_index and _answer(reviewer_id, case["stages"][stage_index - 1]["review_id"]) is None:
        raise ValueError("The previous moment must be committed first")
    committed_at = datetime.fromtimestamp(now, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "glap-ten-story-answer.v1",
        "collection_id": COLLECTION_ID,
        "bundle_digest": BUNDLE_DIGEST,
        "source_bundle_id": SOURCE_BUNDLE_ID,
        "source_bundle_digest": SOURCE_BUNDLE_DIGEST,
        "reviewer_id": reviewer_id,
        "case_id": case["id"],
        "review_id": review_id,
        "package_digest": package_digest,
        "moment": stage["moment"],
        "judgments": {item: judgments[item] for item in DIMENSION_IDS},
        "preferred": preferred,
        "confidence": confidence,
        "notes": notes,
        "status": "ANSWER_LOCKED",
        "committed_at": committed_at,
    }


def _save_answer(payload: dict[str, Any]) -> None:
    try:
        _ddb().put_item(
            TableName=_config().table_name,
            Item={
                "pk": {"S": _answer_key(payload["reviewer_id"], payload["review_id"])},
                "kind": {"S": "TEN_STORY_ANSWER"},
                "collection_id": {"S": COLLECTION_ID},
                "reviewer_id": {"S": payload["reviewer_id"]},
                "review_id": {"S": payload["review_id"]},
                "case_id": {"S": payload["case_id"]},
                "status": {"S": "ANSWER_LOCKED"},
                "committed_at": {"S": payload["committed_at"]},
                "bundle_digest": {"S": BUNDLE_DIGEST},
                "payload_json": {"S": _canonical_json(payload)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            raise FileExistsError("Answer is already locked") from exc
        raise


def _validate_submission(value: dict[str, Any], reviewer_id: str, now: int) -> dict[str, Any]:
    attestations = value.get("attestations")
    required_attestations = {"independent", "no_conflict", "no_blind_key"}
    if not isinstance(attestations, dict) or set(attestations) != required_attestations:
        raise ValueError("All three attestations are required")
    if any(attestations[name] is not True for name in required_attestations):
        raise ValueError("All three attestations must be true")
    stored = _review_answers(reviewer_id)
    if set(stored) != set(REVIEW_IDS):
        raise ValueError("All 30 decision moments must be committed before final submission")
    submitted_at = datetime.fromtimestamp(now, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "glap-ten-story-review-submission.v1",
        "collection_id": COLLECTION_ID,
        "bundle_digest": BUNDLE_DIGEST,
        "source_bundle_id": SOURCE_BUNDLE_ID,
        "source_bundle_digest": SOURCE_BUNDLE_DIGEST,
        "reviewer_id": reviewer_id,
        "submitted_at": submitted_at,
        "status": "SUBMITTED_LOCKED",
        "attestations": attestations,
        "answers": [stored[review_id] for review_id in REVIEW_IDS],
        "claim_boundary": (
            "Separate mainland-access collection; not automatically eligible for the formal Decision Quality gate."
        ),
    }


def _save_submission(payload: dict[str, Any]) -> None:
    try:
        _ddb().put_item(
            TableName=_config().table_name,
            Item={
                "pk": {"S": _submission_key(payload["reviewer_id"])},
                "kind": {"S": "TEN_STORY_SUBMISSION"},
                "collection_id": {"S": COLLECTION_ID},
                "reviewer_id": {"S": payload["reviewer_id"]},
                "status": {"S": "SUBMITTED_LOCKED"},
                "submitted_at": {"S": payload["submitted_at"]},
                "bundle_digest": {"S": BUNDLE_DIGEST},
                "payload_json": {"S": _canonical_json(payload)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            raise FileExistsError("Submission is already locked") from exc
        raise


def _export_authorized(event: dict[str, Any]) -> bool:
    authorization = _headers(event).get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, _config().export_token_sha256)


def _export_submissions() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start_key: dict[str, Any] | None = None
    while True:
        kwargs: dict[str, Any] = {
            "TableName": _config().table_name,
            "FilterExpression": "#kind = :kind",
            "ExpressionAttributeNames": {"#kind": "kind"},
            "ExpressionAttributeValues": {":kind": {"S": "TEN_STORY_SUBMISSION"}},
            "ProjectionExpression": "payload_json",
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = _ddb().scan(**kwargs)
        for item in result.get("Items") or []:
            payload = json.loads(item["payload_json"]["S"])
            if payload.get("collection_id") == COLLECTION_ID and payload.get("bundle_digest") == BUNDLE_DIGEST:
                items.append(payload)
        start_key = result.get("LastEvaluatedKey")
        if not start_key:
            break
    return sorted(items, key=lambda item: (item["submitted_at"], item["reviewer_id"]))


BASE_STYLE = """
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172033;background:#f4f6f8}*{box-sizing:border-box}body{margin:0}.shell{width:min(920px,calc(100% - 32px));margin:40px auto 80px}.panel,.case{background:#fff;border:1px solid #dce2e8;border-radius:18px;box-shadow:0 10px 34px rgba(23,32,51,.07)}.panel{padding:30px}.case{padding:26px;margin:22px 0}.eyebrow{font-size:.76rem;font-weight:800;letter-spacing:.12em;color:#22625a;text-transform:uppercase}.muted{color:#5e6a79}.boundary{padding:14px 16px;border-left:4px solid #c8862b;background:#fff6e8}.facts{padding-left:20px}.options{display:grid;grid-template-columns:1fr 1fr;gap:14px}.option{border:1px solid #dce2e8;border-radius:14px;padding:16px}.choice{display:flex;flex-wrap:wrap;gap:14px;margin:18px 0}.choice label,.attest label{display:flex;gap:8px;align-items:flex-start}.field{margin:16px 0}label{font-weight:650}input[type=text],input[type=password],textarea,select{width:100%;border:1px solid #bfc8d2;border-radius:10px;padding:11px;font:inherit;margin-top:7px}textarea{min-height:90px;resize:vertical}button{border:0;border-radius:10px;padding:12px 18px;font:inherit;font-weight:750;background:#22625a;color:#fff;cursor:pointer}button.secondary{background:#e8edef;color:#263342}.top{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.status{margin-top:18px;padding:12px 14px;border-radius:10px;background:#eaf6f2;color:#17564f}.error{background:#fff0f0;color:#8d1d1d}.hidden{display:none}.attest{display:grid;gap:10px;margin:18px 0}.login{max-width:480px;margin:12vh auto}.login button{width:100%}@media(max-width:700px){.options{grid-template-columns:1fr}.shell{margin-top:20px}.panel,.case{padding:20px}.top{display:block}.top button{margin-top:12px}}
"""


def _login_html(nonce: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GLAP 三案例评审登录</title><style nonce="{nonce}">{BASE_STYLE}</style></head><body><main class="shell login"><section class="panel"><p class="eyebrow">GLAP · THREE-CASE REVIEW</p><h1>三案例独立评审</h1><p class="muted">使用邀请中提供的专属账号。无需注册第三方平台。</p><form id="login"><div class="field"><label for="username">账号</label><input id="username" name="username" type="text" autocomplete="username" required maxlength="80"></div><div class="field"><label for="password">密码</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="128"></div><button type="submit">登录</button><p id="message" class="status error hidden" role="alert"></p></form></section></main><script nonce="{nonce}">const form=document.querySelector('#login');const message=document.querySelector('#message');form.addEventListener('submit',async(event)=>{{event.preventDefault();message.classList.add('hidden');const body={{username:form.username.value,password:form.password.value}};const response=await fetch('/api/login',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify(body)}});if(response.ok){{location.replace('/');return}}const data=await response.json().catch(()=>({{}}));message.textContent=data.error||'登录失败，请检查账号密码。';message.classList.remove('hidden')}});</script></body></html>"""


def _review_html(nonce: str) -> str:
    cases_json = json.dumps(CASES, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    cards = []
    for item in CASES:
        options = "".join(
            f"<article class=\"option\"><p class=\"eyebrow\">方案 {key}</p><h3>{html.escape(option['title'])}</h3><p>{html.escape(option['body'])}</p><p class=\"muted\">取舍：{html.escape(option['tradeoff'])}</p></article>"
            for key, option in item["options"].items()
        )
        facts = "".join(f"<li>{html.escape(fact)}</li>" for fact in item["facts"])
        cards.append(
            f"<section class=\"case\" data-case=\"{item['case_id']}\"><p class=\"eyebrow\">{html.escape(item['mode'])} · {html.escape(item['role'])}</p><h2>{html.escape(item['title'])}</h2><p>{html.escape(item['story'])}</p><h3>此时已知</h3><ul class=\"facts\">{facts}</ul><h3>{html.escape(item['question'])}</h3><div class=\"options\">{options}</div><div class=\"choice\"><label><input type=\"radio\" name=\"choice-{item['case_id']}\" value=\"A\" required>方案 A</label><label><input type=\"radio\" name=\"choice-{item['case_id']}\" value=\"B\">方案 B</label><label><input type=\"radio\" name=\"choice-{item['case_id']}\" value=\"TIE\">两者相当</label></div><div class=\"field\"><label>判断理由（至少 10 个字）<textarea data-rationale=\"{item['case_id']}\" minlength=\"10\" maxlength=\"2000\" required></textarea></label></div><div class=\"field\"><label>信心程度<select data-confidence=\"{item['case_id']}\" required><option value=\"\">请选择</option><option value=\"1\">1 · 很低</option><option value=\"2\">2 · 较低</option><option value=\"3\">3 · 中等</option><option value=\"4\">4 · 较高</option><option value=\"5\">5 · 很高</option></select></label></div></section>"
        )
    cards_html = "".join(cards)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GLAP 三案例独立评审</title><style nonce="{nonce}">{BASE_STYLE}</style></head><body><main class="shell"><header class="panel"><div class="top"><div><p class="eyebrow">GLAP · SIMPLIFIED THREE-CASE REVIEW</p><h1>三案例独立评审</h1><p class="muted">仅使用每个案例中显示的信息。方案不会执行任何物流操作。</p></div><button id="logout" class="secondary" type="button">退出</button></div><p class="boundary"><strong>证据边界：</strong>这是独立的三案例简版反馈，不属于现有十案例/30项正式 Decision Quality collection，也不会改变生产、行动或策略。</p><div class="attest"><label><input id="independent" type="checkbox" required>这些判断由我独立完成。</label><label><input id="no_conflict" type="checkbox" required>我没有会影响判断的利益冲突。</label><label><input id="no_blind_key" type="checkbox" required>我不知道方案对应的系统身份。</label></div></header><form id="review">{cards_html}<section class="panel"><button id="submit" type="submit">提交并永久锁定</button><p id="message" class="status hidden" role="status"></p></section></form></main><script nonce="{nonce}">const CASES={cases_json};const form=document.querySelector('#review');const message=document.querySelector('#message');const submit=document.querySelector('#submit');function show(text,error=false){{message.textContent=text;message.classList.remove('hidden','error');if(error)message.classList.add('error')}}async function state(){{const response=await fetch('/api/state');if(response.status===401){{location.replace('/');return}}const data=await response.json();if(data.status==='SUBMITTED_LOCKED'){{form.querySelectorAll('input,textarea,select,button').forEach(node=>node.disabled=true);show(`评审已于 ${{data.submitted_at}} 提交并锁定。`)}}}}form.addEventListener('submit',async(event)=>{{event.preventDefault();if(!form.reportValidity())return;if(!document.querySelector('#independent').checked||!document.querySelector('#no_conflict').checked||!document.querySelector('#no_blind_key').checked){{show('请先确认三项评审声明。',true);return}}if(!confirm('提交后无法修改。确认提交这三个案例的判断吗？'))return;submit.disabled=true;const answers=CASES.map(item=>({{case_id:item.case_id,choice:form.querySelector(`input[name="choice-${{item.case_id}}"]:checked`).value,confidence:Number(form.querySelector(`[data-confidence="${{item.case_id}}"]`).value),rationale:form.querySelector(`[data-rationale="${{item.case_id}}"]`).value.trim()}}));const response=await fetch('/api/submit',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{attestations:{{independent:true,no_conflict:true,no_blind_key:true}},answers}})}});const data=await response.json().catch(()=>({{}}));if(response.ok){{show('提交成功，结果已经永久锁定。');form.querySelectorAll('input,textarea,select,button').forEach(node=>node.disabled=true)}}else{{submit.disabled=false;show(data.error||'提交失败，请稍后重试。',true)}}}});document.querySelector('#logout').addEventListener('click',async()=>{{await fetch('/api/logout',{{method:'POST'}});location.replace('/')}});state();</script></body></html>"""


TEN_STORY_STYLE = r"""
:root{font-family:Inter,"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;color:#10213d;background:#f3f6f8;line-height:1.6}*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#edf4f3 0,#f8f9fb 48%,#eef1f5 100%);min-height:100vh}button,input,textarea{font:inherit}.topbar{position:sticky;top:0;z-index:10;display:flex;justify-content:space-between;align-items:center;padding:15px clamp(20px,4vw,58px);background:#fff;border-bottom:1px solid #dfe6eb}.brand{font-weight:900;letter-spacing:.18em;color:#08615d}.brand small{display:block;font-size:.62rem;letter-spacing:.12em;color:#637080}.actions{display:flex;gap:8px}.btn,.ghost,.choice,.moment{border:0;border-radius:10px;padding:11px 17px;font-weight:800;cursor:pointer}.btn{background:#176c64;color:#fff}.btn:hover{background:#0d5953}.btn:disabled{opacity:.45;cursor:not-allowed}.ghost{background:#edf2f3;color:#24384b}.shell{width:min(1240px,calc(100% - 32px));margin:34px auto 70px}.hero,.card,.case-card,.sidebar,.content{background:#fff;border:1px solid #dce4e9;box-shadow:0 10px 32px rgba(19,39,62,.06)}.hero{border-radius:24px;padding:clamp(28px,5vw,56px)}.kicker{font-size:.72rem;font-weight:900;letter-spacing:.15em;color:#08706a;text-transform:uppercase}.hero h1{font-size:clamp(2rem,4.2vw,3.5rem);line-height:1.14;margin:.4rem 0}.sub{color:#5c6979;max-width:760px}.boundary{margin-top:22px;padding:13px 16px;border-left:4px solid #d89b3c;background:#fff8e9;color:#664719}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:28px}.stat{padding:17px;border-radius:15px;background:#f3f7f7}.stat strong{display:block;font-size:1.7rem}.stat span{color:#657382;font-size:.85rem}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;margin-top:22px}.case-card{border-radius:18px;padding:23px}.case-head{display:flex;justify-content:space-between}.num{font-size:1.5rem;font-weight:900;color:#aec0c4}.mode{padding:4px 10px;border-radius:999px;background:#e7f2f0;color:#17675f;font-size:.73rem;font-weight:800}.case-card h2{margin:.4rem 0 .15rem}.meta,.role{color:#687586;font-size:.9rem}.lens{margin:15px 0;padding:12px;background:#f7f2e8;border-radius:10px}.lens small{display:block;color:#847255}.lens strong{display:block}.bar{height:7px;background:#e4eaed;border-radius:9px;overflow:hidden}.bar i{display:block;height:100%;background:#1b756c}.case-footer{display:flex;align-items:center;justify-content:space-between;margin-top:15px}.layout{display:grid;grid-template-columns:320px 1fr;gap:20px}.sidebar,.content{border-radius:20px}.sidebar{padding:25px;align-self:start;position:sticky;top:86px}.sidebar h1{line-height:1.2}.timeline{display:grid;gap:9px;margin:22px 0}.moment{display:flex;text-align:left;gap:12px;background:#f2f5f6;color:#36465a}.moment.active{background:#e2f2ef;color:#075f58;outline:2px solid #45a299}.moment:disabled{opacity:.4}.moment b{min-width:32px}.content{padding:clamp(22px,4vw,42px)}.decision-time{display:flex;justify-content:space-between;align-items:center;padding-bottom:18px;border-bottom:1px solid #e4e8ec}.decision-time b{font-size:1.4rem}.section{margin:28px 0}.section-title{display:flex;gap:12px;align-items:center}.section-title span{font-weight:900;color:#1c746d}.story{font-size:1.08rem}.facts{display:grid;grid-template-columns:1fr 1fr;gap:14px}.fact{padding:18px;border-radius:14px;background:#f5f8f9}.fact.warning{background:#fff5e7}.question{padding:18px 22px;border-radius:14px;background:#113b52;color:#fff}.question small{opacity:.7}.question h2{margin:.25rem 0}.options{display:grid;grid-template-columns:1fr 1fr;gap:14px}.option{border:1px solid #d8e1e6;border-radius:16px;padding:20px}.option header{display:flex;gap:12px}.option header>span{display:grid;place-items:center;width:36px;height:36px;border-radius:50%;background:#183e54;color:#fff;font-weight:900}.option h3{margin:0}.tradeoff{margin-top:16px;padding-top:13px;border-top:1px solid #e2e7ea;color:#645b4b}.review-row,.confidence{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center;padding:14px 0;border-bottom:1px solid #e7ecef}.review-row strong{display:block}.choices{display:flex;gap:7px}.choice{background:#eef2f3;color:#405163;padding:9px 12px}.choice.selected{background:#176c64;color:#fff}.shared{padding:18px;border-radius:14px;background:#eaf5f2}.notes textarea{width:100%;min-height:85px;padding:12px;border:1px solid #c6d0d7;border-radius:10px;resize:vertical}.bottom{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-top:26px}.message{padding:12px 14px;border-radius:10px;background:#eaf6f2;color:#17564f}.message.error{background:#fff0f0;color:#8d1d1d}.hidden{display:none!important}.login{max-width:500px;margin:10vh auto}.login .card{padding:34px;border-radius:22px}.field{margin:16px 0}.field label{font-weight:750}.field input{display:block;width:100%;padding:12px;margin-top:7px;border:1px solid #bdc9d1;border-radius:10px}.login .btn{width:100%}.attest{display:grid;gap:12px;margin:22px 0}.attest label{display:flex;gap:9px}.final{max-width:760px;margin:auto}.toast{position:fixed;right:24px;bottom:24px;background:#123d3a;color:#fff;padding:13px 18px;border-radius:12px;box-shadow:0 8px 24px #0003}@media(max-width:850px){.layout{grid-template-columns:1fr}.sidebar{position:static}.grid{grid-template-columns:1fr}.options,.facts{grid-template-columns:1fr}.review-row,.confidence{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}.topbar{position:static}}@media(max-width:520px){.shell{width:min(100% - 18px,1240px);margin-top:14px}.hero,.content,.sidebar{padding:20px}.stats{grid-template-columns:1fr}.choices{flex-wrap:wrap}.bottom{align-items:stretch;flex-direction:column}.bottom .btn{width:100%}.actions span{display:none}}
"""


def _login_html(nonce: str) -> str:
    page = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GLAP 十案例评审登录</title><style nonce="__NONCE__">__STYLE__</style></head><body><main class="shell login"><section class="card"><p class="kicker">GLAP · HUMAN EVALUATION</p><h1>十案例独立评审</h1><p class="sub">使用邀请中提供的专属账号。无需注册第三方平台。</p><form id="login"><div class="field"><label for="username">账号</label><input id="username" name="username" type="text" autocomplete="username" required maxlength="80"></div><div class="field"><label for="password">密码</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="128"></div><button class="btn" type="submit">登录</button><p id="message" class="message error hidden" role="alert"></p></form></section></main><script nonce="__NONCE__">const form=document.querySelector('#login'),message=document.querySelector('#message');form.addEventListener('submit',async e=>{e.preventDefault();message.classList.add('hidden');const response=await fetch('/api/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:form.username.value,password:form.password.value})});if(response.ok){location.replace('/');return}const data=await response.json().catch(()=>({}));message.textContent=data.error||'登录失败，请检查账号密码。';message.classList.remove('hidden')});</script></body></html>"""
    return page.replace("__NONCE__", nonce).replace("__STYLE__", TEN_STORY_STYLE)


def _review_html(nonce: str) -> str:
    cases_json = json.dumps(CASES, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    page = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GLAP 十案例独立评审</title><style nonce="__NONCE__">__STYLE__</style></head><body><header class="topbar"><div class="brand">GLAP<small>HUMAN EVALUATION</small></div><div class="actions"><span class="sub">10 案例 · 30 时点</span><button id="locale" class="ghost" type="button">EN</button><button id="logout" class="ghost" type="button">退出</button></div></header><main id="app" class="shell"></main><div id="toast" class="toast hidden"></div><script nonce="__NONCE__">
const CASES=__CASES_JSON__;
const DIMS=['evidence_grounding','risk_detection_and_proportionality','policy_compliance','actionability','authority_compliance'];
const Q={zh:{evidence_grounding:'哪个方案更符合你现在已经知道的情况？',risk_detection_and_proportionality:'哪个方案处理风险更合适：既不过度，也不拖延？',policy_compliance:'哪个方案更守规则和安全底线？',actionability:'哪个方案更容易让团队马上照着做？',authority_compliance:'哪个方案更清楚地把最终执行留给负责人批准？'},en:{evidence_grounding:'Which plan best fits what you know right now?',risk_detection_and_proportionality:'Which plan handles risk without overreacting or waiting too long?',policy_compliance:'Which plan better respects rules and safety limits?',actionability:'Which plan is easier for the team to carry out now?',authority_compliance:'Which plan leaves final execution to the responsible person?'}};
const T={zh:{all:'全部案例',title:'在信息逐步出现时，做出真正的运营判断',intro:'每个案例有三个按时间解锁的决策时点。每次提交都会保存到服务器并锁定当前判断，后续事实不会提前显示。',cases:'已完成案例',saved:'已保存判断',progress:'整体进度',start:'开始案例',continue:'继续评审',view:'查看结果',lens:'独特决策焦点',moments:'个时点',role:'你的角色',boundary:'只根据当前时点已经出现的信息判断。提交后锁定，后续事实不会提前显示。',time:'当前决策时间',situation:'你正在处理的情况',task:'你的任务',update:'刚刚收到的消息',unknown:'还不知道',conditions:'你手上的条件',inventory:'库存余量',fallback:'备用办法',fallbackYes:'有一个备选方向，但价格和时效还没确认',fallbackNo:'暂时没有现成的备用办法',protect:'不能出问题',decide:'你现在必须决定',routes:'两条不同的行动路线',shared:'两套系统此刻意见一致',plan:'方案',tradeoff:'你需要注意的代价',compare:'用五个简单问题比较',locked:'已锁定，只能查看',overall:'如果由你负责，最终会选哪条路线？',confidence:'你对这组判断有多大信心？',notes:'补充说明（选填）',prev:'上一个时点',commit:'提交并进入下一时点',finishCase:'提交并完成本案例',done:'返回十个案例',final:'检查并最终提交',finalTitle:'全部 10 个案例、30 个时点均已完成',finalText:'最终提交后整份评审将永久锁定。提交不会执行任何物流操作，也不代表生产就绪。',submit:'最终提交评审',independent:'这些判断由我独立完成。',conflict:'我没有会影响判断的利益冲突。',blind:'我不知道方案对应的系统身份。',tie:'相当',savedMsg:'当前判断已保存并锁定。'},en:{all:'All cases',title:'Make real operational judgments as evidence unfolds',intro:'Each case has three decision moments unlocked in time order. Every judgment is server-saved and locked; later facts are not shown early.',cases:'cases complete',saved:'judgments saved',progress:'overall progress',start:'Start case',continue:'Continue review',view:'View results',lens:'Distinct decision focus',moments:'moments',role:'Your role',boundary:'Judge only from information available now. Saving locks the judgment; later facts are not shown early.',time:'Current decision time',situation:'The situation you are handling',task:'Your task',update:'The latest update',unknown:'Still unknown',conditions:'What you have to work with',inventory:'Inventory cover',fallback:'Fallback',fallbackYes:'A fallback exists, but cost and timing are not confirmed',fallbackNo:'No ready fallback is available',protect:'What must be protected',decide:'You must decide now',routes:'Two different courses of action',shared:'Both systems agree at this moment',plan:'Plan',tradeoff:'What to watch',compare:'Compare with five simple questions',locked:'Locked and view-only',overall:'If you were responsible, which course would you choose?',confidence:'How confident are you in these judgments?',notes:'Notes (optional)',prev:'Previous moment',commit:'Commit and reveal next moment',finishCase:'Commit and complete case',done:'Return to all cases',final:'Review and submit',finalTitle:'All 10 cases and 30 moments are complete',finalText:'Final submission permanently locks the review. It executes no logistics action and does not establish production readiness.',submit:'Submit final review',independent:'I completed these judgments independently.',conflict:'I have no conflict that affects my judgment.',blind:'I do not know the systems behind Plan A or B.',tie:'Tie',savedMsg:'This judgment is saved and locked.'}};
let locale='zh',saved={},submitted=false,activeCase=null,activeStage=0,drafts={};const app=document.querySelector('#app');const tx=(o)=>o?.[locale]||'';const esc=(v)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function progress(c){let n=0;for(const s of c.stages){if(!saved[s.review_id])break;n++}return n}function totals(){const n=Object.keys(saved).length;return{moments:n,cases:CASES.filter(c=>progress(c)===3).length}}function toast(text,error=false){const el=document.querySelector('#toast');el.textContent=text;el.classList.toggle('error',error);el.classList.remove('hidden');setTimeout(()=>el.classList.add('hidden'),2600)}function choice(v){return v==='TIE'?T[locale].tie:`${T[locale].plan} ${v==='OPTION_A'?'A':'B'}`}function pct(n,d){return Math.round(n/d*100)}
function renderHub(){activeCase=null;const t=totals();app.innerHTML=`<section class="hero"><p class="kicker">FORMAL STORY EXPERIENCE · 10 DISTINCT DECISION STORIES</p><h1>${T[locale].title}</h1><p class="sub">${T[locale].intro}</p><p class="boundary"><strong>${locale==='zh'?'评审边界：':'Review boundary: '}</strong>${locale==='zh'?'这是国内入口的独立收集批次；使用相同冻结案例，但结果在完成治理校验前不会自动并入正式 Decision Quality 门槛。':'This mainland-access collection reuses the frozen stories but is not automatically included in the formal Decision Quality gate.'}</p><div class="stats"><div class="stat"><strong>${t.cases}/10</strong><span>${T[locale].cases}</span></div><div class="stat"><strong>${t.moments}/30</strong><span>${T[locale].saved}</span></div><div class="stat"><strong>${pct(t.moments,30)}%</strong><span>${T[locale].progress}</span></div></div></section><section class="grid">${CASES.map((c,i)=>{const p=progress(c);return`<article class="case-card"><div class="case-head"><span class="num">${String(i+1).padStart(2,'0')}</span><span class="mode">${esc(c.mode)}</span></div><div class="meta">${esc(tx(c.region))} · ${esc(tx(c.disruption))}</div><h2>${esc(tx(c.title))}</h2><div class="role">${esc(tx(c.role))}</div><div class="lens"><small>${T[locale].lens}</small><strong>${esc(tx(c.decision_lens))}</strong></div><div class="bar"><i style="width:${pct(p,3)}%"></i></div><div class="case-footer"><small>${p}/3 ${T[locale].moments}</small><button class="btn open" data-case="${esc(c.id)}">${p===3?T[locale].view:p?T[locale].continue:T[locale].start}</button></div></article>`}).join('')}</section><section class="hero" style="margin-top:22px"><div class="bottom"><p class="sub">${submitted?(locale==='zh'?'本轮评审已最终提交并永久锁定。':'This review has been finally submitted and locked.'):(t.moments===30?(locale==='zh'?'全部判断已保存，可以进行最终提交。':'All judgments are saved and ready for final submission.'):(locale==='zh'?'只有完成全部 30 个时点后才能最终提交。':'Final submission is available after all 30 moments.'))}</p><button id="final" class="btn" ${t.moments===30&&!submitted?'':'disabled'}>${T[locale].final}</button></div></section>`;document.querySelectorAll('.open').forEach(b=>b.onclick=()=>openCase(b.dataset.case));document.querySelector('#final').onclick=renderFinal}
function emptyAnswer(s){return{review_id:s.review_id,package_digest:s.package_digest,judgments:Object.fromEntries(DIMS.map(d=>[d,null])),preferred:null,confidence:null,notes:''}}function complete(a){return a&&DIMS.every(d=>a.judgments[d])&&a.preferred&&a.confidence}function openCase(id){activeCase=CASES.find(c=>c.id===id);activeStage=progress(activeCase)===3?0:progress(activeCase);renderCase()}
function renderCase(){const c=activeCase,s=c.stages[activeStage],p=progress(c),stored=saved[s.review_id],a=stored||drafts[s.review_id]||emptyAnswer(s);drafts[s.review_id]=a;const locked=!!stored;app.innerHTML=`<div class="layout"><aside class="sidebar"><button id="back" class="ghost">← ${T[locale].all}</button><p class="kicker">${esc(tx(c.region))} · ${esc(c.mode)}</p><h1>${esc(tx(c.title))}</h1><p class="role">${T[locale].role}<br><strong>${esc(tx(c.role))}</strong></p><div class="lens"><small>${T[locale].lens}</small><strong>${esc(tx(c.decision_lens))}</strong></div><div class="timeline">${c.stages.map((x,i)=>`<button class="moment ${i===activeStage?'active':''}" data-stage="${i}" ${i>p?'disabled':''}><b>${saved[x.review_id]?'✓':x.moment}</b><span>${i>p?(locale==='zh'?'未解锁':'Locked'):esc(tx(x.status))}</span></button>`).join('')}</div><p class="boundary">${T[locale].boundary}</p><div class="bar"><i style="width:${pct(p,3)}%"></i></div></aside><section class="content"><div class="decision-time"><div><small>${T[locale].time}</small><br><b>${new Date(s.cutoff_at).toLocaleDateString(locale==='zh'?'zh-CN':'en-GB')}</b></div><span class="mode">${esc(s.moment)} · ${esc(tx(s.status))}</span></div><section class="section"><div class="section-title"><span>01</span><h2>${T[locale].situation}</h2></div><p class="story">${esc(tx(c.story_intro))}</p><p><strong>${T[locale].task}：</strong>${esc(tx(c.goal))}</p><div class="facts"><div class="fact"><p class="kicker">${T[locale].update}</p><p>◆ ${esc(tx(s.update))}</p><p><strong>? ${T[locale].unknown}：</strong>${esc(tx(s.unknown))}</p></div><div class="fact warning"><p class="kicker">${T[locale].conditions}</p><p><strong>${T[locale].inventory}：</strong>${locale==='zh'?`约 ${s.inventory_cover_days} 天`:`About ${s.inventory_cover_days} days`}</p><p><strong>${T[locale].protect}：</strong>${esc(tx(c.stakes))}</p><p><strong>${T[locale].fallback}：</strong>${s.alternate_capacity_available?T[locale].fallbackYes:T[locale].fallbackNo}</p></div></div></section><div class="question"><small>${T[locale].decide}</small><h2>${esc(tx(s.question))}</h2></div><section class="section"><div class="section-title"><span>02</span><h2>${s.shared_plan?T[locale].shared:T[locale].routes}</h2></div><div class="options">${(s.shared_plan?[s.options[0]]:s.options).map(o=>`<article class="option"><header><span>${s.shared_plan?'=':o.id}</span><div><small>${s.shared_plan?(locale==='zh'?'共同方案':'Shared plan'):`${T[locale].plan} ${o.id}`}</small><h3>${esc(tx(o.title))}</h3></div></header><p>${esc(tx(o.body))}</p><p class="tradeoff"><strong>${T[locale].tradeoff}：</strong>${esc(tx(o.tradeoff))}</p></article>`).join('')}</div></section><section class="section"><div class="section-title"><span>03</span><h2>${s.shared_plan?T[locale].shared:T[locale].compare}</h2></div>${s.shared_plan?`<div class="shared"><p>${locale==='zh'?'这个时点两套系统意见一致。确认后五项比较与整体偏好都会记录为“两者相当”。':'Both systems agree at this moment. Confirmation records ties for all comparisons and overall preference.'}</p><button id="shared" class="choice ${a.preferred==='TIE'?'selected':''}" ${locked?'disabled':''}>${a.preferred==='TIE'?'✓ ':''}${locale==='zh'?'确认共同方案':'Confirm shared plan'}</button></div>`:DIMS.map((d,i)=>`<div class="review-row"><div><small>${String(i+1).padStart(2,'0')}</small><strong>${Q[locale][d]}</strong></div><div class="choices">${['OPTION_A','OPTION_B','TIE'].map(v=>`<button class="choice judgment ${a.judgments[d]===v?'selected':''}" data-dim="${d}" data-value="${v}" ${locked?'disabled':''}>${choice(v)}</button>`).join('')}</div></div>`).join('')}<div class="review-row"><div><small>06</small><strong>${T[locale].overall}</strong></div><div class="choices">${['OPTION_A','OPTION_B','TIE'].map(v=>`<button class="choice pref ${a.preferred===v?'selected':''}" data-value="${v}" ${locked?'disabled':''}>${choice(v)}</button>`).join('')}</div></div><div class="confidence"><div><small>07</small><strong>${T[locale].confidence}</strong></div><div class="choices">${[1,2,3,4,5].map(v=>`<button class="choice conf ${a.confidence===v?'selected':''}" data-value="${v}" ${locked?'disabled':''}>${v}</button>`).join('')}</div></div><div class="notes"><label><strong>${T[locale].notes}</strong><textarea id="notes" maxlength="2000" ${locked?'disabled':''}>${esc(a.notes)}</textarea></label></div></section><div class="bottom"><button id="previous" class="ghost" ${activeStage===0?'disabled':''}>← ${T[locale].prev}</button><p class="sub">${locked?T[locale].locked:(complete(a)?(locale==='zh'?'提交后锁定当前判断。':'Commit locks this judgment.'):(locale==='zh'?'请完成五项比较、整体偏好和信心。':'Complete all comparisons, preference, and confidence.'))}</p><button id="commit" class="btn" ${locked||!complete(a)?'disabled':''}>${activeStage===2?T[locale].finishCase:T[locale].commit} →</button></div></section></div>`;
document.querySelector('#back').onclick=renderHub;document.querySelectorAll('.moment:not(:disabled)').forEach(b=>b.onclick=()=>{activeStage=Number(b.dataset.stage);renderCase()});document.querySelector('#previous').onclick=()=>{activeStage=Math.max(0,activeStage-1);renderCase()};if(!locked){document.querySelectorAll('.judgment').forEach(b=>b.onclick=()=>{a.judgments[b.dataset.dim]=b.dataset.value;renderCase()});document.querySelectorAll('.pref').forEach(b=>b.onclick=()=>{a.preferred=b.dataset.value;renderCase()});document.querySelectorAll('.conf').forEach(b=>b.onclick=()=>{a.confidence=Number(b.dataset.value);renderCase()});const shared=document.querySelector('#shared');if(shared)shared.onclick=()=>{DIMS.forEach(d=>a.judgments[d]='TIE');a.preferred='TIE';renderCase()};document.querySelector('#notes').oninput=e=>a.notes=e.target.value;document.querySelector('#commit').onclick=()=>commit(a)}}
async function commit(a){const b=document.querySelector('#commit');b.disabled=true;b.textContent=locale==='zh'?'正在保存…':'Saving…';const response=await fetch('/api/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(a)});const data=await response.json().catch(()=>({}));if(!response.ok){toast(data.error||'保存失败',true);renderCase();return}saved[a.review_id]=data.answer;toast(T[locale].savedMsg);if(activeStage===2)renderHub();else{activeStage++;renderCase()}}
function renderFinal(){if(totals().moments!==30||submitted)return;app.innerHTML=`<section class="hero final"><button id="back" class="ghost">← ${T[locale].all}</button><p class="kicker">FINAL SUBMISSION</p><h1>${T[locale].finalTitle}</h1><p class="sub">${T[locale].finalText}</p><div class="attest"><label><input id="independent" type="checkbox">${T[locale].independent}</label><label><input id="conflict" type="checkbox">${T[locale].conflict}</label><label><input id="blind" type="checkbox">${T[locale].blind}</label></div><button id="submit" class="btn" disabled>${T[locale].submit}</button></section>`;document.querySelector('#back').onclick=renderHub;const checks=[...document.querySelectorAll('input[type=checkbox]')],submit=document.querySelector('#submit');checks.forEach(x=>x.onchange=()=>submit.disabled=!checks.every(c=>c.checked));submit.onclick=async()=>{if(!confirm(locale==='zh'?'最终提交后无法修改，确认提交吗？':'Final submission cannot be changed. Continue?'))return;submit.disabled=true;const response=await fetch('/api/submit',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({attestations:{independent:true,no_conflict:true,no_blind_key:true}})});const data=await response.json().catch(()=>({}));if(!response.ok){toast(data.error||'提交失败',true);submit.disabled=false;return}submitted=true;toast(locale==='zh'?'最终提交成功，评审已永久锁定。':'Final submission succeeded and is locked.');renderHub()}}
async function load(){const response=await fetch('/api/state');if(response.status===401){location.replace('/');return}const data=await response.json();saved=data.answers||{};submitted=data.status==='SUBMITTED_LOCKED';renderHub()}document.querySelector('#locale').onclick=()=>{locale=locale==='zh'?'en':'zh';document.querySelector('#locale').textContent=locale==='zh'?'EN':'中文';document.querySelector('#logout').textContent=locale==='zh'?'退出':'Sign out';activeCase?renderCase():renderHub()};document.querySelector('#logout').onclick=async()=>{await fetch('/api/logout',{method:'POST'});location.replace('/')};load();
</script></body></html>"""
    return (
        page.replace("__NONCE__", nonce)
        .replace("__STYLE__", TEN_STORY_STYLE)
        .replace("__CASES_JSON__", cases_json)
    )


def _html_page(content: str, nonce: str) -> dict[str, Any]:
    return _response(200, content, "text/html; charset=utf-8", nonce=nonce)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    now = int(time.time())
    method = _method(event)
    path = str(event.get("rawPath") or "/")

    try:
        config = _config()
    except RuntimeError:
        return _json_response(503, {"error": "Review service is not configured"})

    if method == "GET" and path == "/health":
        return _json_response(
            200,
            {
                "status": "ok",
                "build_id": BUILD_ID,
                "collection_id": COLLECTION_ID,
                "case_count": len(CASES),
                "moment_count": len(REVIEW_IDS),
                "bundle_digest": BUNDLE_DIGEST,
                "source_bundle_id": SOURCE_BUNDLE_ID,
            },
        )

    if method == "POST" and path == "/api/login":
        if not _same_origin(event):
            return _json_response(403, {"error": "Origin check failed"})
        try:
            body = _body_json(event)
        except ValueError as exc:
            return _json_response(400, {"error": str(exc)})
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        rate_key, rate = _rate_item(event, username)
        if _number(rate, "blocked_until") > now:
            return _json_response(429, {"error": "登录尝试过多，请 15 分钟后再试。"})
        account = _verify_credentials(username, password)
        if account is None:
            _record_login_failure(event, username, now)
            return _json_response(401, {"error": "账号或密码不正确。"})
        _ddb().delete_item(TableName=config.table_name, Key={"pk": {"S": rate_key}})
        return _json_response(
            200,
            {"status": "authenticated"},
            cookies=[_session_cookie(account.reviewer_id, now)],
        )

    if method == "POST" and path == "/api/logout":
        if not _same_origin(event):
            return _json_response(403, {"error": "Origin check failed"})
        return _json_response(200, {"status": "signed_out"}, cookies=[_clear_session_cookie()])

    if method == "GET" and path == "/api/export":
        if not _export_authorized(event):
            return _json_response(401, {"error": "Export authorization required"})
        return _json_response(
            200,
            {
                "schema_version": "glap-ten-story-review-export.v1",
                "collection_id": COLLECTION_ID,
                "bundle_digest": BUNDLE_DIGEST,
                "source_bundle_id": SOURCE_BUNDLE_ID,
                "source_bundle_digest": SOURCE_BUNDLE_DIGEST,
                "submissions": _export_submissions(),
            },
        )

    reviewer = _reviewer(event, now)

    if method == "GET" and path == "/":
        nonce = secrets.token_urlsafe(18)
        return _html_page(_review_html(nonce) if reviewer else _login_html(nonce), nonce)

    if method == "GET" and path == "/api/state":
        if reviewer is None:
            return _json_response(401, {"error": "Authentication required"})
        stored = _submission(reviewer.reviewer_id)
        answers = _review_answers(reviewer.reviewer_id)
        return _json_response(
            200,
            {
                "status": stored["status"] if stored else "NOT_STARTED",
                "submitted_at": stored.get("submitted_at") if stored else None,
                "collection_id": COLLECTION_ID,
                "bundle_digest": BUNDLE_DIGEST,
                "answers": answers,
            },
        )

    if method == "POST" and path == "/api/answer":
        if reviewer is None:
            return _json_response(401, {"error": "Authentication required"})
        if not _same_origin(event):
            return _json_response(403, {"error": "Origin check failed"})
        if _submission(reviewer.reviewer_id) is not None:
            return _json_response(409, {"error": "Final submission is already locked"})
        try:
            payload = _validate_answer(_body_json(event), reviewer.reviewer_id, now)
            _save_answer(payload)
        except ValueError as exc:
            return _json_response(400, {"error": str(exc)})
        except FileExistsError:
            return _json_response(409, {"error": "Answer is already locked"})
        return _json_response(201, {"status": "ANSWER_LOCKED", "answer": payload})

    if method == "POST" and path == "/api/submit":
        if reviewer is None:
            return _json_response(401, {"error": "Authentication required"})
        if not _same_origin(event):
            return _json_response(403, {"error": "Origin check failed"})
        try:
            payload = _validate_submission(_body_json(event), reviewer.reviewer_id, now)
            _save_submission(payload)
        except ValueError as exc:
            return _json_response(400, {"error": str(exc)})
        except FileExistsError:
            return _json_response(409, {"error": "Submission is already locked"})
        return _json_response(
            201,
            {"status": "SUBMITTED_LOCKED", "submitted_at": payload["submitted_at"]},
        )

    return _json_response(404, {"error": "Not found"})
