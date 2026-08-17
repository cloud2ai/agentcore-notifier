"""
Feishu event-subscription / card-callback verification.

One callback URL serves both the event subscription check ("url_verification"
challenge, event delivery) and interactive-card button clicks — Feishu's
unified v2.0 event schema routes card actions through the same mechanism as
any other event (event_type="card.action.trigger"), so one decrypt+verify
path covers both. See https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case

Two supported modes, both configured on the same NotificationChannel
(channel_type=feishu_app, user=None) row's config:
  - encrypt_key set: body arrives as {"encrypt": "<base64>"}, AES-256-CBC
    encrypted. Must decrypt before anything else is readable.
  - encrypt_key unset: body arrives as plain JSON. verification_token is
    still checked directly on it.

Security note: token comparison MUST be constant-time (hmac.compare_digest)
— a naive `==` leaks timing information an attacker can use to guess the
token character-by-character. This is the one piece of code in the whole
feature where "looks like it works" and "is actually safe" can silently
diverge, per #62: "不可省略，否则任何人 POST 一下就能批准文章。"
"""
import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional, Tuple

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """Raised for any callback body that fails decrypt/token verification.
    Callers must treat this as "reject the request", never as "treat as
    unauthenticated but still process"."""


def _derive_key(encrypt_key: str) -> bytes:
    """Feishu's own scheme: the AES key is SHA-256(encrypt_key), not the
    raw encrypt_key bytes."""
    return hashlib.sha256(encrypt_key.encode("utf-8")).digest()


def decrypt_event(encrypted_b64: str, encrypt_key: str) -> Dict[str, Any]:
    """Decrypt an {"encrypt": "..."} body's value into the event dict.

    Layout (Feishu's documented scheme): base64-decode, then the first 16
    bytes are the IV, the rest is AES-256-CBC ciphertext, PKCS7-padded.
    Raises VerificationError on any decrypt/parse failure — a malformed
    or wrong-key body must never surface a Python traceback that could
    hint at internals to whoever sent it.
    """
    try:
        raw = base64.b64decode(encrypted_b64)
        if len(raw) <= AES.block_size:
            raise ValueError("ciphertext too short to contain an IV")
        iv, ciphertext = raw[: AES.block_size], raw[AES.block_size :]
        cipher = AES.new(_derive_key(encrypt_key), AES.MODE_CBC, iv)
        plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return json.loads(plaintext.decode("utf-8"))
    except Exception as e:
        # Deliberately one broad except: every failure mode here (bad
        # base64, wrong key producing bad padding, non-JSON plaintext)
        # means the same thing to the caller — reject — so there is no
        # branch that needs a different response.
        raise VerificationError(f"Failed to decrypt event body: {e}") from e


def _extract_token(event: Dict[str, Any]) -> Optional[str]:
    """Token lives at different paths depending on schema:
    v2.0 events: header.token. url_verification challenges: top-level
    token. Check both rather than assuming the caller already knows
    which shape it is."""
    header = event.get("header")
    if isinstance(header, dict) and header.get("token"):
        return header["token"]
    return event.get("token")


def verify_and_parse(
    body: bytes, *, encrypt_key: str, verification_token: str
) -> Dict[str, Any]:
    """Single entry point for both the event-subscription and card-callback
    views: parse `body`, decrypt if needed, verify the token, return the
    event dict. Raises VerificationError if anything doesn't check out —
    callers must respond 4xx and do nothing else.
    """
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise VerificationError(f"Request body is not valid JSON: {e}") from e

    if not isinstance(parsed, dict):
        raise VerificationError("Request body is not a JSON object")

    if "encrypt" in parsed:
        if not encrypt_key:
            raise VerificationError(
                "Received an encrypted body but no encrypt_key is "
                "configured"
            )
        event = decrypt_event(parsed["encrypt"], encrypt_key)
    else:
        event = parsed

    token = _extract_token(event)
    if not token or not hmac.compare_digest(token, verification_token):
        raise VerificationError("Token mismatch")

    return event


def is_url_verification(event: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """(True, challenge) if `event` is Feishu's URL-verification challenge,
    else (False, None). The callback view must echo `challenge` back
    verbatim as {"challenge": challenge} and do nothing else."""
    if event.get("type") == "url_verification":
        return True, event.get("challenge")
    return False, None
