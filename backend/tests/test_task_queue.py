import pytest
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.task_queue import FactCheckTaskQueue


@pytest.mark.asyncio
async def test_queue_waits_when_concurrency_limit_reached():
    queue = FactCheckTaskQueue(max_concurrent=1)

    first = queue.acquire("task-a", notify_interval=0.01)
    first_snapshot = await first.__anext__()
    assert first_snapshot.state == "started"
    assert first_snapshot.running == 1

    second = queue.acquire("task-b", notify_interval=0.01)
    second_snapshot = await second.__anext__()
    assert second_snapshot.state == "queued"
    assert second_snapshot.running == 1
    assert second_snapshot.queued == 1
    assert second_snapshot.position == 1
    assert second_snapshot.active_others == 1

    await queue.release("task-a")
    next_snapshot = await second.__anext__()
    assert next_snapshot.state == "started"
    assert next_snapshot.running == 1

    await queue.release("task-b")


@pytest.mark.asyncio
async def test_queue_snapshot_clears_after_release():
    queue = FactCheckTaskQueue(max_concurrent=2)

    acquire = queue.acquire("task-a")
    snapshot = await acquire.__anext__()
    assert snapshot.state == "started"

    await queue.release("task-a")
    status = await queue.snapshot()
    assert status.running == 0
    assert status.queued == 0
