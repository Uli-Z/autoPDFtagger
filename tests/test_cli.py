import logging
import sys
from types import SimpleNamespace

import pytest

import autoPDFtagger.autoPDFtagger as core_module
import autoPDFtagger.main as cli_module


def test_cli_requires_output_option(tmp_path, monkeypatch, caplog):
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[OPENAI-API]\nAPI-Key=test\n[DEFAULT]\nlanguage=English\n",
        encoding="utf-8",
    )

    class StubArchive:
        instances = []

        def __init__(self):
            self.ai_text_called = False
            self.file_list = SimpleNamespace(
                pdf_documents={},
                import_from_json=lambda *_: None,
                get_sorted_pdf_filenames=lambda: list(self.file_list.pdf_documents),
                create_new_filenames=lambda: None,
                export_to_json_file=lambda *_: None,
                export_to_json=lambda: "[]",
                export_to_csv_file=lambda *_: None,
            )
            self.__class__.instances.append(self)

        def add_file(self, path, base_dir):
            self.file_list.pdf_documents[path] = object()

        def keep_incomplete_documents(self, *_):
            pass

        def keep_complete_documents(self, *_):
            pass

        def file_analysis(self):
            pass

        def ai_text_analysis(self):
            self.ai_text_called = True

        def ai_image_analysis(self):
            pass

        def ai_tag_analysis(self):
            pass

        def get_stats(self):
            return {}

        def print_file_list(self):
            pass

    monkeypatch.setattr(core_module, "autoPDFtagger", StubArchive)
    monkeypatch.setattr(cli_module.os, "isatty", lambda *_: True)
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)

    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(
        sys,
        "argv",
        ["autoPDFtagger", "--config-file", str(config_path), "input.json", "-t"],
    )

    cli_module.main()

    assert not any(record.levelname == "INFO" and "Doing basic file-analysis" in record.message for record in caplog.records)
    assert any("No output option is set. Skipping text analysis." in record.message for record in caplog.records)

    created_instances = StubArchive.instances
    assert created_instances, "stub archive was not instantiated"
    assert not created_instances[-1].ai_text_called
