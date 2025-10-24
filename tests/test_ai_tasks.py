import json

from autoPDFtagger import ai_tasks


class _StubDoc:
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


def test_analyze_text_model_selection(monkeypatch):
    captured = {}

    def fake_run_chat(model, messages, json_mode=False, schema=None, temperature=0.3, max_tokens=None):
        captured["model"] = model
        captured["messages"] = messages
        return "{}", {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_chat", fake_run_chat)

    # long text uses long model
    long_doc = _StubDoc("word " * 150)
    ai_tasks.analyze_text(long_doc, model_short="m_short", model_long="m_long", threshold_words=100)
    assert captured["model"] == "m_long"

    # short text uses short model
    short_doc = _StubDoc("word " * 20)
    ai_tasks.analyze_text(short_doc, model_short="m_short", model_long="m_long", threshold_words=100)
    assert captured["model"] == "m_short"


def test_analyze_images_non_scanned_selects_largest(monkeypatch):
    calls = []

    def fake_run_vision(model, prompt, images_b64, temperature=0.2, max_tokens=None):
        calls.append(images_b64)
        return "{}", {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_vision", fake_run_vision)

    class Doc:
        def __init__(self):
            self.image_coverage = 50
            self.images = [[
                {"xref": 1, "original_width": 400, "original_height": 400},
                {"xref": 2, "original_width": 310, "original_height": 310},
                {"xref": 3, "original_width": 10, "original_height": 10},
            ]]
            self.pages = []

        def analyze_document_images(self):
            pass

        def get_png_image_base64_by_xref(self, xref):
            return f"img-{xref}"

        def to_api_json(self):
            return "{}"

    doc = Doc()
    ai_tasks.analyze_images(doc, model="vision")
    assert calls and calls[-1] == ["img-1", "img-2", "img-3"][:2] or len(calls[-1]) >= 2


def test_analyze_images_scanned_uses_page_max(monkeypatch):
    calls = []

    def fake_run_vision(model, prompt, images_b64, temperature=0.2, max_tokens=None):
        calls.append(images_b64)
        return "{}", {"cost": 0.0}

    monkeypatch.setattr(ai_tasks, "run_vision", fake_run_vision)

    class Doc:
        def __init__(self):
            self.image_coverage = 100
            self.pages = [
                {"page_number": 1, "max_img_xref": None},
                {"page_number": 2, "max_img_xref": 42},
            ]
            self.images = []

        def analyze_document_images(self):
            pass

        def get_png_image_base64_by_xref(self, xref):
            return f"page-{xref}"

        def to_api_json(self):
            return "{}"

    doc = Doc()
    ai_tasks.analyze_images(doc, model="vision")
    assert calls and calls[-1] == ["page-42"]


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


def test_analyze_text_skips_without_model():
    doc = _StubDoc("hello world")
    text, usage = ai_tasks.analyze_text(doc, model_short="", model_long="", threshold_words=10)
    assert text is None and usage.get("cost", 1) == 0.0


def test_analyze_images_skips_without_model():
    class Doc:
        def get_png_image_base64_by_xref(self, *_):
            return None

        def to_api_json(self):
            return "{}"

        def analyze_document_images(self):
            self.image_coverage = 0
            self.images = []
            self.pages = []

    doc = Doc()
    text, usage = ai_tasks.analyze_images(doc, model="")
    assert text is None and usage.get("cost", 1) == 0.0
