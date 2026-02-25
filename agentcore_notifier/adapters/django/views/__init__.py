"""Views for agentcore_notifier API."""
from agentcore_notifier.adapters.django.views.stats import (
    AdminNotificationRecordListView,
    AdminNotificationStatsView,
)
from agentcore_notifier.adapters.django.views.config import (
    GlobalConfigView,
    SilenceRulesView,
)
from agentcore_notifier.adapters.django.views.channels import (
    NotificationChannelListView,
    NotificationChannelDetailView,
    ChannelValidateView,
)

__all__ = [
    "AdminNotificationStatsView",
    "AdminNotificationRecordListView",
    "GlobalConfigView",
    "SilenceRulesView",
    "NotificationChannelListView",
    "NotificationChannelDetailView",
    "ChannelValidateView",
]
