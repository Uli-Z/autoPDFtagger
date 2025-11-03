import json

import pytest

from autoPDFtagger import ai_tasks
from autoPDFtagger.ai_tasks import ImageCandidate
from autoPDFtagger.config import config


class _StubTextDoc:
    def __init__(self, text="short text"):
        self._text = text
        self._api_json = json.dumps({
            "summary": "",
            "summary_confidence": 0,
            "title": "",
            "title_confidence": 0,
            "creation_date": None,
            "creation_date_confidence": 0,
            "creator": "",
            "creator_confidence": 0,
            "tags": [],
            "tags_confidence": [],
            "importance": None,
            "importance_confidence": 0,
        })

    def get_pdf_text(self):
        return self._text

    def get_short_description(self):
        return "desc"

    def to_api_json(self):
        return self._api_json


def _make_selection_doc(pages, images):
    class _Doc:
        def __init__(self, pages, images):
            self.pages = pages
            self.images = images

        def analyze_document_images(self):
            return None

    return _Doc(pages, images)


def test_analyze_text_model_selection(monkeypatch):
    captured = {}

    def fake_run_chat(model, messages, json_mode=False, schema=None, temperature=0.3, max_tokens=None):
        captured["model"] = model
        captured["messages"] = messages
        return "{}", {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_chat", fake_run_chat)

    long_doc = _StubTextDoc("word " * 150)
    ai_tasks.analyze_text(long_doc, model_short="m_short", model_long="m_long", threshold_words=100)
    assert captured["model"] == "m_long"

    short_doc = _StubTextDoc("word " * 20)
    ai_tasks.analyze_text(short_doc, model_short="m_short", model_long="m_long", threshold_words=100)
    assert captured["model"] == "m_short"


def test_analyze_text_skips_without_model():
    doc = _StubTextDoc("hello world")
    text, usage = ai_tasks.analyze_text(doc, model_short="", model_long="", threshold_words=10)
    assert text is None and usage.get("cost", 1) == 0.0


def test_analyze_tags_parses_and_cleans(monkeypatch):
    payload = json.dumps([
        {"original": " Alpha ", "replacement": "alpha"},
        ["bad", "entry"],
        {"original": 123, "replacement": 456},
    ])

    def fake_run_chat(model, messages, json_mode=False, schema=None, temperature=0.3, max_tokens=None):
        return payload, {"cost": 0.01}

    monkeypatch.setattr(ai_tasks, "run_chat", fake_run_chat)

    repl, usage = ai_tasks.analyze_tags(["Alpha", "BETA"], model="stub/tagger")
    assert usage.get("cost") == 0.01
    assert {tuple(sorted(d.items())) for d in repl} == {
        tuple(sorted({"original": " Alpha ", "replacement": "alpha"}.items())),
        tuple(sorted({"original": "123", "replacement": "456"}.items())),
    }


def test_json_guard_extracts_embedded_json():
    payload = 'noise {"key": "value", "num": 1} trailing'
    guarded = ai_tasks._json_guard(payload)
    assert json.loads(guarded) == {"key": "value", "num": 1}


def test_json_guard_returns_empty_object_for_invalid_text():
    guarded = ai_tasks._json_guard("no braces here")
    assert json.loads(guarded) == {}


def test_select_images_prioritizes_front_pages():
    config.set("AI", "max_images_per_pdf", "2")
    config.set("AI", "first_pages_priority", "3")

    doc = _make_selection_doc(
        pages=[
            {"words_count": 18},
            {"words_count": 25},
            {"words_count": 15},
            {"words_count": 12},
        ],
        images=[
            [{"xref": 11, "width": 300, "height": 300, "page_coverage_percent": 40}],
            [],
            [],
            [{"xref": 44, "width": 600, "height": 600, "page_coverage_percent": 90}],
        ],
    )

    candidates = ai_tasks._select_images_for_analysis(doc)
    assert len(candidates) == 2
    assert candidates[0].kind == "xref" and candidates[0].page_index == 0
    assert candidates[1].kind == "xref" and candidates[1].page_index == 3


def test_select_images_groups_small_icons_into_page_candidate():
    config.set("AI", "max_images_per_pdf", "1")
    config.set("AI", "group_small_images_per_page", "true")
    config.set("AI", "small_images_group_threshold", "3")
    config.set("AI", "exclude_small_icons", "true")
    config.set("AI", "min_icon_edge_cm", "2.5")

    tiny = {"width": 36, "height": 36, "page_coverage_percent": 5, "xref": 1}
    doc = _make_selection_doc(
        pages=[{"words_count": 10}],
        images=[[tiny, dict(tiny, xref=2), dict(tiny, xref=3)]],
    )

    candidates = ai_tasks._select_images_for_analysis(doc)
    assert len(candidates) == 1
    assert candidates[0].kind == "page" and candidates[0].page_index == 0


def test_select_images_marks_scan_pages():
    config.set("AI", "max_images_per_pdf", "1")
    config.set("AI", "scan_coverage_threshold", "0.95")

    doc = _make_selection_doc(
        pages=[{"words_count": 4}],
        images=[[{"xref": 5, "width": 600, "height": 800, "page_coverage_percent": 98}]],
    )

    candidates = ai_tasks._select_images_for_analysis(doc)
    assert len(candidates) == 1
    assert candidates[0].kind == "page" and candidates[0].is_scan is True


def test_select_images_vector_fallback_when_no_images():
    config.set("AI", "max_images_per_pdf", "2")
    config.set("AI", "vector_fallback_words_threshold", "5")
    config.set("AI", "vector_fallback_max_pages", "1")

    doc = _make_selection_doc(
        pages=[{"words_count": 3}, {"words_count": 12}],
        images=[[], []],
    )

    candidates = ai_tasks._select_images_for_analysis(doc)
    assert len(candidates) == 1
    assert candidates[0].kind == "page" and candidates[0].page_index == 0


def test_analyze_images_renders_candidates_with_context(monkeypatch, caplog):
    config.set("AI", "image_context_max_chars", "30")
    config.set("AI", "page_render_max_px", "512")
    config.set("AI", "image_render_max_px", "256")

    class Doc:
        def __init__(self):
            self.render_calls = []

        def get_page_text(self, page_index, use_ocr_if_needed=True):
            assert use_ocr_if_needed
            return f"Page {page_index} text with extra context and details"

        def render_image_region_png_base64(self, xref, max_px):
            self.render_calls.append(("region", xref, max_px))
            return f"region-{xref}"

        def get_png_image_base64_by_xref(self, xref):
            self.render_calls.append(("fallback", xref, None))
            return f"raw-{xref}"

        def render_page_png_base64(self, page_index, max_px):
            self.render_calls.append(("page", page_index, max_px))
            return f"page-{page_index}"

        def to_api_json(self):
            return "{}"

    doc = Doc()
    candidates = [
        ImageCandidate(kind="xref", page_index=0, xref=5, area_ratio=0.6, is_scan=False, words_count=0, score=1000.5),
        ImageCandidate(kind="page", page_index=1, xref=None, area_ratio=1.0, is_scan=True, words_count=0, score=995.0),
    ]
    monkeypatch.setattr(ai_tasks, "_select_images_for_analysis", lambda _doc: candidates)

    captured = {}

    def fake_run_vision(model, prompt, images_b64, temperature=0.8, max_tokens=None):
        captured["model"] = model
        captured["prompt"] = prompt
        captured["images"] = images_b64
        return 'noise {"foo": 1}', {"cost": 0.123}

    monkeypatch.setattr(ai_tasks, "run_vision", fake_run_vision)
    caplog.set_level("INFO")

    response, usage = ai_tasks.analyze_images(doc, model="stub/vision")

    assert json.loads(response) == {"foo": 1}
    assert usage["cost"] == pytest.approx(0.123)
    assert captured["images"] == ["region-5", "page-1"]
    assert "Image 1 (page 1; kind=xref" in captured["prompt"]
    assert "Image 2 (page 2; kind=page" in captured["prompt"]
    assert "Context (trimmed): Page 0 text" in captured["prompt"]
    assert "…" in captured["prompt"]
    assert "Image selection summary — page 1: 1, page 2: 1" in caplog.text
    assert ("fallback", 5, None) not in doc.render_calls


def test_analyze_images_falls_back_to_raw_xref(monkeypatch):
    class Doc:
        def get_page_text(self, page_index, use_ocr_if_needed=True):
            return "context"

        def render_image_region_png_base64(self, xref, max_px):
            return None

        def get_png_image_base64_by_xref(self, xref):
            return f"raw-{xref}"

        def render_page_png_base64(self, page_index, max_px):
            raise AssertionError("should not render page")

        def to_api_json(self):
            return "{}"

    doc = Doc()
    candidates = [
        ImageCandidate(kind="xref", page_index=0, xref=8, area_ratio=0.4, is_scan=False, words_count=0, score=1000.0)
    ]
    monkeypatch.setattr(ai_tasks, "_select_images_for_analysis", lambda _doc: candidates)

    captured = {}

    def fake_run_vision(model, prompt, images_b64, temperature=0.8, max_tokens=None):
        captured["images"] = images_b64
        return "{}", {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_vision", fake_run_vision)

    response, usage = ai_tasks.analyze_images(doc, model="stub/vision")
    assert json.loads(response) == {}
    assert captured["images"] == ["raw-8"]


def test_analyze_images_returns_none_when_no_candidates(monkeypatch):
    class Doc:
        def to_api_json(self):
            return "{}"

    monkeypatch.setattr(ai_tasks, "_select_images_for_analysis", lambda _doc: [])
    response, usage = ai_tasks.analyze_images(Doc(), model="stub/vision")
    assert response is None
    assert usage == {"cost": 0.0}


def test_analyze_images_skips_without_model():
    class Doc:
        def analyze_document_images(self):
            pass

    text, usage = ai_tasks.analyze_images(Doc(), model="")
    assert text is None and usage.get("cost", 1) == 0.0
