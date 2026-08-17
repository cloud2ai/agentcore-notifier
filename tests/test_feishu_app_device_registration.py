"""Tests for feishu_app.device_registration — begin/poll against the
device-flow app-registration endpoint."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from agentcore_notifier.adapters.django.services.feishu_app import (
    device_registration as dr,
)

MODULE = (
    "agentcore_notifier.adapters.django.services.feishu_app."
    "device_registration"
)


def _response(body, status_code=200):
    """status_code=400 by default for a real requests.Response would
    raise on .raise_for_status() — reproduce that exactly (not a bare
    no-op mock) so a regression to calling it would fail these tests,
    not just live traffic. Confirmed live: Feishu's poll endpoint
    responds HTTP 400 for authorization_pending/slow_down/
    access_denied/expired_token — those are expected control-flow
    states, not request failures, which is why the real code must
    never call raise_for_status() on this endpoint."""
    resp = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Client Error"
        )
    else:
        resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


@pytest.mark.unit
class TestBeginAppRegistration:
    @patch(f"{MODULE}.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = _response(
            {
                "device_code": "dc-1",
                "user_code": "uc-1",
                "verification_uri_complete": (
                    "https://open.feishu.cn/page/launcher?user_code=uc-1"
                ),
                "interval": 5,
                "expire_in": 600,
            }
        )
        result = dr.begin_app_registration()
        assert result["device_code"] == "dc-1"
        assert result["interval"] == 5
        assert result["expires_in"] == 600
        call = mock_post.call_args
        assert call.kwargs["data"]["action"] == "begin"
        assert call.kwargs["data"]["archetype"] == "PersonalAgent"

    @patch(f"{MODULE}.requests.post")
    def test_defaults_missing_interval_and_expiry(self, mock_post):
        mock_post.return_value = _response(
            {
                "device_code": "dc-1",
                "verification_uri_complete": "https://example/x",
            }
        )
        result = dr.begin_app_registration()
        assert result["interval"] == dr.DEFAULT_POLL_INTERVAL_SECONDS
        assert result["expires_in"] == dr.DEFAULT_EXPIRE_IN_SECONDS

    @patch(f"{MODULE}.requests.post")
    def test_malformed_response_returns_none(self, mock_post):
        mock_post.return_value = _response({"unexpected": "shape"})
        assert dr.begin_app_registration() is None

    @patch(f"{MODULE}.requests.post", side_effect=Exception("boom"))
    def test_network_error_returns_none(self, mock_post):
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError("down")
        assert dr.begin_app_registration() is None


@pytest.mark.unit
class TestPollAppRegistration:
    @patch(f"{MODULE}.requests.post")
    def test_pending(self, mock_post):
        # status_code=400 — matches the real API exactly (see _response's
        # docstring); this is the case that broke live before the
        # raise_for_status() call was removed from the source.
        mock_post.return_value = _response(
            {"error": "authorization_pending"}, status_code=400,
        )
        assert dr.poll_app_registration("dc-1") == {"status": "pending"}

    @patch(f"{MODULE}.requests.post")
    def test_slow_down(self, mock_post):
        mock_post.return_value = _response(
            {"error": "slow_down"}, status_code=400,
        )
        assert dr.poll_app_registration("dc-1") == {
            "status": "slow_down"
        }

    @patch(f"{MODULE}.requests.post")
    def test_denied(self, mock_post):
        mock_post.return_value = _response(
            {"error": "access_denied"}, status_code=400,
        )
        assert dr.poll_app_registration("dc-1") == {"status": "denied"}

    @patch(f"{MODULE}.requests.post")
    def test_expired(self, mock_post):
        mock_post.return_value = _response(
            {"error": "expired_token"}, status_code=400,
        )
        assert dr.poll_app_registration("dc-1") == {"status": "expired"}

    @patch(f"{MODULE}.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = _response(
            {
                "error": "",
                "client_id": "cli_1",
                "client_secret": "secret_1",
                "user_info": {
                    "open_id": "ou_1",
                    "tenant_brand": "feishu",
                },
            }
        )
        result = dr.poll_app_registration("dc-1")
        assert result == {
            "status": "success",
            "client_id": "cli_1",
            "client_secret": "secret_1",
            "open_id": "ou_1",
            "tenant_brand": "feishu",
        }

    @patch(f"{MODULE}.requests.post")
    def test_success_without_credentials_is_an_error(self, mock_post):
        mock_post.return_value = _response({"error": ""})
        result = dr.poll_app_registration("dc-1")
        assert result["status"] == "error"

    @patch(f"{MODULE}.requests.post")
    def test_unrecognized_error_is_passed_through_as_error(
        self, mock_post
    ):
        mock_post.return_value = _response(
            {"error": "something_new", "error_description": "??"}
        )
        result = dr.poll_app_registration("dc-1")
        assert result["status"] == "error"
        assert result["error"] == "something_new"

    @patch(f"{MODULE}.requests.post")
    def test_network_error_returns_error_status_not_raise(
        self, mock_post
    ):
        import requests

        mock_post.side_effect = requests.exceptions.Timeout("slow")
        result = dr.poll_app_registration("dc-1")
        assert result["status"] == "error"
