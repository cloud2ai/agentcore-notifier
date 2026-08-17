"""
QR/OAuth identity binding — exchanging an authorization `code` (from
Feishu's scan-to-authorize redirect) for the scanning user's open_id.

State handling (who initiated the bind, expiry, CSRF) is deliberately NOT
here — that ties to the consuming project's own session/User model, which
this submodule has no opinion about. This module only knows how to talk
to Feishu.
"""
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from .token import get_app_access_token

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://open.feishu.cn/open-apis/authen/v1/index"
ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v1/access_token"
REQUEST_TIMEOUT = 10


def build_authorize_url(app_id: str, redirect_uri: str, state: str) -> str:
    """The URL a user scans (rendered as a QR code by the caller) to
    authorize this app and get redirected back with a `code`."""
    query = urlencode(
        {"app_id": app_id, "redirect_uri": redirect_uri, "state": state}
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code_for_identity(
    code: str, app_id: str, app_secret: str
) -> Optional[Dict[str, Any]]:
    """Exchange an authorization code for the scanning user's identity.

    Returns {"open_id", "union_id", "tenant_key", "name"} on success,
    None on any failure (network, bad code, Feishu-side error) — callers
    must treat None as "binding failed, ask the user to scan again", not
    retry with the same code (authorization codes are single-use).
    """
    app_access_token = get_app_access_token(app_id, app_secret)
    if not app_access_token:
        logger.error(
            "exchange_code_for_identity: could not obtain app_access_token"
        )
        return None

    try:
        response = requests.post(
            ACCESS_TOKEN_URL,
            headers={
                "Authorization": f"Bearer {app_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"grant_type": "authorization_code", "code": code},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"exchange_code_for_identity: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"exchange_code_for_identity: bad JSON response: {e}")
        return None

    if data.get("code") != 0:
        logger.error(
            f"exchange_code_for_identity: Feishu error "
            f"code={data.get('code')} msg={data.get('msg')}"
        )
        return None

    payload = data.get("data")
    if not isinstance(payload, dict) or not payload.get("open_id"):
        logger.error(
            f"exchange_code_for_identity: malformed response body: {data}"
        )
        return None

    return {
        "open_id": payload.get("open_id"),
        "union_id": payload.get("union_id"),
        "tenant_key": payload.get("tenant_key"),
        "name": payload.get("name"),
    }
