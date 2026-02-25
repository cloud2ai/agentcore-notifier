"""
Email service for sending notifications via SMTP.
Reads config from NotificationChannel table (channel_type=email); sends using
smtplib and records NotificationRecord with channel=email.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from django.utils import timezone

from agentcore_notifier.adapters.django.models import (
    NotificationChannel,
    NotificationRecord,
)
from agentcore_notifier.constants import (
    Channel,
    DEFAULT_SOURCE_APP,
    Provider,
    Status,
)

logger = logging.getLogger(__name__)


def get_default_email_channel():
    """
    Get the email channel used for sending: among active channels, the one
    with smallest ordering (then earliest created_at).
    Returns (channel, config_dict) or (None, None).
    """
    qs = NotificationChannel.objects.filter(
        channel_type=NotificationChannel.TYPE_EMAIL,
        is_active=True,
    ).order_by("ordering", "created_at")
    channel = qs.first()
    if not channel or not channel.config:
        return None, None
    cfg = channel.config
    host = (cfg.get("smtp_host") or "").strip()
    if not host:
        return None, None
    config_dict = {
        "smtp_host": host,
        "smtp_port": int(cfg.get("smtp_port") or 587),
        "use_tls": cfg.get("use_tls", True),
        "smtp_user": (cfg.get("smtp_user") or "").strip() or None,
        "smtp_password": (cfg.get("smtp_password") or "").strip() or None,
        "from_email": (cfg.get("from_email") or "").strip(),
        "from_name": (cfg.get("from_name") or "").strip() or None,
        "subject_prefix": (cfg.get("subject_prefix") or "").strip() or None,
    }
    return channel, config_dict


class EmailService:
    """
    Service for sending email notifications.
    Config from NotificationChannel (channel_type=email); send via SMTP.
    """

    def get_email_channel_and_config(self):
        """Return (channel, config_dict) for the active email channel."""
        return get_default_email_channel()

    def _send_smtp(
        self,
        config: Dict[str, Any],
        subject: str,
        body: str,
        to_addrs: List[str],
    ) -> Dict[str, Any]:
        """Send one email via SMTP. Returns { success, response?, error? }."""
        from_addr = config.get("from_email") or ""
        from_name = config.get("from_name")
        if from_name:
            from_header = f"{from_name} <{from_addr}>"
        else:
            from_header = from_addr
        prefix = (config.get("subject_prefix") or "").strip()
        full_subject = f"{prefix} {subject}".strip() if prefix else subject
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = full_subject
        msg["From"] = from_header
        msg["To"] = ", ".join(to_addrs)
        host = config["smtp_host"]
        port = config["smtp_port"]
        use_tls = config.get("use_tls", True)
        try:
            smtp_class = smtplib.SMTP
            with smtp_class(host, port, timeout=30) as smtp:
                if use_tls:
                    smtp.starttls()
                user = config.get("smtp_user")
                password = config.get("smtp_password")
                if user and password:
                    smtp.login(user, password)
                smtp.sendmail(from_addr, to_addrs, msg.as_string())
            return {"success": True, "response": {"to": to_addrs}}
        except Exception as e:
            err = str(e)
            logger.warning(f"EmailService._send_smtp failed: {err}")
            return {"success": False, "response": None, "error": err}

    def _record_notification(
        self,
        payload: Dict[str, Any],
        result: Dict[str, Any],
        source_app: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        user: Optional[Any] = None,
        channel_id: Optional[int] = None,
    ) -> Optional[NotificationRecord]:
        """Record email send result."""
        status = Status.SUCCESS if result.get("success") else Status.FAILED
        try:
            record = NotificationRecord.objects.create(
                provider_type=Provider.EMAIL,
                channel=Channel.EMAIL,
                channel_link_id=channel_id,
                user=user,
                source_app=source_app or DEFAULT_SOURCE_APP,
                source_type=source_type or "",
                source_id=source_id or "",
                payload=payload,
                status=status,
                response=result.get("response"),
                error_message=result.get("error") or "",
                sent_at=timezone.now() if status == Status.SUCCESS else None,
            )
            return record
        except Exception as e:
            logger.warning(f"EmailService._record_notification failed: {e}")
            return None

    def send(
        self,
        subject: str,
        body: str,
        to: List[str],
        source_app: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        user: Optional[Any] = None,
        channel_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Send email notification. Uses default email channel config.
        to: list of recipient email addresses.
        """
        channel, config = self.get_email_channel_and_config()
        if not channel or not config:
            result = {
                "success": False,
                "response": None,
                "error": "Email channel not found or not active",
            }
            if source_app:
                payload = {"subject": subject, "to": to}
                self._record_notification(
                    payload,
                    result,
                    source_app,
                    source_type,
                    source_id,
                    user,
                    channel_id=channel_id,
                )
            return result
        if channel_id is None:
            channel_id = channel.id
        to_addrs = [a.strip() for a in to if (a or "").strip()]
        if not to_addrs:
            result = {
                "success": False,
                "response": None,
                "error": "No valid recipient addresses",
            }
            if source_app:
                self._record_notification(
                    {"subject": subject, "to": to},
                    result,
                    source_app,
                    source_type,
                    source_id,
                    user,
                    channel_id=channel_id,
                )
            return result
        payload = {"subject": subject, "body": body, "to": to_addrs}
        result = self._send_smtp(config, subject, body, to_addrs)
        if source_app:
            record = self._record_notification(
                payload,
                result,
                source_app,
                source_type,
                source_id,
                user,
                channel_id=channel_id,
            )
            if record:
                result["record_uuid"] = str(record.uuid)
        return result
