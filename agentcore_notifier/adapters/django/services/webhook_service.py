"""
Webhook service for sending notifications.
Reads config from NotificationChannel (webhook type); dispatches by
provider_type via WebhookDriverRegistry.
"""
import logging
from typing import Any, Dict, Optional, Tuple, Union
from uuid import UUID

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


def build_webhook_config_from_dict(
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Build internal webhook config dict from a raw config dict (e.g. from
    application layer or NotificationChannel.config). Callers can pass
    channel config at call time for maximum flexibility.
    Returns None if url is missing or empty.
    """
    if not cfg:
        return None
    url = (cfg.get("url") or "").strip()
    if not url:
        return None
    return {
        "is_active": True,
        "provider": (
            cfg.get("provider_type")
            or cfg.get("provider")
            or DEFAULT_PROVIDER_TYPE
        ),
        "url": url,
        "headers": cfg.get("headers") or {},
        "message_prefix": (
            (cfg.get("message_prefix") or "").strip() or None
        ),
        "sign_secret": (cfg.get("sign_secret") or "").strip() or None,
        "timeout": cfg.get("timeout"),
    }


def get_default_webhook_channel():
    """
    Get webhook channel for sending: first active channel ordered by
    created_at (earliest first). Name/ordering changes do not affect default.
    Returns (channel, config) or (None, None).
    """
    qs = (
        NotificationChannel.objects.filter(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
        )
        .order_by("created_at")
    )
    channel = qs.first()
    if not channel or not channel.config:
        return None, None
    config = build_webhook_config_from_dict(channel.config)
    if not config:
        return None, None
    return channel, config


def get_webhook_channel_by_uuid(
    channel_uuid: Union[str, UUID],
) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """
    Get webhook channel by UUID for application-layer channel selection.
    Use UUID so that channel name changes do not break references.
    Returns (channel, config) or (None, None) if not found or inactive.
    """
    try:
        uuid_val = (
            UUID(str(channel_uuid))
            if isinstance(channel_uuid, str)
            else channel_uuid
        )
    except (ValueError, TypeError):
        return None, None
    channel = (
        NotificationChannel.objects.filter(
            uuid=uuid_val,
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
        )
        .first()
    )
    if not channel or not channel.config:
        return None, None
    config = build_webhook_config_from_dict(channel.config)
    if not config:
        return None, None
    return channel, config


def _get_webhook_config() -> Optional[Dict[str, Any]]:
    """Get active webhook config dict (for backward compat)."""
    _channel, config = get_default_webhook_channel()
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
        """Return (channel, config) for active webhook or (None, None)."""
        channel, config = get_default_webhook_channel()
        return channel, config

    def _get_config(
        self, channel_config: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        if channel_config is not None:
            return channel_config
        config = self.get_webhook_config()
        if not config:
            logger.warning(
                f"WebhookService._get_config: no active webhook channel in "
                f"NotificationChannel table"
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
        channel_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[NotificationRecord]:
        """Record notification send result."""
        config = self._get_config(channel_config=channel_config)
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
        channel_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Send notification by provider type via driver registry.
        When channel_config is provided (e.g. from application layer), use it
        instead of default webhook channel; otherwise use NotificationChannel.
        """
        config = self._get_config(channel_config=channel_config)
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
                    channel_config=channel_config,
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
                channel_config=channel_config,
            )
            if record:
                result["record_uuid"] = str(record.uuid)

        return result
