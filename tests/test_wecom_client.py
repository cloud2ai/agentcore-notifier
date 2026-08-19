"""Tests for wecom.client — bearer-token exchange, identity lookup,
and message sending against the qyapi.weixin.qq.com/cli gateway."""
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from agentcore_notifier.adapters.django.services.wecom import client

MODULE = "agentcore_notifier.adapters.django.services.wecom.client"


def _response(body):
    resp = MagicMock()
    resp.json.return_value = body
    return resp


def _gateway_success(inner_result):
    """The /cli gateway's response envelope: {errcode, errmsg,
    results_json: '{"result": "<json-string-of-inner_result>"}'}."""
    return _response(
        {
            "errcode": 0,
            "errmsg": "ok",
            "results_json": json.dumps(
                {"result": json.dumps(inner_result, ensure_ascii=False)}
            ),
        }
    )


@pytest.mark.unit
class TestFetchBotToken:
    @patch(f"{MODULE}.requests.post")
    def test_success_returns_token(self, mock_post):
        mock_post.return_value = _response({"errcode": 0, "token": "tok-1"})
        assert client.fetch_bot_token("bid-1", "sec-1") == "tok-1"
        call = mock_post.call_args
        assert call.args[0] == client.AUTH_ENDPOINT
        body = call.kwargs["json"]
        assert body["bot_id"] == "bid-1"
        assert body["bind_source"] == client.BIND_SOURCE_QRCODE
        assert len(body["signature"]) == 64  # sha256 hex digest length

    @patch(f"{MODULE}.requests.post")
    def test_business_error_returns_none(self, mock_post):
        mock_post.return_value = _response(
            {"errcode": 40001, "errmsg": "invalid signature"}
        )
        assert client.fetch_bot_token("bid-1", "sec-1") is None

    @patch(f"{MODULE}.requests.post")
    def test_network_error_returns_none(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("down")
        assert client.fetch_bot_token("bid-1", "sec-1") is None

    @patch(f"{MODULE}.requests.post")
    def test_missing_token_field_returns_none(self, mock_post):
        mock_post.return_value = _response({"errcode": 0})
        assert client.fetch_bot_token("bid-1", "sec-1") is None


@pytest.mark.unit
class TestGetIdentityContext:
    @patch(f"{MODULE}.requests.post")
    def test_success_returns_the_raw_context_string(self, mock_post):
        mock_post.return_value = _gateway_success(
            {"extra_identity_context": "some context text"}
        )
        assert client.get_identity_context("tok-1") == "some context text"
        call = mock_post.call_args
        assert call.args[0] == client.IDENTITY_WHOAMI_URL
        assert call.kwargs["headers"]["Authorization"] == "Bearer tok-1"

    @patch(f"{MODULE}.requests.post")
    def test_business_error_returns_none(self, mock_post):
        mock_post.return_value = _response(
            {"errcode": 401, "errmsg": "unauthorized"}
        )
        assert client.get_identity_context("tok-1") is None

    @patch(f"{MODULE}.requests.post")
    def test_malformed_results_json_returns_none(self, mock_post):
        mock_post.return_value = _response(
            {"errcode": 0, "results_json": "not json"}
        )
        assert client.get_identity_context("tok-1") is None

    @patch(f"{MODULE}.requests.post")
    def test_network_error_returns_none(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("slow")
        assert client.get_identity_context("tok-1") is None


@pytest.mark.unit
class TestSendAibotMarkdown:
    @patch(f"{MODULE}.requests.post")
    @patch(f"{MODULE}.fetch_bot_token")
    def test_success(self, mock_fetch_token, mock_post):
        mock_fetch_token.return_value = "tok-1"
        mock_post.return_value = _gateway_success({"success": True})

        result = client.send_aibot_markdown(
            "wo-user-1", "hello", "bid-1", "sec-1",
        )
        assert result == {
            "success": True,
            "response": mock_post.return_value.json.return_value,
            "error": None,
        }
        call = mock_post.call_args
        assert call.args[0] == client.SEND_AIBOT_MESSAGE_URL
        sent_payload = json.loads(call.kwargs["json"]["payload"])
        assert sent_payload["chat_id"] == "wo-user-1"
        assert sent_payload["msg_type"] == "markdown"
        assert sent_payload["markdown"]["content"] == "hello"

    @patch(f"{MODULE}.fetch_bot_token")
    def test_token_failure_short_circuits_without_sending(
        self, mock_fetch_token
    ):
        mock_fetch_token.return_value = None
        with patch(f"{MODULE}.requests.post") as mock_post:
            result = client.send_aibot_markdown(
                "wo-user-1", "hello", "bid-1", "sec-1",
            )
            mock_post.assert_not_called()
        assert result["success"] is False

    @patch(f"{MODULE}.requests.post")
    @patch(f"{MODULE}.fetch_bot_token")
    def test_business_error_returns_failure(
        self, mock_fetch_token, mock_post
    ):
        mock_fetch_token.return_value = "tok-1"
        mock_post.return_value = _response(
            {"errcode": 40003, "errmsg": "invalid userid"}
        )
        result = client.send_aibot_markdown(
            "wo-user-1", "hello", "bid-1", "sec-1",
        )
        assert result["success"] is False
        assert result["error"] == "invalid userid"

    @patch(f"{MODULE}.requests.post")
    @patch(f"{MODULE}.fetch_bot_token")
    def test_network_error_returns_failure(
        self, mock_fetch_token, mock_post
    ):
        mock_fetch_token.return_value = "tok-1"
        mock_post.side_effect = requests.exceptions.ConnectionError("down")
        result = client.send_aibot_markdown(
            "wo-user-1", "hello", "bid-1", "sec-1",
        )
        assert result["success"] is False
