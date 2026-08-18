"""
Device-flow app auto-registration — lets an admin scan a QR code to
create (or pick an existing) self-built Feishu app instead of hand-
creating one in Feishu's console and pasting app_id/app_secret in.

This is the OAuth 2.0 Device Authorization Grant applied to "register an
app" rather than "log a user in". Verified against the real, public
`accounts.feishu.cn` endpoint (not documented, but not private either —
it's the same one https://github.com/larksuite/cli uses for `lark
config init --new`), confirmed end to end: a freshly-registered app can
send a real DM immediately and already has `card.action.trigger` in its
event subscriptions.

Two-step protocol, same shape both times (POST form body, `action`
switches behavior):
  begin -> {device_code, user_code, verification_uri_complete, ...}
  poll  -> pending | slow_down | denied | expired | {client_id, ...}
"""
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

REGISTRATION_URL = "https://accounts.feishu.cn/oauth/v1/app/registration"
REQUEST_TIMEOUT = 15

# The only archetype lark-cli's own source ever sends. There's no public
# doc enumerating alternatives, so this is deliberately not a parameter.
ARCHETYPE = "PersonalAgent"
AUTH_METHOD = "client_secret"
REQUEST_USER_INFO = "open_id tenant_brand"

DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_EXPIRE_IN_SECONDS = 600

# Feishu's poll-response `error` values, normalized into our own status
# vocabulary so callers never branch on Feishu's raw strings directly.
_STATUS_BY_ERROR = {
    "": "success",
    "authorization_pending": "pending",
    "slow_down": "slow_down",
    "access_denied": "denied",
    "expired_token": "expired",
    "invalid_grant": "expired",
}


def begin_app_registration() -> Optional[Dict[str, Any]]:
    """Starts a registration attempt. Returns the state the caller must
    hand back to poll_app_registration() and show as a QR code, or None
    on any failure (network, malformed response) — callers should treat
    None as "could not start, try again", there's nothing to retry with.
    """
    try:
        response = requests.post(
            REGISTRATION_URL,
            data={
                "action": "begin",
                "archetype": ARCHETYPE,
                "auth_method": AUTH_METHOD,
                "request_user_info": REQUEST_USER_INFO,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },
            timeout=REQUEST_TIMEOUT,
        )
        # Deliberately no raise_for_status() — confirmed live that this
        # endpoint uses HTTP 400 for expected, non-error states (see
        # poll_app_registration below); reading the body regardless of
        # status code is the only way that's compatible with both.
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"begin_app_registration: request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"begin_app_registration: bad JSON response: {e}")
        return None

    device_code = data.get("device_code")
    verification_uri_complete = data.get("verification_uri_complete")
    if not device_code or not verification_uri_complete:
        logger.error(
            f"begin_app_registration: malformed response body: {data}"
        )
        return None

    return {
        "device_code": device_code,
        "user_code": data.get("user_code"),
        "verification_uri_complete": verification_uri_complete,
        "interval": int(
            data.get("interval") or DEFAULT_POLL_INTERVAL_SECONDS
        ),
        "expires_in": int(
            data.get("expire_in")
            or data.get("expires_in")
            or DEFAULT_EXPIRE_IN_SECONDS
        ),
    }


def poll_app_registration(device_code: str) -> Dict[str, Any]:
    """One poll attempt. Always returns a dict with a "status" key —
    never raises, never returns None, so callers (an HTTP view doing one
    poll per request) don't need a separate error-handling path from the
    normal pending/slow_down/denied/expired states.

    status == "success" is the only state carrying client_id/
    client_secret/open_id/tenant_brand.
    """
    try:
        response = requests.post(
            REGISTRATION_URL,
            data={"action": "poll", "device_code": device_code},
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },
            timeout=REQUEST_TIMEOUT,
        )
        # No raise_for_status() — confirmed live against the real API:
        # this endpoint responds HTTP 400 for authorization_pending (a
        # normal "not yet" state, polled repeatedly by design), not
        # just for genuine errors. A 400 here is not an HTTP failure,
        # the body's "error" field is what actually carries meaning —
        # see _STATUS_BY_ERROR below.
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"poll_app_registration: request failed: {e}")
        return {"status": "error", "error": str(e)}
    except ValueError as e:
        logger.error(f"poll_app_registration: bad JSON response: {e}")
        return {"status": "error", "error": "bad JSON response"}

    error = data.get("error", "")
    status = _STATUS_BY_ERROR.get(error)
    if status is None:
        logger.error(
            f"poll_app_registration: unrecognized error={error!r} "
            f"body={data}"
        )
        return {
            "status": "error",
            "error": error,
            "error_description": data.get("error_description"),
        }

    if status != "success":
        return {"status": status}

    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    if not client_id or not client_secret:
        logger.error(
            f"poll_app_registration: success with no credentials: {data}"
        )
        return {"status": "error", "error": "missing credentials"}

    user_info = data.get("user_info") or {}
    return {
        "status": "success",
        "client_id": client_id,
        "client_secret": client_secret,
        "open_id": user_info.get("open_id"),
        "tenant_brand": user_info.get("tenant_brand"),
    }
