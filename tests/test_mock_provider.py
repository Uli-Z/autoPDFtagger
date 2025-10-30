import json
from pathlib import Path

import pytest

from autoPDFtagger import ai_tasks, mock_provider


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


def test_fetch_prefers_task_specific_then_falls_back(make_pdf_document, tmp_path):
    doc = make_pdf_document("fixture.pdf")
    pdf_path = Path(doc.get_absolute_path())

    mock_provider.reset()
    _write_mock(pdf_path.with_name(f"{pdf_path.stem}.text.json"), {"response": {"value": "task"}})
    _write_mock(pdf_path.with_name(f"{pdf_path.stem}.json"), {"response": {"value": "generic"}})

    first_response, first_usage = mock_provider.fetch(doc, "text")
    second_response, second_usage = mock_provider.fetch(doc, "text")

    assert json.loads(first_response)["value"] == "task"
    assert json.loads(second_response)["value"] == "generic"
    assert first_usage["cost"] == 0.0
    assert second_usage["cost"] == 0.0


def test_fetch_numeric_usage_is_coerced(make_pdf_document):
    doc = make_pdf_document("usage.pdf")
    pdf_path = Path(doc.get_absolute_path())

    mock_provider.reset()
    _write_mock(pdf_path.with_name(f"{pdf_path.stem}.text.json"), {"response": {"value": "ok"}, "usage": 0.42})

    response, usage = mock_provider.fetch(doc, "text")

    assert json.loads(response)["value"] == "ok"
    assert usage == {"cost": 0.42}


def test_fetch_logs_context_mismatch(make_pdf_document, caplog):
    doc = make_pdf_document("context.pdf")
    pdf_path = Path(doc.get_absolute_path())

    mock_provider.reset()
    _write_mock(
        pdf_path.with_name(f"{pdf_path.stem}.text.json"),
        {"response": {"value": "ok"}, "meta": {"expected": {"words": 10}}},
    )

    caplog.set_level("INFO")
    response, usage = mock_provider.fetch(doc, "text", context={"words": 20})

    assert json.loads(response)["value"] == "ok"
    assert usage["cost"] == 0.0
    assert any("Mock metadata mismatch" in record.message for record in caplog.records)


def test_fetch_handles_invalid_json(make_pdf_document, caplog):
    doc = make_pdf_document("broken.pdf")
    pdf_path = Path(doc.get_absolute_path())

    mock_provider.reset()
    broken_file = pdf_path.with_name(f"{pdf_path.stem}.text.json")
    broken_file.write_text("{not-valid-json", encoding="utf-8")

    caplog.set_level("WARNING")
    response, usage = mock_provider.fetch(doc, "text")

    assert response is None
    assert usage == {"cost": 0.0}
    assert any("Failed to load mock response" in record.message for record in caplog.records)
