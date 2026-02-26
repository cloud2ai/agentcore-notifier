"""Tests for WebhookService (config from NotificationChannel)."""
import pytest
from unittest.mock import patch

from agentcore_notifier.adapters.django.models import NotificationChannel
from agentcore_notifier.adapters.django.services.webhook_service import (
    WebhookService,
    _get_webhook_config,
    build_webhook_config_from_dict,
    get_default_webhook_channel,
    get_webhook_channel_by_uuid,
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


@pytest.mark.django_db
class TestBuildWebhookConfigFromDict:
    """Test build_webhook_config_from_dict."""

    def test_returns_none_when_empty(self):
        assert build_webhook_config_from_dict({}) is None
        assert build_webhook_config_from_dict(None) is None

    def test_returns_none_when_url_missing(self):
        assert build_webhook_config_from_dict({"provider_type": "feishu"}) is None
        assert build_webhook_config_from_dict({"url": ""}) is None
        assert build_webhook_config_from_dict({"url": "   "}) is None

    def test_returns_config_when_url_present(self):
        cfg = {
            "url": "https://example.com/webhook",
            "provider_type": "feishu",
            "headers": {"X-Custom": "v"},
        }
        out = build_webhook_config_from_dict(cfg)
        assert out is not None
        assert out["url"] == "https://example.com/webhook"
        assert out["provider"] == "feishu"
        assert out["headers"] == {"X-Custom": "v"}

    def test_accepts_provider_or_provider_type(self):
        out = build_webhook_config_from_dict({
            "url": "https://x.com",
            "provider": "wechat",
        })
        assert out is not None
        assert out["provider"] == "wechat"


@pytest.mark.django_db
class TestGetDefaultWebhookChannel:
    """Test get_default_webhook_channel (first active by created_at)."""

    def test_returns_none_when_no_channel(self):
        channel, config = get_default_webhook_channel()
        assert channel is None
        assert config is None

    def test_returns_earliest_created_at_channel(self, webhook_channel_config):
        first = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config=webhook_channel_config,
        )
        second = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config={**webhook_channel_config, "url": "https://second.example.com"},
        )
        channel, config = get_default_webhook_channel()
        assert channel is not None
        assert config is not None
        assert channel.created_at <= second.created_at
        assert channel.id == first.id
        assert config["url"] == webhook_channel_config["url"]

    def test_ignores_inactive_channel(self, webhook_channel_config):
        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=False,
            config=webhook_channel_config,
        )
        channel, config = get_default_webhook_channel()
        assert channel is None
        assert config is None


@pytest.mark.django_db
class TestGetWebhookChannelByUuid:
    """Test get_webhook_channel_by_uuid (application-layer channel selection)."""

    def test_returns_none_for_invalid_uuid(self):
        channel, config = get_webhook_channel_by_uuid("not-a-uuid")
        assert channel is None
        assert config is None
        channel, config = get_webhook_channel_by_uuid("")
        assert channel is None
        assert config is None

    def test_returns_none_when_not_found(self, webhook_channel_config):
        import uuid
        channel, config = get_webhook_channel_by_uuid(uuid.uuid4())
        assert channel is None
        assert config is None

    def test_returns_channel_when_found_by_str_uuid(self, webhook_channel_config):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config=webhook_channel_config,
        )
        channel, config = get_webhook_channel_by_uuid(str(ch.uuid))
        assert channel is not None
        assert channel.id == ch.id
        assert config is not None
        assert config["url"] == webhook_channel_config["url"]

    def test_returns_channel_when_found_by_uuid_type(self, webhook_channel_config):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config=webhook_channel_config,
        )
        channel, config = get_webhook_channel_by_uuid(ch.uuid)
        assert channel is not None
        assert channel.id == ch.id
        assert config is not None

    def test_returns_none_when_channel_inactive(self, webhook_channel_config):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=False,
            config=webhook_channel_config,
        )
        channel, config = get_webhook_channel_by_uuid(str(ch.uuid))
        assert channel is None
        assert config is None
