import json

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
