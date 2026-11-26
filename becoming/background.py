"""Durable post-turn worker for local API background tasks."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .long_memory import LongMemory
from .memory import SQLiteConversationStore
from .models import DemoModel, Model
from .personal_understanding import PersonalUnderstanding


MAX_ATTEMPTS = 3


class BackgroundWorker:
    """Single-process worker using its own SQLite connection.

    API requests only enqueue jobs in the same transaction as their transcript
    turn. This worker owns a separate connection so model calls never hold the
    API runtime lock or the request-side SQLite connection.
    """

    def __init__(
        self,
        db_path: str | Path,
        model_provider: Callable[[], Model | None],
        *,
        enable_long_memory: bool = True,
        enable_personal_understanding: bool = True,
        poll_interval: float = 0.25,
    ):
        self.db_path = str(db_path)
        self.model_provider = model_provider
        self.enable_long_memory = enable_long_memory
        self.enable_personal_understanding = enable_personal_understanding
        self.poll_interval = max(0.05, poll_interval)
        self.store = SQLiteConversationStore(self.db_path)
        self.db = self.store.connection
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_error: str | None = None
        self._closed = False
        self._close_lock = threading.Lock()
        self._state = threading.Condition()
        self._paused = False
        self._active_jobs = 0

        # Ensure worker-owned schemas exist and recover the older
        # understanding-specific queue before accepting work.
        bootstrap_model = self.model_provider() or DemoModel()
        default_store = self.store.for_conversation("default")
        self.long_memory = (
            LongMemory(default_store, bootstrap_model) if enable_long_memory else None
        )
        self.personal_understanding = (
            PersonalUnderstanding(default_store, bootstrap_model)
            if enable_personal_understanding else None
        )
        with self.db:
            self.db.execute("""
                UPDATE background_jobs
                SET status='pending',started_at=NULL,available_at=0,
                    updated_at=CURRENT_TIMESTAMP
                WHERE status='running'
            """)

    def set_model(self, model: Model) -> None:
        if self.long_memory is not None:
            self.long_memory.model = model
        if self.personal_understanding is not None:
            self.personal_understanding.model = model

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run, name="becoming-background-worker", daemon=True
        )
        self.thread.start()
        self.wake_event.set()

    def wake(self) -> None:
        self.wake_event.set()

    def pause(self, timeout: float = 5.0) -> bool:
        """Stop claiming new jobs and wait for the active job to finish.

        A timed-out pause remains in effect; callers must call resume() in a
        finally block so the worker cannot be left paused accidentally.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self._state:
            self._paused = True
            self.wake_event.set()
            while self._active_jobs:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._state.wait(remaining)
            return True

    def resume(self) -> None:
        with self._state:
            self._paused = False
            self._state.notify_all()
        self.wake_event.set()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread is not None:
            self.thread.join(timeout=max(0.0, timeout))
        if self.thread is None or not self.thread.is_alive():
            self._close_store()

    def _close_store(self) -> None:
        with self._close_lock:
            if not self._closed:
                self.store.close()
                self._closed = True

    def _claim(self) -> dict | None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("""
                SELECT id,kind,source_turn_id,attempts
                FROM background_jobs
                WHERE status='pending' AND attempts < ?
                  AND available_at <= ?
                ORDER BY priority DESC,id
                LIMIT 1
            """, (MAX_ATTEMPTS, time.time())).fetchone()
            if row is None:
                self.db.commit()
                return None
            self.db.execute("""
                UPDATE background_jobs
                SET status='running',attempts=attempts+1,started_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='pending'
            """, (row[0],))
            self.db.commit()
            return {"id": row[0], "kind": row[1], "source_turn_id": row[2],
                    "attempts": row[3] + 1}
        except BaseException:
            self.db.rollback()
            raise

    def _finish(self, job_id: int, status: str, *, error: str | None = None) -> None:
        with self.db:
            self.db.execute("""
                UPDATE background_jobs
                SET status=?,last_error=?,finished_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (status, error, job_id))

    def _fail(self, job: dict, error: str) -> None:
        attempts = job["attempts"]
        status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
        delay = min(2 ** attempts, 30)
        with self.db:
            self.db.execute("""
                UPDATE background_jobs
                SET status=?,attempts=?,available_at=?,last_error=?,
                    finished_at=CASE WHEN ?='failed' THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (status, attempts, time.time() + delay, error, status, job["id"]))

    def _process(self, job: dict) -> None:
        row = self.db.execute("""
            SELECT t.user_text,t.assistant_text
            FROM turns t WHERE t.id=?
        """, (job["source_turn_id"],)).fetchone()
        if row is None:
            self._finish(job["id"], "cancelled", error="source_turn_missing")
            return
        model = self.model_provider()
        if model is None:
            raise RuntimeError("model_not_configured")

        turn_id = job["source_turn_id"]
        user_text, assistant_text = row
        if job["kind"] == "long_memory.extract":
            if self.long_memory is not None:
                self.long_memory.model = model
                self.long_memory.extract(turn_id, user_text)
        elif job["kind"] == "personal_understanding.process":
            if self.personal_understanding is not None:
                manager = self.personal_understanding
                manager.model = model
                manager.observe_turn(
                    turn_id, user_text, assistant_text, process=False
                )
                event = manager.process_pending(limit=5, retry_failed=True)
                manager.resolve_deferred_confirmations()
                internal = self.db.execute("""
                    SELECT status,attempts FROM understanding_jobs
                    WHERE job_key=?
                """, (f"turn:{turn_id}",)).fetchone()
                if event.errors or (internal and internal[0] != "done"):
                    raise RuntimeError("personal_understanding_update_failed")
        else:
            raise RuntimeError("unknown_background_job")
        self._finish(job["id"], "done")

    def run_once(self) -> bool:
        """Process one ready job; exposed for deterministic unit tests."""
        # Claim and register the active job under one condition lock. This
        # closes the race where pause() could observe zero active jobs after a
        # claim but before processing had registered itself.
        with self._state:
            if self._paused:
                return False
            job = self._claim()
            if job is None:
                return False
            self._active_jobs += 1
        try:
            try:
                self._process(job)
                self.last_error = None
            except Exception as exc:
                error = str(exc) if str(exc) in {
                    "model_not_configured", "personal_understanding_update_failed",
                    "unknown_background_job",
                } else "background_task_failed"
                self.last_error = error
                self._fail(job, error)
        finally:
            with self._state:
                self._active_jobs -= 1
                self._state.notify_all()
        return True

    def _run(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    worked = self.run_once()
                except Exception:
                    self.last_error = "background_worker_error"
                    worked = False
                if not worked:
                    self.wake_event.wait(self.poll_interval)
                    self.wake_event.clear()
        finally:
            self._close_store()

    def status(self, *, by_kind: dict[str, dict[str, int]] | None = None) -> dict:
        if by_kind is None:
            rows = self.db.execute("""
                SELECT kind,status,COUNT(*) FROM background_jobs GROUP BY kind,status
            """).fetchall()
            by_kind = {}
            for kind, state, count in rows:
                by_kind.setdefault(kind, {})[state] = count
        totals = {state: 0 for state in ("pending", "running", "done", "failed", "cancelled")}
        for states in by_kind.values():
            for state, count in states.items():
                totals[state] += count
        with self._state:
            return {
                "running": bool(self.thread and self.thread.is_alive()),
                "counts": totals,
                "by_kind": by_kind,
                "last_error": self.last_error,
                "paused": self._paused,
                "active_jobs": self._active_jobs,
                "max_attempts": MAX_ATTEMPTS,
            }
