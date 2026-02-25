"""
API views for NotificationChannel: list, create, retrieve, update,
delete, validate.
"""
import json
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

# NOTE(Ray): get_user_model at top for channel user; no circular deps.
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
from agentcore_notifier.adapters.django.services.webhook import (
    get_default_registry,
)
from agentcore_notifier.constants import Channel, Provider, Status

logger = logging.getLogger(__name__)

SOURCE_APP_VALIDATE = "agentcore_notifier"
SOURCE_TYPE_VALIDATE = "channel_validate"


def _validate_webhook_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Send minimal test to webhook. Returns { success, error? }. Records."""
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
    test_payload = {
        "msg_type": "text",
        "content": {"text": _("[DevMind] Channel validation test")},
    }
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
            user_id=None,
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
) -> Dict[str, Any]:
    """
    Test SMTP: connect (and optional STARTTLS/login). If test_recipient
    is given, send one test email; from_email must be in config.
    Returns { success, error? }.
    """
    host = (config.get("smtp_host") or "").strip()
    if not host:
        return {"success": False, "error": _("SMTP host not configured")}
    port = int(config.get("smtp_port") or 587)
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
        "subject": _("[DevMind] Email validation test"),
        "to": to_send if to_send else _("(connection only)"),
    }
    try:
        smtp_class = smtplib.SMTP
        with smtp_class(host, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            user = (config.get("smtp_user") or "").strip()
            password = (config.get("smtp_password") or "").strip()
            if user and password:
                smtp.login(user, password)
            if to_send:
                from_addr = (config.get("from_email") or "").strip()
                body_text = _("[DevMind] Email channel validation test")
                msg = MIMEText(body_text, "plain", "utf-8")
                msg["Subject"] = _("[DevMind] Email validation test")
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
                user_id=None,
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
                user_id=None,
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
                "Server cannot reach SMTP host (no route). Check deployment: "
                "firewall/security group outbound rules, or container network. "
                "Original: "
            )
            return {"success": False, "error": f"{base_msg}{err_msg}"}
        if "timed out" in err_lower or "timeout" in err_lower:
            base_msg = _(
                "SMTP connection timed out. Check server network and "
                "firewall/proxy. Original: "
            )
            return {"success": False, "error": f"{base_msg}{err_msg}"}
        return {"success": False, "error": err_msg}


def _channel_to_dict(ch: NotificationChannel) -> dict:
    scope = "global"
    user_id = None
    user_display = None
    if ch.user_id and ch.user:
        scope = "user"
        user_id = ch.user_id
        user_display = getattr(ch.user, "username", None) or str(ch.user_id)
    config = ch.config if isinstance(ch.config, dict) else {}
    try:
        config = json.loads(json.dumps(config))
    except (TypeError, ValueError):
        config = {}
    created_at = ch.created_at
    updated_at = ch.updated_at
    return {
        "uuid": str(ch.uuid),
        "channel_type": str(ch.channel_type),
        "name": str(ch.name or ""),
        "is_active": bool(ch.is_active),
        "is_default": bool(ch.is_default),
        "ordering": int(ch.ordering),
        "config": config,
        "scope": scope,
        "user_id": user_id,
        "user_display": (
            str(user_display) if user_display is not None else None
        ),
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


class NotificationChannelListView(APIView):
    """GET list, POST create."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request):
        try:
            qs = NotificationChannel.objects.select_related("user").all()
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
        name = (data.get("name") or "").strip()
        is_active = data.get("is_active", True)
        is_default = bool(data.get("is_default", False))
        ordering = (
            int(data.get("ordering", 0))
            if data.get("ordering") is not None
            else 0
        )
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
            ordering=ordering,
            config=config,
            user=user,
        )
        return Response(_channel_to_dict(ch), status=status.HTTP_201_CREATED)


class NotificationChannelDetailView(APIView):
    """GET, PUT, DELETE by uuid."""

    permission_classes = [IsAdminUser]

    def _get_channel(self, uuid) -> Optional[NotificationChannel]:
        try:
            return (
            NotificationChannel.objects.select_related("user").get(uuid=uuid)
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
        if "name" in data:
            ch.name = (data.get("name") or "").strip()
        if "is_active" in data:
            ch.is_active = bool(data["is_active"])
        if "is_default" in data:
            is_default = bool(data["is_default"])
            if is_default and not ch.is_default:
                NotificationChannel.objects.filter(
                    channel_type=ch.channel_type
                ).update(is_default=False)
            ch.is_default = is_default
        if "ordering" in data:
            ch.ordering = (
                int(data["ordering"]) if data["ordering"] is not None else 0
            )
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
        if channel_type == NotificationChannel.TYPE_WEBHOOK:
            out = _validate_webhook_config(config)
        else:
            test_recipient = (data.get("test_recipient") or "").strip() or None
            out = _validate_email_config(
                config, test_recipient=test_recipient
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
