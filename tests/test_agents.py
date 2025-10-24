from types import SimpleNamespace

import pytest


try:
    from autoPDFtagger.AIAgents import AIAgent_OpenAI, OpenAI_model_pricelist
except Exception as exc:  # pragma: no cover - debug aid
    import sys
    import traceback

    traceback.print_exc()
    print("autoPDFtagger-related modules:", [name for name in sys.modules if name.startswith("autoPDFtagger")])
    raise exc
from autoPDFtagger import AIAgents_OpenAI_pdf
from autoPDFtagger.AIAgents_OpenAI_pdf import (
    AIAgent_OpenAI_pdf_image_analysis,
    AIAgent_OpenAI_pdf_text_analysis,
)


class _StubDoc:
    def __init__(self, text="short text"):
        self._text = text

    def get_pdf_text(self):
        return self._text

    def get_short_description(self):
        return "desc"


def test_text_agent_model_selection(monkeypatch):
    captured = []

    def fake_send_request(self, *args, **kwargs):
        captured.append({"model": self.model, "message": self.messages[-1]["content"]})
        return "{}"

    monkeypatch.setattr(AIAgent_OpenAI, "send_request", fake_send_request, raising=False)

    long_doc = _StubDoc("word " * 150)
    agent = AIAgent_OpenAI_pdf_text_analysis()
    agent.analyze_text(long_doc)
    assert captured[-1]["model"] == "gpt-3.5-turbo-1106"

    short_doc = _StubDoc("word " * 20)
    agent = AIAgent_OpenAI_pdf_text_analysis()
    agent.analyze_text(short_doc)
    assert captured[-1]["model"] == "gpt-4-1106-preview"


def test_text_agent_trims_message_when_exceeding_limit(monkeypatch):
    trimmed_messages = []

    def fake_num_tokens(_text, encoding_name="cl100k_base"):
        limit = OpenAI_model_pricelist["gpt-4-1106-preview"][2]
        return limit + 2000

    monkeypatch.setattr(AIAgents_OpenAI_pdf, "num_tokens_from_string", fake_num_tokens)

    def fake_send_request(self, *args, **kwargs):
        trimmed_messages.append(self.messages[-1]["content"])
        return "{}"

    monkeypatch.setattr(AIAgent_OpenAI, "send_request", fake_send_request, raising=False)

    # Use short text to keep model at gpt-4 (lower token limit), then force trimming
    short_doc = _StubDoc("word " * 20)
    agent = AIAgent_OpenAI_pdf_text_analysis()
    agent.analyze_text(short_doc)

    assert trimmed_messages  # ensure call happened
    # Message should have been trimmed to empty due to aggressive over-limit stub
    assert trimmed_messages[-1] == ""


def test_process_images_by_size_short_circuits(monkeypatch):
    calls = []

    def fake_send(self, document, images):
        calls.append(images)
        return "{}"

    monkeypatch.setattr(AIAgent_OpenAI_pdf_image_analysis, "send_image_request", fake_send, raising=False)

    class Doc:
        def __init__(self):
            self.images = [
                [
                    {"xref": 1, "original_width": 400, "original_height": 400},
                    {"xref": 2, "original_width": 310, "original_height": 310},
                ]
            ]
            self._ready = False

        def get_png_image_base64_by_xref(self, xref):
            return f"img-{xref}"

        def set_from_json(self, _):
            self._ready = True

        def has_sufficient_information(self, _threshold=7):
            return self._ready

    agent = AIAgent_OpenAI_pdf_image_analysis()
    doc = Doc()
    agent.process_images_by_size(doc)

    assert len(calls) == 1
    assert calls[0] == ["img-1", "img-2"]


def test_process_images_by_page_skips_missing_images(monkeypatch):
    calls = []

    def fake_send(self, document, images):
        calls.append(images)
        return "{}"

    monkeypatch.setattr(AIAgent_OpenAI_pdf_image_analysis, "send_image_request", fake_send, raising=False)

    class Doc:
        def __init__(self):
            self.pages = [
                {"page_number": 1, "max_img_xref": None},
                {"page_number": 2, "max_img_xref": 42},
            ]
            self._ready = False

        def get_png_image_base64_by_xref(self, xref):
            return f"page-{xref}"

        def set_from_json(self, _):
            self._ready = True

        def has_sufficient_information(self, _threshold=7):
            return self._ready

    agent = AIAgent_OpenAI_pdf_image_analysis()
    doc = Doc()
    agent.process_images_by_page(doc)

    assert len(calls) == 1
    assert calls[0] == ["page-42"]
