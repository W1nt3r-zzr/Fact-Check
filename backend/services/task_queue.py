"""
Process-local task queue for expensive fact-check jobs.

The queue protects upstream LLM/search concurrency and exposes snapshots that
can be streamed to browser clients.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class QueueSnapshot:
    task_id: str
    state: str
    max_concurrent: int
    running: int
    queued: int
    position: int = 0
    active_others: int = 0
    queued_ahead: int = 0
    wait_seconds: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "max_concurrent": self.max_concurrent,
            "running": self.running,
            "queued": self.queued,
            "position": self.position,
            "active_others": self.active_others,
            "queued_ahead": self.queued_ahead,
            "wait_seconds": round(self.wait_seconds, 1),
        }


class FactCheckTaskQueue:
    def __init__(self, max_concurrent: int):
        self.max_concurrent = max(1, int(max_concurrent or 1))
        self._condition = asyncio.Condition()
        self._running: set[str] = set()
        self._waiting: List[str] = []
        self._created_at: Dict[str, float] = {}

    def create_task_id(self) -> str:
        return uuid.uuid4().hex

    async def snapshot(self, task_id: Optional[str] = None, state: str = "status") -> QueueSnapshot:
        async with self._condition:
            return self._snapshot_locked(task_id or "", state)

    async def acquire(self, task_id: str, notify_interval: float = 5.0):
        async with self._condition:
            if task_id not in self._created_at:
                self._created_at[task_id] = time.monotonic()
            if task_id not in self._waiting and task_id not in self._running:
                self._waiting.append(task_id)

        while True:
            async with self._condition:
                can_start = (
                    task_id in self._waiting
                    and self._waiting[0] == task_id
                    and len(self._running) < self.max_concurrent
                )
                if can_start:
                    self._waiting.pop(0)
                    self._running.add(task_id)
                    self._condition.notify_all()
                    snapshot = self._snapshot_locked(task_id, "started")
                    should_wait = False
                else:
                    snapshot = self._snapshot_locked(task_id, "queued")
                    should_wait = True

            yield snapshot
            if not should_wait:
                return

            async with self._condition:
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=notify_interval)
                except asyncio.TimeoutError:
                    pass

    async def wait_until_acquired(self, task_id: str):
        async for _snapshot in self.acquire(task_id):
            pass

    async def release(self, task_id: str):
        async with self._condition:
            self._running.discard(task_id)
            if task_id in self._waiting:
                self._waiting.remove(task_id)
            self._created_at.pop(task_id, None)
            self._condition.notify_all()

    def _snapshot_locked(self, task_id: str, state: str) -> QueueSnapshot:
        running = len(self._running)
        queued = len(self._waiting)
        position = 0
        queued_ahead = 0
        if task_id in self._waiting:
            queued_ahead = self._waiting.index(task_id)
            position = queued_ahead + 1

        active_others = running - (1 if task_id in self._running else 0)
        created_at = self._created_at.get(task_id, time.monotonic())
        return QueueSnapshot(
            task_id=task_id,
            state=state,
            max_concurrent=self.max_concurrent,
            running=running,
            queued=queued,
            position=position,
            active_others=max(0, active_others),
            queued_ahead=queued_ahead,
            wait_seconds=time.monotonic() - created_at,
        )
