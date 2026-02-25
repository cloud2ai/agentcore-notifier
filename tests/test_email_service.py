"""Tests for EmailService and get_default_email_channel."""
import pytest
from unittest.mock import patch

from agentcore_notifier.adapters.django.models import (
    NotificationChannel,
    NotificationRecord,
)
from agentcore_notifier.adapters.django.services.email_service import (
    EmailService,
    get_default_email_channel,
)
from agentcore_notifier.constants import Channel, Provider, Status


@pytest.mark.django_db
class TestGetDefaultEmailChannel:
    """Test get_default_email_channel."""

    def test_returns_none_when_no_channel(self):
        ch, cfg = get_default_email_channel()
        assert ch is None
        assert cfg is None

    def test_returns_none_when_channel_has_no_smtp_host(
        self, email_channel_config
    ):
        c = dict(email_channel_config)
        c["smtp_host"] = ""
        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_EMAIL,
            is_active=True,
            config=c,
        )
        ch, cfg = get_default_email_channel()
        assert ch is None
        assert cfg is None

    def test_returns_channel_and_config_when_set(self, email_channel_config):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_EMAIL,
            is_active=True,
            config=email_channel_config,
        )
        ch_out, cfg = get_default_email_channel()
        assert ch_out is not None
        assert ch_out.id == ch.id
        assert cfg is not None
        assert cfg["smtp_host"] == email_channel_config["smtp_host"]
        assert cfg["smtp_port"] == 587
        assert cfg["from_email"] == email_channel_config["from_email"]


@pytest.mark.django_db
class TestEmailService:
    """Test EmailService send and record."""

    def test_send_returns_error_when_no_channel(self):
        svc = EmailService()
        result = svc.send(
            subject="Test",
            body="Body",
            to=["a@b.com"],
            source_app="test",
        )
        assert result["success"] is False
        err = result["error"].lower()
        assert "not found" in err or "not active" in err

    def test_send_returns_error_when_no_valid_recipients(
        self, email_channel_config
    ):
        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_EMAIL,
            is_active=True,
            config=email_channel_config,
        )
        svc = EmailService()
        result = svc.send(
            subject="Test",
            body="Body",
            to=[],
            source_app="test",
        )
        assert result["success"] is False
        assert "recipient" in result["error"].lower()

    @patch(
        "agentcore_notifier.adapters.django.services.email_service."
        "smtplib.SMTP"
    )
    def test_send_success_and_record(
        self, mock_smtp_class, email_channel_config
    ):
        mock_smtp_class.return_value.__enter__ = lambda self: self
        mock_smtp_class.return_value.__exit__ = lambda *a: None
        mock_smtp_class.return_value.starttls = lambda: None
        mock_smtp_class.return_value.sendmail = lambda *a, **k: None

        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_EMAIL,
            is_active=True,
            config=email_channel_config,
        )
        svc = EmailService()
        result = svc.send(
            subject="Test Subject",
            body="Test body",
            to=["user@example.com"],
            source_app="test_app",
            source_type="alert",
            source_id="1",
        )
        assert result["success"] is True
        assert "record_uuid" in result
        rec = NotificationRecord.objects.filter(
            channel=Channel.EMAIL,
            provider_type=Provider.EMAIL,
            source_app="test_app",
        ).first()
        assert rec is not None
        assert rec.status == Status.SUCCESS
        assert rec.payload.get("subject") == "Test Subject"
        assert "user@example.com" in rec.payload.get("to", [])
