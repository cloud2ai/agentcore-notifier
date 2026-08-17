"""Tests for feishu_app.client — DM sending and card patching."""
from unittest.mock import MagicMock, patch

import pytest

from agentcore_notifier.adapters.django.services.feishu_app.client import (
    send_card_dm,
    update_card_message,
)

MODULE = "agentcore_notifier.adapters.django.services.feishu_app.client"


def _response(code=0, **extra):
    body = {"code": code, **extra}
    if code != 0:
        body.setdefault("msg", "boom")
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


@pytest.mark.unit
class TestSendCardDm:
    @patch(f"{MODULE}.get_tenant_access_token", return_value="tok")
    @patch(f"{MODULE}.requests.request")
    def test_success(self, mock_request, mock_token):
        mock_request.return_value = _response(
            data={"message_id": "om_123"}
        )
        result = send_card_dm(
            "ou_123", {"config": {}}, "app-1", "secret-1"
        )
        assert result["success"] is True
        assert result["error"] is None
        call = mock_request.call_args
        assert call.args[0] == "POST"
        assert call.kwargs["params"] == {"receive_id_type": "open_id"}
        assert call.kwargs["json"]["receive_id"] == "ou_123"
        assert call.kwargs["json"]["msg_type"] == "interactive"

    @patch(f"{MODULE}.get_tenant_access_token", return_value=None)
    def test_no_token_fails_without_network_call(self, mock_token):
        result = send_card_dm("ou_123", {}, "app-1", "secret-1")
        assert result["success"] is False
        assert "tenant_access_token" in result["error"]

    @patch(f"{MODULE}.invalidate_tenant_access_token")
    @patch(f"{MODULE}.get_tenant_access_token", return_value="tok")
    @patch(f"{MODULE}.requests.request")
    def test_expired_token_invalidates_cache(
        self, mock_request, mock_token, mock_invalidate
    ):
        mock_request.return_value = _response(code=99991663)
        result = send_card_dm("ou_123", {}, "app-1", "secret-1")
        assert result["success"] is False
        mock_invalidate.assert_called_once_with("app-1")

    @patch(f"{MODULE}.get_tenant_access_token", return_value="tok")
    @patch(f"{MODULE}.requests.request")
    def test_business_error_surfaces_message(
        self, mock_request, mock_token
    ):
        mock_request.return_value = _response(code=12345, msg="no perm")
        result = send_card_dm("ou_123", {}, "app-1", "secret-1")
        assert result["success"] is False
        assert result["error"] == "no perm"

    @patch(f"{MODULE}.get_tenant_access_token", return_value="tok")
    @patch(f"{MODULE}.requests.request")
    def test_network_failure_returns_error(self, mock_request, mock_token):
        import requests

        mock_request.side_effect = requests.exceptions.ConnectionError(
            "down"
        )
        result = send_card_dm("ou_123", {}, "app-1", "secret-1")
        assert result["success"] is False
        assert result["response"] is None


@pytest.mark.unit
class TestUpdateCardMessage:
    @patch(f"{MODULE}.get_tenant_access_token", return_value="tok")
    @patch(f"{MODULE}.requests.request")
    def test_success_uses_patch_method(self, mock_request, mock_token):
        mock_request.return_value = _response()
        result = update_card_message(
            "om_123", {"config": {}}, "app-1", "secret-1"
        )
        assert result["success"] is True
        call = mock_request.call_args
        assert call.args[0] == "PATCH"
        assert "om_123" in call.args[1]

    @patch(f"{MODULE}.get_tenant_access_token", return_value=None)
    def test_no_token_fails_without_network_call(self, mock_token):
        result = update_card_message(
            "om_123", {}, "app-1", "secret-1"
        )
        assert result["success"] is False
