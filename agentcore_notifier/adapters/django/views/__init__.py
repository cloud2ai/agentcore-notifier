"""Views for agentcore_notifier API."""
from agentcore_notifier.adapters.django.views.stats import (
    AdminNotificationRecordDetailView,
    AdminNotificationRecordListView,
    AdminNotificationStatsView,
    AdminNotificationUserListView,
)
from agentcore_notifier.adapters.django.views.config import (
    GlobalConfigView,
    SilenceRulesView,
)
from agentcore_notifier.adapters.django.views.channels import (
    NotificationChannelListView,
    NotificationChannelDetailView,
    NotificationChannelTestView,
    ChannelValidateView,
    FeishuAppRegistrationStartView,
    FeishuAppRegistrationPollView,
)

__all__ = [
    "AdminNotificationStatsView",
    "AdminNotificationRecordDetailView",
    "AdminNotificationRecordListView",
    "AdminNotificationUserListView",
    "GlobalConfigView",
    "SilenceRulesView",
    "NotificationChannelListView",
    "NotificationChannelDetailView",
    "NotificationChannelTestView",
    "ChannelValidateView",
    "FeishuAppRegistrationStartView",
    "FeishuAppRegistrationPollView",
]
