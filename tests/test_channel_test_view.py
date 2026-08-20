"""Tests for NotificationChannelTestView — admin-facing test-send by
uuid, any channel (not scoped to one user, unlike the articlehub
user-facing equivalent)."""
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from agentcore_notifier.adapters.django.models import NotificationChannel

MODULE = "agentcore_notifier.adapters.django.views.channels"


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin-test-send",
        email="admin-test-send@test.com",
        password="adminpass",
    )


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="channel-owner",
        email="channel-owner@test.com",
        password="x",
    )


@pytest.mark.django_db
class TestNotificationChannelTestView:
    def test_requires_admin(self, owner):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=owner,
            is_active=True,
            config={"bot_id": "b", "secret": "s", "userid": "u"},
        )
        client = APIClient()
        client.force_authenticate(user=owner)
        resp = client.post(f"/channels/{ch.uuid}/test/")
        assert resp.status_code == 403

    def test_unknown_uuid_is_404(self, api_client):
        import uuid as uuid_mod

        resp = api_client.post(f"/channels/{uuid_mod.uuid4()}/test/")
        assert resp.status_code == 404

    @patch(f"{MODULE}.notification_test.send_test_message")
    def test_success_passes_through_the_channel(
        self, mock_send, api_client, owner
    ):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=owner,
            is_active=True,
            config={"bot_id": "b", "secret": "s", "userid": "u"},
        )
        mock_send.return_value = {
            "success": True, "response": {}, "error": None,
        }
        resp = api_client.post(f"/channels/{ch.uuid}/test/")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert mock_send.call_args[0][0].uuid == ch.uuid

    @patch(f"{MODULE}.notification_test.send_test_message")
    def test_failure_is_still_a_200_with_success_false(
        self, mock_send, api_client, owner
    ):
        ch = NotificationChannel.objects.create(
            channel_type=NotificationChannel.TYPE_WECOM_BOT,
            user=owner,
            is_active=True,
            config={},
        )
        mock_send.return_value = {
            "success": False, "response": None, "error": "配置不完整",
        }
        resp = api_client.post(f"/channels/{ch.uuid}/test/")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
