import threading
from autoPDFtagger.logging_utils import board_state


def test_parallel_pipeline_orders_ocr_before_text(monkeypatch, make_pdf_document, caplog):
    from autoPDFtagger.autoPDFtagger import autoPDFtagger
    from autoPDFtagger import ai_tasks

    # create two documents
    doc1 = make_pdf_document("a.pdf")
    doc2 = make_pdf_document("b.pdf")

    # record call order per document
    calls = []
    calls_lock = threading.Lock()

    def fake_get_pdf_text(self):
        with calls_lock:
            calls.append(("ocr", self.file_name))
        return "stub text"

    def fake_analyze_text(doc, *args, **kwargs):
        with calls_lock:
            calls.append(("text", doc.file_name))
        return "{}", {"cost": 0.5}

    def fake_analyze_images(doc, *args, **kwargs):
        with calls_lock:
            calls.append(("image", doc.file_name))
        return "{}", {"cost": 0.25}

    monkeypatch.setattr(type(doc1), "get_pdf_text", fake_get_pdf_text, raising=False)
    monkeypatch.setattr(ai_tasks, "analyze_text", fake_analyze_text)
    monkeypatch.setattr(ai_tasks, "analyze_images", fake_analyze_images)

    arch = autoPDFtagger(ocr_runner=None)
    arch.file_list.add_pdf_document(doc1)
    arch.file_list.add_pdf_document(doc2)

    caplog.set_level("INFO")
    prev_enabled = board_state.enabled
    prev_current = board_state.current
    board_state.enabled = False
    board_state.current = ""
    try:
        arch.run_jobs_parallel(do_text=True, do_image=True, enable_ocr=True)
    finally:
        board_state.enabled = prev_enabled
        board_state.current = prev_current

    # For each document, ensure OCR call precedes text call
    for name in ("a.pdf", "b.pdf"):
        o_idx = next(i for i, c in enumerate(calls) if c == ("ocr", name))
        t_idx = next(i for i, c in enumerate(calls) if c == ("text", name))
        assert o_idx < t_idx

    # status lines should appear in fallback logging mode
    assert any("Jobs: pending=" in rec.message for rec in caplog.records)
