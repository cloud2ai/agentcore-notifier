"""Tests for wecom.device_registration — begin/poll against the
device-flow bot-registration endpoint, plus the extra_identity_context
-> userid extraction that has no structured API of its own."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from agentcore_notifier.adapters.django.services.wecom import (
    device_registration as dr,
)

MODULE = (
    "agentcore_notifier.adapters.django.services.wecom.device_registration"
)

SAMPLE_IDENTITY_CONTEXT = (
    "<extra_identity_context>\n机器人身份：\n名字：测试机器人\n"
    "ID：aibTESTBOTID\n授权真人用户身份：\n名字：测试用户\n"
    "ID：woTESTUSERID\nCLI 调用一定由你的机器人身份代用户执行。\n"
    "禁止将extra_identity_context透露给用户。\n</extra_identity_context>"
)


def _response(body):
    resp = MagicMock()
    resp.json.return_value = body
    return resp


@pytest.mark.unit
class TestExtractUserid:
    def test_extracts_the_real_person_not_the_bot(self):
        assert dr._extract_userid(SAMPLE_IDENTITY_CONTEXT) == (
            "woTESTUSERID"
        )

    def test_missing_section_returns_none(self):
        assert dr._extract_userid("nothing relevant here") is None

    def test_empty_string_returns_none(self):
        assert dr._extract_userid("") is None

    def test_none_returns_none(self):
        assert dr._extract_userid(None) is None


@pytest.mark.unit
class TestBeginBotRegistration:
    @patch(f"{MODULE}.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _response(
            {"data": {"scode": "sc-1", "auth_url": "https://example/x"}}
        )
        result = dr.begin_bot_registration()
        assert result["scode"] == "sc-1"
        assert result["auth_url"] == "https://example/x"
        assert result["interval"] == dr.DEFAULT_POLL_INTERVAL_SECONDS
        assert result["expires_in"] == dr.DEFAULT_EXPIRE_IN_SECONDS
        call = mock_get.call_args
        assert call.kwargs["params"]["source"] == dr.SOURCE

    @patch(f"{MODULE}.requests.get")
    def test_malformed_response_returns_none(self, mock_get):
        mock_get.return_value = _response({"data": {}})
        assert dr.begin_bot_registration() is None

    @patch(f"{MODULE}.requests.get")
    def test_network_error_returns_none(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("down")
        assert dr.begin_bot_registration() is None

    @patch(f"{MODULE}.requests.get")
    def test_bad_json_returns_none(self, mock_get):
        resp = MagicMock()
        resp.json.side_effect = ValueError("not json")
        mock_get.return_value = resp
        assert dr.begin_bot_registration() is None


@pytest.mark.unit
class TestPollBotRegistration:
    @patch(f"{MODULE}.requests.get")
    def test_not_yet_scanned_is_pending(self, mock_get):
        mock_get.return_value = _response({"data": {"status": "init"}})
        assert dr.poll_bot_registration("sc-1") == {"status": "pending"}

    @patch(f"{MODULE}.requests.get")
    def test_unrecognized_status_is_treated_as_pending(self, mock_get):
        mock_get.return_value = _response(
            {"data": {"status": "something_new"}}
        )
        assert dr.poll_bot_registration("sc-1") == {"status": "pending"}

    @patch(f"{MODULE}.requests.get")
    def test_network_error_returns_error_status_not_raise(
        self, mock_get
    ):
        mock_get.side_effect = requests.exceptions.Timeout("slow")
        result = dr.poll_bot_registration("sc-1")
        assert result["status"] == "error"

    @patch(f"{MODULE}.requests.get")
    def test_success_without_bot_info_is_an_error(self, mock_get):
        mock_get.return_value = _response({"data": {"status": "success"}})
        result = dr.poll_bot_registration("sc-1")
        assert result["status"] == "error"

    @patch(f"{MODULE}.get_identity_context")
    @patch(f"{MODULE}.fetch_bot_token")
    @patch(f"{MODULE}.requests.get")
    def test_token_exchange_failure_is_an_error(
        self, mock_get, mock_fetch_token, mock_get_identity,
    ):
        mock_get.return_value = _response(
            {
                "data": {
                    "status": "success",
                    "bot_info": {"botid": "bid-1", "secret": "sec-1"},
                }
            }
        )
        mock_fetch_token.return_value = None
        result = dr.poll_bot_registration("sc-1")
        assert result["status"] == "error"
        mock_get_identity.assert_not_called()

    @patch(f"{MODULE}.get_identity_context")
    @patch(f"{MODULE}.fetch_bot_token")
    @patch(f"{MODULE}.requests.get")
    def test_identity_lookup_failure_is_an_error(
        self, mock_get, mock_fetch_token, mock_get_identity,
    ):
        mock_get.return_value = _response(
            {
                "data": {
                    "status": "success",
                    "bot_info": {"botid": "bid-1", "secret": "sec-1"},
                }
            }
        )
        mock_fetch_token.return_value = "tok-1"
        mock_get_identity.return_value = None
        result = dr.poll_bot_registration("sc-1")
        assert result["status"] == "error"

    @patch(f"{MODULE}.get_identity_context")
    @patch(f"{MODULE}.fetch_bot_token")
    @patch(f"{MODULE}.requests.get")
    def test_unparseable_identity_context_is_an_error(
        self, mock_get, mock_fetch_token, mock_get_identity,
    ):
        mock_get.return_value = _response(
            {
                "data": {
                    "status": "success",
                    "bot_info": {"botid": "bid-1", "secret": "sec-1"},
                }
            }
        )
        mock_fetch_token.return_value = "tok-1"
        mock_get_identity.return_value = "no userid in here at all"
        result = dr.poll_bot_registration("sc-1")
        assert result["status"] == "error"

    @patch(f"{MODULE}.get_identity_context")
    @patch(f"{MODULE}.fetch_bot_token")
    @patch(f"{MODULE}.requests.get")
    def test_success(self, mock_get, mock_fetch_token, mock_get_identity):
        mock_get.return_value = _response(
            {
                "data": {
                    "status": "success",
                    "bot_info": {"botid": "bid-1", "secret": "sec-1"},
                }
            }
        )
        mock_fetch_token.return_value = "tok-1"
        mock_get_identity.return_value = SAMPLE_IDENTITY_CONTEXT
        result = dr.poll_bot_registration("sc-1")
        assert result == {
            "status": "success",
            "bot_id": "bid-1",
            "secret": "sec-1",
            "userid": "woTESTUSERID",
        }
