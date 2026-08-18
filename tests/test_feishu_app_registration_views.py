"""Tests for the admin-facing device-flow registration endpoints:
FeishuAppRegistrationStartView / FeishuAppRegistrationPollView."""
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from agentcore_notifier.adapters.django.models import NotificationChannel

VIEWS = "agentcore_notifier.adapters.django.views.channels"


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin2",
        email="admin2@test.com",
        password="adminpass",
    )


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.mark.django_db
class TestFeishuAppRegistrationStartView:
    def test_requires_admin(self):
        client = APIClient()
        resp = client.post("/channels/feishu-app/register/start/")
        assert resp.status_code in (401, 403)

    @patch(f"{VIEWS}.device_registration.begin_app_registration")
    def test_success_returns_qr(self, mock_begin, api_client):
        mock_begin.return_value = {
            "device_code": "dc-1",
            "verification_uri_complete": "https://example/x?user_code=1",
            "interval": 5,
            "expires_in": 600,
        }
        resp = api_client.post("/channels/feishu-app/register/start/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_code"] == "dc-1"
        assert data["qr_code_base64"].startswith(
            "data:image/png;base64,"
        )

    @patch(
        f"{VIEWS}.device_registration.begin_app_registration",
        return_value=None,
    )
    def test_upstream_failure_returns_502(self, mock_begin, api_client):
        resp = api_client.post("/channels/feishu-app/register/start/")
        assert resp.status_code == 502


@pytest.mark.django_db
class TestFeishuAppRegistrationPollView:
    def test_requires_admin(self):
        client = APIClient()
        resp = client.get(
            "/channels/feishu-app/register/poll/",
            {"device_code": "dc-1"},
        )
        assert resp.status_code in (401, 403)

    def test_missing_device_code_is_400(self, api_client):
        resp = api_client.get("/channels/feishu-app/register/poll/")
        assert resp.status_code == 400

    @patch(f"{VIEWS}.device_registration.poll_app_registration")
    def test_pending_passthrough(self, mock_poll, api_client):
        mock_poll.return_value = {"status": "pending"}
        resp = api_client.get(
            "/channels/feishu-app/register/poll/",
            {"device_code": "dc-1"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "pending"}
        assert not NotificationChannel.objects.exists()

    @patch(f"{VIEWS}.device_registration.poll_app_registration")
    def test_success_creates_global_channel(self, mock_poll, api_client):
        mock_poll.return_value = {
            "status": "success",
            "client_id": "cli_new",
            "client_secret": "secret_new",
            "open_id": "ou_1",
            "tenant_brand": "feishu",
        }
        resp = api_client.get(
            "/channels/feishu-app/register/poll/",
            {"device_code": "dc-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "app_secret" not in data["channel"]["config"]

        channel = NotificationChannel.objects.get(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user__isnull=True,
        )
        assert channel.config["app_id"] == "cli_new"
        assert channel.config["app_secret"] == "secret_new"
        assert channel.is_active is True

    @patch(f"{VIEWS}.device_registration.poll_app_registration")
    def test_success_updates_existing_channel_in_place(
        self, mock_poll, api_client
    ):
        """Re-scanning must upsert the one global channel, not create a
        second row, and must preserve unrelated config keys (e.g. a
        callback encrypt_key set up separately) rather than wiping the
        whole config dict."""
        NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=None,
            name="old",
            is_active=False,
            config={
                "app_id": "cli_old",
                "app_secret": "secret_old",
                "encrypt_key": "keep-me",
            },
        )
        mock_poll.return_value = {
            "status": "success",
            "client_id": "cli_new",
            "client_secret": "secret_new",
            "open_id": "ou_1",
            "tenant_brand": "feishu",
        }
        resp = api_client.get(
            "/channels/feishu-app/register/poll/",
            {"device_code": "dc-1"},
        )
        assert resp.status_code == 200

        qs = NotificationChannel.objects.filter(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user__isnull=True,
        )
        assert qs.count() == 1
        channel = qs.first()
        assert channel.config["app_id"] == "cli_new"
        assert channel.config["app_secret"] == "secret_new"
        assert channel.config["encrypt_key"] == "keep-me"
        assert channel.is_active is True

    @patch(f"{VIEWS}.device_registration.poll_app_registration")
    def test_error_status_passthrough_does_not_touch_channels(
        self, mock_poll, api_client
    ):
        mock_poll.return_value = {"status": "error", "error": "boom"}
        resp = api_client.get(
            "/channels/feishu-app/register/poll/",
            {"device_code": "dc-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert not NotificationChannel.objects.exists()


@pytest.mark.django_db
class TestFeishuAppConfigMergeOnPut:
    """PUT on a feishu_app channel must merge into existing config,
    never replace it wholesale — app_secret is masked out of every API
    response, so a client editing e.g. just the callback secrets never
    legitimately has app_id/app_secret to resend."""

    def test_put_encrypt_key_preserves_app_id_and_secret(self, api_client):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=None,
            name="Feishu",
            is_active=True,
            config={"app_id": "cli_1", "app_secret": "secret_1"},
        )
        resp = api_client.put(
            f"/channels/{ch.uuid}/",
            data={
                "config": {
                    "encrypt_key": "ek-1",
                    "verification_token": "vt-1",
                }
            },
            format="json",
        )
        assert resp.status_code == 200
        ch.refresh_from_db()
        assert ch.config["app_id"] == "cli_1"
        assert ch.config["app_secret"] == "secret_1"
        assert ch.config["encrypt_key"] == "ek-1"
        assert ch.config["verification_token"] == "vt-1"

    def test_put_overwrites_only_submitted_keys(self, api_client):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_FEISHU_APP,
            user=None,
            name="Feishu",
            is_active=True,
            config={
                "app_id": "cli_1",
                "app_secret": "secret_1",
                "encrypt_key": "ek-old",
                "verification_token": "vt-old",
            },
        )
        resp = api_client.put(
            f"/channels/{ch.uuid}/",
            data={"config": {"encrypt_key": "ek-new"}},
            format="json",
        )
        assert resp.status_code == 200
        ch.refresh_from_db()
        assert ch.config["encrypt_key"] == "ek-new"
        assert ch.config["verification_token"] == "vt-old"
        assert ch.config["app_id"] == "cli_1"
        assert ch.config["app_secret"] == "secret_1"
