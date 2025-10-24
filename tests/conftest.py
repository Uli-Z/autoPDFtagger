from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def configure_config():
    """Ensure the global config has the minimum sections for tests."""
    from autoPDFtagger.config import config

    config.clear()
    config.read_dict(
        {
            "OPENAI-API": {"API-Key": "test-key"},
            "DEFAULT": {"language": "English"},
        }
    )
    yield
    config.clear()


@pytest.fixture(autouse=True)
def stub_openai_client(monkeypatch):
    """Replace the OpenAI client with a lightweight stub."""
    from autoPDFtagger import AIAgents

    class _StubCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            message = SimpleNamespace(content="{}")
            usage = SimpleNamespace(prompt_tokens=kwargs.get("prompt_tokens", 0), completion_tokens=kwargs.get("completion_tokens", 0))
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    class _StubClient:
        def __init__(self, *_, **__):
            self.chat = SimpleNamespace(completions=_StubCompletions())

    monkeypatch.setattr(AIAgents, "OpenAI", _StubClient)
    yield


@pytest.fixture(autouse=True)
def stub_token_counter(monkeypatch):
    """Use a deterministic token counter to keep tests fast."""
    from autoPDFtagger import AIAgents_OpenAI_pdf

    monkeypatch.setattr(
        AIAgents_OpenAI_pdf,
        "num_tokens_from_string",
        lambda text, encoding_name="cl100k_base": len(text),
    )
    yield


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
