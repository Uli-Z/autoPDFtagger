import base64
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytz

import autoPDFtagger.PDFDocument as pdf_module
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
    assert doc.new_file_name == "2022-01-01-ACME-Corp-Budget-Memo.pdf"


def test_create_new_filename_custom_format(make_pdf_document):
    doc = make_pdf_document("2022-01-01-Memo.pdf")
    doc.set_creation_date("2022-01-01", 8)
    doc.set_title("Budget Memo", 7)
    doc.set_creator("ACME Corp", 6)

    doc.create_new_filename("%Y%m%d_{TITLE}.pdf")
    assert doc.new_file_name == "20220101_Budget-Memo.pdf"


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


def test_get_pdf_text_uses_fitz(monkeypatch, make_pdf_document):
    calls = []

    class FakePage:
        def get_text(self, mode):
            assert mode == "text"
            return "Hello\nWorld™\x00 "

    class FakeDoc:
        def __init__(self):
            self.closed = False

        def __len__(self):
            return 1

        def __getitem__(self, index):
            assert index == 0
            return FakePage()

        def close(self):
            self.closed = True

    fake_doc = FakeDoc()

    def fake_open(path):
        calls.append(path)
        return fake_doc

    monkeypatch.setattr("autoPDFtagger.PDFDocument.fitz.open", fake_open)

    doc = make_pdf_document("ocr.pdf")
    text_first = doc.get_pdf_text()
    text_second = doc.get_pdf_text()

    assert text_first == "Hello World"
    assert text_second == "Hello World"
    assert calls.count(doc.get_absolute_path()) == 1  # cached after first read
    assert fake_doc.closed


def test_get_pdf_text_uses_ocr_when_text_layer_missing(monkeypatch, make_pdf_document):
    from autoPDFtagger.PDFDocument import PDFDocument

    class DummyRunner:
        def __init__(self):
            self.calls = 0

        def extract_text_from_page(self, page):
            self.calls += 1
            return f"page{self.calls}"

    runner = DummyRunner()
    PDFDocument.configure_ocr(runner)

    class FakePage:
        def get_text(self, mode):
            assert mode == "text"
            return ""

    class FakeDoc:
        def __init__(self):
            self.closed = False

        def __len__(self):
            return 2

        def __getitem__(self, index):
            assert index in (0, 1)
            return FakePage()

        def close(self):
            self.closed = True

    fake_doc = FakeDoc()
    monkeypatch.setattr("autoPDFtagger.PDFDocument.fitz.open", lambda _: fake_doc)

    doc = make_pdf_document("scan.pdf")
    text_first = doc.get_pdf_text()
    text_second = doc.get_pdf_text()

    assert text_first == "page1 page2"
    assert text_second == "page1 page2"
    assert runner.calls == 2
    assert fake_doc.closed


def test_save_to_file_updates_metadata(tmp_path, monkeypatch, make_pdf_document):
    doc = make_pdf_document("source.pdf")
    doc.set_title("Budget Memo", 7)
    doc.set_summary("A concise summary", 6)
    doc.set_creator("ACME Corp", 5)
    doc.set_tags(["finance", "2024"], [4, 3])
    doc.creation_date = pytz.UTC.localize(datetime(2024, 1, 2, 13, 14, 15))
    doc.title_confidence = 7
    doc.summary_confidence = 6
    doc.creation_date_confidence = 8
    doc.creator_confidence = 5

    class FakeFitzDoc:
        def __init__(self):
            self.metadata = {
                "title": "",
                "summary": "",
                "author": "",
                "keywords": "",
            }
            self.saved_metadata = None
            self.saved_path = None
            self.closed = False

        def set_metadata(self, metadata):
            self.saved_metadata = metadata

        def save(self, path):
            self.saved_path = path

        def close(self):
            self.closed = True

    fake_doc = FakeFitzDoc()
    monkeypatch.setattr(
        "autoPDFtagger.PDFDocument.fitz.open",
        lambda path: fake_doc if path == doc.get_absolute_path() else None,
    )

    target = tmp_path / "export" / "out.pdf"
    doc.save_to_file(str(target))

    assert fake_doc.saved_path == str(target)
    metadata = fake_doc.saved_metadata
    assert metadata["title"] == "Budget Memo"
    assert metadata["summary"] == "A concise summary"
    assert metadata["author"] == "ACME Corp"
    assert "finance" in metadata["keywords"]
    assert "title_confidence=7" in metadata["keywords"]
    assert metadata["creationDate"] == "D:20240102131415+00'00'"
    assert fake_doc.closed


def test_extract_metadata_parses_confidence(monkeypatch, make_pdf_document):
    doc = make_pdf_document("meta.pdf")

    class FakeFitzDoc:
        def __init__(self):
            self.metadata = {
                "title": "Existing Title",
                "summary": "Existing Summary",
                "creationDate": "D:20240102131415+02'00'",
                "author": "Author Name",
                "keywords": (
                    "finance, report - Metadata automatically updated by autoPDFtagger, "
                    "title_confidence=6, summary_confidence=5, "
                    "creation_date_confidence=8, creator_confidence=7, tag_confidence=3,4"
                ),
            }

        def close(self):
            pass

    monkeypatch.setattr(
        "autoPDFtagger.PDFDocument.fitz.open",
        lambda path: FakeFitzDoc(),
    )

    doc.extract_metadata()

    assert doc.title == "Existing Title"
    assert doc.title_confidence == 6
    assert doc.summary == "Existing Summary"
    assert doc.summary_confidence == 5
    assert doc.creator == "Author Name"
    assert doc.creator_confidence == 7
    assert doc.tags == ["finance", "report"]
    assert doc.tags_confidence == [3.0, 4.0]
    assert doc.creation_date.isoformat() == "2024-01-02T11:14:15+00:00"


def test_analyze_document_images_computes_metrics(monkeypatch, make_pdf_document):
    doc = make_pdf_document("images.pdf")

    class FakeRect:
        def __init__(self, width, height):
            self.width = width
            self.height = height

    class FakePage:
        def __init__(self, xref):
            self.rect = FakeRect(10, 10)
            self._xref = xref
            self.parent = SimpleNamespace()

        def get_images(self, full=True):
            assert full is True
            return [(self._xref,)]

        def get_image_rects(self, xref):
            assert xref == self._xref
            return [FakeRect(2, 5)]

        def get_text(self, mode):
            assert mode == "text"
            return "word another third"

    class FakeDoc:
        def __init__(self):
            self.pages = [FakePage(1), FakePage(2)]

        def __iter__(self):
            return iter(self.pages)

        def __len__(self):
            return len(self.pages)

        def __getitem__(self, idx):
            return self.pages[idx]

        def close(self):
            pass

    class FakePixmap:
        def __init__(self, parent, xref):
            self.width = 2
            self.height = 5

    monkeypatch.setattr("autoPDFtagger.PDFDocument.fitz.open", lambda path: FakeDoc())
    monkeypatch.setattr("autoPDFtagger.PDFDocument.fitz.Pixmap", FakePixmap)

    doc.analyze_document_images()

    assert doc.images_already_analyzed is True
    assert len(doc.images) == 2
    assert len(doc.pages) == 2
    assert doc.pages[0]["words_count"] == 3
    assert doc.images[0][0]["page_coverage_percent"] == pytest.approx(10.0)
    assert doc.image_coverage == pytest.approx(10.0)


def test_rect_to_cm_and_icon_detection():
    from autoPDFtagger.PDFDocument import PDFDocument

    rect = SimpleNamespace(width=72.0, height=144.0)
    width_cm, height_cm = PDFDocument.rect_to_cm(rect)

    assert width_cm == pytest.approx(2.54)
    assert height_cm == pytest.approx(5.08)
    assert PDFDocument.is_small_icon_rect(rect, min_edge_cm=3.0) is True
    assert PDFDocument.is_small_icon_rect(rect, min_edge_cm=1.0) is False


def test_render_page_png_base64_scales_to_max_px(monkeypatch, make_pdf_document):
    from autoPDFtagger.PDFDocument import PDFDocument

    doc = make_pdf_document("render-page.pdf")
    calls = {}

    class FakeMatrix:
        def __init__(self, sx, sy):
            self.sx = sx
            self.sy = sy

    class FakePixmap:
        def tobytes(self, fmt):
            assert fmt == "png"
            return b"DATA"

    class FakePage:
        rect = SimpleNamespace(width=400.0, height=200.0)

        def get_pixmap(self, matrix):
            calls["matrix"] = matrix
            return FakePixmap()

    class FakeDoc:
        def __len__(self):
            return 1

        def __getitem__(self, idx):
            assert idx == 0
            return FakePage()

        def close(self):
            calls["closed"] = True

    def fake_open(path):
        calls["opened"] = path
        return FakeDoc()

    fake_module = SimpleNamespace(open=fake_open, Matrix=FakeMatrix)
    monkeypatch.setattr(pdf_module, "fitz", fake_module)

    encoded = doc.render_page_png_base64(0, max_px=200)

    assert encoded == base64.b64encode(b"DATA").decode()
    assert calls["matrix"].sx == pytest.approx(0.5)
    assert calls["closed"] is True


def test_render_image_region_png_base64_clips_region(monkeypatch, make_pdf_document):
    from autoPDFtagger.PDFDocument import PDFDocument

    doc = make_pdf_document("render-region.pdf")
    calls = {}

    class FakeMatrix:
        def __init__(self, sx, sy):
            self.sx = sx
            self.sy = sy

    class FakePixmap:
        def tobytes(self, fmt):
            assert fmt == "png"
            return b"IMG"

    rect = SimpleNamespace(width=120.0, height=80.0)

    class Page0:
        rect = SimpleNamespace(width=400.0, height=400.0)

        def get_image_rects(self, xref):
            return []

        def get_pixmap(self, *args, **kwargs):
            raise AssertionError("Unexpected render on page 0")

    class Page1:
        rect = SimpleNamespace(width=400.0, height=400.0)

        def get_image_rects(self, xref):
            return [rect] if xref == 99 else []

        def get_pixmap(self, matrix, clip=None):
            calls["matrix"] = matrix
            calls["clip"] = clip
            return FakePixmap()

    class FakeDoc:
        def __len__(self):
            return 2

        def __getitem__(self, idx):
            return [Page0(), Page1()][idx]

        def close(self):
            calls["closed"] = True

    def fake_open(path):
        return FakeDoc()

    fake_module = SimpleNamespace(open=fake_open, Matrix=FakeMatrix)
    monkeypatch.setattr(pdf_module, "fitz", fake_module)

    encoded = doc.render_image_region_png_base64(99, max_px=100)

    assert encoded == base64.b64encode(b"IMG").decode()
    assert calls["clip"] is rect
    assert calls["matrix"].sx == pytest.approx(100 / rect.width)
    assert calls["closed"] is True


def test_render_image_region_png_base64_returns_none_when_missing(monkeypatch, make_pdf_document):
    from autoPDFtagger.PDFDocument import PDFDocument

    doc = make_pdf_document("no-region.pdf")

    class Page:
        rect = SimpleNamespace(width=400.0, height=400.0)

        def get_image_rects(self, xref):
            return []

    class FakeDoc:
        def __len__(self):
            return 1

        def __getitem__(self, idx):
            return Page()

        def close(self):
            self.closed = True

    fake_doc = FakeDoc()

    def fake_open(path):
        return fake_doc

    fake_module = SimpleNamespace(open=fake_open, Matrix=lambda sx, sy: SimpleNamespace(sx=sx, sy=sy))
    monkeypatch.setattr(pdf_module, "fitz", fake_module)

    assert doc.render_image_region_png_base64(5, max_px=200) is None
    assert getattr(fake_doc, "closed", False) is True


def test_get_page_text_uses_ocr_when_text_missing(monkeypatch, make_pdf_document):
    from autoPDFtagger.PDFDocument import PDFDocument

    doc = make_pdf_document("ocr-page.pdf")

    class FakePage:
        def get_text(self, mode):
            assert mode == "text"
            return ""

    class FakeDoc:
        def __len__(self):
            return 1

        def __getitem__(self, idx):
            assert idx == 0
            return FakePage()

        def close(self):
            pass

    def fake_open(path):
        return FakeDoc()

    monkeypatch.setattr("autoPDFtagger.PDFDocument.fitz.open", fake_open)

    class Runner:
        def __init__(self):
            self.calls = 0

        def extract_text_from_page(self, page):
            self.calls += 1
            return "ocr text\n"

    runner = Runner()
    PDFDocument.configure_ocr(runner)
    try:
        text = doc.get_page_text(0, use_ocr_if_needed=True)
        assert text == "ocr text"
        assert runner.calls == 1

        text_no_ocr = doc.get_page_text(0, use_ocr_if_needed=False)
        assert text_no_ocr == ""
    finally:
        PDFDocument.configure_ocr(None)
