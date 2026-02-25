"""Tests for send_webhook_notification and send_email_notification tasks."""
import pytest
from unittest.mock import patch

from agentcore_notifier.adapters.django.models import (
    NotificationChannel,
    NotificationRecord,
)
from agentcore_notifier.adapters.django.tasks.send import (
    send_email_notification,
    send_webhook_notification,
)
from agentcore_notifier.constants import Channel, Provider, Status


@pytest.mark.django_db
class TestSendWebhookNotification:
    """Test send_webhook_notification task."""

    @patch(
        "agentcore_notifier.adapters.django.services.webhook.feishu."
        "requests.post"
    )
    def test_send_webhook_success(self, mock_post, webhook_channel_config):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"StatusCode": 0}
        mock_post.return_value.raise_for_status = lambda: None

        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config=webhook_channel_config,
        )
        payload = {"msg_type": "text", "content": {"text": "hello"}}
        result = send_webhook_notification(
            payload=payload,
            provider_type="feishu",
            source_app="test_app",
            source_type="alert",
            source_id="1",
        )
        assert result.get("success") is True
        rec = NotificationRecord.objects.filter(
            channel=Channel.WEBHOOK,
            source_app="test_app",
        ).first()
        assert rec is not None
        assert rec.status == Status.SUCCESS

    def test_send_webhook_no_channel_returns_error(self):
        result = send_webhook_notification(
            payload={"msg_type": "text", "content": {"text": "hi"}},
            provider_type="feishu",
            source_app="test_app",
        )
        assert result.get("success") is False


@pytest.mark.django_db
class TestSendEmailNotification:
    """Test send_email_notification task."""

    @patch(
        "agentcore_notifier.adapters.django.services.email_service."
        "smtplib.SMTP"
    )
    def test_send_email_success(self, mock_smtp_class, email_channel_config):
        mock_smtp_class.return_value.__enter__ = lambda self: self
        mock_smtp_class.return_value.__exit__ = lambda *a: None
        mock_smtp_class.return_value.starttls = lambda: None
        mock_smtp_class.return_value.sendmail = lambda *a, **k: None

        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_EMAIL,
            is_active=True,
            config=email_channel_config,
        )
        result = send_email_notification(
            subject="Test",
            body="Body",
            to=["u@example.com"],
            source_app="test_app",
            source_type="alert",
            source_id="1",
        )
        assert result.get("success") is True
        rec = NotificationRecord.objects.filter(
            channel=Channel.EMAIL,
            provider_type=Provider.EMAIL,
            source_app="test_app",
        ).first()
        assert rec is not None
        assert rec.status == Status.SUCCESS

    def test_send_email_no_channel_returns_error(self):
        result = send_email_notification(
            subject="Test",
            body="Body",
            to=["u@example.com"],
            source_app="test_app",
        )
        assert result.get("success") is False
