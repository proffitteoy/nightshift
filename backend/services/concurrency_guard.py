from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator, Optional
from uuid import uuid4

from backend.repositories.job_lock_repository import JobLockRepository


class ConcurrencyLockTimeoutError(RuntimeError):
    def __init__(self, lock_key: str, wait_timeout_seconds: float) -> None:
        self.lock_key = lock_key
        self.wait_timeout_seconds = wait_timeout_seconds
        super().__init__(f"lock timeout for '{lock_key}' after {wait_timeout_seconds:.1f}s")


class ConcurrencyGuard:
    def __init__(self, lock_repository: Optional[JobLockRepository] = None) -> None:
        self.lock_repository = lock_repository or JobLockRepository()

    @contextmanager
    def acquire(
        self,
        lock_key: str,
        *,
        ttl_seconds: int = 240,
        wait_timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 0.2,
    ) -> Iterator[None]:
        owner_id = uuid4().hex
        deadline = time.monotonic() + max(wait_timeout_seconds, 0.0)
        lock_acquired = False

        while True:
            if self.lock_repository.try_acquire(lock_key=lock_key, owner_id=owner_id, ttl_seconds=ttl_seconds):
                lock_acquired = True
                break
            if time.monotonic() >= deadline:
                raise ConcurrencyLockTimeoutError(lock_key=lock_key, wait_timeout_seconds=wait_timeout_seconds)
            time.sleep(max(poll_interval_seconds, 0.05))

        try:
            yield
        finally:
            if lock_acquired:
                self.lock_repository.release(lock_key=lock_key, owner_id=owner_id)
