"""Tests for notification channel API (list, create, get, validate)."""
import pytest
from unittest.mock import patch

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from agentcore_notifier.adapters.django.models import NotificationChannel


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin",
        email="admin@test.com",
        password="adminpass",
    )


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.mark.django_db
class TestNotificationChannelListCreate:
    """Test GET/POST channels/."""

    def test_list_channels_empty(self, api_client):
        response = api_client.get("/channels/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["results"] == []

    def test_list_channels_filter_by_type(
        self, api_client, webhook_channel_config
    ):
        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            is_active=True,
            config=webhook_channel_config,
        )
        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_EMAIL,
            is_active=True,
            config={"smtp_host": "smtp.example.com", "from_email": "a@b.com"},
        )
        response = api_client.get("/channels/?channel_type=webhook")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["results"][0]["channel_type"] == "webhook"

    def test_create_webhook_channel(self, api_client, webhook_channel_config):
        response = api_client.post(
            "/channels/",
            data={
                "channel_type": "webhook",
                "name": "Feishu",
                "config": webhook_channel_config,
            },
            format="json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["channel_type"] == "webhook"
        assert data["name"] == "Feishu"
        assert data["config"]["url"] == webhook_channel_config["url"]
        assert NotificationChannel.objects.filter(
            channel_type=NotificationChannel.TYPE_WEBHOOK
        ).count() == 1

    def test_create_email_channel(self, api_client, email_channel_config):
        response = api_client.post(
            "/channels/",
            data={
                "channel_type": "email",
                "name": "SMTP",
                "config": email_channel_config,
            },
            format="json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["channel_type"] == "email"
        assert data["config"]["smtp_host"] == email_channel_config["smtp_host"]

    def test_create_channel_invalid_type_returns_400(self, api_client):
        response = api_client.post(
            "/channels/",
            data={"channel_type": "sms", "config": {}},
            format="json",
        )
        assert response.status_code == 400

    def test_create_channel_blank_name_returns_400(
        self, api_client, webhook_channel_config
    ):
        response = api_client.post(
            "/channels/",
            data={
                "channel_type": "webhook",
                "name": "  ",
                "config": webhook_channel_config,
            },
            format="json",
        )
        assert response.status_code == 400
        assert "name" in response.json().get("detail", "").lower()


@pytest.mark.django_db
class TestNotificationChannelDetail:
    """Test GET/PUT/DELETE channels/<uuid>/."""

    def test_get_channel_by_uuid(self, api_client, webhook_channel_config):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            name="Test",
            config=webhook_channel_config,
        )
        response = api_client.get(f"/channels/{ch.uuid}/")
        assert response.status_code == 200
        assert response.json()["uuid"] == str(ch.uuid)
        assert response.json()["name"] == "Test"

    def test_get_channel_404(self, api_client):
        response = api_client.get(
            "/channels/00000000-0000-0000-0000-000000000000/"
        )
        assert response.status_code == 404

    def test_update_channel_blank_name_returns_400(
        self, api_client, webhook_channel_config
    ):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WEBHOOK,
            name="Test",
            config=webhook_channel_config,
        )
        response = api_client.put(
            f"/channels/{ch.uuid}/",
            data={"name": " ", "config": webhook_channel_config},
            format="json",
        )
        assert response.status_code == 400
        assert "name" in response.json().get("detail", "").lower()


@pytest.mark.django_db
class TestChannelValidateView:
    """Test POST channels/validate/."""

    @patch(
        "agentcore_notifier.adapters.django.services.webhook.feishu."
        "requests.post"
    )
    def test_validate_webhook_success(self, mock_post, api_client):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"StatusCode": 0}
        mock_post.return_value.raise_for_status = lambda: None
        response = api_client.post(
            "/channels/validate/",
            data={
                "channel_type": "webhook",
                "config": {
                    "url": "https://open.feishu.cn/webhook/xxx",
                    "provider_type": "feishu",
                },
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}

    @patch(
        "agentcore_notifier.adapters.django.services.webhook.feishu."
        "requests.post"
    )
    def test_validate_wecom_uses_msgtype_payload(self, mock_post, api_client):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"errcode": 0}
        mock_post.return_value.raise_for_status = lambda: None
        webhook_url = (
            "https://qyapi.weixin.qq.com/"
            "cgi-bin/webhook/send?key=xxx"
        )
        response = api_client.post(
            "/channels/validate/",
            data={
                "channel_type": "webhook",
                "config": {
                    "url": webhook_url,
                    "provider_type": "wecom",
                },
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}
        call_kwargs = mock_post.call_args[1]
        # Matches AGENTCORE_NOTIFIER_BRAND's default in channels.py; this
        # assertion was left behind when that default was uppercased.
        expected_content = "[AGENTCORE NOTIFIER] Channel validation test"
        assert call_kwargs["json"] == {
            "msgtype": "text",
            "text": {"content": expected_content},
        }

    def test_validate_webhook_missing_url_returns_400(self, api_client):
        response = api_client.post(
            "/channels/validate/",
            data={"channel_type": "webhook", "config": {}},
            format="json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "success" not in data or data.get("success") is False

    def test_validate_email_invalid_type_returns_400(self, api_client):
        response = api_client.post(
            "/channels/validate/",
            data={"channel_type": "invalid", "config": {}},
            format="json",
        )
        assert response.status_code == 400
        detail = response.json().get("detail", "").lower()
        assert "channel_type must be one of" in detail
        assert "webhook" in detail


class TestAdminCanCreateAppChannels:
    """Creation used to be hardcoded to (webhook, email) while the model
    offered five types and admin UIs put them in a dropdown. Picking
    "WeCom App" returned "channel_type must be webhook or email" and the
    channel could not be created at all -- reported from production.
    """

    @pytest.mark.parametrize("channel_type", [
        "webhook", "email", "feishu_app", "wecom_app", "wecom_bot",
    ])
    def test_every_implemented_type_can_be_created(
        self, api_client, channel_type, db,
    ):
        response = api_client.post(
            "/channels/",
            data={
                "channel_type": channel_type,
                "name": "c-%s" % channel_type,
                "config": {},
            },
            format="json",
        )

        assert response.status_code in (200, 201), response.json()

    def test_sms_stays_out_because_nothing_sends_it(self, api_client, db):
        response = api_client.post(
            "/channels/",
            data={"channel_type": "sms", "name": "c", "config": {}},
            format="json",
        )

        assert response.status_code == 400

    def test_an_unknown_type_is_still_refused(self, api_client, db):
        response = api_client.post(
            "/channels/",
            data={"channel_type": "carrier-pigeon", "name": "c",
                  "config": {}},
            format="json",
        )

        assert response.status_code == 400

    def test_the_creatable_set_follows_the_model(self):
        """Derived, not restated -- an inline list is what drifted from
        the model's choices in the first place."""
        from agentcore_notifier.adapters.django.views.channels import (
            CREATABLE_CHANNEL_TYPES,
        )
        from agentcore_notifier.adapters.django.models import (
            NotificationChannel,
        )

        all_choices = {v for v, _ in NotificationChannel.TYPE_CHOICES}
        assert CREATABLE_CHANNEL_TYPES == all_choices - {
            NotificationChannel.TYPE_SMS
        }


class TestWecomAppValidation:
    """Validation has to deliver, not just introspect.

    An earlier two-call version (gettoken + agent/get) reported success
    for a config that reached nobody: neither call can see whether the
    recipient falls inside the app's visible range. Reported from
    production as "validated fine, no message arrived".
    """

    URL = "/channels/validate/"
    GOOD = {"corp_id": "ww-1", "corp_secret": "s-1", "agent_id": "1000002"}
    MODULE = "agentcore_notifier.adapters.django.views.channels"

    def _post(self, api_client, config=None):
        return api_client.post(
            self.URL,
            data={"channel_type": "wecom_app", "config": config or self.GOOD},
            format="json",
        )

    def test_wecom_app_is_accepted_as_a_validatable_type(self, api_client, db):
        """It used to return "channel_type must be webhook or email", so
        the admin page could not offer a validate button at all."""
        with patch("%s.fetch_access_token" % self.MODULE, return_value=None):
            response = self._post(api_client)

        assert response.status_code == 400
        assert "webhook or email" not in str(response.json()).lower()

    @pytest.mark.parametrize("missing,expected", [
        ("corp_id", "CorpID"),
        ("corp_secret", "Secret"),
        ("agent_id", "AgentId"),
    ])
    def test_missing_fields_are_named_individually(
        self, api_client, missing, expected, db,
    ):
        config = {k: v for k, v in self.GOOD.items() if k != missing}

        response = self._post(api_client, config)

        assert response.status_code == 400
        assert expected in response.json()["error"]

    def test_a_working_config_sends_and_passes(self, api_client, db):
        with patch("%s.fetch_access_token" % self.MODULE, return_value="t"), \
             patch("%s.requests.get" % self.MODULE) as get, \
             patch("%s.send_app_markdown" % self.MODULE) as send:
            get.return_value.json.return_value = {"errcode": 0}
            send.return_value = {"success": True, "response": {"errcode": 0}}

            response = self._post(api_client)

        assert response.status_code == 200
        assert send.called, "validation must deliver, not just introspect"

    def test_errcode_zero_with_invaliduser_is_not_a_success(
        self, api_client, db,
    ):
        """WeCom returns errcode 0 even when it dropped every recipient,
        so a bare errcode check calls a delivery to nobody a success."""
        with patch("%s.fetch_access_token" % self.MODULE, return_value="t"), \
             patch("%s.requests.get" % self.MODULE) as get, \
             patch("%s.send_app_markdown" % self.MODULE) as send:
            get.return_value.json.return_value = {"errcode": 0}
            send.return_value = {
                "success": True,
                "response": {"errcode": 0, "invaliduser": "zhangsan"},
            }

            response = self._post(api_client)

        assert response.status_code == 400
        assert "zhangsan" in response.json()["error"]

    def test_the_trusted_ip_error_names_the_ip_to_whitelist(
        self, api_client, db,
    ):
        """errcode 60020 carries the rejected IP, which is the one piece
        of information needed to fix it."""
        with patch("%s.fetch_access_token" % self.MODULE, return_value="t"), \
             patch("%s.requests.get" % self.MODULE) as get, \
             patch("%s.send_app_markdown" % self.MODULE) as send:
            get.return_value.json.return_value = {
                "errcode": 60020, "errmsg": "not allow to access from ip"
                                            ", from ip: 1.2.3.4",
            }

            response = self._post(api_client)

        assert response.status_code == 400
        assert "1.2.3.4" in response.json()["error"]
        assert not send.called, "a 60020 config cannot send; do not try"


class TestGlobalFeishuCredentialLookup:
    """An incomplete global channel must not shadow a working one.

    The lookup used to take .first() on an unordered queryset and give up
    if that row had no credentials. Harmless while the type could not be
    created by hand; reachable the moment the admin endpoint accepts it,
    and the failure mode is every Feishu notification stopping at once.
    """

    def test_an_empty_global_channel_does_not_shadow_a_working_one(self, db):
        from agentcore_notifier.adapters.django.models import (
            NotificationChannel,
        )
        from agentcore_notifier.adapters.django.services.notification_test \
            import _global_feishu_app_credentials

        NotificationChannel.objects.create(
            user=None, channel_type=NotificationChannel.TYPE_FEISHU_APP,
            name="empty", is_active=True, config={},
        )
        NotificationChannel.objects.create(
            user=None, channel_type=NotificationChannel.TYPE_FEISHU_APP,
            name="real", is_active=True,
            config={"app_id": "cli_x", "app_secret": "s"},
        )

        assert _global_feishu_app_credentials() == ("cli_x", "s")

    def test_no_credentials_anywhere_still_returns_none(self, db):
        from agentcore_notifier.adapters.django.models import (
            NotificationChannel,
        )
        from agentcore_notifier.adapters.django.services.notification_test \
            import _global_feishu_app_credentials

        NotificationChannel.objects.create(
            user=None, channel_type=NotificationChannel.TYPE_FEISHU_APP,
            name="empty", is_active=True, config={},
        )

        assert _global_feishu_app_credentials() is None
