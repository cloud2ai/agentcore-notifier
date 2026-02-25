"""
Notification statistics for admin API.
Series: by day = 24 hours (0-23), by month = 30 days, by year = 12 months;
all buckets always present, fill 0 when no data.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.db.models import Count, Q
from django.db.models.functions import ExtractHour, ExtractMonth, TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from agentcore_notifier.adapters.django.models import NotificationRecord
from agentcore_notifier.constants import PROVIDER_DISPLAY_NAMES, Status


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = parse_datetime(value)
        if dt:
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        return timezone.make_aware(
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except (ValueError, TypeError):
        return None


def _parse_end_date(value: Optional[str]) -> Optional[datetime]:
    dt = _parse_date(value)
    if dt is None:
        return None
    s = (value or "").strip()
    if "T" not in s and " " not in s and len(s) <= 10:
        return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def get_notification_stats_from_query(
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build stats: summary, by_source, by_provider.
    Optional series (time buckets).
    """
    start_date = _parse_date(params.get("start_date"))
    end_date = _parse_end_date(params.get("end_date"))
    user_id = params.get("user_id")
    granularity = (params.get("granularity") or "").strip().lower()

    qs = NotificationRecord.objects.all()
    if user_id is not None:
        qs = qs.filter(user_id=user_id)
    if start_date:
        qs = qs.filter(created_at__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__lte=end_date)

    summary_agg = qs.aggregate(
        total=Count("id"),
        total_sent=Count("id", filter=Q(status=Status.SUCCESS)),
        total_failed=Count("id", filter=Q(status=Status.FAILED)),
        total_merged=Count("id", filter=Q(status=Status.MERGED)),
        total_silenced=Count("id", filter=Q(status=Status.SILENCED)),
        total_pending=Count("id", filter=Q(status=Status.PENDING)),
    )
    summary = {
        "total": summary_agg["total"] or 0,
        "total_sent": summary_agg["total_sent"] or 0,
        "total_failed": summary_agg["total_failed"] or 0,
        "total_merged": summary_agg["total_merged"] or 0,
        "total_silenced": summary_agg["total_silenced"] or 0,
        "total_pending": summary_agg["total_pending"] or 0,
    }

    by_source = list(
        qs.values("source_app", "source_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    by_provider_qs = (
        qs.values("provider_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    by_provider = []
    for row in by_provider_qs:
        pt = row["provider_type"]
        by_provider.append({
            "provider_type": pt,
            "provider_display_name": PROVIDER_DISPLAY_NAMES.get(pt, pt),
            "count": row["count"],
        })

    result = {
        "summary": summary,
        "by_source": by_source,
        "by_provider": by_provider,
    }

    if granularity in ("day", "month", "year"):
        result["series"] = _build_series_fixed_buckets(
            qs, granularity, start_date, end_date
        )

    return result


def _build_series_fixed_buckets(
    qs,
    granularity: str,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> List[Dict[str, Any]]:
    """
    Build series with fixed buckets; fill 0 for missing buckets.
    day -> 24 hours (0-23); month -> 30 days; year -> 12 months.
    """
    tz = timezone.get_current_timezone()
    if not start_date and end_date:
        start_date = end_date
    if not end_date and start_date:
        end_date = start_date
    if not end_date:
        end_date = timezone.now()
    if not start_date:
        start_date = end_date

    if granularity == "day":
        day_start = start_date.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if timezone.is_naive(day_start):
            day_start = timezone.make_aware(day_start, tz)
        day_qs = qs.filter(
            created_at__gte=day_start,
            created_at__lt=day_start + timedelta(days=1),
        )
        hour_counts = dict(
            day_qs.annotate(hour=ExtractHour("created_at"))
            .values("hour")
            .annotate(count=Count("id"))
            .values_list("hour", "count")
        )
        hour_success = dict(
            day_qs.filter(status=Status.SUCCESS)
            .annotate(hour=ExtractHour("created_at"))
            .values("hour")
            .annotate(count=Count("id"))
            .values_list("hour", "count")
        )
        hour_failed = dict(
            day_qs.filter(status=Status.FAILED)
            .annotate(hour=ExtractHour("created_at"))
            .values("hour")
            .annotate(count=Count("id"))
            .values_list("hour", "count")
        )
        return [
            {
                "bucket": f"{h:02d}:00",
                "count": hour_counts.get(h, 0),
                "success": hour_success.get(h, 0),
                "failed": hour_failed.get(h, 0),
            }
            for h in range(24)
        ]

    if granularity == "month":
        end_d = end_date.date() if hasattr(end_date, "date") else end_date
        start_d = end_d - timedelta(days=29)
        day_list = [start_d + timedelta(days=i) for i in range(30)]
        rows = list(
            qs.annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(count=Count("id"))
            .values_list("d", "count")
        )
        date_counts = {}
        for d_val, cnt in rows:
            if d_val is None:
                continue
            d_date = d_val.date() if hasattr(d_val, "date") else d_val
            date_counts[d_date] = cnt
        return [
            {"bucket": d.isoformat(), "count": date_counts.get(d, 0)}
            for d in day_list
        ]

    if granularity == "year":
        year = (
            end_date.year
            if hasattr(end_date, "year")
            else timezone.now().year
        )
        month_counts = dict(
            qs.annotate(month=ExtractMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
            .values_list("month", "count")
        )
        month_labels = [
            "01", "02", "03", "04", "05", "06",
            "07", "08", "09", "10", "11", "12",
        ]
        return [
            {
                "bucket": f"{year}-{month_labels[m-1]}",
                "count": month_counts.get(m, 0),
            }
            for m in range(1, 13)
        ]

    return []


def get_notification_record_list_from_query(
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Paginated list of NotificationRecord with filters."""
    page = max(1, int(params.get("page") or 1))
    page_size = min(100, max(1, int(params.get("page_size") or 20)))
    start_date = _parse_date(params.get("start_date"))
    end_date = _parse_end_date(params.get("end_date"))

    qs = (
        NotificationRecord.objects.all()
        .select_related("user")
        .order_by("-created_at")
    )
    if params.get("source_app"):
        qs = qs.filter(source_app=params["source_app"])
    if params.get("source_type"):
        qs = qs.filter(source_type=params["source_type"])
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    if params.get("user_id") is not None:
        qs = qs.filter(user_id=params["user_id"])
    if start_date:
        qs = qs.filter(created_at__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__lte=end_date)

    total = qs.count()
    start = (page - 1) * page_size
    records = list(qs[start : start + page_size])
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": records,
    }
