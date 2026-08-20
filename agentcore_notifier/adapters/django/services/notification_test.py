"""
Ad-hoc "does this channel actually work" test send for feishu_app and
wecom_bot channels.

Both types are entirely scan-driven with no manual config to validate
before creation the way webhook/email channels can (see
_validate_webhook_config/_validate_email_config) — a real notification
was previously the first and only way to find out a scan actually
worked. One shared function so the admin console (testing any
channel by uuid) and the user-facing settings page (testing only
one's own) don't each reimplement the same per-type send/fallback
logic.

Every actual send attempt (past the pre-flight config checks — an
early "this channel has no open_id at all" isn't a send attempt) gets
a NotificationRecord the same way _validate_webhook_config/
_validate_email_config do, so a test send shows up in usage stats
like any other notification instead of being invisible.
"""
import logging
from typing import Any, Dict

from django.utils import timezone

from agentcore_notifier.constants import Provider, Status

from ..models import NotificationChannel, NotificationRecord
from .feishu_app.client import send_card_dm
from .wecom.client import send_aibot_markdown

logger = logging.getLogger(__name__)

SOURCE_APP_CHANNEL_TEST = "agentcore_notifier"
SOURCE_TYPE_CHANNEL_TEST = "channel_test"

TEST_MARKDOWN_CONTENT = (
    "**测试消息**\n\n这是一条测试消息，收到说明这个渠道配置正确。"
)


def _test_card() -> Dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "测试消息"},
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "这是一条测试消息，收到说明这个渠道配置正确。",
                },
            },
        ],
    }


def _record_test_send(
    channel: NotificationChannel,
    provider_type: str,
    payload: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    """Best-effort — a recording failure must never take down the
    actual test-send response, same guarantee
    _validate_webhook_config's own try/except gives."""
    record_status = Status.SUCCESS if result.get("success") else Status.FAILED
    try:
        rec = NotificationRecord.objects.create(
            source_app=SOURCE_APP_CHANNEL_TEST,
            source_type=SOURCE_TYPE_CHANNEL_TEST,
            source_id="",
            channel=channel.channel_type,
            channel_link_id=channel.id,
            provider_type=provider_type,
            user_id=channel.user_id,
            payload=payload,
            status=record_status,
            response=result.get("response"),
            error_message=result.get("error") or "",
            sent_at=(
                timezone.now() if record_status == Status.SUCCESS else None
            ),
        )
        logger.info(
            f"Channel test-send record created uuid={rec.uuid} "
            f"channel={channel.uuid} status={record_status}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to record channel test send: {e}", exc_info=True,
        )


def _global_feishu_app_credentials():
    """Same lookup as trendforge.services.notification_card's
    _get_global_app_config, duplicated here rather than imported —
    trendforge depends on this submodule, not the other way around."""
    channel = NotificationChannel.objects.filter(
        channel_type=NotificationChannel.TYPE_FEISHU_APP,
        user__isnull=True,
        is_active=True,
    ).first()
    if not channel or not isinstance(channel.config, dict):
        return None
    app_id = (channel.config.get("app_id") or "").strip()
    app_secret = (channel.config.get("app_secret") or "").strip()
    if not (app_id and app_secret):
        return None
    return app_id, app_secret


def _send_test_feishu(channel: NotificationChannel) -> Dict[str, Any]:
    if channel.user_id is None:
        # The global row has no personal open_id of its own to send a
        # DM to — testing "does the shared app work" only makes sense
        # through a specific bound person's channel, which already
        # falls back to these same credentials below. Never reaches a
        # real send, so nothing to record.
        return {
            "success": False,
            "response": None,
            "error": (
                "全局应用没有绑定的个人身份，无法直接测试；"
                "请通过某个已绑定用户自己的渠道测试。"
            ),
        }

    cfg = channel.config if isinstance(channel.config, dict) else {}
    app_id = (cfg.get("app_id") or "").strip()
    app_secret = (cfg.get("app_secret") or "").strip()
    open_id = (cfg.get("open_id") or "").strip()

    if not open_id:
        return {
            "success": False,
            "response": None,
            "error": "该渠道还没有绑定飞书身份，无法测试。",
        }

    if not (app_id and app_secret):
        # A "bind to the shared app" row (feishu_bind.py's
        # FeishuAppBindCallbackView) carries only open_id/union_id/
        # tenant_key, never its own credentials — borrow the global
        # app's, the same way notify_draft_pending_review's fallback
        # path does.
        global_credentials = _global_feishu_app_credentials()
        if not global_credentials:
            return {
                "success": False,
                "response": None,
                "error": "还没有配置全局飞书应用，无法测试。",
            }
        app_id, app_secret = global_credentials

    payload = _test_card()
    result = send_card_dm(open_id, payload, app_id, app_secret)
    _record_test_send(channel, Provider.FEISHU, payload, result)
    return result


def _send_test_wecom(channel: NotificationChannel) -> Dict[str, Any]:
    cfg = channel.config if isinstance(channel.config, dict) else {}
    bot_id = (cfg.get("bot_id") or "").strip()
    secret = (cfg.get("secret") or "").strip()
    userid = (cfg.get("userid") or "").strip()
    if not (bot_id and secret and userid):
        # Never reaches a real send, so nothing to record — same rule
        # as the missing-open_id case above.
        return {
            "success": False,
            "response": None,
            "error": "该渠道配置不完整，无法测试。",
        }
    payload = {
        "chat_id": userid,
        "msg_type": "markdown",
        "markdown": {"content": TEST_MARKDOWN_CONTENT},
    }
    result = send_aibot_markdown(userid, TEST_MARKDOWN_CONTENT, bot_id, secret)
    _record_test_send(channel, Provider.WECOM, payload, result)
    return result


def send_test_message(channel: NotificationChannel) -> Dict[str, Any]:
    """Returns {success, response, error} — same shape as
    send_card_dm/send_aibot_markdown, so callers don't need a third
    convention."""
    if channel.channel_type == NotificationChannel.TYPE_FEISHU_APP:
        return _send_test_feishu(channel)
    if channel.channel_type == NotificationChannel.TYPE_WECOM_BOT:
        return _send_test_wecom(channel)
    return {
        "success": False,
        "response": None,
        "error": f"暂不支持测试该渠道类型：{channel.channel_type}",
    }
