"""
Feishu app-level tokens: fetch + cache. Feishu's docs list both as ~2h
(7200s) lived; we refresh a bit early so a request never races an
about-to-expire token against the network round trip to use it.

Two distinct token types, not interchangeable:
- tenant_access_token: calling tenant-resource APIs (im/v1/messages).
- app_access_token: calling authen APIs (exchanging an OAuth `code` for
  a user's open_id during the QR bind flow). Fetched the same way for a
  self-built (non-ISV) app, but Feishu's own docs treat them as separate
  token types with separate endpoints — don't assume one covers the
  other's calls.
"""
import logging
from typing import Optional

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

TENANT_ACCESS_TOKEN_URL = (
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
)
APP_ACCESS_TOKEN_URL = (
    "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
)
# Feishu returns expire=7200 (seconds); refresh this many seconds early so
# a token fetched right before expiry doesn't die mid-request.
REFRESH_MARGIN_SECONDS = 120
REQUEST_TIMEOUT = 10
CACHE_KEY_PREFIX = "agentcore_notifier:feishu_token"


def _cache_key(kind: str, app_id: str) -> str:
    # Keyed by (kind, app_id), not a single global slot — a project could
    # plausibly configure more than one Feishu app (e.g. staging + prod
    # tenants), and the two token kinds must never collide in the cache.
    return f"{CACHE_KEY_PREFIX}:{kind}:{app_id}"


def _fetch_and_cache(
    kind: str, url: str, response_field: str, app_id: str, app_secret: str
) -> Optional[str]:
    try:
        response = requests.post(
            url,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"fetch {kind}: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"fetch {kind}: bad JSON response: {e}")
        return None

    if data.get("code") != 0:
        logger.error(
            f"fetch {kind}: Feishu error "
            f"code={data.get('code')} msg={data.get('msg')}"
        )
        return None

    token = data.get(response_field)
    expire = data.get("expire")
    if not token or not isinstance(expire, int):
        logger.error(f"fetch {kind}: malformed response body: {data}")
        return None

    ttl = max(1, expire - REFRESH_MARGIN_SECONDS)
    cache.set(_cache_key(kind, app_id), token, timeout=ttl)
    return token


def fetch_tenant_access_token(
    app_id: str, app_secret: str
) -> Optional[str]:
    """Always hits the network — callers wanting the cache should use
    get_tenant_access_token() instead. Returns None on failure."""
    return _fetch_and_cache(
        "tenant_access_token",
        TENANT_ACCESS_TOKEN_URL,
        "tenant_access_token",
        app_id,
        app_secret,
    )


def get_tenant_access_token(
    app_id: str, app_secret: str
) -> Optional[str]:
    """Cached tenant_access_token for app_id, fetching a fresh one on a
    cache miss. Use for im/v1/messages and other tenant-resource calls."""
    cached = cache.get(_cache_key("tenant_access_token", app_id))
    if cached:
        return cached
    return fetch_tenant_access_token(app_id, app_secret)


def invalidate_tenant_access_token(app_id: str) -> None:
    """Drop the cached tenant_access_token — call this when the API
    reports the token itself was rejected (e.g. auth error mid-send), so
    the next call fetches a fresh one instead of retrying with the same
    bad token."""
    cache.delete(_cache_key("tenant_access_token", app_id))


def fetch_app_access_token(app_id: str, app_secret: str) -> Optional[str]:
    """Always hits the network — see fetch_tenant_access_token."""
    return _fetch_and_cache(
        "app_access_token",
        APP_ACCESS_TOKEN_URL,
        "app_access_token",
        app_id,
        app_secret,
    )


def get_app_access_token(app_id: str, app_secret: str) -> Optional[str]:
    """Cached app_access_token for app_id. Use for authen/v1/* calls
    (the OAuth code-for-open_id exchange), not for messaging."""
    cached = cache.get(_cache_key("app_access_token", app_id))
    if cached:
        return cached
    return fetch_app_access_token(app_id, app_secret)


def invalidate_app_access_token(app_id: str) -> None:
    cache.delete(_cache_key("app_access_token", app_id))
