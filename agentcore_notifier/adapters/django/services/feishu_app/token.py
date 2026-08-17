"""
tenant_access_token: fetch + cache. Feishu's docs list it as ~2h (7200s)
lived; we refresh a bit early so a request never races an about-to-expire
token against the network round trip to use it.
"""
import logging
from typing import Optional

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

TENANT_ACCESS_TOKEN_URL = (
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
)
# Feishu returns expire=7200 (seconds); refresh this many seconds early so
# a token fetched right before expiry doesn't die mid-request.
REFRESH_MARGIN_SECONDS = 120
REQUEST_TIMEOUT = 10
CACHE_KEY_PREFIX = "agentcore_notifier:feishu_tenant_access_token"


def _cache_key(app_id: str) -> str:
    # Keyed by app_id, not a single global slot — a project could plausibly
    # configure more than one Feishu app (e.g. staging + prod tenants).
    return f"{CACHE_KEY_PREFIX}:{app_id}"


def fetch_tenant_access_token(
    app_id: str, app_secret: str
) -> Optional[str]:
    """Always hits the network — callers wanting the cache should use
    get_tenant_access_token() instead. Returns None on failure."""
    try:
        response = requests.post(
            TENANT_ACCESS_TOKEN_URL,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"fetch_tenant_access_token: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"fetch_tenant_access_token: bad JSON response: {e}")
        return None

    if data.get("code") != 0:
        logger.error(
            f"fetch_tenant_access_token: Feishu error "
            f"code={data.get('code')} msg={data.get('msg')}"
        )
        return None

    token = data.get("tenant_access_token")
    expire = data.get("expire")
    if not token or not isinstance(expire, int):
        logger.error(
            f"fetch_tenant_access_token: malformed response body: {data}"
        )
        return None

    ttl = max(1, expire - REFRESH_MARGIN_SECONDS)
    cache.set(_cache_key(app_id), token, timeout=ttl)
    return token


def get_tenant_access_token(
    app_id: str, app_secret: str
) -> Optional[str]:
    """Cached token for app_id, fetching a fresh one on a cache miss."""
    cached = cache.get(_cache_key(app_id))
    if cached:
        return cached
    return fetch_tenant_access_token(app_id, app_secret)


def invalidate_tenant_access_token(app_id: str) -> None:
    """Drop the cached token — call this when the API reports the token
    itself was rejected (e.g. auth error mid-send), so the next call
    fetches a fresh one instead of retrying with the same bad token."""
    cache.delete(_cache_key(app_id))
