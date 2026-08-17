"""Tests for feishu_app.token — tenant_access_token fetch + cache."""
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from agentcore_notifier.adapters.django.services.feishu_app.token import (
    fetch_tenant_access_token,
    get_tenant_access_token,
    invalidate_tenant_access_token,
)


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def _response(code=0, token="tok-abc", expire=7200):
    body = {"code": code, "tenant_access_token": token, "expire": expire}
    if code != 0:
        body["msg"] = "boom"
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


@pytest.mark.unit
class TestFetchTenantAccessToken:
    @patch(
        "agentcore_notifier.adapters.django.services.feishu_app.token."
        "requests.post"
    )
    def test_success_caches_token(self, mock_post):
        mock_post.return_value = _response()
        token = fetch_tenant_access_token("app-1", "secret-1")
        assert token == "tok-abc"
        assert cache.get(
            "agentcore_notifier:feishu_tenant_access_token:app-1"
        ) == "tok-abc"

    @patch(
        "agentcore_notifier.adapters.django.services.feishu_app.token."
        "requests.post"
    )
    def test_business_error_returns_none_and_does_not_cache(
        self, mock_post
    ):
        mock_post.return_value = _response(code=99991661)
        token = fetch_tenant_access_token("app-1", "secret-1")
        assert token is None
        assert cache.get(
            "agentcore_notifier:feishu_tenant_access_token:app-1"
        ) is None

    @patch(
        "agentcore_notifier.adapters.django.services.feishu_app.token."
        "requests.post"
    )
    def test_malformed_response_returns_none(self, mock_post):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"code": 0}  # missing token/expire
        mock_post.return_value = resp
        assert fetch_tenant_access_token("app-1", "secret-1") is None

    @patch(
        "agentcore_notifier.adapters.django.services.feishu_app.token."
        "requests.post",
        side_effect=Exception("network down"),
    )
    def test_request_exception_returns_none(self, mock_post):
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError("down")
        assert fetch_tenant_access_token("app-1", "secret-1") is None


@pytest.mark.unit
class TestGetTenantAccessToken:
    @patch(
        "agentcore_notifier.adapters.django.services.feishu_app.token."
        "fetch_tenant_access_token"
    )
    def test_cache_hit_skips_fetch(self, mock_fetch):
        cache.set(
            "agentcore_notifier:feishu_tenant_access_token:app-1",
            "cached-tok",
        )
        token = get_tenant_access_token("app-1", "secret-1")
        assert token == "cached-tok"
        mock_fetch.assert_not_called()

    @patch(
        "agentcore_notifier.adapters.django.services.feishu_app.token."
        "fetch_tenant_access_token",
        return_value="fresh-tok",
    )
    def test_cache_miss_fetches(self, mock_fetch):
        token = get_tenant_access_token("app-1", "secret-1")
        assert token == "fresh-tok"
        mock_fetch.assert_called_once_with("app-1", "secret-1")

    def test_different_app_ids_do_not_share_cache_slot(self):
        cache.set(
            "agentcore_notifier:feishu_tenant_access_token:app-1", "tok-1"
        )
        cache.set(
            "agentcore_notifier:feishu_tenant_access_token:app-2", "tok-2"
        )
        assert get_tenant_access_token("app-1", "s") == "tok-1"
        assert get_tenant_access_token("app-2", "s") == "tok-2"


@pytest.mark.unit
class TestInvalidateTenantAccessToken:
    def test_clears_cached_value(self):
        cache.set(
            "agentcore_notifier:feishu_tenant_access_token:app-1", "tok"
        )
        invalidate_tenant_access_token("app-1")
        assert cache.get(
            "agentcore_notifier:feishu_tenant_access_token:app-1"
        ) is None
