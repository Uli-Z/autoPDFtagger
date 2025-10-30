from types import SimpleNamespace

import pytest

import sys
from pathlib import Path

# Ensure project root is importable for the installed/editable package case
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide a minimal fallback for tiktoken in case it isn't installed
try:
    import tiktoken  # noqa: F401
except Exception:  # pragma: no cover
    import types

    tiktoken = types.ModuleType("tiktoken")

    class _Encoding:
        @staticmethod
        def encode(value):
            return list(str(value))

    def _encoding_for_model(_):
        return _Encoding()

    def _get_encoding(_):
        return _Encoding()

    tiktoken.encoding_for_model = _encoding_for_model
    tiktoken.get_encoding = _get_encoding
    sys.modules["tiktoken"] = tiktoken

# Configure autoPDFtagger config early (module import time) so imports don't fail
from autoPDFtagger.config import config as _config  # noqa: E402
_config.clear()
_config.read_dict(
    {
        "DEFAULT": {"language": "English"},
        "AI": {
            "text_model_short": "stub/short",
            "text_model_long": "stub/long",
            "text_threshold_words": "100",
            "image_model": "stub/vision",
            "tag_model": "stub/tagger",
        },
        "OCR": {
            "enabled": "auto",
            "languages": "eng",
        },
    }
)


@pytest.fixture(autouse=True)
def configure_config():
    """Ensure the global config has the minimum sections for tests."""
    from autoPDFtagger.config import config

    config.clear()
    config.read_dict(
        {
            "DEFAULT": {"language": "English"},
            "AI": {
                "text_model_short": "stub/short",
                "text_model_long": "stub/long",
                "text_threshold_words": "100",
                "image_model": "stub/vision",
                "tag_model": "stub/tagger",
            },
            "OCR": {
                "enabled": "auto",
                "languages": "eng",
            },
        }
    )
    yield
    config.clear()


@pytest.fixture
def make_pdf_document(tmp_path):
    """Factory that creates on-disk placeholder PDFs for PDFDocument tests."""
    from autoPDFtagger.PDFDocument import PDFDocument

    def _builder(filename="sample.pdf", relative_subdir=""):
        base_dir = tmp_path / "pdf_base"
        base_dir.mkdir(parents=True, exist_ok=True)

        target_dir = base_dir / relative_subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = target_dir / filename
        pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")

        return PDFDocument(str(pdf_path), str(base_dir))

    return _builder


@pytest.fixture(autouse=True)
def reset_pdfdocument_ocr():
    """Ensure OCR runner state is isolated between tests."""
    from autoPDFtagger.PDFDocument import PDFDocument
    from autoPDFtagger import mock_provider

    PDFDocument.configure_ocr(None)
    mock_provider.reset()
    yield
    PDFDocument.configure_ocr(None)
    mock_provider.reset()
