"""Tests for services.notification_test.send_test_message — the
shared "does this channel actually work" sender used by both the
admin console and the user-facing settings page."""
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from agentcore_notifier.adapters.django.models import (
    NotificationChannel,
    NotificationRecord,
)
from agentcore_notifier.adapters.django.services.notification_test import (
    send_test_message,
)
from agentcore_notifier.constants import Provider, Status

MODULE = "agentcore_notifier.adapters.django.services.notification_test"


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="test-owner", email="test-owner@test.com", password="x",
    )


def _global_feishu_channel(**overrides):
    config = {"app_id": "cli_global", "app_secret": "secret_global"}
    config.update(overrides)
    return NotificationChannel.objects.create(
        channel_type=NotificationChannel.TYPE_FEISHU_APP,
        user=None,
        is_active=True,
        config=config,
    )


@pytest.mark.django_db
class TestSendTestFeishu:
    def test_global_channel_has_no_one_to_send_to(self):
        channel = _global_feishu_channel()
        result = send_test_message(channel)
        assert result["success"] is False
        assert "全局应用" in result["error"]
        assert not NotificationRecord.objects.exists()

    def test_no_open_id_is_an_error(self, owner):
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=owner,
            is_active=True,
            config={"app_id": "cli_1", "app_secret": "secret_1"},
        )
        result = send_test_message(channel)
        assert result["success"] is False
        assert "绑定飞书身份" in result["error"]
        assert not NotificationRecord.objects.exists()

    @patch(f"{MODULE}.send_card_dm")
    def test_self_registered_uses_its_own_credentials(
        self, mock_send, owner
    ):
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=owner,
            is_active=True,
            config={
                "app_id": "cli_own", "app_secret": "secret_own",
                "open_id": "ou_own",
            },
        )
        mock_send.return_value = {
            "success": True, "response": {"message_id": "om_1"}, "error": None,
        }
        result = send_test_message(channel)
        assert result["success"] is True
        call_args = mock_send.call_args[0]
        assert call_args[0] == "ou_own"
        assert call_args[2] == "cli_own"
        assert call_args[3] == "secret_own"

        rec = NotificationRecord.objects.get()
        assert rec.channel == NotificationChannel.TYPE_FEISHU_APP
        assert rec.channel_link_id == channel.id
        assert rec.provider_type == Provider.FEISHU
        assert rec.user_id == owner.id
        assert rec.status == Status.SUCCESS
        assert rec.response == {"message_id": "om_1"}
        assert rec.sent_at is not None

    @patch(f"{MODULE}.send_card_dm")
    def test_failed_send_is_still_recorded(self, mock_send, owner):
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=owner,
            is_active=True,
            config={
                "app_id": "cli_own", "app_secret": "secret_own",
                "open_id": "ou_own",
            },
        )
        mock_send.return_value = {
            "success": False, "response": None, "error": "rate limited",
        }
        result = send_test_message(channel)
        assert result["success"] is False

        rec = NotificationRecord.objects.get()
        assert rec.status == Status.FAILED
        assert rec.error_message == "rate limited"
        assert rec.sent_at is None

    @patch(f"{MODULE}.send_card_dm")
    def test_bound_to_global_borrows_global_credentials(
        self, mock_send, owner
    ):
        _global_feishu_channel()
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=owner,
            is_active=True,
            config={"open_id": "ou_bound", "union_id": "un_1"},
        )
        mock_send.return_value = {
            "success": True, "response": {}, "error": None,
        }
        result = send_test_message(channel)
        assert result["success"] is True
        call_args = mock_send.call_args[0]
        assert call_args[0] == "ou_bound"
        assert call_args[2] == "cli_global"
        assert call_args[3] == "secret_global"

        rec = NotificationRecord.objects.get()
        assert rec.status == Status.SUCCESS
        assert rec.channel_link_id == channel.id

    def test_bound_to_global_but_no_global_app_configured(self, owner):
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=owner,
            is_active=True,
            config={"open_id": "ou_bound"},
        )
        result = send_test_message(channel)
        assert result["success"] is False
        assert "全局飞书应用" in result["error"]
        assert not NotificationRecord.objects.exists()


@pytest.mark.django_db
class TestSendTestWecom:
    @patch(f"{MODULE}.send_aibot_markdown")
    def test_success(self, mock_send, owner):
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=owner,
            is_active=True,
            config={
                "bot_id": "bid-1", "secret": "sec-1", "userid": "wo-1",
            },
        )
        mock_send.return_value = {
            "success": True, "response": {}, "error": None,
        }
        result = send_test_message(channel)
        assert result["success"] is True
        call_args = mock_send.call_args[0]
        assert call_args[0] == "wo-1"
        assert call_args[2] == "bid-1"
        assert call_args[3] == "sec-1"

        rec = NotificationRecord.objects.get()
        assert rec.channel == NotificationChannel.TYPE_WECOM_BOT
        assert rec.channel_link_id == channel.id
        assert rec.provider_type == Provider.WECOM
        assert rec.status == Status.SUCCESS

    def test_incomplete_config_is_an_error(self, owner):
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=owner,
            is_active=True,
            config={"bot_id": "bid-1"},
        )
        result = send_test_message(channel)
        assert result["success"] is False
        assert result["error"]
        assert not NotificationRecord.objects.exists()


@pytest.mark.django_db
class TestSendTestUnsupportedType:
    def test_webhook_channel_returns_a_clear_error(self, owner):
        channel = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            user=owner,
            is_active=True,
            config={"url": "https://example.com/hook"},
        )
        result = send_test_message(channel)
        assert result["success"] is False
        assert result["error"]
