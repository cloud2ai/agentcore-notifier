"""Tests for WebhookService (config from NotificationChannel)."""
import pytest
from unittest.mock import patch

from agentcore_notifier.adapters.django.models import NotificationChannel
from agentcore_notifier.adapters.django.services.webhook_service import (
    WebhookService,
    _get_webhook_config,
)


@pytest.mark.django_db
class TestWebhookService:
    """Test WebhookService with NotificationChannel config."""

    def test_get_webhook_config_empty_when_no_config(self):
        svc = WebhookService()
        assert svc.get_webhook_config() is None

    def test_get_webhook_config_returns_config_when_channel_set(
        self,
        webhook_channel_config,
    ):
        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config=webhook_channel_config,
        )
        cfg = _get_webhook_config()
        assert cfg is not None
        assert cfg.get("url") == webhook_channel_config["url"]
        assert cfg.get("provider") == "feishu"
        svc = WebhookService()
        assert svc.get_webhook_config() is not None
        assert svc.get_webhook_config()["url"] == webhook_channel_config["url"]

    def test_send_returns_error_when_no_config(self):
        svc = WebhookService()
        result = svc.send(
            payload={"msg_type": "text", "text": {"text": "hi"}},
            source_app="test",
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @patch(
        "agentcore_notifier.adapters.django.services.webhook.feishu."
        "requests.post"
    )
    def test_send_feishu_success(self, mock_post, webhook_channel_config):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"StatusCode": 0}
        mock_post.return_value.raise_for_status = lambda: None

        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config=webhook_channel_config,
        )
        svc = WebhookService()
        payload = {"msg_type": "text", "text": {"text": "hello"}}
        result = svc.send(payload, provider_type="feishu")
        assert result["success"] is True
        assert result.get("error") is None
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"] == payload
        assert call_kwargs["timeout"] == 10
