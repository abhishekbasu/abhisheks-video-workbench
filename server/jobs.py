"""In-memory job registry for long-running Sora / upscale operations.

The ``modules/*`` functions block for minutes at a time and report
progress through an ``on_progress(status, pct)`` callback. The browser can't hold
a request open that long, so each operation runs on a background thread and writes
its progress into a :class:`Job` record here. The API surfaces those records as a
snapshot (``GET /api/jobs/{id}``) and as a live SSE stream
(``GET /api/jobs/{id}/events``).

The registry is process-local and unbounded — fine for a single-user local tool.
A job keeps running even if the browser disconnects, so closing the tab never
kills an in-flight render; the result still lands in ``output/``.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)

# What the background work receives: the module-style on_progress(status, pct)
# callback. What it returns: the JSON-able result dict surfaced to the client.
ProgressFn = Callable[[Optional[str], Optional[float]], None]
TaskFn = Callable[[ProgressFn], dict]


@dataclass
class Job:
    """A single background operation and its latest observable state."""

    id: str
    status: str = "queued"  # queued | running | done | error
    progress: int = 0  # 0..100
    stage: str = ""  # human-readable status line
    result: Optional[dict] = None
    error: Optional[str] = None
    # Bumped on every mutation so the SSE stream can cheaply detect changes.
    version: int = 0


class JobManager:
    """Thread-safe registry that runs tasks and tracks their progress."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> Optional[dict[str, Any]]:
        """A JSON-able copy of the job's state, or ``None`` if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "stage": job.stage,
                "result": job.result,
                "error": job.error,
                "version": job.version,
            }

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                setattr(job, key, value)
            job.version += 1

    def _progress_fn(self, job_id: str) -> ProgressFn:
        """Build the on_progress(status, pct) the modules expect for this job."""

        def cb(status: Optional[str], pct: Optional[float]) -> None:
            changes: dict[str, Any] = {"status": "running"}
            if status is not None:
                changes["stage"] = str(status)
            if pct is not None:
                try:
                    changes["progress"] = max(0, min(100, int(pct)))
                except (TypeError, ValueError):
                    pass
            self._update(job_id, **changes)

        return cb

    def run(self, job: Job, task: TaskFn) -> None:
        """Run ``task(on_progress)`` on a daemon thread, recording its outcome."""

        def _runner() -> None:
            self._update(job.id, status="running", stage="starting…")
            try:
                result = task(self._progress_fn(job.id))
                self._update(
                    job.id, status="done", progress=100, stage="done", result=result
                )
            except Exception as exc:  # noqa: BLE001 — surface any failure to the client
                logger.exception("Job %s failed", job.id)
                self._update(job.id, status="error", error=str(exc))

        threading.Thread(target=_runner, name=f"job-{job.id[:8]}", daemon=True).start()
