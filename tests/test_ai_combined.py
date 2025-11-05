import json
import logging
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from autoPDFtagger.PDFDocument import PDFDocument
from autoPDFtagger import ai_tasks
from autoPDFtagger.config import config


def make_pdf(tmp_path: Path, name: str, pages: list[str]) -> Path:
    p = tmp_path / name
    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        rect = fitz.Rect(36, 36, 559, 806)
        page.insert_textbox(rect, text, fontsize=12, fontname="helv")
    doc.save(p)
    doc.close()
    return p


@pytest.fixture(autouse=True)
def _reset_config():
    # Ensure AI section exists and set generous defaults; tests will override per-case
    if not config.has_section("AI"):
        config.add_section("AI")
    # Yield to test and then clean up any specific keys we set
    pre = dict(config.items("AI")) if config.has_section("AI") else {}
    try:
        yield
    finally:
        # Restore previous values
        for k in list(dict(config.items("AI"))):
            if k not in pre:
                config.remove_option("AI", k)
        for k, v in pre.items():
            config.set("AI", k, v)


def test_combined_text_only_trimming_and_log(tmp_path, monkeypatch, caplog):
    # Build a 3-page text-only PDF with enough text to trigger trimming under a small limit
    text1 = "Page1 " * 400
    text2 = "Page2 " * 400
    text3 = "Page3 " * 400
    pdf_path = make_pdf(tmp_path, "a.pdf", [text1, text2, text3])
    doc = PDFDocument(str(pdf_path), str(tmp_path))

    # Set a per-file token limit to force trimming but not abort on intro
    config.set("AI", "token_limit", "1000")

    captured_parts = {}

    def fake_run_vision(model, prompt, images_b64, temperature=1.0, parts=None):
        captured_parts["parts"] = parts or []
        # Minimal JSON object response
        return json.dumps({"title": "X", "title_confidence": 9}), {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_vision", fake_run_vision)

    caplog.set_level(logging.INFO)
    resp, usage = ai_tasks.analyze_combined(doc, model="openai/gpt-5-nano")
    assert resp is not None
    # Trimming should be logged for this file
    assert any("[image budget]" in rec.message and "trimmed text" in rec.message and "a.pdf" in rec.message for rec in caplog.records)
    # Parts should begin with a text element containing [Page 1], then [Page 2], etc.
    parts = captured_parts.get("parts", [])
    assert parts, "Expected parts to be built and sent to vision client"
    texts = [p for p in parts if p.get("type") == "text"]
    assert any("[Page 1]" in (t.get("text") or "") for t in texts)
    assert any("[Page 2]" in (t.get("text") or "") for t in texts)


def test_visual_debug_writes_pdf_and_no_api(tmp_path, monkeypatch):
    pdf_path = make_pdf(tmp_path, "b.pdf", ["Hello world"])
    doc = PDFDocument(str(pdf_path), str(tmp_path))

    called = {"run": False}

    def should_not_call(*args, **kwargs):
        called["run"] = True
        raise AssertionError("run_vision must not be called in visual-debug mode")

    monkeypatch.setattr(ai_tasks, "run_vision", should_not_call)

    out_pdf = tmp_path / "vis.pdf"
    resp, usage = ai_tasks.analyze_combined(doc, model="openai/gpt-5-nano", visual_debug_path=str(out_pdf))
    assert out_pdf.exists() and out_pdf.stat().st_size > 0
    assert called["run"] is False
    # In visual debug, no API response is expected
    assert usage.get("dry_run") is True


def test_text_confidence_normalization(tmp_path, monkeypatch, caplog):
    pdf_path = make_pdf(tmp_path, "c.pdf", ["Short text for normalization test."])
    doc = PDFDocument(str(pdf_path), str(tmp_path))

    # Force the short model to be chosen to hit our stub deterministically
    config.set("AI", "text_model_short", "stub/text")
    config.set("AI", "text_model_long", "")
    config.set("AI", "token_limit", "100000")

    def fake_run_chat(model, messages, json_mode=True, temperature=0.3):
        payload = {
            "title": "T",
            "title_confidence": 0.8,
            "summary": "S",
            "summary_confidence": 0.6,
            "tags": ["A"],
            "tags_confidence": [0.7],
        }
        return json.dumps(payload), {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_chat", fake_run_chat)
    caplog.set_level(logging.INFO)
    text, usage = ai_tasks.analyze_text(doc, model_short="stub/text", model_long="", threshold_words=100)
    assert text is not None
    data = json.loads(text)
    # Expect scaled confidences to integers 0..10
    assert data["title_confidence"] == 8
    assert data["summary_confidence"] == 6
    assert data["tags_confidence"] == [7]
    # And the normalization was logged
    assert any("[confidence normalize]" in rec.message for rec in caplog.records)


def test_pre_call_log_includes_tokens(tmp_path, monkeypatch, caplog):
    pdf_path = make_pdf(tmp_path, "d.pdf", ["Alpha", "Beta"])  # two small pages
    doc = PDFDocument(str(pdf_path), str(tmp_path))
    config.set("AI", "token_limit", "10000")

    def fake_run_vision(model, prompt, images_b64, temperature=1.0, parts=None):
        return json.dumps({}), {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_vision", fake_run_vision)
    caplog.set_level(logging.DEBUG)
    ai_tasks.analyze_combined(doc, model="openai/gpt-5-nano")
    # Unified request log should include tokens and parts
    lines = [rec.message for rec in caplog.records if "request] tokens:" in rec.message]
    assert any("(parts=" in line for line in lines), f"Missing parts info in logs: {lines}"
