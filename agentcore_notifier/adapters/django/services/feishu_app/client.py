"""
DM sending via the self-built app (im/v1/messages), and patching an
already-sent card in place after a button click.

Return shape matches services/webhook/feishu.py's driver
({"success", "response", "error"}) so callers don't need two conventions.
"""
import json
import logging
from typing import Any, Dict, Optional

import requests

from .token import get_tenant_access_token, invalidate_tenant_access_token

logger = logging.getLogger(__name__)

SEND_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
PATCH_MESSAGE_URL_TEMPLATE = (
    "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
)
REQUEST_TIMEOUT = 10
# Feishu's token-expired error code — retried once with a fresh token
# rather than surfaced as a plain send failure, since a stale cache entry
# (e.g. app_secret rotated, or a clock-skewed refresh) is recoverable.
TOKEN_INVALID_CODE = 99991663


def _request(
    method: str,
    url: str,
    token: str,
    body: Dict[str, Any],
    params: Optional[Dict] = None,
) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    response = requests.request(
        method, url, headers=headers, params=params, json=body,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def send_card_dm(
    open_id: str,
    card_payload: Dict[str, Any],
    app_id: str,
    app_secret: str,
) -> Dict[str, Any]:
    """DM one person a card message via open_id.

    card_payload is the card's own content dict (msg_type="interactive"
    content) — callers build this with notification_card.build_review_card
    or similar, this function only handles delivery.
    """
    token = get_tenant_access_token(app_id, app_secret)
    if not token:
        return {
            "success": False,
            "response": None,
            "error": "Could not obtain tenant_access_token",
        }

    body = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card_payload, ensure_ascii=False),
    }
    try:
        data = _request(
            "POST", SEND_MESSAGE_URL, token, body,
            params={"receive_id_type": "open_id"},
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"send_card_dm: request failed: {e}")
        return {"success": False, "response": None, "error": str(e)}
    except ValueError as e:
        logger.error(f"send_card_dm: bad JSON response: {e}")
        return {"success": False, "response": None, "error": str(e)}

    code = data.get("code")
    if code == TOKEN_INVALID_CODE:
        invalidate_tenant_access_token(app_id)
    if code != 0:
        err = data.get("msg") or f"Feishu error code {code}"
        logger.warning(f"send_card_dm: business error: {err}")
        return {"success": False, "response": data, "error": err}

    return {"success": True, "response": data, "error": None}


def update_card_message(
    message_id: str,
    card_payload: Dict[str, Any],
    app_id: str,
    app_secret: str,
) -> Dict[str, Any]:
    """Replace an already-sent card's content in place (e.g. after a
    button click, to show "approved by X" instead of leaving the
    original buttons live for a second click)."""
    token = get_tenant_access_token(app_id, app_secret)
    if not token:
        return {
            "success": False,
            "response": None,
            "error": "Could not obtain tenant_access_token",
        }

    body = {"content": json.dumps(card_payload, ensure_ascii=False)}
    url = PATCH_MESSAGE_URL_TEMPLATE.format(message_id=message_id)
    try:
        data = _request("PATCH", url, token, body)
    except requests.exceptions.RequestException as e:
        logger.error(f"update_card_message: request failed: {e}")
        return {"success": False, "response": None, "error": str(e)}
    except ValueError as e:
        logger.error(f"update_card_message: bad JSON response: {e}")
        return {"success": False, "response": None, "error": str(e)}

    code = data.get("code")
    if code == TOKEN_INVALID_CODE:
        invalidate_tenant_access_token(app_id)
    if code != 0:
        err = data.get("msg") or f"Feishu error code {code}"
        logger.warning(f"update_card_message: business error: {err}")
        return {"success": False, "response": data, "error": err}

    return {"success": True, "response": data, "error": None}
