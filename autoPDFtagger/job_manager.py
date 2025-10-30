import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from autoPDFtagger.logging_utils import board_state


@dataclass
class Job:
    id: str
    kind: str  # 'ocr' | 'text' | 'image'
    run: Callable[[], None]
    deps: List[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed
    error: Optional[str] = None


class JobManager:
    """Lightweight job manager with per-queue concurrency and simple dependencies.

    - Maintains three queues: OCR, AI (combined text+image), and optional per-kind splitting later.
    - Enforces dependencies by waiting for dependency futures before submitting work.
    - Emits periodic status summaries to the log.
    """

    def __init__(
        self,
        ocr_workers: int,
        ai_workers: int,
        status_interval_sec: float = 2.0,
    ) -> None:
        self.ocr_workers = max(1, int(ocr_workers or 1))
        self.ai_workers = max(1, int(ai_workers or 1))
        self.status_interval_sec = max(0.5, float(status_interval_sec))

        self.jobs: Dict[str, Job] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._status_thread: Optional[threading.Thread] = None
        self._spinner_index = 0
        self._last_log_time = 0.0

    def add_job(self, job: Job) -> None:
        with self._lock:
            if job.id in self.jobs:
                raise ValueError(f"Duplicate job id: {job.id}")
            self.jobs[job.id] = job

    def _status_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                pending = running = done = failed = 0
                kinds = {
                    "ocr": {"p": 0, "r": 0, "d": 0, "f": 0},
                    "text": {"p": 0, "r": 0, "d": 0, "f": 0},
                    "image": {"p": 0, "r": 0, "d": 0, "f": 0},
                }
                with self._lock:
                    for j in self.jobs.values():
                        if j.status == "pending":
                            pending += 1
                            kinds[j.kind]["p"] += 1
                        elif j.status == "running":
                            running += 1
                            kinds[j.kind]["r"] += 1
                        elif j.status == "done":
                            done += 1
                            kinds[j.kind]["d"] += 1
                        elif j.status == "failed":
                            failed += 1
                            kinds[j.kind]["f"] += 1
                spinner = "|/-\\"[self._spinner_index % 4]
                self._spinner_index += 1

                def render_bar(metrics, width=20):
                    done_count = metrics["d"]
                    running_count = metrics["r"]
                    failed_count = metrics["f"]
                    pending_count = metrics["p"]
                    total = max(1, done_count + running_count + failed_count + pending_count)
                    done_w = int(width * done_count / total)
                    run_w = int(width * running_count / total)
                    fail_w = int(width * failed_count / total)
                    remaining = width - done_w - run_w - fail_w
                    return "[" + "#" * done_w + "+" * run_w + "!" * fail_w + "." * max(0, remaining) + "]"

                status_line = (
                    f"{spinner} Jobs P:{pending} R:{running} D:{done} F:{failed} | "
                    f"OCR {render_bar(kinds['ocr'])} | TEXT {render_bar(kinds['text'])} | IMG {render_bar(kinds['image'])}"
                )

                if board_state.enabled:
                    board_state.update(status_line)
                else:
                    now = time.time()
                    if now - self._last_log_time >= self.status_interval_sec:
                        logging.info(
                            "Jobs: pending=%d running=%d done=%d failed=%d | "
                            "OCR(p/r/d/f=%d/%d/%d/%d) | TEXT(%d/%d/%d/%d) | IMAGE(%d/%d/%d/%d)",
                            pending,
                            running,
                            done,
                            failed,
                            kinds["ocr"]["p"], kinds["ocr"]["r"], kinds["ocr"]["d"], kinds["ocr"]["f"],
                            kinds["text"]["p"], kinds["text"]["r"], kinds["text"]["d"], kinds["text"]["f"],
                            kinds["image"]["p"], kinds["image"]["r"], kinds["image"]["d"], kinds["image"]["f"],
                        )
                        self._last_log_time = now
            except Exception:
                # Keep status thread robust
                pass
            finally:
                self._stop_event.wait(self.status_interval_sec)

    def _mark(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        with self._lock:
            j = self.jobs[job_id]
            j.status = status
            j.error = error

    def _submit_with_status(self, executor: ThreadPoolExecutor, job: Job, wait_for: List[Future]) -> Future:
        def runner():
            # Wait for dependencies
            for f in wait_for:
                try:
                    f.result()
                except Exception:
                    # Upstream failed; mark failed and abort
                    raise RuntimeError("Dependency failed")
            self._mark(job.id, "running")
            try:
                job.run()
                self._mark(job.id, "done")
            except Exception as exc:
                self._mark(job.id, "failed", error=str(exc))
                raise

        return executor.submit(runner)

    def run(self) -> Tuple[int, int, int, int]:
        """Run all added jobs. Blocks until all completed.

        Returns a tuple: (pending, running, done, failed) at completion time.
        """
        # Start status thread
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()

        # Build executors
        ocr_pool = ThreadPoolExecutor(max_workers=self.ocr_workers, thread_name_prefix="ocr")
        ai_pool = ThreadPoolExecutor(max_workers=self.ai_workers, thread_name_prefix="ai")

        try:
            # Submit jobs respecting dependencies and queues
            with self._lock:
                # We first submit OCR-only jobs so AI deps can reference futures
                for job in self.jobs.values():
                    if job.kind != "ocr":
                        continue
                    fut = self._submit_with_status(ocr_pool, job, [self._futures[d] for d in job.deps if d in self._futures])
                    self._futures[job.id] = fut

                # Submit AI jobs (text/image), wiring dependencies (including OCR)
                for job in self.jobs.values():
                    if job.kind == "ocr":
                        continue
                    wait_for = [self._futures[d] for d in job.deps if d in self._futures]
                    fut = self._submit_with_status(ai_pool, job, wait_for)
                    self._futures[job.id] = fut

            # Wait for completion
            for fut in as_completed(list(self._futures.values())):
                try:
                    fut.result()
                except Exception:
                    # Errors already recorded in job status; continue waiting
                    pass

        finally:
            self._stop_event.set()
            if self._status_thread:
                self._status_thread.join(timeout=1.0)
            ocr_pool.shutdown(wait=True, cancel_futures=False)
            ai_pool.shutdown(wait=True, cancel_futures=False)
            board_state.clear()

        # Final counts
        pending = running = done = failed = 0
        with self._lock:
            for j in self.jobs.values():
                if j.status == "pending":
                    pending += 1
                elif j.status == "running":
                    running += 1
                elif j.status == "done":
                    done += 1
                elif j.status == "failed":
                    failed += 1
        return pending, running, done, failed
