"""WeCom self-built app: token caching and app-message delivery.

This channel exists because its predecessor — the AI Bot behind a QR
device-flow scan — had its message permission granted for 7 days and
then failed every send with 850003 until a human re-authorized by hand.
The tests that matter here are the ones proving this path needs no such
human step: the token is cached and refreshed programmatically, and a
token WeCom rejects early is replaced rather than reused until its TTL
runs out.
"""
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from agentcore_notifier.adapters.django.services.wecom_app import (
    client,
    token as token_mod,
)

TOKEN_MODULE = (
    "agentcore_notifier.adapters.django.services.wecom_app.token"
)
CLIENT_MODULE = (
    "agentcore_notifier.adapters.django.services.wecom_app.client"
)

CORP = "corp-1"
SECRET = "secret-1"
AGENT = "1000002"
USER = "zhangsan"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _resp(payload, status_code=200):
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    m.status_code = status_code
    return m


@pytest.mark.unit
class TestAccessToken:
    @patch(f"{TOKEN_MODULE}.requests.get")
    def test_token_is_cached_so_a_second_send_costs_no_request(self, get):
        get.return_value = _resp(
            {"errcode": 0, "access_token": "tok-1", "expires_in": 7200}
        )

        first = token_mod.fetch_access_token(CORP, SECRET, AGENT)
        second = token_mod.fetch_access_token(CORP, SECRET, AGENT)

        assert first == second == "tok-1"
        assert get.call_count == 1, "the cached token was not reused"

    @patch(f"{TOKEN_MODULE}.requests.get")
    def test_cache_is_keyed_per_app(self, get):
        """WeCom mints a separate token per app and rejects one app's
        token used by another, so a single global slot would hand app B
        the token of app A."""
        get.side_effect = [
            _resp({"errcode": 0, "access_token": "tok-a", "expires_in": 7200}),
            _resp({"errcode": 0, "access_token": "tok-b", "expires_in": 7200}),
        ]

        a = token_mod.fetch_access_token(CORP, SECRET, "agent-a")
        b = token_mod.fetch_access_token(CORP, SECRET, "agent-b")

        assert (a, b) == ("tok-a", "tok-b")

    @patch(f"{TOKEN_MODULE}.requests.get")
    def test_business_error_returns_none_rather_than_raising(self, get):
        get.return_value = _resp({"errcode": 40001, "errmsg": "invalid secret"})

        assert token_mod.fetch_access_token(CORP, SECRET, AGENT) is None

    @patch(f"{TOKEN_MODULE}.requests.get")
    def test_incomplete_config_never_reaches_the_network(self, get):
        assert token_mod.fetch_access_token("", SECRET, AGENT) is None
        assert token_mod.fetch_access_token(CORP, "", AGENT) is None
        get.assert_not_called()

    @patch(f"{TOKEN_MODULE}.requests.get")
    def test_invalidate_forces_a_refetch(self, get):
        get.side_effect = [
            _resp({"errcode": 0, "access_token": "tok-1", "expires_in": 7200}),
            _resp({"errcode": 0, "access_token": "tok-2", "expires_in": 7200}),
        ]

        assert token_mod.fetch_access_token(CORP, SECRET, AGENT) == "tok-1"
        token_mod.invalidate_access_token(CORP, AGENT)
        assert token_mod.fetch_access_token(CORP, SECRET, AGENT) == "tok-2"


@pytest.mark.unit
class TestSendAppMarkdown:
    @patch(f"{CLIENT_MODULE}.fetch_access_token", return_value="tok-1")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_successful_send_targets_one_member(self, post, _tok):
        post.return_value = _resp({"errcode": 0, "errmsg": "ok"})

        result = client.send_app_markdown(
            USER, "# hi", CORP, SECRET, AGENT
        )

        assert result["success"] is True
        body = post.call_args.kwargs["json"]
        assert body["touser"] == USER, "not addressed to a single member"
        assert body["agentid"] == AGENT
        assert body["msgtype"] == "markdown"

    @patch(f"{CLIENT_MODULE}.invalidate_access_token")
    @patch(f"{CLIENT_MODULE}.fetch_access_token")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_a_rejected_token_is_refreshed_and_the_send_retried(
        self, post, tok, invalidate
    ):
        """WeCom may invalidate a token before its stated expiry. Without
        this the cache would keep serving the dead token until the TTL
        lapsed, failing every send in between."""
        tok.side_effect = ["stale", "fresh"]
        post.side_effect = [
            _resp({"errcode": 42001, "errmsg": "access_token expired"}),
            _resp({"errcode": 0, "errmsg": "ok"}),
        ]

        result = client.send_app_markdown(USER, "# hi", CORP, SECRET, AGENT)

        assert result["success"] is True
        invalidate.assert_called_once_with(CORP, AGENT)
        assert post.call_count == 2

    @patch(f"{CLIENT_MODULE}.fetch_access_token", return_value="tok-1")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_retry_happens_at_most_once(self, post, _tok):
        """A permanently rejected token must not loop."""
        post.return_value = _resp({"errcode": 42001, "errmsg": "expired"})

        result = client.send_app_markdown(USER, "# hi", CORP, SECRET, AGENT)

        assert result["success"] is False
        assert post.call_count == 2

    @patch(f"{CLIENT_MODULE}.fetch_access_token", return_value="tok-1")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_business_error_is_returned_not_raised(self, post, _tok):
        post.return_value = _resp({"errcode": 81013, "errmsg": "user not found"})

        result = client.send_app_markdown(USER, "# hi", CORP, SECRET, AGENT)

        assert result["success"] is False
        assert "81013" in result["error"]

    @patch(f"{CLIENT_MODULE}.fetch_access_token")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_incomplete_credentials_never_reach_the_network(self, post, tok):
        """A missing touser is NOT incomplete config — see
        TestRecipientFallback. Only the app credentials are required."""
        for args in (
            (USER, "# hi", "", SECRET, AGENT),
            (USER, "# hi", CORP, "", AGENT),
            (USER, "# hi", CORP, SECRET, ""),
        ):
            result = client.send_app_markdown(*args)
            assert result["success"] is False
        post.assert_not_called()
        tok.assert_not_called()


@pytest.mark.unit
class TestRecipientFallback:
    """touser is optional. WeCom requires one of touser/toparty/totag, and
    @all means "every member this app is visible to" — which the admin
    chose when creating the app, not the whole company. Requiring a
    UserID would make people hunt it down in 通讯录, where it is easily
    confused with a phone number or display name.
    """

    @patch(f"{CLIENT_MODULE}.fetch_access_token", return_value="tok-1")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_missing_touser_falls_back_to_all_members(self, post, _tok):
        post.return_value = _resp({"errcode": 0, "errmsg": "ok"})

        result = client.send_app_markdown("", "# hi", CORP, SECRET, AGENT)

        assert result["success"] is True
        assert post.call_args.kwargs["json"]["touser"] == client.ALL_MEMBERS

    @patch(f"{CLIENT_MODULE}.fetch_access_token", return_value="tok-1")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_whitespace_only_touser_is_treated_as_missing(self, post, _tok):
        post.return_value = _resp({"errcode": 0, "errmsg": "ok"})

        client.send_app_markdown("   ", "# hi", CORP, SECRET, AGENT)

        assert post.call_args.kwargs["json"]["touser"] == client.ALL_MEMBERS

    @patch(f"{CLIENT_MODULE}.fetch_access_token", return_value="tok-1")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_an_explicit_touser_still_wins(self, post, _tok):
        post.return_value = _resp({"errcode": 0, "errmsg": "ok"})

        client.send_app_markdown(USER, "# hi", CORP, SECRET, AGENT)

        assert post.call_args.kwargs["json"]["touser"] == USER

    @patch(f"{CLIENT_MODULE}.fetch_access_token")
    @patch(f"{CLIENT_MODULE}.requests.post")
    def test_the_app_credentials_are_still_required(self, post, tok):
        """Relaxing touser must not relax the rest — without an agent_id
        the request cannot be addressed at all."""
        for args in (
            ("", "# hi", "", SECRET, AGENT),
            ("", "# hi", CORP, "", AGENT),
            ("", "# hi", CORP, SECRET, ""),
        ):
            assert client.send_app_markdown(*args)["success"] is False
        post.assert_not_called()
        tok.assert_not_called()
