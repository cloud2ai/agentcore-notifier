"""
API views for NotificationChannel: list, create, retrieve, update,
delete, validate.
"""
import base64
import io
import json
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

# NOTE(Ray): get_user_model at top for channel user; no circular deps.
import qrcode
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agentcore_notifier.adapters.django.models import (
    NotificationChannel,
    NotificationRecord,
)
from agentcore_notifier.adapters.django.services.feishu_app import (
    device_registration,
)
from agentcore_notifier.adapters.django.services.webhook import (
    get_default_registry,
)
from agentcore_notifier.adapters.django.services.webhook_service import (
    build_text_payload,
)
from agentcore_notifier.constants import Channel, Provider, Status

logger = logging.getLogger(__name__)

SOURCE_APP_VALIDATE = "agentcore_notifier"
SOURCE_TYPE_VALIDATE = "channel_validate"


def _get_validation_brand() -> str:
    return getattr(settings, "AGENTCORE_NOTIFIER_BRAND", "AGENTCORE NOTIFIER")


def _validate_webhook_config(
    config: Dict[str, Any],
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Send minimal test to webhook. Returns { success, error? }. Records.
    user_id: optional operator (e.g. request.user.pk) for the validate action.
    """
    url = (config.get("url") or "").strip()
    if not url:
        return {"success": False, "error": _("Webhook URL not configured")}
    provider_type = (config.get("provider_type") or "feishu").strip().lower()
    cfg = {
        "url": url,
        "provider_type": provider_type,
        "message_prefix": (
            (config.get("message_prefix") or "").strip() or None
        ),
        "sign_secret": (config.get("sign_secret") or "").strip() or None,
        "timeout": config.get("timeout"),
    }
    test_message = _("[%s] Channel validation test") % _get_validation_brand()
    test_payload = build_text_payload(provider_type, test_message)
    registry = get_default_registry()
    result = registry.send(provider_type, test_payload, cfg)
    record_status = Status.SUCCESS if result.get("success") else Status.FAILED
    try:
        rec = NotificationRecord.objects.create(
            source_app=SOURCE_APP_VALIDATE,
            source_type=SOURCE_TYPE_VALIDATE,
            source_id="",
            channel=Channel.WEBHOOK,
            channel_link_id=None,
            user_id=user_id,
            provider_type=provider_type,
            payload=test_payload,
            status=record_status,
            response=result.get("response"),
            error_message=result.get("error") or "",
            sent_at=(
                timezone.now()
                if record_status == Status.SUCCESS
                else None
            ),
        )
        logger.info(
            f"Channel validate record created uuid={rec.uuid} "
            f"status={record_status}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to record channel validate send: {e}",
            exc_info=True,
        )
    if result.get("success"):
        return {"success": True}
    return {"success": False, "error": result.get("error") or _("Send failed")}


def _validate_email_config(
    config: Dict[str, Any],
    test_recipient: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Test SMTP: connect (and optional STARTTLS/login). If test_recipient
    is given, send one test email; from_email must be in config.
    Returns { success, error? }. user_id: optional operator for the action.
    """
    host = (config.get("smtp_host") or "").strip()
    if not host:
        return {"success": False, "error": _("SMTP host not configured")}
    port = int(config.get("smtp_port") or 587)
    use_ssl = bool(config.get("use_ssl", False))
    use_tls = config.get("use_tls", True)
    to_send = (test_recipient or "").strip()
    if to_send:
        from_addr = (config.get("from_email") or "").strip()
        if not from_addr:
            return {
                "success": False,
                "error": _("From address required to send test"),
            }
    payload_record = {
        "subject": _("[%s] Email validation test") % _get_validation_brand(),
        "to": to_send if to_send else _("(connection only)"),
    }
    try:
        if use_ssl:
            smtp_class = smtplib.SMTP_SSL
        else:
            smtp_class = smtplib.SMTP
        with smtp_class(host, port, timeout=10) as smtp:
            if (not use_ssl) and use_tls:
                smtp.starttls()
            user = (config.get("smtp_user") or "").strip()
            password = (config.get("smtp_password") or "").strip()
            if user and password:
                smtp.login(user, password)
            if to_send:
                from_addr = (config.get("from_email") or "").strip()
                body_text = _("[%s] Email channel validation test") % (
                    _get_validation_brand()
                )
                msg = MIMEText(body_text, "plain", "utf-8")
                msg["Subject"] = _("[%s] Email validation test") % (
                    _get_validation_brand()
                )
                msg["From"] = from_addr
                msg["To"] = to_send
                smtp.sendmail(from_addr, [to_send], msg.as_string())
        try:
            rec = NotificationRecord.objects.create(
                source_app=SOURCE_APP_VALIDATE,
                source_type=SOURCE_TYPE_VALIDATE,
                source_id="",
                channel=Channel.EMAIL,
                channel_link_id=None,
                user_id=user_id,
                provider_type=Provider.EMAIL,
                payload=payload_record,
                status=Status.SUCCESS,
                response={},
                error_message="",
                sent_at=timezone.now(),
            )
            logger.info(
                f"Channel validate record created uuid={rec.uuid} "
                f"status=success"
            )
        except Exception as rec_exc:
            logger.warning(
                f"Failed to record email validate success: {rec_exc}",
                exc_info=True,
            )
        return {"success": True}
    except Exception as e:
        logger.exception(f"SMTP validation failed: {e}")
        err_msg = str(e)
        try:
            rec = NotificationRecord.objects.create(
                source_app=SOURCE_APP_VALIDATE,
                source_type=SOURCE_TYPE_VALIDATE,
                source_id="",
                channel=Channel.EMAIL,
                channel_link_id=None,
                user_id=user_id,
                provider_type=Provider.EMAIL,
                payload=payload_record,
                status=Status.FAILED,
                response=None,
                error_message=err_msg,
                sent_at=None,
            )
            logger.info(
                f"Channel validate record created uuid={rec.uuid} "
                f"status=failed"
            )
        except Exception as rec_exc:
            logger.warning(
                f"Failed to record email validate failure: {rec_exc}",
                exc_info=True,
            )
        err_lower = err_msg.lower()
        if "no route to host" in err_lower or "errno 113" in err_lower:
            base_msg = _(
                "Server cannot reach SMTP host (no route). "
                "Check deployment: firewall/security group outbound, "
                "or container network. Original: "
            )
            return {"success": False, "error": f"{base_msg}{err_msg}"}
        if "timed out" in err_lower or "timeout" in err_lower:
            base_msg = _(
                "SMTP connection timed out. Check server network and "
                "firewall/proxy. Original: "
            )
            return {"success": False, "error": f"{base_msg}{err_msg}"}
        return {"success": False, "error": err_msg}


def _config_for_api(config: dict, channel_type: str) -> dict:
    """
    Return a copy of config with sensitive fields removed so they are never
    sent to the client (list/retrieve/update response). Editing without
    re-entering password is handled in PUT by preserving existing value.
    """
    try:
        out = json.loads(json.dumps(config))
    except (TypeError, ValueError):
        out = {}
    if not isinstance(out, dict):
        return {}
    if channel_type == NotificationChannel.TYPE_EMAIL:
        out.pop("smtp_password", None)
    elif channel_type == NotificationChannel.TYPE_WEBHOOK:
        out.pop("sign_secret", None)
    elif channel_type == NotificationChannel.TYPE_FEISHU_APP:
        out.pop("app_secret", None)
        out.pop("encrypt_key", None)
        out.pop("verification_token", None)
    elif channel_type == NotificationChannel.TYPE_WECOM_BOT:
        out.pop("secret", None)
    return out


def _channel_to_dict(ch: NotificationChannel) -> dict:
    scope = "global"
    user_id = None
    user_display = None
    if ch.user_id and ch.user:
        scope = "user"
        user_id = ch.user_id
        user_display = getattr(ch.user, "username", None) or str(ch.user_id)
    raw_config = ch.config if isinstance(ch.config, dict) else {}
    config = _config_for_api(raw_config, str(ch.channel_type))
    created_at = ch.created_at
    updated_at = ch.updated_at
    return {
        "uuid": str(ch.uuid),
        "channel_type": str(ch.channel_type),
        "name": str(ch.name or ""),
        "is_active": bool(ch.is_active),
        "is_default": bool(ch.is_default),
        "config": config,
        "scope": scope,
        "user_id": user_id,
        "user_display": (
            str(user_display) if user_display is not None else None
        ),
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _read_required_channel_name(data: Dict[str, Any]) -> Optional[str]:
    """Return stripped channel name, or None when missing/blank."""
    name = (data.get("name") or "").strip()
    return name or None


class NotificationChannelListView(APIView):
    """GET list, POST create."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request):
        try:
            qs = (
                NotificationChannel.objects.select_related("user")
                .order_by("created_at")
            )
            channel_type = request.query_params.get("channel_type")
            if channel_type:
                qs = qs.filter(channel_type=channel_type)
            results = [_channel_to_dict(ch) for ch in qs]
            return Response({"total": len(results), "results": results})
        except Exception as e:
            logger.exception(f"NotificationChannelListView.get failed: {e}")
            return Response(
                {"detail": "Failed to list channels.", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request: Request):
        data = request.data
        channel_type = (data.get("channel_type") or "").strip().lower()
        if channel_type not in (
            NotificationChannel.TYPE_WEBHOOK,
            NotificationChannel.TYPE_EMAIL,
        ):
            return Response(
                {"detail": "channel_type must be webhook or email"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = _read_required_channel_name(data)
        if not name:
            return Response(
                {"detail": "name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        is_active = data.get("is_active", True)
        is_default = bool(data.get("is_default", False))
        config = data.get("config")
        if config is None:
            config = {}
        if not isinstance(config, dict):
            return Response(
                {"detail": "config must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if is_default:
            NotificationChannel.objects.filter(
                channel_type=channel_type,
            ).update(is_default=False)
        user_id = data.get("user_id")
        user = None
        if user_id is not None:
            try:
                user = get_user_model().objects.filter(pk=user_id).first()
            except (TypeError, ValueError):
                pass
        ch = NotificationChannel.objects.create(
            channel_type=channel_type,
            name=name,
            is_active=is_active,
            is_default=is_default,
            config=config,
            user=user,
        )
        return Response(_channel_to_dict(ch), status=status.HTTP_201_CREATED)


class NotificationChannelDetailView(APIView):
    """GET, PUT, DELETE by uuid."""

    permission_classes = [IsAdminUser]

    def _get_channel(self, uuid) -> Optional[NotificationChannel]:
        try:
            return NotificationChannel.objects.select_related("user").get(
                uuid=uuid
            )
        except (NotificationChannel.DoesNotExist, ValueError):
            return None

    def get(self, request: Request, uuid):
        ch = self._get_channel(uuid)
        if not ch:
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_channel_to_dict(ch))

    def put(self, request: Request, uuid):
        ch = self._get_channel(uuid)
        if not ch:
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = request.data
        name = (
            _read_required_channel_name(data)
            if "name" in data
            else (ch.name or "").strip()
        )
        if not name:
            return Response(
                {"detail": "name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "name" in data:
            ch.name = name
        if "is_active" in data:
            ch.is_active = bool(data["is_active"])
        if "is_default" in data:
            is_default = bool(data["is_default"])
            if is_default and not ch.is_default:
                NotificationChannel.objects.filter(
                    channel_type=ch.channel_type
                ).update(is_default=False)
            ch.is_default = is_default
        if "user_id" in data:
            user_id = data.get("user_id")
            if user_id is None:
                ch.user = None
            else:
                try:
                    ch.user = get_user_model().objects.filter(
                        pk=user_id,
                    ).first()
                except (TypeError, ValueError):
                    pass
        if "config" in data:
            cfg = data["config"]
            if isinstance(cfg, dict):
                # Preserve existing secrets when client sends empty (edit
                # without re-entering password/sign_secret).
                merged = None
                if ch.channel_type == NotificationChannel.TYPE_EMAIL and (
                    (cfg.get("smtp_password") or "").strip() == ""
                    and isinstance(ch.config, dict)
                    and (ch.config.get("smtp_password") or "").strip()
                ):
                    merged = dict(ch.config)
                    merged.update(cfg)
                    merged["smtp_password"] = (
                        ch.config.get("smtp_password") or ""
                    )
                elif ch.channel_type == NotificationChannel.TYPE_WEBHOOK and (
                    (cfg.get("sign_secret") or "").strip() == ""
                    and isinstance(ch.config, dict)
                    and (ch.config.get("sign_secret") or "").strip()
                ):
                    merged = dict(ch.config)
                    merged.update(cfg)
                    merged["sign_secret"] = (
                        ch.config.get("sign_secret") or ""
                    )
                elif (
                    ch.channel_type in (
                        NotificationChannel.TYPE_FEISHU_APP,
                        NotificationChannel.TYPE_WECOM_BOT,
                    )
                    and isinstance(ch.config, dict)
                ):
                    # Always merge, not just when a secret is blank —
                    # app_id/app_secret (feishu_app) and bot_id/secret/
                    # userid (wecom_bot) all arrive via their own
                    # device-flow scan (a completely separate write
                    # path from this PUT), and the secret is masked out
                    # of every API response either way, so a client
                    # editing e.g. just name/is_active here never
                    # legitimately has it to resend. A wholesale
                    # replace would silently null it out.
                    merged = dict(ch.config)
                    merged.update(cfg)
                if merged is not None:
                    ch.config = merged
                else:
                    ch.config = cfg
            else:
                return Response(
                    {"detail": "config must be an object"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        ch.save()
        return Response(_channel_to_dict(ch))

    def delete(self, request: Request, uuid):
        ch = self._get_channel(uuid)
        if not ch:
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ch.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChannelValidateView(APIView):
    """
    POST to validate channel config without saving.
    Body: { channel_type: "webhook"|"email", config: { ... } }.
    Webhook: sends test message to URL; email: tests SMTP connect.
    """

    permission_classes = [IsAdminUser]

    def post(self, request: Request):
        data = request.data
        channel_type = (data.get("channel_type") or "").strip().lower()
        if channel_type not in (
            NotificationChannel.TYPE_WEBHOOK,
            NotificationChannel.TYPE_EMAIL,
        ):
            return Response(
                {"detail": "channel_type must be webhook or email"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        config = data.get("config")
        if config is None:
            config = {}
        if not isinstance(config, dict):
            return Response(
                {"detail": "config must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        channel_uuid = (data.get("channel_uuid") or "").strip() or None
        if channel_uuid and channel_type in (
            NotificationChannel.TYPE_WEBHOOK,
            NotificationChannel.TYPE_EMAIL,
        ):
            try:
                ch = NotificationChannel.objects.get(uuid=channel_uuid)
                if (
                    ch.channel_type == channel_type
                    and isinstance(ch.config, dict)
                ):
                    merged = dict(ch.config)
                    merged.update(config)
                    if channel_type == NotificationChannel.TYPE_EMAIL and (
                        (merged.get("smtp_password") or "").strip() == ""
                    ):
                        merged["smtp_password"] = (
                            ch.config.get("smtp_password") or ""
                        )
                    elif channel_type == NotificationChannel.TYPE_WEBHOOK and (
                        (merged.get("sign_secret") or "").strip() == ""
                    ):
                        merged["sign_secret"] = (
                            ch.config.get("sign_secret") or ""
                        )
                    config = merged
            except (NotificationChannel.DoesNotExist, ValueError):
                pass
        if getattr(request.user, "is_authenticated", True):
            user_id = getattr(request.user, "pk", None)
        else:
            user_id = None
        if channel_type == NotificationChannel.TYPE_WEBHOOK:
            out = _validate_webhook_config(config, user_id=user_id)
        else:
            test_recipient = (data.get("test_recipient") or "").strip() or None
            out = _validate_email_config(
                config, test_recipient=test_recipient, user_id=user_id
            )
        if out.get("success"):
            return Response({"success": True})
        return Response(
            {
                "success": False,
                "error": out.get("error") or _("Validation failed"),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


def _qr_png_base64(data: str) -> str:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _upsert_global_feishu_app_channel(
    client_id: str, client_secret: str, tenant_brand: Optional[str]
) -> NotificationChannel:
    """The device-flow success path writes here — this IS the
    replacement for an admin hand-filling app_id/app_secret. Merges
    into any existing config (rather than overwriting it wholesale) so
    a re-scan doesn't wipe out encrypt_key/verification_token set up
    separately for the event-callback endpoint."""
    name = (
        f"Feishu ({tenant_brand})" if tenant_brand else "Feishu"
    )
    existing = NotificationChannel.objects.filter(
        channel_type=NotificationChannel.TYPE_FEISHU_APP,
        user__isnull=True,
    ).first()
    config = (
        dict(existing.config)
        if existing and isinstance(existing.config, dict)
        else {}
    )
    config["app_id"] = client_id
    config["app_secret"] = client_secret
    if existing:
        existing.name = name
        existing.is_active = True
        existing.config = config
        existing.save(
            update_fields=["name", "is_active", "config", "updated_at"]
        )
        return existing
    return NotificationChannel.objects.create(
        channel_type=NotificationChannel.TYPE_FEISHU_APP,
        user=None,
        name=name,
        is_active=True,
        config=config,
    )


class FeishuAppRegistrationStartView(APIView):
    """
    POST -> begin a device-flow Feishu app registration and return a QR
    code to scan. Scanning walks the admin through creating (or
    picking) a self-built app on their own Feishu tenant; completing it
    is what FeishuAppRegistrationPollView picks up.

    This is the "don't require Django admin" setup path for the global
    feishu_app channel — see services/feishu_app/device_registration.py
    for the underlying protocol.
    """

    permission_classes = [IsAdminUser]

    def post(self, request: Request):
        state = device_registration.begin_app_registration()
        if not state:
            return Response(
                {"detail": "Failed to start Feishu app registration."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "device_code": state["device_code"],
                "verification_uri_complete": (
                    state["verification_uri_complete"]
                ),
                "qr_code_base64": _qr_png_base64(
                    state["verification_uri_complete"]
                ),
                "interval": state["interval"],
                "expires_in": state["expires_in"],
            }
        )


class FeishuAppRegistrationPollView(APIView):
    """
    GET ?device_code=... -> one poll attempt against Feishu. The
    frontend calls this on a timer (same pattern as the PR2 personal
    bind modal) until status is a terminal one.

    On status == "success", upserts the global (user=None) feishu_app
    NotificationChannel with the newly-issued client_id/client_secret
    and returns it — that upsert is the whole mechanism, there's
    nothing left for an admin to type in afterward.
    """

    permission_classes = [IsAdminUser]

    def get(self, request: Request):
        device_code = request.query_params.get("device_code")
        if not device_code:
            return Response(
                {"detail": "device_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = device_registration.poll_app_registration(device_code)
        if result.get("status") != "success":
            return Response(result)

        channel = _upsert_global_feishu_app_channel(
            result["client_id"],
            result["client_secret"],
            result.get("tenant_brand"),
        )
        return Response(
            {"status": "success", "channel": _channel_to_dict(channel)}
        )
