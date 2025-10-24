from pathlib import Path
from types import SimpleNamespace
import configparser
import importlib.util
import sys
import types

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _ensure_openai_stub():
    if "openai" in sys.modules:
        return

    openai_stub = types.ModuleType("openai")

    class _OpenAI:
        def __init__(self, *_, **__):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: None))

    openai_stub.OpenAI = _OpenAI
    sys.modules["openai"] = openai_stub


def _ensure_tiktoken_stub():
    if "tiktoken" in sys.modules:
        return

    tiktoken_stub = types.ModuleType("tiktoken")

    class _Encoding:
        @staticmethod
        def encode(value):
            if isinstance(value, str):
                return list(value)
            return list(str(value))

    def _encoding_for_model(_):
        return _Encoding()

    def _get_encoding(_):
        return _Encoding()

    tiktoken_stub.encoding_for_model = _encoding_for_model
    tiktoken_stub.get_encoding = _get_encoding
    sys.modules["tiktoken"] = tiktoken_stub


def _ensure_fitz_stub():
    if "fitz" in sys.modules:
        return

    fitz_stub = types.ModuleType("fitz")

    class _Unsupported:
        def __getattr__(self, name):
            raise RuntimeError("fitz stub does not implement attribute: %s" % name)

    def _open(*_, **__):
        raise RuntimeError("fitz stub open() called without monkeypatch.")

    fitz_stub.open = _open
    fitz_stub.Pixmap = _Unsupported
    sys.modules["fitz"] = fitz_stub


def _ensure_tenacity_stub():
    if "tenacity" in sys.modules:
        return

    tenacity_stub = types.ModuleType("tenacity")

    def _retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def _wait_random_exponential(*args, **kwargs):
        return None

    def _stop_after_attempt(*args, **kwargs):
        return None

    tenacity_stub.retry = _retry
    tenacity_stub.wait_random_exponential = _wait_random_exponential
    tenacity_stub.stop_after_attempt = _stop_after_attempt
    sys.modules["tenacity"] = tenacity_stub

def _ensure_config_defaults():
    package_name = "autoPDFtagger"
    module_name = "autoPDFtagger.config"

    if package_name not in sys.modules:
        pkg_spec = importlib.util.spec_from_file_location(
            package_name, PROJECT_ROOT / "autoPDFtagger" / "__init__.py"
        )
        pkg_module = importlib.util.module_from_spec(pkg_spec)
        sys.modules[package_name] = pkg_module
        pkg_spec.loader.exec_module(pkg_module)
        pkg_module.__path__ = [str(PROJECT_ROOT / "autoPDFtagger")]

    if module_name not in sys.modules:
        config_spec = importlib.util.spec_from_file_location(
            module_name, PROJECT_ROOT / "autoPDFtagger" / "config.py"
        )
        config_module = importlib.util.module_from_spec(config_spec)
        sys.modules[module_name] = config_module
        config_spec.loader.exec_module(config_module)
    else:
        config_module = sys.modules[module_name]

    config = getattr(config_module, "config")
    if not config.has_section("AI"):
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
            }
        )


_ensure_openai_stub()
_ensure_tiktoken_stub()
_ensure_fitz_stub()
_ensure_tenacity_stub()
_ensure_config_defaults()
