from __future__ import annotations

from sqlite3 import IntegrityError
from typing import Dict, List, Optional, Sequence

from backend.models.schemas import SubscriptionResponse
from backend.repositories.subscription_repository import SubscriptionRepository
from backend.security import SecurityValidationError, normalize_email, normalize_github_repo_url
from backend.services.runtime_config_utils import (
    RUNTIME_CONFIG_MUTABLE_KEYS,
    build_effective_runtime_config,
)


class DuplicateSubscriptionError(Exception):
    pass


class SubscriptionService:
    def __init__(self, repository: Optional[SubscriptionRepository] = None) -> None:
        self.repository = repository or SubscriptionRepository()

    def list_subscriptions(self, user_id: Optional[int] = None) -> List[Dict[str, object]]:
        subscriptions: List[Dict[str, object]] = []
        for item in self.repository.list_subscriptions(user_id=user_id):
            try:
                subscriptions.append(self._normalize_subscription_record(item))
            except Exception:
                continue
        return subscriptions

    def create_subscription(self, user_id: Optional[int], payload: Dict[str, object]) -> Dict[str, object]:
        try:
            created = self.repository.create_subscription(user_id=user_id, payload=payload)
        except IntegrityError as exc:
            raise DuplicateSubscriptionError("repo_url already exists") from exc
        return self._normalize_subscription_record(created)

    def update_subscription(
        self,
        user_id: Optional[int],
        subscription_id: int,
        payload: Dict[str, object],
    ) -> Optional[Dict[str, object]]:
        try:
            updated = self.repository.update_subscription(
                user_id=user_id,
                subscription_id=subscription_id,
                payload=payload,
            )
        except IntegrityError as exc:
            raise DuplicateSubscriptionError("repo_url already exists") from exc
        if not updated:
            return None
        return self._normalize_subscription_record(updated)

    def delete_subscription(self, user_id: Optional[int], subscription_id: int) -> bool:
        return self.repository.delete_subscription(user_id=user_id, subscription_id=subscription_id)

    def get_runtime_config(self, user_id: Optional[int]) -> Dict[str, object]:
        raw = self.repository.get_runtime_configs(user_id=user_id)
        return build_effective_runtime_config(raw)

    def update_runtime_config(self, user_id: Optional[int], payload: Dict[str, object]) -> Dict[str, object]:
        updates: Dict[str, str] = {}
        deletes: List[str] = []

        for key in RUNTIME_CONFIG_MUTABLE_KEYS:
            if key not in payload:
                continue
            normalized = self._normalize_runtime_value(payload[key])
            if normalized is None:
                deletes.append(key)
                continue
            updates[key] = normalized

        if updates:
            self.repository.upsert_runtime_configs(user_id=user_id, payload=updates)
        if deletes:
            self.repository.delete_runtime_config_keys(user_id=user_id, keys=deletes)

        return self.get_runtime_config(user_id=user_id)

    def get_runtime_config_raw(self, user_id: Optional[int]) -> Dict[str, str]:
        return self.repository.get_runtime_configs(user_id=user_id)

    def clear_runtime_config(self, user_id: Optional[int]) -> Dict[str, object]:
        self.repository.delete_runtime_config_keys(user_id=user_id, keys=list(RUNTIME_CONFIG_MUTABLE_KEYS))
        return self.get_runtime_config(user_id=user_id)

    def sync_public_repositories(
        self,
        *,
        user_id: int,
        repo_urls: Sequence[str],
        recipient_email: str,
    ) -> Dict[str, object]:
        normalized_recipient_email = str(recipient_email or "").strip().lower()
        if normalized_recipient_email:
            normalized_recipient_email = normalize_email(normalized_recipient_email, allow_empty=True)
        existing = set()
        for item in self.repository.list_subscriptions(user_id=user_id):
            if not str(item.get("repo_url", "")).strip():
                continue
            try:
                normalized_existing = self._normalize_subscription_record(item)
            except Exception:
                continue
            existing.add(str(normalized_existing.get("repo_url", "")).strip().lower())

        unique_repo_urls: List[str] = []
        seen = set()
        for repo_url in repo_urls:
            try:
                normalized_repo_url = normalize_github_repo_url(repo_url, allow_empty=True)
            except SecurityValidationError:
                continue
            if not normalized_repo_url:
                continue
            normalized_key = normalized_repo_url.lower()
            if normalized_key in seen:
                continue
            seen.add(normalized_key)
            unique_repo_urls.append(normalized_repo_url)

        added_count = 0
        skipped_existing_count = 0

        for repo_url in unique_repo_urls:
            normalized_key = repo_url.lower()
            if normalized_key in existing:
                skipped_existing_count += 1
                continue
            self.repository.create_subscription(
                user_id=user_id,
                payload={
                    "repo_url": repo_url,
                    "morning_report_enabled": True,
                    "code_panorama_enabled": True,
                    "recipient_email": normalized_recipient_email,
                    "delivery_mode": "scheduled",
                    "frequency": "daily",
                    "delivery_time": "09:00",
                    "update_strategy": "incremental",
                },
            )
            existing.add(normalized_key)
            added_count += 1

        return {
            "added_count": added_count,
            "skipped_existing_count": skipped_existing_count,
            "public_repo_count": len(unique_repo_urls),
        }

    def _normalize_runtime_value(self, value: object) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return str(value)

    def _normalize_subscription_record(self, payload: Dict[str, object]) -> Dict[str, object]:
        sanitized = dict(payload)
        sanitized["repo_url"] = normalize_github_repo_url(sanitized.get("repo_url", ""))
        recipient_email = str(sanitized.get("recipient_email", "")).strip()
        sanitized["recipient_email"] = normalize_email(recipient_email, allow_empty=True)
        return SubscriptionResponse.model_validate(sanitized).model_dump()
