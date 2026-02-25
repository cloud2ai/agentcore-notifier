"""
Celery tasks: send webhook or email (merge/silence from channel config).
"""
import logging
from typing import Any, Dict, List, Optional

from celery import shared_task
from django.utils import timezone

from agentcore_notifier.adapters.django.conf import (
    get_merge_enabled,
    get_merge_window_minutes,
)
from agentcore_notifier.adapters.django.models import NotificationRecord
from agentcore_notifier.adapters.django.services import merge_and_silence
from agentcore_notifier.adapters.django.services.email_service import (
    get_default_email_channel,
    EmailService,
)
from agentcore_notifier.adapters.django.services.webhook_service import (
    get_default_webhook_channel,
    WebhookService,
)
from agentcore_notifier.constants import Channel, Provider, Status

logger = logging.getLogger(__name__)


_TASK_SEND_NAME = (
    "agentcore_notifier.adapters.django.tasks.send.send_webhook_notification"
)


def _write_record_with_channel(
    provider_type: str,
    source_app: str,
    source_type: str,
    source_id: str,
    user_id: Optional[int],
    status: str,
    channel_id: Optional[int] = None,
    channel: str = Channel.WEBHOOK,
    payload: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
):
    """Create NotificationRecord (merged/silenced) with optional channel_id."""
    NotificationRecord.objects.create(
        provider_type=provider_type,
        channel=channel,
        channel_link_id=channel_id,
        user_id=user_id,
        source_app=source_app,
        source_type=source_type,
        source_id=source_id or "",
        payload=payload or {},
        status=status,
        response=result.get("response") if result else None,
        error_message=result.get("error", "") if result else "",
        sent_at=timezone.now() if status == Status.SUCCESS else None,
    )


@shared_task(name=_TASK_SEND_NAME)
def send_webhook_notification(
    payload: Dict[str, Any],
    provider_type: str,
    source_app: str,
    source_type: str = "",
    source_id: str = "",
    user_id: Optional[int] = None,
):
    """
    Send webhook notification. Merge and silence are read from the active
    webhook channel's config; then WebhookService.send is called.
    """
    channel, _ = get_default_webhook_channel()
    channel_id = channel.id if channel else None
    channel_config = (channel.config or {}) if channel else {}

    silence_window = None
    if channel_config:
        try:
            silence_window = int(
                channel_config.get("silence_window_minutes") or 0
            )
        except (TypeError, ValueError):
            silence_window = 0
    if silence_window and silence_window > 0:
        if merge_and_silence.should_skip_due_to_merge(
            provider_type,
            source_app,
            source_type,
            source_id,
            silence_window,
            channel_id=channel_id,
            user_id=user_id,
        ):
            logger.info(
                f"send_webhook_notification: silenced "
                f"(same alert within {silence_window}min) "
                f"provider_type={provider_type} "
                f"source={source_app}:{source_type}:{source_id}"
            )
            _write_record_with_channel(
                provider_type,
                source_app,
                source_type,
                source_id,
                user_id,
                Status.SILENCED,
                channel_id=channel_id,
            )
            return {"skipped": True, "reason": "silenced"}

    merge_enabled = (
        channel_config.get("merge_enabled") if channel_config else False
    )
    merge_window = (
        channel_config.get("merge_window_minutes")
        if channel_config
        else None
    )
    if not merge_enabled or not merge_window or merge_window <= 0:
        merge_enabled = get_merge_enabled(provider_type)
        merge_window = get_merge_window_minutes(provider_type)

    if merge_enabled and merge_window and merge_window > 0:
        if merge_and_silence.should_skip_due_to_merge(
            provider_type,
            source_app,
            source_type,
            source_id,
            merge_window,
            channel_id=channel_id,
            user_id=user_id,
        ):
            logger.info(
                f"send_webhook_notification: merged "
                f"provider_type={provider_type} "
                f"source={source_app}:{source_type}:{source_id}"
            )
            _write_record_with_channel(
                provider_type,
                source_app,
                source_type,
                source_id,
                user_id,
                Status.MERGED,
                channel_id=channel_id,
            )
            return {"skipped": True, "reason": "merged"}

    svc = WebhookService()
    user = None if user_id is None else _user_from_id(user_id)
    result = svc.send(
        payload=payload,
        provider_type=provider_type,
        source_app=source_app,
        source_type=source_type,
        source_id=source_id,
        user=user,
        channel_id=channel_id,
    )
    return result


def _user_from_id(user_id: int):
    # NOTE(Ray): Lazy import to avoid loading User at module import time.
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(pk=user_id).first()


_TASK_SEND_EMAIL_NAME = (
    "agentcore_notifier.adapters.django.tasks.send.send_email_notification"
)


@shared_task(name=_TASK_SEND_EMAIL_NAME)
def send_email_notification(
    subject: str,
    body: str,
    to: List[str],
    source_app: str,
    source_type: str = "",
    source_id: str = "",
    user_id: Optional[int] = None,
):
    """
    Send email notification. Uses default email channel (SMTP). Optional
    silence window from channel config; then EmailService.send is called.
    """
    channel, _ = get_default_email_channel()
    channel_id = channel.id if channel else None
    channel_config = (channel.config or {}) if channel else {}
    silence_window = None
    if channel_config:
        try:
            silence_window = int(
                channel_config.get("silence_window_minutes") or 0
            )
        except (TypeError, ValueError):
            silence_window = 0
    if silence_window and silence_window > 0:
        if merge_and_silence.should_skip_due_to_merge(
            Provider.EMAIL,
            source_app,
            source_type,
            source_id,
            silence_window,
            channel_id=channel_id,
            user_id=user_id,
        ):
            logger.info(
                f"send_email_notification: silenced "
                f"(same alert within {silence_window}min) "
                f"source={source_app}:{source_type}:{source_id}"
            )
            _write_record_with_channel(
                Provider.EMAIL,
                source_app,
                source_type,
                source_id,
                user_id,
                Status.SILENCED,
                channel_id=channel_id,
                channel=Channel.EMAIL,
            )
            return {"skipped": True, "reason": "silenced"}
    svc = EmailService()
    user = None if user_id is None else _user_from_id(user_id)
    result = svc.send(
        subject=subject,
        body=body,
        to=to,
        source_app=source_app,
        source_type=source_type,
        source_id=source_id,
        user=user,
        channel_id=channel_id,
    )
    return result
