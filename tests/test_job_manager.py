import time
from autoPDFtagger.job_manager import JobManager, Job
from autoPDFtagger.logging_utils import board_state


def test_job_manager_executes_with_dependencies(caplog):
    calls = []

    def a_run():
        calls.append("a")

    def b_run():
        calls.append("b")

    jm = JobManager(ocr_workers=1, ai_workers=1, status_interval_sec=0.2)
    jm.add_job(Job(id="a", kind="ocr", run=a_run))
    jm.add_job(Job(id="b", kind="text", run=b_run, deps=["a"]))

    pending, running, done, failed = jm.run()

    assert failed == 0
    assert done == 2
    assert calls == ["a", "b"]  # dependency enforced


def test_job_manager_logs_status(caplog):
    caplog.set_level("INFO")
    prev_enabled = board_state.enabled
    prev_current = board_state.current
    board_state.enabled = False
    board_state.current = ""
    try:
        jm = JobManager(ocr_workers=1, ai_workers=1, status_interval_sec=0.05)
        jm.add_job(Job(id="x", kind="ocr", run=lambda: time.sleep(0.2)))
        jm.add_job(Job(id="y", kind="text", run=lambda: None, deps=["x"]))
        jm.run()
    finally:
        board_state.enabled = prev_enabled
        board_state.current = prev_current
    # at least one periodic summary line
    assert any("Jobs: pending=" in rec.message for rec in caplog.records)
