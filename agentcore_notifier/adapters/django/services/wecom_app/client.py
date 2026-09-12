"""
WeCom self-built app messaging: DM a specific member by userid.

Endpoint is message/send (the ordinary app-message API), not the AI
Bot's /cli gateway. The practical difference is not the URL but the
authorization model: this one never asks a human to re-authorize, so a
channel configured once keeps working.
"""
import logging
from typing import Any, Dict, Optional

import requests

from agentcore_notifier.adapters.django.services.wecom_app.token import (
    fetch_access_token,
    invalidate_access_token,
)

logger = logging.getLogger(__name__)

SEND_MESSAGE_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
REQUEST_TIMEOUT = 15
# WeCom's documented wildcard: "指定为@all，则向该企业应用的全部成员发送".
# "All members" means all members *of this app's visible scope*, which the
# admin chose when creating the app — not the whole company. That makes it
# a safe default for the common single-recipient setup, and it spares the
# user hunting their own UserID in 通讯录, which is easy to confuse with a
# phone number or display name.
ALL_MEMBERS = "@all"
# WeCom's "access_token expired/invalid" codes. Seeing one of these means
# the cached token is dead regardless of its TTL, so it is dropped and the
# send retried once -- otherwise every send until the TTL lapses would
# fail against a token we already know is bad.
TOKEN_INVALID_ERRCODES = {40014, 42001}


def _post(url: str, params: Dict[str, str], body: Dict[str, Any]) -> Optional[Dict]:
    try:
        response = requests.post(
            url, params=params, json=body, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"wecom app send: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"wecom app send: bad JSON response: {e}")
        return None


def send_app_markdown(
    touser: str,
    markdown: str,
    corp_id: str,
    corp_secret: str,
    agent_id: str,
) -> Dict[str, Any]:
    """Send a markdown app message.

    `touser` is a member's UserID, or falsy to fall back to ALL_MEMBERS —
    WeCom requires one of touser/toparty/totag to be set, and @all is the
    documented way to say "whoever this app is visible to". It is not
    required config: an app scoped to one person delivers to that person
    either way.

    Returns {"success": bool, "response": dict|None, "error": str|None}
    rather than raising: delivery is best-effort and must never fail the
    workflow that produced the message.
    """
    if not (corp_id and corp_secret and agent_id):
        return {
            "success": False, "response": None,
            "error": "incomplete wecom app config",
        }

    body = {
        "touser": (touser or "").strip() or ALL_MEMBERS,
        "msgtype": "markdown",
        "agentid": agent_id,
        "markdown": {"content": markdown},
    }

    for attempt in (1, 2):
        token = fetch_access_token(corp_id, corp_secret, agent_id)
        if not token:
            return {
                "success": False, "response": None,
                "error": "could not obtain access_token",
            }

        data = _post(SEND_MESSAGE_URL, {"access_token": token}, body)
        if data is None:
            return {
                "success": False, "response": None,
                "error": "request to WeCom failed",
            }

        errcode = data.get("errcode")
        if errcode in TOKEN_INVALID_ERRCODES and attempt == 1:
            logger.info(
                f"wecom app send: token rejected (errcode={errcode}), "
                f"refreshing once"
            )
            invalidate_access_token(corp_id, agent_id)
            continue

        if errcode:
            logger.warning(
                f"wecom app send: business error: errcode={errcode} "
                f"errmsg={data.get('errmsg')}"
            )
            return {
                "success": False, "response": data,
                "error": f"{data.get('errmsg')} (errcode={errcode})",
            }

        return {"success": True, "response": data, "error": None}

    return {
        "success": False, "response": None,
        "error": "access_token rejected twice",
    }
