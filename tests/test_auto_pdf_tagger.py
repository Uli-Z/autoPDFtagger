import logging
from types import SimpleNamespace

import pytest

from autoPDFtagger.autoPDFtagger import autoPDFtagger


def test_add_file_uses_directory_when_base_dir_missing(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")

    tagger = autoPDFtagger()
    captured = {}

    def fake_add(path, base_dir):
        captured["args"] = (path, base_dir)

    monkeypatch.setattr(tagger.file_list, "add_pdf_documents_from_folder", fake_add)

    tagger.add_file(str(pdf_path), base_dir=str(tmp_path / "missing"))

    assert captured["args"] == (str(pdf_path), str(tmp_path))


def test_add_file_relative_path_uses_cwd_when_no_base_dir(tmp_path, monkeypatch):
    # Create a file in the temp cwd and switch into it
    pdf_name = "rel.pdf"
    (tmp_path / pdf_name).write_bytes(b"%PDF-1.4\n%EOF\n")

    tagger = autoPDFtagger()
    called = {}

    def fake_add(folder_or_file, base_dir):
        called["args"] = (folder_or_file, base_dir)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tagger.file_list, "add_pdf_documents_from_folder", fake_add)

    # Call with relative file name; base_dir should resolve to CWD
    tagger.add_file(pdf_name, base_dir=None)

    assert called["args"][0] == pdf_name
    assert called["args"][1] == str(tmp_path)


def test_keep_incomplete_documents_filters(monkeypatch):
    tagger = autoPDFtagger()
    good = SimpleNamespace(
        has_sufficient_information=lambda threshold: True,
        get_absolute_path=lambda: "good.pdf",
    )
    bad = SimpleNamespace(
        has_sufficient_information=lambda threshold: False,
        get_absolute_path=lambda: "bad.pdf",
    )
    tagger.file_list.pdf_documents = {"good": good, "bad": bad}

    tagger.keep_incomplete_documents(threshold=5)

    assert list(tagger.file_list.pdf_documents.values()) == [good]


def test_keep_complete_documents_filters(monkeypatch):
    tagger = autoPDFtagger()
    good = SimpleNamespace(
        has_sufficient_information=lambda threshold: True,
        get_absolute_path=lambda: "good.pdf",
    )
    bad = SimpleNamespace(
        has_sufficient_information=lambda threshold: False,
        get_absolute_path=lambda: "bad.pdf",
    )
    tagger.file_list.pdf_documents = {"good": good, "bad": bad}

    tagger.keep_complete_documents(threshold=5)

    assert list(tagger.file_list.pdf_documents.values()) == [bad]


def test_ai_text_analysis_accumulates_cost(monkeypatch, caplog):
    tagger = autoPDFtagger()

    class DummyDoc:
        def __init__(self, name):
            self.file_name = name
            self.received = []

        def set_from_json(self, payload):
            self.received.append(payload)

    doc_a = DummyDoc("a.pdf")
    doc_b = DummyDoc("b.pdf")
    tagger.file_list.pdf_documents = {"a": doc_a, "b": doc_b}

    call_index = {"i": 0}

    def fake_analyze_text(doc, ms, ml, thr):
        # simulate two calls with different costs
        idx = call_index["i"]
        call_index["i"] = idx + 1
        return "{}", {"cost": 0.5 if idx == 0 else 1.0}

    monkeypatch.setattr("autoPDFtagger.ai_tasks.analyze_text", fake_analyze_text)

    caplog.set_level(logging.INFO)
    tagger.ai_text_analysis()

    assert doc_a.received == ["{}"]
    assert doc_b.received == ["{}"]
    assert any("Spent 1.5000 $ for text analysis" in record.message for record in caplog.records)


def test_ai_image_analysis_updates_documents(monkeypatch, caplog):
    tagger = autoPDFtagger()

    class DummyDoc:
        def __init__(self):
            self.file_name = "img.pdf"
            self.received = []

        def set_from_json(self, payload):
            self.received.append(payload)

    doc = DummyDoc()
    tagger.file_list.pdf_documents = {"img": doc}

    def fake_analyze_images(doc, model=None):
        return '{"image": true}', {"cost": 0.75}

    monkeypatch.setattr("autoPDFtagger.ai_tasks.analyze_images", fake_analyze_images)

    caplog.set_level(logging.INFO)
    tagger.ai_image_analysis()

    assert doc.received == ['{"image": true}']
    assert any("Spent 0.75 $ for image analysis" in record.message for record in caplog.records)


def test_ai_text_analysis_handles_errors(monkeypatch, caplog):
    tagger = autoPDFtagger()

    class DummyDoc:
        def __init__(self):
            self.file_name = "failed.pdf"
            self.received = []

        def set_from_json(self, payload):
            self.received.append(payload)

    doc = DummyDoc()
    tagger.file_list.pdf_documents = {"doc": doc}

    def failing_analyze_text(doc, *a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("autoPDFtagger.ai_tasks.analyze_text", failing_analyze_text)

    caplog.set_level(logging.ERROR)
    tagger.ai_text_analysis()

    assert not doc.received  # no data written on failure
    assert any("Text analysis failed" in record.message for record in caplog.records)


def test_ai_tag_analysis_applies_replacements(monkeypatch):
    tagger = autoPDFtagger()
    tagger.file_list.pdf_documents = {}
    monkeypatch.setattr(tagger.file_list, "get_unique_tags", lambda: ["alpha", "beta"])
    applied = {}

    def fake_apply(replacements):
        applied["value"] = replacements

    monkeypatch.setattr(tagger.file_list, "apply_tag_replacements_to_all", fake_apply)

    def fake_analyze_tags(tags, model=""):
        return [{"original": "alpha", "replacement": "a"}], {"cost": 2.0}

    monkeypatch.setattr("autoPDFtagger.ai_tasks.analyze_tags", fake_analyze_tags)

    tagger.ai_tag_analysis()

    assert applied["value"] == [{"original": "alpha", "replacement": "a"}]


def test_get_stats_compiles_summary(monkeypatch):
    tagger = autoPDFtagger()

    class StatsDoc:
        def __init__(self, name, text, images):
            self.file_name = name
            self.pages = list(range(3))
            self._text = text
            self._images = images

        def get_image_number(self):
            return self._images

        def get_pdf_text(self):
            return self._text

        def get_confidence_index(self):
            return 7.2

    doc = StatsDoc("stat.pdf", "word " * 30, 2)
    tagger.file_list.pdf_documents = {"stat": doc}
    monkeypatch.setattr(tagger.file_list, "get_unique_tags", lambda: ["x", "y"])

    stats = tagger.get_stats()

    assert stats["Total Documents"] == 1
    assert stats["Total Pages"] == 3
    assert stats["Total Images"] == 2
    assert stats["Unique Tags"] == 2
    assert stats["Estimated Text Analysis Cost ($)"] == "0.00 - 0.01"
    assert "7: #" in stats["Confidence-index Histogram"]


def test_create_confidence_histogram_empty_list(monkeypatch):
    tagger = autoPDFtagger()
    tagger.file_list.pdf_documents = {}

    histogram = tagger.create_confidence_histogram(tagger.file_list)

    assert histogram.strip() == "(no documents)"
