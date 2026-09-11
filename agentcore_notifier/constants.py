"""
Constants for agentcore_notifier.
"""


class Status:
    """Notification status constants."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    MERGED = "merged"
    SILENCED = "silenced"


class Provider:
    """Notification provider type constants."""

    FEISHU = "feishu"
    # WeCom is the preferred canonical provider type for WeCom webhook.
    # WECHAT is kept as a legacy compatibility alias because older configs
    # and integrations may still persist that value.
    WECOM = "wecom"
    WECHAT = "wechat"
    EMAIL = "email"


class Channel:
    """Notification channel constants."""

    WEBHOOK = "webhook"
    EMAIL = "email"
    SMS = "sms"
    # Feishu self-built app (im/v1/messages, tenant_access_token) — distinct
    # from WEBHOOK's custom-bot incoming webhook: this can DM a specific
    # person by open_id, not just post into a group. A channel row of this
    # type with user=None holds the tenant's app credentials; a row with
    # user=<someone> holds that person's open_id binding (see the OAuth QR
    # bind flow) and carries no credentials of its own.
    FEISHU_APP = "feishu_app"
    # WeCom AI Bot (qyapi.weixin.qq.com/cli message gateway) — DMs a
    # specific person by userid, bound by a QR device-flow scan that hands
    # back the bot's own botid/secret *and* the scanning user's userid
    # together, so every row of this type is per-user and self-contained.
    #
    # DEPRECATED in favour of WECOM_APP; kept working for channels already
    # configured against it. WeCom grants an AI Bot's message permission
    # for only **7 days**, after which every send fails with 850003
    # "authorization expired" until a human re-authorizes by hand from
    # 工作台 → 智能机器人.
    #
    # What makes that expiry worse than a plain limitation: nothing in the
    # API surfaces the remaining validity, and the bot's own credentials
    # keep working throughout — the token exchange and identity/whoami
    # both still succeed after it lapses — so no pre-send check can detect
    # it. Observed in production: a channel bound 08-19 was already
    # expired at its first real send on 08-27, and the next 104 sends over
    # two weeks all failed the same way. Prefer WECOM_APP for anything new.
    WECOM_BOT = "wecom_bot"
    # WeCom self-built app (cgi-bin/message/send, access_token) — WeCom's
    # analog of FEISHU_APP, and the recommended replacement for WECOM_BOT:
    # same ability to DM one person, without the 7-day grant. corp_secret
    # is a static credential and the access_token it mints refreshes
    # programmatically, like Feishu's tenant_access_token, so a channel
    # configured once keeps working with no human step. Config carries
    # corp_id / corp_secret / agent_id / touser.
    WECOM_APP = "wecom_app"


DEFAULT_SOURCE_APP = "unknown"
DEFAULT_PROVIDER_TYPE = Provider.FEISHU
DEFAULT_TIMEOUT = 10

CONFIG_KEY_WEBHOOK = "webhook"

FEISHU_PROVIDERS = [Provider.FEISHU, Provider.WECOM]

PROVIDER_DISPLAY_NAMES = {
    Provider.FEISHU: "飞书",
    Provider.WECOM: "WeCom",
    Provider.WECHAT: "WeChat Work",
    Provider.EMAIL: "Email",
}
