import configparser

from autoPDFtagger import ocr


def _config_with(section=None):
    cfg = configparser.ConfigParser()
    if section:
        cfg.read_dict(section)
    return cfg


def test_prepare_ocr_setup_respects_cli_disable(monkeypatch):
    monkeypatch.setattr("autoPDFtagger.ocr.shutil.which", lambda _: "/usr/bin/tesseract")
    cfg = _config_with({"OCR": {"enabled": "auto", "languages": "eng"}})

    setup = ocr.prepare_ocr_setup(cfg, cli_enabled=False)

    assert setup.runner is None


def test_prepare_ocr_setup_enables_runner_with_languages(monkeypatch):
    monkeypatch.setattr("autoPDFtagger.ocr.shutil.which", lambda _: "/opt/tesseract")
    cfg = _config_with({"OCR": {"enabled": "auto", "languages": "eng"}})

    setup = ocr.prepare_ocr_setup(cfg, cli_enabled=True, cli_languages="deu, eng")

    assert setup.runner is not None
    assert setup.runner.languages == "deu+eng"


def test_prepare_ocr_setup_handles_missing_binary(monkeypatch):
    monkeypatch.setattr("autoPDFtagger.ocr.shutil.which", lambda _: None)
    cfg = _config_with({"OCR": {"enabled": "auto", "languages": "eng"}})

    setup = ocr.prepare_ocr_setup(cfg, cli_enabled=None)

    assert setup.runner is None
