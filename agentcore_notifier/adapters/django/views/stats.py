"""Stats and record list API views."""
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from agentcore_notifier.adapters.django.services.notification_stats import (
    get_notification_record_list_from_query,
    get_notification_stats_from_query,
    get_notification_user_list,
)
from agentcore_notifier.constants import PROVIDER_DISPLAY_NAMES


class AdminNotificationStatsView(APIView):
    """
    GET: Notification statistics (summary, by_source, by_provider).
    Optional series for time buckets.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        data = get_notification_stats_from_query(request.query_params)
        return Response(data)


class AdminNotificationRecordListView(APIView):
    """GET: Paginated notification records list."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        data = get_notification_record_list_from_query(request.query_params)
        results = data.get("results", [])
        out = []
        for r in results:
            pt = r.provider_type
            out.append({
                "uuid": str(r.uuid),
                "source_app": r.source_app,
                "source_type": r.source_type,
                "source_id": r.source_id,
                "provider_type": pt,
                "provider_display_name": PROVIDER_DISPLAY_NAMES.get(pt, pt),
                "status": r.status,
                "created_at": r.created_at,
                "sent_at": r.sent_at,
                "user_id": r.user_id,
            })
        data["results"] = out
        return Response(data)


class AdminNotificationUserListView(APIView):
    """
    GET: List users that have at least one notification record.
    Used for stats/records user scope dropdown. Returns [{"user_id": int, "display": str}].
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        data = get_notification_user_list()
        return Response(data)
