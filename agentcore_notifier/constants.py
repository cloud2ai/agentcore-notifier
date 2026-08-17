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
