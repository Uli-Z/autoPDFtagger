import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Set

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
        # Track which kind status bars have been finalized and logged
        self._finalized_kinds: Set[str] = set()
        # Fast tick for UI smoothness; real log rate still throttled
        self._tick_interval = min(0.2, self.status_interval_sec)
        # Event to wake the status loop immediately on job state changes
        self._wakeup = threading.Event()

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

                def render_bar(metrics, width=24):
                    total = max(1, sum(metrics.values()))
                    remaining = width

                    def take(count: int) -> int:
                        nonlocal remaining
                        if count <= 0 or remaining <= 0:
                            return 0
                        portion = int(round(width * count / total))
                        if portion == 0:
                            portion = 1
                        portion = min(portion, remaining)
                        remaining -= portion
                        return portion

                    done_w = take(metrics["d"])
                    run_w = take(metrics["r"])
                    fail_w = take(metrics["f"])
                    pending_w = max(0, remaining)
                    return "[" + "=" * done_w + ">" * run_w + "!" * fail_w + "." * pending_w + "]"

                def render_line(label: str, metrics: Dict[str, int], show_spinner: bool = False) -> str:
                    prefix = f"{spinner} " if show_spinner else "  "
                    bar = render_bar(metrics)
                    return (
                        f"{prefix}{label:<5} {bar} "
                        f"pending {metrics['p']} · running {metrics['r']} · "
                        f"done {metrics['d']} · failed {metrics['f']}"
                    )

                def render_done_line(label: str, metrics: Dict[str, int]) -> str:
                    bar = render_bar(metrics)
                    prefix = "✅ " if metrics.get("f", 0) == 0 else "⚠️ "
                    return (
                        f"{prefix}{label:<5} {bar} "
                        f"pending {metrics['p']} · running {metrics['r']} · "
                        f"done {metrics['d']} · failed {metrics['f']}"
                    )

                ordered_kinds = [
                    ("OCR", "OCR", kinds["ocr"]),
                    ("AI-Text", "AI-Text-Analysis", kinds["text"]),
                    ("AI-Image", "AI-Image-Analysis", kinds["image"]),
                ]
                active = [(short, full, metrics) for short, full, metrics in ordered_kinds if metrics["p"] or metrics["r"]]

                # Flush finished kinds once with a non-sticky, checkmarked status line
                finished_kinds: List[Tuple[str, str, Dict[str, int]]] = []
                for key, (_, full_label, metrics) in zip(["ocr", "text", "image"], ordered_kinds):
                    if key in self._finalized_kinds:
                        continue
                    if metrics["p"] == 0 and metrics["r"] == 0 and (metrics["d"] + metrics["f"]) > 0:
                        finished_kinds.append((key, full_label, metrics))
                        self._finalized_kinds.add(key)

                # Log finalized lines; upgrade to WARNING when failures occurred
                for key, label, metrics in finished_kinds:
                    line = render_done_line(label, metrics)
                    if board_state.enabled:
                        # Print the final line without timestamp, in-place above the live board
                        if board_state.suspend():
                            try:
                                board_state.stream.write(line + "\n")
                                board_state.stream.flush()
                            finally:
                                board_state.resume()
                    else:
                        # Fallback to standard logging when board is not active
                        if metrics.get("f", 0) > 0:
                            logging.warning(line)
                        else:
                            logging.info(line)
                    # Additionally, if there were failures, list failed files via logging (kept with timestamps)
                    if metrics.get("f", 0) > 0:
                        failed_files: List[str] = []
                        with self._lock:
                            for j in self.jobs.values():
                                if j.kind == key and j.status == "failed":
                                    try:
                                        _kind, path = j.id.split(":", 1)
                                    except ValueError:
                                        path = j.id
                                    failed_files.append(os.path.basename(path) or path)
                        if failed_files:
                            logging.warning(
                                "Failed %s files (%d): %s",
                                label,
                                len(failed_files),
                                ", ".join(sorted(failed_files)),
                            )

                status_lines = []
                for _idx, (short_label, full_label, metrics) in enumerate(active):
                    status_lines.append(
                        render_line(full_label, metrics, show_spinner=True)
                    )

                status_text = "\n".join(status_lines)

                if board_state.enabled:
                    if status_lines:
                        board_state.update(status_text)
                    else:
                        board_state.clear()
                else:
                    now = time.time()
                    if now - self._last_log_time >= self.status_interval_sec:
                        if status_lines:
                            logging.info("Job status:\n%s", status_text)
                            self._last_log_time = now
            except Exception:
                # Keep status thread robust
                pass
            finally:
                # Wait for either a tick or an explicit wakeup (job state change)
                self._wakeup.wait(self._tick_interval)
                # reset the wakeup flag so future job transitions can wake immediately
                self._wakeup.clear()

    def _mark(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        with self._lock:
            j = self.jobs[job_id]
            j.status = status
            j.error = error
        # Wake the status loop so final lines render immediately
        self._wakeup.set()

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
