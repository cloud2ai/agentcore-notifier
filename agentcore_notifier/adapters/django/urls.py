"""
URL configuration for agentcore_notifier (stats and config API).
Include under admin prefix, e.g.:
  path('api/v1/admin/notifications/', include(...))
"""
from django.urls import path

from agentcore_notifier.adapters.django.views import (
    AdminNotificationRecordDetailView,
    AdminNotificationRecordListView,
    AdminNotificationStatsView,
    AdminNotificationUserListView,
    GlobalConfigView,
    SilenceRulesView,
    NotificationChannelListView,
    NotificationChannelDetailView,
    ChannelValidateView,
    FeishuAppRegistrationStartView,
    FeishuAppRegistrationPollView,
)

urlpatterns = [
    path(
        "notification-stats/",
        AdminNotificationStatsView.as_view(),
        name="notifier-stats",
    ),
    path(
        "notification-records/",
        AdminNotificationRecordListView.as_view(),
        name="notifier-records",
    ),
    path(
        "notification-records/<uuid:uuid>/",
        AdminNotificationRecordDetailView.as_view(),
        name="notifier-record-detail",
    ),
    path(
        "users/",
        AdminNotificationUserListView.as_view(),
        name="notifier-users",
    ),
    path(
        "channels/",
        NotificationChannelListView.as_view(),
        name="notifier-channels-list",
    ),
    path(
        "channels/validate/",
        ChannelValidateView.as_view(),
        name="notifier-channels-validate",
    ),
    path(
        "channels/<uuid:uuid>/",
        NotificationChannelDetailView.as_view(),
        name="notifier-channels-detail",
    ),
    path(
        "channels/feishu-app/register/start/",
        FeishuAppRegistrationStartView.as_view(),
        name="notifier-feishu-app-register-start",
    ),
    path(
        "channels/feishu-app/register/poll/",
        FeishuAppRegistrationPollView.as_view(),
        name="notifier-feishu-app-register-poll",
    ),
    path("global/", GlobalConfigView.as_view(), name="notifier-global"),
    path(
        "silence-rules/",
        SilenceRulesView.as_view(),
        name="notifier-silence-rules",
    ),
]
