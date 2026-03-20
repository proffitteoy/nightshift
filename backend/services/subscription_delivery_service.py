from __future__ import annotations

import logging
import os
import queue
import threading
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from html import escape
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.clients.email_client import (
    DEFAULT_DM_ENDPOINT,
    DEFAULT_DM_REGION_ID,
    EmailClient,
    EmailClientConfig,
)
from backend.repositories.subscription_repository import SubscriptionRepository
from backend.services.project_service import ProjectService
from backend.services.runtime_config_utils import build_email_config


LOGGER = logging.getLogger(__name__)


class SubscriptionDeliveryService:
    def __init__(
        self,
        repository: Optional[SubscriptionRepository] = None,
        project_service: Optional[ProjectService] = None,
        email_client: Optional[EmailClient] = None,
    ) -> None:
        self.repository = repository or SubscriptionRepository()
        self.project_service = project_service or ProjectService(subscription_repository=self.repository)
        self.email_client = email_client or EmailClient()
        self._timezone = self._load_timezone(os.getenv("NIGHTSHIFT_DELIVERY_TIMEZONE", "Asia/Shanghai"))
        self._poll_interval_seconds = self._parse_positive_float(
            os.getenv("NIGHTSHIFT_DELIVERY_POLL_SECONDS"),
            default=30.0,
        )
        self._delivery_dedup_seconds = self._parse_positive_float(
            os.getenv("NIGHTSHIFT_DELIVERY_DEDUP_SECONDS"),
            default=15.0,
        )
        self._scheduler_enabled = self._parse_bool(
            os.getenv("NIGHTSHIFT_DELIVERY_SCHEDULER_ENABLED"),
            default=True,
        )
        self._email_config_missing_logged = False
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._cycle_lock = threading.Lock()
        self._instant_queue: "queue.Queue[int]" = queue.Queue()
        self._delivery_state_lock = threading.Lock()
        self._active_delivery_ids: set[int] = set()
        self._recent_success_at: Dict[int, datetime] = {}
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self._scheduler_enabled:
            LOGGER.info("subscription delivery scheduler disabled")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="nightshift-subscription-delivery",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def queue_instant_delivery(self, subscription_id: int) -> None:
        if subscription_id <= 0:
            return
        self._instant_queue.put(subscription_id)
        self._wake_event.set()

    def send_subscription_now(
        self,
        subscription_id: int,
        now_local: Optional[datetime] = None,
        owner_user_id: Optional[int] = None,
    ) -> None:
        if subscription_id <= 0:
            raise ValueError("subscription_id must be positive")

        if owner_user_id is None:
            subscription = self.repository.get_any_subscription_with_delivery_state(subscription_id)
        else:
            subscription = self.repository.get_subscription_with_delivery_state(
                subscription_id,
                user_id=owner_user_id,
            )
        if not subscription:
            raise LookupError(f"subscription {subscription_id} not found")
        if not str(subscription.get("recipient_email", "")).strip():
            raise ValueError("recipient_email is required for delivery")

        config = self._resolve_email_config(subscription.get("user_id"))
        if config is None:
            missing = ",".join(self._missing_email_config_keys(subscription.get("user_id")))
            raise RuntimeError(f"missing email config keys={missing}")

        delivered = self._deliver_subscription(subscription=subscription, trigger="manual", now_local=self._normalize_now_local(now_local))
        if delivered:
            return

        if owner_user_id is None:
            refreshed = self.repository.get_any_subscription_with_delivery_state(subscription_id) or {}
        else:
            refreshed = self.repository.get_subscription_with_delivery_state(subscription_id, user_id=owner_user_id) or {}
        error_message = str(refreshed.get("last_delivery_error", "")).strip() or "delivery failed"
        raise RuntimeError(error_message)

    def run_delivery_cycle(self, now_local: Optional[datetime] = None) -> None:
        resolved_now = self._normalize_now_local(now_local)
        with self._cycle_lock:
            self._deliver_queued_instant_subscriptions(now_local=resolved_now)
            self._deliver_due_scheduled_subscriptions(now_local=resolved_now)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_delivery_cycle()
            except Exception as exc:
                LOGGER.warning("subscription delivery cycle failed: %s", exc)
            self._wake_event.wait(timeout=self._poll_interval_seconds)
            self._wake_event.clear()

    def _deliver_queued_instant_subscriptions(self, now_local: datetime) -> None:
        queued_ids: List[int] = []
        while True:
            try:
                queued_ids.append(self._instant_queue.get_nowait())
            except queue.Empty:
                break

        if not queued_ids:
            return

        for subscription_id in sorted(set(queued_ids)):
            subscription = self.repository.get_any_subscription_with_delivery_state(subscription_id)
            if not subscription:
                continue
            if self._normalize_delivery_mode(subscription.get("delivery_mode")) != "instant":
                continue
            if not str(subscription.get("recipient_email", "")).strip():
                continue
            self._deliver_subscription(subscription=subscription, trigger="instant", now_local=now_local)

    def _deliver_due_scheduled_subscriptions(self, now_local: datetime) -> None:
        for subscription in self.repository.list_all_subscriptions_with_delivery_state():
            if not self._is_scheduled_due(subscription=subscription, now_local=now_local):
                continue
            self._deliver_subscription(subscription=subscription, trigger="scheduled", now_local=now_local)

    def _is_scheduled_due(self, subscription: Dict[str, object], now_local: datetime) -> bool:
        if self._normalize_delivery_mode(subscription.get("delivery_mode")) != "scheduled":
            return False
        if not str(subscription.get("recipient_email", "")).strip():
            return False
        if not self._matches_frequency(subscription=subscription, now_local=now_local):
            return False

        scheduled_time = self._parse_delivery_time(subscription.get("delivery_time"))
        if scheduled_time is None:
            return False
        scheduled_at = datetime.combine(now_local.date(), scheduled_time, tzinfo=self._timezone)
        if now_local < scheduled_at:
            return False

        today = now_local.date()
        if self._local_date_from_iso(subscription.get("last_delivery_at")) == today:
            return False
        if self._local_date_from_iso(subscription.get("last_delivery_attempt_at")) == today:
            return False
        return True

    def _matches_frequency(self, subscription: Dict[str, object], now_local: datetime) -> bool:
        frequency = str(subscription.get("frequency", "daily")).strip().lower()
        if frequency == "weekday":
            return now_local.weekday() < 5
        if frequency == "weekly":
            created_weekday = self._local_weekday_from_iso(subscription.get("created_at"))
            return now_local.weekday() == (created_weekday if created_weekday is not None else 0)
        return True

    def _deliver_subscription(
        self,
        subscription: Dict[str, object],
        trigger: str,
        now_local: datetime,
    ) -> bool:
        subscription_id = int(subscription.get("id", 0))
        if subscription_id <= 0:
            return False
        if self._should_skip_duplicate_delivery(subscription=subscription, trigger=trigger, now_local=now_local):
            return True
        if not self._try_mark_delivery_active(subscription_id):
            LOGGER.info(
                "subscription delivery suppressed: id=%s trigger=%s reason=delivery_in_progress",
                subscription_id,
                trigger,
            )
            return True

        try:
            config = self._resolve_email_config(subscription.get("user_id"))
            if config is None:
                missing_keys = ",".join(self._missing_email_config_keys(subscription.get("user_id")))
                self.repository.record_delivery_attempt(
                    subscription_id=subscription_id,
                    attempted_at=now_local.astimezone(timezone.utc).isoformat(),
                    delivered_at=None,
                    error_message=f"missing email config keys={missing_keys}",
                )
                if not self._email_config_missing_logged:
                    LOGGER.warning("subscription delivery skipped: missing email config keys=%s", missing_keys)
                    self._email_config_missing_logged = True
                return False
            self._email_config_missing_logged = False

            attempted_at = now_local.astimezone(timezone.utc).isoformat()
            report = self._build_report(subscription)
            subject = self._build_subject(subscription=subscription, trigger=trigger)
            html_body = self._build_html_body(
                subscription=subscription,
                report=report,
                trigger=trigger,
                now_local=now_local,
            )
            response = self.email_client.send_html_email(
                config=config,
                to_address=str(subscription.get("recipient_email", "")).strip(),
                subject=subject,
                html_body=html_body,
            )
            delivered_at = now_local.astimezone(timezone.utc).isoformat()
            self.repository.record_delivery_attempt(
                subscription_id=subscription_id,
                attempted_at=attempted_at,
                delivered_at=delivered_at,
                error_message="",
            )
            LOGGER.info(
                "subscription email delivered: id=%s trigger=%s recipient=%s request_id=%s",
                subscription_id,
                trigger,
                self._mask_email(str(subscription.get("recipient_email", "")).strip()),
                str(response.get("RequestId", "")),
            )
            self._mark_recent_success(subscription_id, delivered_at)
            return True
        except Exception as exc:
            attempted_at = now_local.astimezone(timezone.utc).isoformat()
            self.repository.record_delivery_attempt(
                subscription_id=subscription_id,
                attempted_at=attempted_at,
                delivered_at=None,
                error_message=str(exc)[:500],
            )
            LOGGER.warning(
                "subscription email failed: id=%s trigger=%s recipient=%s error=%s",
                subscription_id,
                trigger,
                self._mask_email(str(subscription.get("recipient_email", "")).strip()),
                exc,
            )
            return False
        finally:
            self._clear_delivery_active(subscription_id)

    def _build_report(self, subscription: Dict[str, object]) -> Dict[str, object]:
        repo_url = str(subscription.get("repo_url", "")).strip()
        if not repo_url:
            raise ValueError("repo_url is required for email delivery")

        if not bool(subscription.get("morning_report_enabled", True)):
            return {
                "repository": self._repo_name_from_url(repo_url),
                "report_date": datetime.now(self._timezone).strftime("%Y-%m-%d"),
                "time_range": "delivery-only",
                "stats": {"pr_count": 0, "commit_count": 0},
                "summary_text": "Morning report is disabled for this subscription.",
                "todo_list": [],
                "details": {"top_prs": [], "top_commits": []},
            }

        user_id = self._to_optional_int(subscription.get("user_id"))
        result = self.project_service.generate_email_report_by_user(
            token=self.project_service.get_runtime_token(user_id=user_id),
            repo_url=repo_url,
            user_id=user_id,
        )
        report = result.get("report")
        if not isinstance(report, dict):
            raise RuntimeError("report payload is missing")
        LOGGER.info(
            "subscription delivery report selected: subscription_id=%s user_id=%s repo=%s source=%s",
            subscription.get("id"),
            user_id,
            self._repo_name_from_url(repo_url),
            str(result.get("report_source", "unknown")),
        )
        return report

    def _build_subject(self, subscription: Dict[str, object], trigger: str) -> str:
        repo_name = self._repo_name_from_url(str(subscription.get("repo_url", "")).strip())
        prefix = {
            "instant": "Immediate",
            "manual": "Manual",
        }.get(trigger, "Scheduled")
        return f"NightShift {prefix} Delivery | {repo_name}"

    def _build_html_body(
        self,
        subscription: Dict[str, object],
        report: Dict[str, object],
        trigger: str,
        now_local: datetime,
    ) -> str:
        repo_url = str(subscription.get("repo_url", "")).strip()
        repo_name = self._repo_name_from_url(repo_url)
        stats = report.get("stats", {}) if isinstance(report.get("stats"), dict) else {}
        details = report.get("details", {}) if isinstance(report.get("details"), dict) else {}
        summary_text = escape(str(report.get("summary_text", "")).strip() or "No summary generated.")
        email_digest = self.project_service.generate_email_digest(
            report,
            user_id=self._to_optional_int(subscription.get("user_id")),
        )
        todo_items = self._normalize_text_items(report.get("todo_list"))
        top_prs = details.get("top_prs") if isinstance(details.get("top_prs"), list) else []
        top_commits = details.get("top_commits") if isinstance(details.get("top_commits"), list) else []
        code_panorama_enabled = bool(subscription.get("code_panorama_enabled", True))
        delivery_label = {
            "instant": "Immediate",
            "manual": "Manual",
        }.get(trigger, "Scheduled")

        return f"""
<html>
  <body style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6;">
    <h2 style="margin-bottom: 8px;">NightShift {delivery_label} Delivery</h2>
    <p style="margin-top: 0;">
      <strong>Repository:</strong> {escape(repo_name)}<br />
      <strong>Repo URL:</strong> <a href="{escape(repo_url)}">{escape(repo_url)}</a><br />
      <strong>Sent At:</strong> {escape(now_local.strftime("%Y-%m-%d %H:%M:%S %Z"))}<br />
      <strong>Report Date:</strong> {escape(str(report.get("report_date", "")))}<br />
      <strong>Time Range:</strong> {escape(str(report.get("time_range", "")))}<br />
      <strong>Code Panorama:</strong> {"enabled" if code_panorama_enabled else "disabled"}
    </p>
    <h3>Morning Brief</h3>
    {self._render_email_digest(email_digest)}
    <h3>Structured Summary</h3>
    <p>{summary_text}</p>
    <h3>Stats</h3>
    <ul>
      <li>Pull Requests: {self._to_int(stats.get("pr_count"))}</li>
      <li>Commits: {self._to_int(stats.get("commit_count"))}</li>
    </ul>
    <h3>Next Actions</h3>
    {self._render_text_list(todo_items, empty_label="No follow-up actions.")}
    <h3>Top Pull Requests</h3>
    {self._render_pull_request_list(top_prs)}
    <h3>Top Commits</h3>
    {self._render_commit_list(top_commits)}
  </body>
</html>
        """.strip()

    def _render_email_digest(self, digest_text: str) -> str:
        paragraphs = [escape(item.strip()) for item in digest_text.replace("\r\n", "\n").split("\n\n") if item.strip()]
        if not paragraphs:
            return "<p>No digest generated.</p>"
        return "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs[:2])

    def _resolve_email_config(self, user_id: object) -> Optional[EmailClientConfig]:
        user_id_int = self._to_optional_int(user_id)
        if user_id_int is not None:
            raw = self.repository.get_runtime_configs(user_id=user_id_int)
            if raw:
                return build_email_config(raw)

        access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
        access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
        account_name = os.getenv("ALIBABA_CLOUD_DM_ACCOUNT_NAME", "").strip()
        if not access_key_id or not access_key_secret or not account_name:
            return None

        return EmailClientConfig(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            account_name=account_name,
            region_id=os.getenv("ALIBABA_CLOUD_DM_REGION_ID", "").strip() or DEFAULT_DM_REGION_ID,
            endpoint=os.getenv("ALIBABA_CLOUD_DM_ENDPOINT", "").strip() or DEFAULT_DM_ENDPOINT,
            address_type=self._parse_positive_int(os.getenv("ALIBABA_CLOUD_DM_ADDRESS_TYPE"), default=1),
            reply_to_address=self._parse_bool(os.getenv("ALIBABA_CLOUD_DM_REPLY_TO_ADDRESS"), default=False),
            from_alias=os.getenv("ALIBABA_CLOUD_DM_FROM_ALIAS", "").strip(),
            connect_timeout_ms=self._parse_positive_int(
                os.getenv("ALIBABA_CLOUD_DM_CONNECT_TIMEOUT_MS"),
                default=5000,
            ),
            read_timeout_ms=self._parse_positive_int(
                os.getenv("ALIBABA_CLOUD_DM_READ_TIMEOUT_MS"),
                default=10000,
            ),
        )

    def _missing_email_config_keys(self, user_id: object) -> List[str]:
        user_id_int = self._to_optional_int(user_id)
        if user_id_int is not None:
            raw = self.repository.get_runtime_configs(user_id=user_id_int)
            if raw:
                missing = []
                if not str(raw.get("email_access_key_id", "")).strip():
                    missing.append("email_access_key_id")
                if not str(raw.get("email_access_key_secret", "")).strip():
                    missing.append("email_access_key_secret")
                if not str(raw.get("email_account_name", "")).strip():
                    missing.append("email_account_name")
                return missing

        missing: List[str] = []
        if not os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip():
            missing.append("ALIBABA_CLOUD_ACCESS_KEY_ID")
        if not os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip():
            missing.append("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        if not os.getenv("ALIBABA_CLOUD_DM_ACCOUNT_NAME", "").strip():
            missing.append("ALIBABA_CLOUD_DM_ACCOUNT_NAME")
        return missing

    def _normalize_now_local(self, now_local: Optional[datetime]) -> datetime:
        if now_local is None:
            return datetime.now(self._timezone)
        if now_local.tzinfo is None:
            return now_local.replace(tzinfo=self._timezone)
        return now_local.astimezone(self._timezone)

    def _local_date_from_iso(self, value: object) -> Optional[date]:
        dt = self._parse_datetime(value)
        if dt is None:
            return None
        return dt.astimezone(self._timezone).date()

    def _local_weekday_from_iso(self, value: object) -> Optional[int]:
        dt = self._parse_datetime(value)
        if dt is None:
            return None
        return dt.astimezone(self._timezone).weekday()

    def _parse_datetime(self, value: object) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def _parse_delivery_time(self, value: object) -> Optional[time]:
        text = str(value or "").strip()
        if not text or ":" not in text:
            return None
        hour_text, minute_text = text.split(":", 1)
        if not (hour_text.isdigit() and minute_text.isdigit()):
            return None
        hour = int(hour_text)
        minute = int(minute_text)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return time(hour=hour, minute=minute)

    def _normalize_delivery_mode(self, value: object) -> str:
        return "instant" if str(value or "").strip().lower() == "instant" else "scheduled"

    def _repo_name_from_url(self, repo_url: str) -> str:
        parsed = urlparse(repo_url)
        path = parsed.path.strip("/").replace(".git", "")
        if path.count("/") == 1:
            return path
        return repo_url or "unknown/unknown"

    def _render_text_list(self, items: Iterable[str], empty_label: str) -> str:
        normalized = [escape(item) for item in items if item]
        if not normalized:
            return f"<p>{escape(empty_label)}</p>"
        return "<ul>" + "".join(f"<li>{item}</li>" for item in normalized[:8]) + "</ul>"

    def _render_pull_request_list(self, items: object) -> str:
        if not isinstance(items, list) or not items:
            return "<p>No pull requests captured.</p>"
        lines = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            title = escape(str(item.get("title", "")).strip() or "Untitled")
            number = self._to_int(item.get("number"))
            user = escape(str(item.get("user", "")).strip() or "unknown")
            lines.append(f"<li>#{number} {title} ({user})</li>")
        return "<ul>" + "".join(lines or ["<li>No pull requests captured.</li>"]) + "</ul>"

    def _render_commit_list(self, items: object) -> str:
        if not isinstance(items, list) or not items:
            return "<p>No commits captured.</p>"
        lines = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            sha = escape(str(item.get("sha", "")).strip()[:7] or "unknown")
            message = escape(str(item.get("message", "")).strip() or "No message")
            author = escape(str(item.get("author", "")).strip() or "unknown")
            lines.append(f"<li>{sha} {message} ({author})</li>")
        return "<ul>" + "".join(lines or ["<li>No commits captured.</li>"]) + "</ul>"

    def _normalize_text_items(self, value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _mask_email(self, value: str) -> str:
        if "@" not in value:
            return value
        local, domain = value.split("@", 1)
        if len(local) <= 2:
            masked_local = local[:1] + "*"
        else:
            masked_local = local[:2] + "***"
        return f"{masked_local}@{domain}"

    def _parse_bool(self, value: Optional[str], default: bool) -> bool:
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    def _parse_positive_int(self, value: Optional[str], default: int) -> int:
        try:
            parsed = int(str(value).strip()) if value is not None else default
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _parse_positive_float(self, value: Optional[str], default: float) -> float:
        try:
            parsed = float(str(value).strip()) if value is not None else default
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _should_skip_duplicate_delivery(
        self,
        subscription: Dict[str, object],
        trigger: str,
        now_local: datetime,
    ) -> bool:
        subscription_id = int(subscription.get("id", 0))
        if subscription_id <= 0 or self._delivery_dedup_seconds <= 0:
            return False
        if str(subscription.get("last_delivery_error", "")).strip():
            return False

        latest_success = self._latest_success_at(subscription_id, subscription)
        if latest_success is None:
            return False

        elapsed_seconds = (now_local.astimezone(timezone.utc) - latest_success).total_seconds()
        if elapsed_seconds < 0 or elapsed_seconds > self._delivery_dedup_seconds:
            return False

        LOGGER.info(
            "subscription delivery suppressed: id=%s trigger=%s reason=recent_success elapsed_seconds=%.2f",
            subscription_id,
            trigger,
            elapsed_seconds,
        )
        return True

    def _latest_success_at(self, subscription_id: int, subscription: Dict[str, object]) -> Optional[datetime]:
        persisted = self._parse_datetime(subscription.get("last_delivery_at"))
        if persisted is not None:
            persisted = persisted.astimezone(timezone.utc)
        with self._delivery_state_lock:
            self._prune_recent_success_locked(datetime.now(timezone.utc))
            recent = self._recent_success_at.get(subscription_id)
        if persisted is None:
            return recent
        if recent is None:
            return persisted
        return recent if recent >= persisted else persisted

    def _try_mark_delivery_active(self, subscription_id: int) -> bool:
        with self._delivery_state_lock:
            if subscription_id in self._active_delivery_ids:
                return False
            self._active_delivery_ids.add(subscription_id)
            return True

    def _clear_delivery_active(self, subscription_id: int) -> None:
        with self._delivery_state_lock:
            self._active_delivery_ids.discard(subscription_id)

    def _mark_recent_success(self, subscription_id: int, delivered_at_iso: str) -> None:
        delivered_at = self._parse_datetime(delivered_at_iso)
        if delivered_at is None:
            delivered_at = datetime.now(timezone.utc)
        else:
            delivered_at = delivered_at.astimezone(timezone.utc)
        with self._delivery_state_lock:
            self._prune_recent_success_locked(delivered_at)
            self._recent_success_at[subscription_id] = delivered_at

    def _prune_recent_success_locked(self, now_utc: datetime) -> None:
        if self._delivery_dedup_seconds <= 0:
            self._recent_success_at.clear()
            return
        threshold = now_utc - timedelta(seconds=self._delivery_dedup_seconds)
        expired = [subscription_id for subscription_id, delivered_at in self._recent_success_at.items() if delivered_at < threshold]
        for subscription_id in expired:
            self._recent_success_at.pop(subscription_id, None)

    def _load_timezone(self, value: str) -> tzinfo:
        normalized = value.strip() or "Asia/Shanghai"
        try:
            return ZoneInfo(normalized)
        except ZoneInfoNotFoundError:
            fallback = self._fallback_timezone(normalized)
            LOGGER.warning(
                "timezone '%s' is unavailable in current Python runtime, fallback to fixed offset %s",
                normalized,
                fallback.tzname(None),
            )
            return fallback

    def _fallback_timezone(self, normalized: str) -> tzinfo:
        if normalized == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="UTC+08")
        return timezone.utc

    def _to_int(self, value: object) -> int:
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError):
            return 0

    def _to_optional_int(self, value: object) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
