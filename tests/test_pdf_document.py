from types import SimpleNamespace

import pytest

from autoPDFtagger.PDFDocument import PDFDocument, pdf_date_to_datetime
from autoPDFtagger.autoPDFtagger import autoPDFtagger


def test_extract_date_from_filename(make_pdf_document):
    doc = make_pdf_document("2024-03-05-Invoice.pdf")
    doc.extract_date_from_filename()
    assert doc.get_creation_date_as_str() == "2024-03-05"


def test_extract_title_from_filename(make_pdf_document):
    doc = make_pdf_document("2024-03-05-Quarterly Report.pdf")
    doc.extract_title_from_filename()
    assert doc.title == "Quarterly Report"
    assert doc.title_confidence == 2


def test_extract_tags_from_relative_path(make_pdf_document):
    doc = make_pdf_document("file.pdf", relative_subdir="finance/2024")
    doc.extract_tags_from_relative_path()
    assert doc.tags == ["finance", "2024"]
    assert doc.tags_confidence == [6, 6]


def test_create_new_filename(make_pdf_document):
    doc = make_pdf_document("2022-01-01-Memo.pdf")
    doc.set_creation_date("2022-01-01", 8)
    doc.set_title("Budget Memo", 7)
    doc.set_creator("ACME Corp", 6)

    doc.create_new_filename()
    assert doc.new_file_name == "2022-01-01-ACME Corp-Budget Memo.pdf"


def test_set_tags_merges_confidence(make_pdf_document):
    doc = make_pdf_document()
    doc.set_tags(["alpha", "beta"], [3, 4])
    doc.set_tags(["alpha", "gamma"], [7, 2])

    confidences = dict(zip(doc.tags, doc.tags_confidence))
    assert confidences["alpha"] == 7  # takes higher confidence
    assert confidences["beta"] == 4
    assert confidences["gamma"] == 2


def test_apply_tag_replacements(make_pdf_document):
    doc = make_pdf_document()
    doc.tags = ["car", "auto", "keep"]
    doc.tags_confidence = [3, 6, 5]

    doc.apply_tag_replacements(
        [
            {"original": "car", "replacement": "vehicle"},
            {"original": "auto", "replacement": "vehicle"},
            {"original": "keep", "replacement": "keep"},
        ]
    )

    assert doc.tags == ["vehicle", "keep"]
    confidences = dict(zip(doc.tags, doc.tags_confidence))
    assert confidences["vehicle"] == 6  # highest of merged tags
    assert confidences["keep"] == 5


def test_get_confidence_index(make_pdf_document):
    doc = make_pdf_document()
    doc.creation_date_confidence = 8
    doc.title_confidence = 6
    doc.summary_confidence = 4
    doc.importance_confidence = 5
    doc.creator_confidence = 3

    assert doc.get_confidence_index() == pytest.approx(5.2)


@pytest.mark.parametrize(
    "input_value,expected",
    [
        ("D:20240102131415+02'00'", "2024-01-02T13:14:15+02:00"),
        ("20240102", "2024-01-02T00:00:00"),
        ("D:2024", "2024-01-01T00:00:00"),
        ("", None),
    ],
)
def test_pdf_date_to_datetime_variants(input_value, expected):
    result = pdf_date_to_datetime(input_value)
    if expected is None:
        assert result is None
    else:
        assert result.isoformat() == expected


def test_create_confidence_histogram():
    doc_low = SimpleNamespace(get_confidence_index=lambda: 6.2)
    doc_high = SimpleNamespace(get_confidence_index=lambda: 7.7)
    pdf_list = SimpleNamespace(pdf_documents={"a": doc_low, "b": doc_high})

    tagger = autoPDFtagger()
    histogram = tagger.create_confidence_histogram(pdf_list)

    assert "6: #" in histogram
    assert "8: #" in histogram
