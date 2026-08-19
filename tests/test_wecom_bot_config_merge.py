"""PUT on a wecom_bot channel must merge into existing config, never
replace it wholesale — same requirement as feishu_app (see
TestFeishuAppConfigMergeOnPut), and for the same reason: `secret` is
masked out of every API response, so a client editing e.g. just
name/is_active here never legitimately has bot_id/secret/userid to
resend."""
from django.contrib.auth.models import User
from rest_framework.test import APIClient

import pytest

from agentcore_notifier.adapters.django.models import NotificationChannel


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin-wecom-merge",
        email="admin-wecom-merge@test.com",
        password="adminpass",
    )


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def bot_owner(db):
    return User.objects.create_user(
        username="wecom-bot-owner",
        email="wecom-bot-owner@test.com",
        password="pass",
    )


@pytest.mark.django_db
class TestWeComBotConfigMergeOnPut:
    def test_put_name_preserves_bot_id_secret_and_userid(
        self, api_client, bot_owner
    ):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=bot_owner,
            name="企业微信",
            is_active=True,
            config={
                "bot_id": "bid-1", "secret": "secret-1", "userid": "wo-1",
            },
        )
        resp = api_client.put(
            f"/channels/{ch.uuid}/",
            data={"name": "renamed"},
            format="json",
        )
        assert resp.status_code == 200
        ch.refresh_from_db()
        assert ch.config["bot_id"] == "bid-1"
        assert ch.config["secret"] == "secret-1"
        assert ch.config["userid"] == "wo-1"
        assert ch.name == "renamed"

    def test_put_with_empty_config_does_not_wipe_credentials(
        self, api_client, bot_owner
    ):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=bot_owner,
            name="企业微信",
            is_active=True,
            config={
                "bot_id": "bid-1", "secret": "secret-1", "userid": "wo-1",
            },
        )
        resp = api_client.put(
            f"/channels/{ch.uuid}/",
            data={"config": {}},
            format="json",
        )
        assert resp.status_code == 200
        ch.refresh_from_db()
        assert ch.config["bot_id"] == "bid-1"
        assert ch.config["secret"] == "secret-1"
        assert ch.config["userid"] == "wo-1"

    def test_response_never_includes_the_secret(
        self, api_client, bot_owner
    ):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=bot_owner,
            name="企业微信",
            is_active=True,
            config={
                "bot_id": "bid-1", "secret": "secret-1", "userid": "wo-1",
            },
        )
        resp = api_client.put(
            f"/channels/{ch.uuid}/",
            data={"name": "renamed"},
            format="json",
        )
        assert "secret" not in resp.json()["config"]
