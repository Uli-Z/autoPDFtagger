import json
from pathlib import Path

import pytest

from autoPDFtagger import ai_tasks


def _write_mock(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_analyze_text_uses_mock_response(monkeypatch, make_pdf_document):
    doc = make_pdf_document("invoice.pdf")
    pdf_path = Path(doc.get_absolute_path())
    mock_path = pdf_path.with_name(f"{pdf_path.stem}.text.json")
    _write_mock(
        mock_path,
        {
            "response": {
                "title": "Mock Title",
                "summary": "Mock Summary",
            },
            "usage": {"cost": 0.0, "tokens": 42},
        },
    )

    def fail_run_chat(*args, **kwargs):
        pytest.fail("run_chat should not be called when using TEST/text")

    monkeypatch.setattr("autoPDFtagger.ai_tasks.run_chat", fail_run_chat)

    response, usage = ai_tasks.analyze_text(doc, model_short="TEST/text", model_long="", threshold_words=100)

    assert json.loads(response)["title"] == "Mock Title"
    assert usage["cost"] == 0.0
    assert usage["tokens"] == 42


def test_analyze_images_handles_multiple_mock_calls(monkeypatch, make_pdf_document):
    doc = make_pdf_document("scan.pdf")
    pdf_path = Path(doc.get_absolute_path())

    first = pdf_path.with_name(f"{pdf_path.stem}.image.0.json")
    second = pdf_path.with_name(f"{pdf_path.stem}.image.1.json")
    _write_mock(first, {"response": {"title": "Vision 1"}, "usage": {"cost": 0.1}})
    _write_mock(second, {"response": {"title": "Vision 2"}, "usage": {"cost": 0.2}})

    # Ensure we do not hit the real vision client
    def fail_run_vision(*args, **kwargs):
        pytest.fail("run_vision should not be called when using TEST/image")

    monkeypatch.setattr("autoPDFtagger.ai_tasks.run_vision", fail_run_vision)
    # Avoid expensive image extraction by stubbing selector
    monkeypatch.setattr("autoPDFtagger.ai_tasks._select_images_for_analysis", lambda _doc: ["img-a", "img-b", "img-c"])

    first_response, first_usage = ai_tasks.analyze_images(doc, model="TEST/image")
    second_response, second_usage = ai_tasks.analyze_images(doc, model="TEST/image")
    third_response, third_usage = ai_tasks.analyze_images(doc, model="TEST/image")

    assert json.loads(first_response)["title"] == "Vision 1"
    assert first_usage["cost"] == 0.1

    assert json.loads(second_response)["title"] == "Vision 2"
    assert second_usage["cost"] == 0.2

    assert third_response is None
    assert third_usage["cost"] == 0.0
