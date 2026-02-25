"""
Webhook service for sending notifications.
Reads config from NotificationChannel (webhook type); dispatches by
provider_type via WebhookDriverRegistry.
"""
import logging
from typing import Any, Dict, Optional

from django.utils import timezone

from agentcore_notifier.adapters.django.models import (
    NotificationChannel,
    NotificationRecord,
)
from agentcore_notifier.adapters.django.services.webhook import (
    get_default_registry,
)
from agentcore_notifier.constants import (
    Channel,
    DEFAULT_PROVIDER_TYPE,
    DEFAULT_SOURCE_APP,
    Status,
)

logger = logging.getLogger(__name__)


def get_default_webhook_channel():
    """
    Get webhook channel for sending: active channels, smallest ordering then
    earliest created_at. No "default" flag; ordering determines which.
    Returns (channel, config_dict) or (None, None).
    """
    qs = NotificationChannel.objects.filter(
        channel_type=NotificationChannel.TYPE_WEBHOOK,
        is_active=True,
    ).order_by("ordering", "created_at")
    channel = qs.first()
    if not channel or not channel.config:
        return None, None
    cfg = channel.config
    url = (cfg.get("url") or "").strip()
    if not url:
        return None, None
    config_dict = {
        "is_active": True,
        "provider": cfg.get("provider_type") or DEFAULT_PROVIDER_TYPE,
        "url": url,
        "headers": cfg.get("headers") or {},
        "message_prefix": (
            (cfg.get("message_prefix") or "").strip() or None
        ),
        "sign_secret": (cfg.get("sign_secret") or "").strip() or None,
        "timeout": cfg.get("timeout"),
    }
    return channel, config_dict


def _get_webhook_config() -> Optional[Dict[str, Any]]:
    """Get active webhook config dict (for backward compat)."""
    _, config = get_default_webhook_channel()
    return config


class WebhookService:
    """
    Service for webhook notifications.
    Config from NotificationChannel (webhook); send via driver registry.
    """

    def __init__(self, registry=None):
        self._webhook_config: Optional[Dict[str, Any]] = None
        self._registry = registry or get_default_registry()

    def get_webhook_config(self) -> Optional[Dict[str, Any]]:
        """Get webhook configuration from NotificationChannel table."""
        if self._webhook_config is None:
            self._webhook_config = _get_webhook_config()
        return self._webhook_config

    def get_webhook_channel_and_config(self):
        """Return (channel, config_dict) for active webhook or (None, None)."""
        return get_default_webhook_channel()

    def _get_config(self) -> Optional[Dict[str, Any]]:
        config = self.get_webhook_config()
        if not config:
            logger.warning(
                "WebhookService: no active webhook channel in "
                "NotificationChannel table"
            )
        return config

    def _record_notification(
        self,
        provider_type: str,
        payload: Dict[str, Any],
        result: Dict[str, Any],
        source_app: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        user: Optional[Any] = None,
        channel_id: Optional[int] = None,
    ) -> Optional[NotificationRecord]:
        """Record notification send result."""
        config = self._get_config()
        status = Status.SUCCESS if result.get("success") else Status.FAILED
        metadata = {}
        if config:
            metadata = {
                "url": config.get("url", ""),
                "headers": config.get("headers", {}),
            }
        try:
            record = NotificationRecord.objects.create(
                provider_type=provider_type,
                channel=Channel.WEBHOOK,
                channel_link_id=channel_id,
                user=user,
                source_app=source_app or DEFAULT_SOURCE_APP,
                source_type=source_type or "",
                source_id=source_id or "",
                payload=payload,
                status=status,
                response=result.get("response"),
                error_message=result.get("error") or "",
                metadata=metadata,
                sent_at=timezone.now() if status == Status.SUCCESS else None,
            )
            return record
        except Exception as e:
            logger.warning(
                f"WebhookService._record_notification: failed: {e}"
            )
            return None

    def send(
        self,
        payload: Dict[str, Any],
        provider_type: Optional[str] = None,
        source_app: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        user: Optional[Any] = None,
        channel_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Send notification by provider type via driver registry."""
        config = self._get_config()
        if not config:
            result = {
                "success": False,
                "response": None,
                "error": "Webhook config not found or not active",
            }
            if source_app:
                self._record_notification(
                    DEFAULT_PROVIDER_TYPE,
                    payload,
                    result,
                    source_app,
                    source_type,
                    source_id,
                    user,
                    channel_id=channel_id,
                )
            return result

        if provider_type is None:
            provider_type = config.get("provider", DEFAULT_PROVIDER_TYPE)

        result = self._registry.send(provider_type, payload, config)

        if source_app:
            record = self._record_notification(
                provider_type,
                payload,
                result,
                source_app,
                source_type,
                source_id,
                user,
                channel_id=channel_id,
            )
            if record:
                result["record_uuid"] = str(record.uuid)

        return result
