"""
Device-flow bot auto-registration — lets a user scan a QR code to
create (and bind their own identity to) a WeCom AI Bot, no admin
console visit and no manual botid/secret entry.

Same shape as feishu_app/device_registration.py's begin/poll pair, but
WeCom's protocol needs one more round trip after the scan succeeds:
the qr poll response only carries botid/secret, not the scanning
user's own userid. Getting that requires exchanging botid/secret for a
bearer token (see client.fetch_bot_token) and calling /identity/whoami,
whose only response field is a natural-language "identity context"
blob meant for LLM consumption, not a structured API contract — see
_extract_userid's docstring for why that's still the only way to get
it and what happens if WeCom ever changes its wording.

Two-step protocol (GET, not POST like Feishu's device flow):
  generate     -> {scode, auth_url}
  query_result -> pending | success -> {botid, secret}
"""
import logging
import re
from typing import Any, Dict, Optional

import requests

from .client import fetch_bot_token, get_identity_context

logger = logging.getLogger(__name__)

QR_GENERATE_URL = "https://work.weixin.qq.com/ai/qc/generate"
QR_QUERY_URL = "https://work.weixin.qq.com/ai/qc/query_result"
REQUEST_TIMEOUT = 15

# Matches the official wecom-cli tool's own source tag (confirmed live
# against the real endpoint) — not our product name, since this
# parameter is Tencent's own client-tracking tag on an undocumented
# endpoint, not a claim about who's calling on the user's behalf.
SOURCE = "wecom_cli_external"
# Linux, matching this service's actual runtime — wecom-cli picks
# 1/2/3 for macOS/Windows/Linux; only used for client-side stats as
# far as we've observed, doesn't gate the flow.
PLAT_CODE = 3

DEFAULT_POLL_INTERVAL_SECONDS = 3
DEFAULT_EXPIRE_IN_SECONDS = 300

# Pulls the real person's userid out of /identity/whoami's
# extra_identity_context text. Observed live shape:
#   授权真人用户身份：
#   名字：<display name>
#   ID：<userid>
# Non-greedy DOTALL match so it lands on the ID directly under
# "授权真人用户身份" (the real person), not the bot's own ID that
# appears earlier in the same blob under "机器人身份：".
_USER_ID_PATTERN = re.compile(
    r"授权真人用户身份[：:].*?ID[：:]\s*(\S+)", re.DOTALL
)


def begin_bot_registration() -> Optional[Dict[str, Any]]:
    """Starts a registration attempt. Returns the state the caller must
    hand back to poll_bot_registration() and show as a QR code, or None
    on any failure (network, malformed response) — callers should treat
    None as "could not start, try again", there's nothing to retry with.
    """
    try:
        response = requests.get(
            QR_GENERATE_URL,
            params={"source": SOURCE, "plat": PLAT_CODE},
            timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"begin_bot_registration: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"begin_bot_registration: bad JSON response: {e}")
        return None

    payload = data.get("data") or {}
    scode = payload.get("scode")
    auth_url = payload.get("auth_url")
    if not scode or not auth_url:
        logger.error(
            f"begin_bot_registration: malformed response body: {data}"
        )
        return None

    return {
        "scode": scode,
        "auth_url": auth_url,
        "interval": DEFAULT_POLL_INTERVAL_SECONDS,
        "expires_in": DEFAULT_EXPIRE_IN_SECONDS,
    }


def _extract_userid(identity_context: str) -> Optional[str]:
    match = _USER_ID_PATTERN.search(identity_context or "")
    return match.group(1) if match else None


def poll_bot_registration(scode: str) -> Dict[str, Any]:
    """One poll attempt. Always returns a dict with a "status" key —
    never raises, never returns None, so callers (an HTTP view doing
    one poll per request) don't need a separate error-handling path
    from the normal pending/success states.

    status == "success" is the only state carrying botid/secret/userid.
    Unlike Feishu's device flow, getting userid takes two more calls
    after the scan itself succeeds (token exchange + identity lookup) —
    both best-effort: any failure in that tail is reported as
    status="error" rather than a half-complete "success" with no
    userid, since a channel with no userid can never actually receive
    a message.
    """
    try:
        response = requests.get(
            QR_QUERY_URL, params={"scode": scode}, timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"poll_bot_registration: request failed: {e}")
        return {"status": "error", "error": str(e)}
    except ValueError as e:
        logger.error(f"poll_bot_registration: bad JSON response: {e}")
        return {"status": "error", "error": "bad JSON response"}

    payload = data.get("data") or {}
    status = payload.get("status")
    if status != "success":
        # Observed values: "init" (not yet scanned) and "success".
        # Anything else (including a missing/unrecognized value) is
        # treated as still-pending rather than a hard error — WeCom's
        # own vocabulary here isn't documented, so failing closed on
        # an unrecognized-but-plausibly-transient value would make the
        # UI dead-end on a QR code that's actually still valid.
        return {"status": "pending"}

    bot_info = payload.get("bot_info") or {}
    bot_id = bot_info.get("botid")
    secret = bot_info.get("secret")
    if not bot_id or not secret:
        logger.error(
            f"poll_bot_registration: success with no credentials: {data}"
        )
        return {"status": "error", "error": "missing credentials"}

    token = fetch_bot_token(bot_id, secret)
    if not token:
        logger.error(
            "poll_bot_registration: scan succeeded but could not "
            "exchange botid/secret for a bearer token"
        )
        return {"status": "error", "error": "token exchange failed"}

    identity_context = get_identity_context(token)
    userid = _extract_userid(identity_context) if identity_context else None
    if not userid:
        logger.error(
            "poll_bot_registration: scan succeeded but could not "
            f"extract userid from identity context: {identity_context!r}"
        )
        return {"status": "error", "error": "could not determine userid"}

    return {
        "status": "success",
        "bot_id": bot_id,
        "secret": secret,
        "userid": userid,
    }
