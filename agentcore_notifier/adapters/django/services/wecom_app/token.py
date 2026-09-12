"""
WeCom self-built app access_token: fetch + cache.

The reason this module exists rather than reusing services/wecom/: that
one authenticates an *AI Bot*, whose message permission WeCom grants for
**7 days** and which a human must then re-authorize by hand from
工作台 → 智能机器人 (error 850003 "authorization expired" once it
lapses). A self-built app has no such grant — `corpsecret` is a static
credential, and the access_token it mints is refreshed programmatically,
exactly like Feishu's tenant_access_token. Same shape as
feishu_app/token.py for that reason.
"""
import logging
from typing import Optional

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

GETTOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
# WeCom returns expires_in=7200 (seconds). Refresh early so a token
# fetched just before expiry does not die mid-request.
REFRESH_MARGIN_SECONDS = 120
DEFAULT_EXPIRES_IN = 7200
REQUEST_TIMEOUT = 10
CACHE_KEY_PREFIX = "agentcore_notifier:wecom_app_token"


def _cache_key(corp_id: str, agent_id: str) -> str:
    # Keyed by (corp_id, agent_id): WeCom mints a *separate* token per
    # app, and a token minted for one agent is rejected by another. A
    # single global slot would hand app B the token of app A.
    return f"{CACHE_KEY_PREFIX}:{corp_id}:{agent_id}"


def fetch_access_token(
    corp_id: str, corp_secret: str, agent_id: str = ""
) -> Optional[str]:
    """Cached access_token for a self-built app.

    Returns None on any failure — callers treat notification delivery as
    best-effort and must not raise into the workflow that triggered it.
    """
    if not (corp_id and corp_secret):
        return None

    key = _cache_key(corp_id, agent_id)
    cached = cache.get(key)
    if cached:
        return cached

    try:
        response = requests.get(
            GETTOKEN_URL,
            params={"corpid": corp_id, "corpsecret": corp_secret},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"fetch wecom access_token: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"fetch wecom access_token: bad JSON response: {e}")
        return None

    if data.get("errcode"):
        # Logged with the code because WeCom's own error catalogue is how
        # a wrong corpid (40013) is told apart from a wrong secret
        # (40001) -- the two are indistinguishable from the message alone.
        logger.warning(
            f"fetch wecom access_token: business error: "
            f"errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
        )
        return None

    token = data.get("access_token")
    if not token:
        return None

    expires_in = data.get("expires_in") or DEFAULT_EXPIRES_IN
    ttl = max(int(expires_in) - REFRESH_MARGIN_SECONDS, 1)
    cache.set(key, token, ttl)
    return token


def invalidate_access_token(corp_id: str, agent_id: str = "") -> None:
    """Drop the cached token so the next send fetches a fresh one.

    WeCom may invalidate a token before its stated expiry, and the only
    signal is a 42001 on the send that follows. Without this the cache
    would keep serving the dead token until its TTL ran out.
    """
    cache.delete(_cache_key(corp_id, agent_id))
