"""Tests for feishu_app.oauth — the QR-bind code-for-identity exchange."""
from unittest.mock import MagicMock, patch

import pytest

from agentcore_notifier.adapters.django.services.feishu_app.oauth import (
    build_authorize_url,
    exchange_code_for_identity,
)

MODULE = "agentcore_notifier.adapters.django.services.feishu_app.oauth"


def _response(code=0, **data_fields):
    body = {"code": code}
    if code == 0:
        body["data"] = {"open_id": "ou_default", **data_fields}
    else:
        body["msg"] = "boom"
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


class TestBuildAuthorizeUrl:
    def test_includes_required_params(self):
        url = build_authorize_url(
            "cli_abc", "https://example.com/callback", "state-123"
        )
        assert url.startswith(
            "https://open.feishu.cn/open-apis/authen/v1/index?"
        )
        assert "app_id=cli_abc" in url
        assert "state=state-123" in url
        assert "redirect_uri=" in url

    def test_redirect_uri_is_url_encoded(self):
        url = build_authorize_url(
            "cli_abc", "https://example.com/cb?a=1&b=2", "s"
        )
        assert "https://example.com/cb?a=1&b=2" not in url
        assert "redirect_uri=https%3A%2F%2Fexample.com" in url


@pytest.mark.unit
class TestExchangeCodeForIdentity:
    @patch(f"{MODULE}.get_app_access_token", return_value="app-tok")
    @patch(f"{MODULE}.requests.post")
    def test_success_returns_identity(self, mock_post, mock_token):
        mock_post.return_value = _response(
            open_id="ou_123", union_id="un_123", tenant_key="tk_1",
            name="Alice",
        )
        identity = exchange_code_for_identity("code-1", "app-1", "secret-1")
        assert identity == {
            "open_id": "ou_123",
            "union_id": "un_123",
            "tenant_key": "tk_1",
            "name": "Alice",
        }
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer app-tok"
        assert mock_post.call_args.kwargs["json"] == {
            "grant_type": "authorization_code",
            "code": "code-1",
        }

    @patch(f"{MODULE}.get_app_access_token", return_value=None)
    def test_no_app_access_token_fails_without_network_call(
        self, mock_token
    ):
        with patch(f"{MODULE}.requests.post") as mock_post:
            identity = exchange_code_for_identity(
                "code-1", "app-1", "secret-1"
            )
            assert identity is None
            mock_post.assert_not_called()

    @patch(f"{MODULE}.get_app_access_token", return_value="app-tok")
    @patch(f"{MODULE}.requests.post")
    def test_business_error_returns_none(self, mock_post, mock_token):
        mock_post.return_value = _response(code=20009)  # e.g. bad code
        assert (
            exchange_code_for_identity("bad-code", "app-1", "secret-1")
            is None
        )

    @patch(f"{MODULE}.get_app_access_token", return_value="app-tok")
    @patch(f"{MODULE}.requests.post")
    def test_missing_open_id_in_response_returns_none(
        self, mock_post, mock_token
    ):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"code": 0, "data": {}}
        mock_post.return_value = resp
        assert (
            exchange_code_for_identity("code-1", "app-1", "secret-1")
            is None
        )

    @patch(f"{MODULE}.get_app_access_token", return_value="app-tok")
    @patch(f"{MODULE}.requests.post")
    def test_network_failure_returns_none(self, mock_post, mock_token):
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError("down")
        assert (
            exchange_code_for_identity("code-1", "app-1", "secret-1")
            is None
        )

    @patch(f"{MODULE}.get_app_access_token", return_value="app-tok")
    @patch(f"{MODULE}.requests.post")
    def test_code_is_single_use_caller_must_not_retry_on_failure(
        self, mock_post, mock_token
    ):
        """Not a behavioral assertion on this function (it has no retry
        logic) — documents the contract so a future caller doesn't add
        a retry loop around a one-shot authorization code."""
        mock_post.return_value = _response(code=20009)
        exchange_code_for_identity("code-1", "app-1", "secret-1")
        assert mock_post.call_count == 1
