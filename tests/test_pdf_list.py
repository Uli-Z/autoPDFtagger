import json
import os

import pytest
import math

from autoPDFtagger.PDFList import PDFList


def test_clean_csv_row_converts_types():
    pdf_list = PDFList()
    raw = {
        "folder_path_abs": "/tmp",
        "relative_path": ".",
        "base_directory_abs": "/tmp",
        "file_name": "doc.pdf",
        "summary": "text",
        "summary_confidence": "4.5",
        "title": "t",
        "title_confidence": "5",
        "creation_date": "2024-01-02",
        "creation_date_confidence": "8",
        "creator": "me",
        "creator_confidence": "7",
        "tags": json.dumps(["a", "b"]),
        "tags_confidence": json.dumps([1, 2]),
        "importance": "3",
        "importance_confidence": "2",
    }

    cleaned = pdf_list.clean_csv_row(raw)
    assert cleaned["summary_confidence"] == 4.5
    assert cleaned["tags"] == ["a", "b"]
    assert cleaned["tags_confidence"] == [1, 2]


def test_clean_csv_row_invalid_value():
    pdf_list = PDFList()
    raw = {
        "folder_path_abs": "/tmp",
        "relative_path": ".",
        "base_directory_abs": "/tmp",
        "file_name": "doc.pdf",
        "summary": "text",
        "summary_confidence": "NaN",
        "title": "t",
        "title_confidence": "5",
        "creation_date": "2024-01-02",
        "creation_date_confidence": "8",
        "creator": "me",
        "creator_confidence": "7",
        "tags": "[]",
        "tags_confidence": "[]",
        "importance": "3",
        "importance_confidence": "2",
    }

    cleaned = pdf_list.clean_csv_row(raw)
    assert math.isnan(cleaned["summary_confidence"])  # NaN preserved


def test_import_from_json_roundtrip(make_pdf_document):
    pdf_doc = make_pdf_document("roundtrip.pdf", relative_subdir="dept")
    pdf_doc.set_title("Report", 5)
    pdf_doc.set_summary("Summary", 4)
    pdf_doc.set_tags(["dept"], [6])

    payload = json.dumps([pdf_doc.to_dict()])

    pdf_list = PDFList()
    pdf_list.import_from_json(payload)

    assert len(pdf_list.pdf_documents) == 1
    imported = next(iter(pdf_list.pdf_documents.values()))
    assert imported.title == "Report"
    assert imported.tags == ["dept"]


def test_add_pdf_document_updates_existing():
    pdf_list = PDFList()

    class RecordingDoc:
        def __init__(self, path, payload):
            self._path = path
            self._payload = payload
            self.updated_with = []
            self.file_name = os.path.basename(path)

        def get_absolute_path(self):
            return self._path

        def to_dict(self):
            return self._payload

        def set_from_dict(self, payload):
            self.updated_with.append(payload)

    path = "/tmp/doc.pdf"
    first = RecordingDoc(path, {"value": "initial"})
    pdf_list.add_pdf_document(first)

    replacement = RecordingDoc(path, {"value": "replacement"})
    pdf_list.add_pdf_document(replacement)

    assert pdf_list.pdf_documents[path] is first
    assert first.updated_with == [{"value": "replacement"}]


def test_add_file_dispatches_by_extension(monkeypatch, tmp_path):
    pdf_list = PDFList()
    calls = []

    class DummyPDFDocument:
        def __init__(self, path, base_dir):
            self.path = path
            self.base_dir = base_dir

    monkeypatch.setattr("autoPDFtagger.PDFList.PDFDocument", DummyPDFDocument)
    monkeypatch.setattr(pdf_list, "add_pdf_document", lambda doc: calls.append(("pdf", doc)))
    monkeypatch.setattr(pdf_list, "import_from_json_file", lambda path: calls.append(("json", path)))
    monkeypatch.setattr(pdf_list, "import_from_csv_file", lambda path: calls.append(("csv", path)))

    pdf_list.add_file(str(tmp_path / "file.pdf"), str(tmp_path))
    pdf_list.add_file(str(tmp_path / "data.json"), str(tmp_path))
    pdf_list.add_file(str(tmp_path / "data.csv"), str(tmp_path))

    assert calls[0][0] == "pdf"
    assert isinstance(calls[0][1], DummyPDFDocument)
    assert calls[1] == ("json", str(tmp_path / "data.json"))
    assert calls[2] == ("csv", str(tmp_path / "data.csv"))


def test_add_pdf_documents_from_folder_scans(monkeypatch, tmp_path):
    pdf_list = PDFList()
    calls = []

    def fake_add_file(path, base_dir):
        calls.append((path, base_dir))

    monkeypatch.setattr(pdf_list, "add_file", fake_add_file)

    root = tmp_path / "root"
    root.mkdir()
    (root / "a.pdf").write_text("pdf")
    (root / "b.json").write_text("json")
    (root / "sub").mkdir()
    (root / "sub" / "c.csv").write_text("csv")

    pdf_list.add_pdf_documents_from_folder(str(root), str(root))

    expected = {
        (str(root / "a.pdf"), str(root)),
        (str(root / "b.json"), str(root)),
        (str(root / "sub" / "c.csv"), str(root)),
    }
    assert set(calls) == expected


def test_export_to_folder_uses_new_names(tmp_path):
    pdf_list = PDFList()
    export_root = tmp_path / "export"
    saved = []

    class DummyDoc:
        def __init__(self, relative_path, file_name, new_rel=None, new_name=None):
            self.relative_path = relative_path
            self.file_name = file_name
            self._abs = str(tmp_path / "src" / file_name)
            if new_rel is not None:
                self.new_relative_path = new_rel
            if new_name is not None:
                self.new_file_name = new_name

        def save_to_file(self, target):
            saved.append(target)

        def get_absolute_path(self):
            return self._abs

    primary = DummyDoc(".", "one.pdf", new_rel="custom/dir", new_name="renamed.pdf")
    secondary = DummyDoc("../archive/year", "two.pdf")

    pdf_list.pdf_documents = {"one": primary, "two": secondary}

    pdf_list.export_to_folder(str(export_root))

    assert str(export_root / "custom/dir/renamed.pdf") in saved
    assert str(export_root / "archive/year/two.pdf") in saved


def test_create_new_filenames_uses_format(make_pdf_document):
    # Build a real PDFDocument to exercise formatting
    doc = make_pdf_document("2022-01-01-Memo.pdf")
    doc.set_creation_date("2022-01-01", 8)
    doc.set_title("Budget Memo", 7)
    doc.set_creator("ACME Corp", 6)

    pdf_list = PDFList()
    pdf_list.add_pdf_document(doc)

    pdf_list.create_new_filenames("%Y%m%d-{TITLE}.pdf")
    assert doc.new_file_name == "20220101-Budget-Memo.pdf"


def test_add_pdf_documents_from_folder_skips_mock_fixtures(tmp_path, caplog):
    base = tmp_path / "docs"
    base.mkdir()
    pdf_path = base / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")

    (base / "scan.text.json").write_text(json.dumps({"response": {"title": "t"}}), encoding="utf-8")
    (base / "scan.image.0.json").write_text(json.dumps({"response": {"title": "img"}}), encoding="utf-8")

    pdf_list = PDFList()

    caplog.set_level("ERROR")
    pdf_list.add_pdf_documents_from_folder(str(base), str(base))

    assert list(pdf_list.pdf_documents.keys()) == [str(pdf_path)]
    assert not any("Could not import file from JSON-File" in record.message for record in caplog.records)
