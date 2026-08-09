"""In-process telemetry pub/sub with bounded per-subscriber queues."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _Subscriber:
    name: str
    maxsize: int
    q: queue.Queue[dict[str, Any]]
    dropped: int = 0


class TelemetryBus:
    """Best-effort pub/sub bus; publish never blocks on slow consumers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_id = 1

    def subscribe(self, *, name: str = "subscriber", maxsize: int = 256) -> int:
        with self._lock:
            sub_id = self._next_id
            self._next_id += 1
            self._subscribers[sub_id] = _Subscriber(
                name=name,
                maxsize=maxsize,
                q=queue.Queue(maxsize=maxsize),
            )
            return sub_id

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish(self, sample: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers.values())
        for subscriber in subscribers:
            try:
                subscriber.q.put_nowait(sample)
            except queue.Full:
                try:
                    subscriber.q.get_nowait()
                    subscriber.dropped += 1
                except queue.Empty:
                    pass
                try:
                    subscriber.q.put_nowait(sample)
                except queue.Full:
                    subscriber.dropped += 1

    def poll(self, subscriber_id: int, *, timeout_s: float = 0.0) -> dict[str, Any] | None:
        with self._lock:
            subscriber = self._subscribers.get(subscriber_id)
        if subscriber is None:
            return None
        try:
            return subscriber.q.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def dropped_count(self, subscriber_id: int) -> int:
        with self._lock:
            subscriber = self._subscribers.get(subscriber_id)
            return subscriber.dropped if subscriber else 0

    def publish_loop_latency_probe(
        self,
        *,
        iterations: int = 1000,
        maxsize: int = 4,
    ) -> float:
        """Return max publish duration in seconds while a subscriber is full."""
        sub_id = self.subscribe(name="probe", maxsize=maxsize)
        durations: list[float] = []
        try:
            for index in range(iterations):
                start = time.perf_counter()
                self.publish({"time_s": float(index)})
                durations.append(time.perf_counter() - start)
        finally:
            self.unsubscribe(sub_id)
        return max(durations)
