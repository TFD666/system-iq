import logging
import queue
import threading
import time
import uuid
from typing import Callable

from ..config import demo_mode
from ..decision.provider import DecisionProvider, DecisionRateLimitError
from ..design import TokenBudget
from ..llm import LLMProvider, RateLimitError
from ..pipeline import map_pipeline_error, run_pipeline
from ..schemas import DesignRequest
from .access import AccessManager

logger = logging.getLogger(__name__)


class JobQueueFull(Exception):
    pass


class JobManager:
    def __init__(
        self,
        llm_factory: Callable[[], LLMProvider],
        decision_factory: Callable[[], DecisionProvider],
        redact: Callable[[str], tuple[str, list]] | None = None,
        budget: TokenBudget | None = None,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = 3600,
        max_waiting: int = 2,
        access: AccessManager | None = None,
    ):
        self._llm_factory = llm_factory
        self._decision_factory = decision_factory
        self._redact = redact
        self._budget = budget if budget is not None else TokenBudget()
        self._clock = clock
        self._ttl = ttl_seconds
        self._max_waiting = max_waiting
        self._access = access

        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._order = 0

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._stop_event.clear()
                self._worker = threading.Thread(
                    target=self._run_worker, daemon=True,
                )
                self._worker.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop_event.set()
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=timeout)
        with self._lock:
            self._worker = None

    # ── public API ────────────────────────────────────────────────────

    def submit(self, idea: str, token: str | None = None) -> tuple[str, int]:
        self.purge_expired()
        with self._lock:
            queued = sum(
                1 for j in self._jobs.values() if j["status"] == "queued"
            )
            if queued >= self._max_waiting:
                raise JobQueueFull()
            job_id = uuid.uuid4().hex
            self._order += 1
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "stage": None,
                "detail": None,
                "error": None,
                "result": None,
                "finished_at": None,
                "_order": self._order,
            }
            position = self._position(job_id)
        self._queue.put((job_id, idea, token))
        self.start()
        return job_id, position

    def get(self, job_id: str) -> dict | None:
        self.purge_expired()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            out: dict = {
                "job_id": job["job_id"],
                "status": job["status"],
                "stage": job["stage"],
                "detail": job["detail"],
                "position": self._position(job_id),
                "error": job["error"],
            }
            if job["status"] == "done":
                out["result"] = job["result"]
            return out

    def purge_expired(self) -> None:
        now = self._clock()
        with self._lock:
            expired = [
                jid
                for jid, j in self._jobs.items()
                if j["status"] in ("done", "failed")
                and j["finished_at"] is not None
                and now - j["finished_at"] > self._ttl
            ]
            for jid in expired:
                del self._jobs[jid]

    # ── internals ─────────────────────────────────────────────────────

    def _position(self, job_id: str) -> int | None:
        """1-based queue position (caller must hold self._lock)."""
        job = self._jobs.get(job_id)
        if not job or job["status"] != "queued":
            return None
        order = job["_order"]
        return sum(
            1
            for j in self._jobs.values()
            if j["status"] == "queued" and j["_order"] <= order
        )

    def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            job_id, idea, token = item
            try:
                self._run_one_job(job_id, idea, token)
            except Exception:
                pass

    def _run_one_job(self, job_id: str, idea: str, token: str | None = None) -> None:
        last_stage: list[str | None] = [None]

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = "running"

        def on_stage(name: str, detail: dict | None) -> None:
            last_stage[0] = name
            with self._lock:
                j = self._jobs.get(job_id)
                if j:
                    j["stage"] = name
                    j["detail"] = detail

        jev_exhausted = self._access is not None and self._access.is_exhausted("jev")
        dm = demo_mode()
        if jev_exhausted:
            mode = "llm_only"
            fallback_reason: str | None = "llm_only (Jev quota exhausted)"
        elif dm == "llm_only":
            mode = "llm_only"
            fallback_reason = None
        else:
            mode = "pipeline"
            fallback_reason = None

        start = self._clock()
        try:
            if self._redact:
                idea, _ = self._redact(idea)

            response = self._try_pipeline(idea, mode, on_stage)
        except DecisionRateLimitError as exc:
            if exc.free_quota_exhausted and mode != "llm_only":
                if self._access:
                    self._access.set_exhausted("jev")
                try:
                    response = self._try_pipeline(idea, "llm_only", on_stage)
                    fallback_reason = "llm_only (Jev quota exhausted)"
                except Exception as retry_exc:
                    self._fail_job(job_id, retry_exc, last_stage[0], token, start)
                    return
            else:
                self._fail_job(job_id, exc, last_stage[0], token, start)
                return
        except Exception as exc:
            if isinstance(exc, RateLimitError):
                retry_after = getattr(exc, "retry_after_seconds", None) or 0
                if retry_after > 300 and self._access:
                    self._access.set_exhausted("groq")
            self._fail_job(job_id, exc, last_stage[0], token, start)
            return

        # ── success ───────────────────────────────────────────────────
        if response.design_warnings:
            for w in response.design_warnings:
                if "validation skipped: rate limited" in w:
                    if self._access:
                        self._access.set_exhausted("jev")
                    break

        result = response.model_dump(mode="json")
        if fallback_reason:
            meta = result.get("meta")
            if meta is not None:
                meta["fallback"] = fallback_reason

        with self._lock:
            j = self._jobs.get(job_id)
            if j:
                j["status"] = "done"
                j["result"] = result
                j["finished_at"] = self._clock()
                j["stage"] = "done"
                j["detail"] = None

        if self._access and token:
            self._access.release(token, app_failure=False)

        logger.info("job %s done %.1fs", job_id, self._clock() - start)

    def _try_pipeline(self, idea, mode, on_stage):
        request = DesignRequest(
            idea=idea,
            stage="validate",
            writer_style="confident",
            max_revisions=0,
            mode=mode,
        )
        llm = self._llm_factory()
        dp = self._decision_factory()
        return run_pipeline(
            request, llm, dp, on_stage=on_stage, budget=self._budget,
        )

    def _fail_job(self, job_id, exc, last_stage, token, start):
        status, msg = map_pipeline_error(exc, last_stage)
        with self._lock:
            j = self._jobs.get(job_id)
            if j:
                j["status"] = "failed"
                j["error"] = {"status": status, "message": msg}
                j["finished_at"] = self._clock()
                j["stage"] = None
                j["detail"] = None
        if self._access and token:
            self._access.release(token, app_failure=True)
        logger.info(
            "job %s failed %d %.1fs",
            job_id, status, self._clock() - start,
        )
