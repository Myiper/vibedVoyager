from __future__ import annotations

import threading
import time


class TokenBucketRateLimiter:
    def __init__(self, rate_per_sec: float, burst: int) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        if burst <= 0:
            raise ValueError("burst must be > 0")
        self._rate = rate_per_sec
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._throttled = False

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    self._throttled = False
                    return
                self._throttled = True
                wait_for = (1 - self._tokens) / self._rate
            time.sleep(max(wait_for, 0.005))

    @property
    def throttled(self) -> bool:
        with self._lock:
            return self._throttled

