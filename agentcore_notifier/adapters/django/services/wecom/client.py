"""
Bearer-token exchange and message sending against the official WeCom
AI Bot REST gateway (qyapi.weixin.qq.com/cli/...) — confirmed live:
this is plain request/response REST, no persistent connection needed,
unlike the WebSocket "长连接" mode WeCom's own docs describe for this
same bot type. Third-party integrations (e.g. the Hermes agent) chose
the WebSocket mode themselves; the official `wecom-cli` tool
(github.com/WecomTeam/wecom-cli) — which is what this module's request
shapes are read from — uses this REST gateway instead, and that's the
one we've verified actually delivers a message.

Return shape matches feishu_app/client.py's ({"success", "response",
"error"}) so callers don't need a second convention.
"""
import hashlib
import json
import logging
import secrets
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

AUTH_ENDPOINT = "https://qyapi.weixin.qq.com/cgi-bin/aibot/cli/get_cli_config"
GATEWAY_BASE_URL = "https://qyapi.weixin.qq.com/cli"
IDENTITY_WHOAMI_URL = f"{GATEWAY_BASE_URL}/identity/whoami"
SEND_AIBOT_MESSAGE_URL = f"{GATEWAY_BASE_URL}/message/aibot/send"
REQUEST_TIMEOUT = 15

# bind_source values from the official CLI's BindSource enum —
# Qrcode = 2. We only ever bind via QR, never "manual" (1).
BIND_SOURCE_QRCODE = 2

# No documented (or even observed) expiry on the bearer token this
# exchange returns, unlike Feishu's tenant_access_token (documented
# ~2h, cached — see feishu_app/token.py). Rather than guess a TTL and
# risk sending with a silently-expired cached token, fetch a fresh one
# on every send; it's one extra signed request, not a real cost here.
def fetch_bot_token(bot_id: str, secret: str) -> Optional[str]:
    """Exchange botid+secret for a bearer token via the signed
    request scheme wecom-cli's auth/bootstrap.rs uses:
    sha256_hex(secret + bot_id + time + nonce)."""
    t = int(time.time())
    nonce = f"newshub_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
    signature = hashlib.sha256(
        f"{secret}{bot_id}{t}{nonce}".encode()
    ).hexdigest()
    body = {
        "bot_id": bot_id,
        "time": t,
        "nonce": nonce,
        "signature": signature,
        "bind_source": BIND_SOURCE_QRCODE,
    }
    try:
        response = requests.post(
            AUTH_ENDPOINT, json=body, timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"fetch_bot_token: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"fetch_bot_token: bad JSON response: {e}")
        return None

    if data.get("errcode"):
        logger.warning(f"fetch_bot_token: business error: {data}")
        return None
    token = data.get("token")
    return token or None


def _gateway_post(
    url: str, token: str, inner_payload: Dict[str, Any]
) -> Dict[str, Any]:
    """The /cli gateway wraps every request body as
    {"payload": "<json-string>"} (wecom-cli's PayloadStringReq
    envelope) and every response as {"errcode", "errmsg",
    "results_json"} regardless of the specific method."""
    body = {"payload": json.dumps(inner_payload, ensure_ascii=False)}
    response = requests.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
    )
    return response.json()


def get_identity_context(token: str) -> Optional[str]:
    """Returns the raw extra_identity_context string, or None on any
    failure. Callers that need the userid out of it should go through
    device_registration._extract_userid rather than parsing here — this
    function only handles the network call."""
    try:
        data = _gateway_post(IDENTITY_WHOAMI_URL, token, {})
    except requests.exceptions.RequestException as e:
        logger.error(f"get_identity_context: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"get_identity_context: bad JSON response: {e}")
        return None

    if data.get("errcode"):
        logger.warning(f"get_identity_context: business error: {data}")
        return None
    try:
        results = json.loads(data.get("results_json") or "{}")
        result = results.get("result")
        result = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError) as e:
        logger.error(f"get_identity_context: malformed results_json: {e}")
        return None
    return (result or {}).get("extra_identity_context")


def send_aibot_markdown(
    chat_id: str, content: str, bot_id: str, secret: str,
) -> Dict[str, Any]:
    """DM one person (or group) markdown content. chat_id is the
    recipient's userid for a 1:1 DM — confirmed live: no pre-existing
    conversation with the bot is required."""
    token = fetch_bot_token(bot_id, secret)
    if not token:
        return {
            "success": False,
            "response": None,
            "error": "Could not obtain a bearer token",
        }

    inner_payload = {
        "chat_id": chat_id,
        "msg_type": "markdown",
        "markdown": {"content": content},
    }
    try:
        data = _gateway_post(SEND_AIBOT_MESSAGE_URL, token, inner_payload)
    except requests.exceptions.RequestException as e:
        logger.error(f"send_aibot_markdown: request failed: {e}")
        return {"success": False, "response": None, "error": str(e)}
    except ValueError as e:
        logger.error(f"send_aibot_markdown: bad JSON response: {e}")
        return {"success": False, "response": None, "error": str(e)}

    if data.get("errcode"):
        err = data.get("errmsg") or f"WeCom error code {data.get('errcode')}"
        logger.warning(f"send_aibot_markdown: business error: {err}")
        return {"success": False, "response": data, "error": err}

    return {"success": True, "response": data, "error": None}
