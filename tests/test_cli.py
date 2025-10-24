import logging
import sys
from types import SimpleNamespace

import pytest

import autoPDFtagger.autoPDFtagger as core_module
import autoPDFtagger.main as cli_module


class TrackingFileList:
    def __init__(self, owner):
        self.owner = owner
        self.pdf_documents = {}

    def import_from_json(self, *_):
        self.owner.calls.append("import_from_json")

    def get_sorted_pdf_filenames(self):
        return list(self.pdf_documents)

    def create_new_filenames(self):
        self.owner.calls.append("create_new_filenames")

    def export_to_json_file(self, path):
        self.owner.calls.append(("json_file", path))

    def export_to_json(self):
        self.owner.calls.append("export_to_json")
        return "[]"

    def export_to_csv_file(self, path):
        self.owner.calls.append(("csv_file", path))

    def export_to_folder(self, path):
        self.owner.calls.append(("export_to_folder", path))

    def get_unique_tags(self):
        return ["tag-a", "tag-b"]

    def apply_tag_replacements_to_all(self, replacements):
        self.owner.calls.append(("apply_tag_replacements", replacements))


class TrackingArchive:
    instances = []

    def __init__(self):
        self.calls = []
        self.file_list = TrackingFileList(self)
        self.__class__.instances.append(self)

    def add_file(self, path, base_dir):
        self.calls.append(("add_file", path, base_dir))
        self.file_list.pdf_documents[path] = SimpleNamespace(file_name=path)

    def keep_incomplete_documents(self, threshold=7):
        self.calls.append(("keep_incomplete", threshold))

    def keep_complete_documents(self, threshold=7):
        self.calls.append(("keep_complete", threshold))

    def file_analysis(self):
        self.calls.append("file_analysis")

    def ai_text_analysis(self):
        self.calls.append("ai_text_analysis")

    def ai_image_analysis(self):
        self.calls.append("ai_image_analysis")

    def ai_tag_analysis(self):
        self.calls.append("ai_tag_analysis")

    def get_stats(self):
        self.calls.append("get_stats")
        return {"Total Documents": len(self.file_list.pdf_documents)}

    def print_file_list(self):
        self.calls.append("print_file_list")


def test_cli_requires_output_option(tmp_path, monkeypatch, caplog):
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[DEFAULT]\nlanguage=English\n[AI]\ntext_model_short=stub/short\ntext_model_long=stub/long\ntext_threshold_words=100\nimage_model=stub/vision\ntag_model=stub/tagger\n",
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


def test_cli_executes_requested_actions(tmp_path, monkeypatch, caplog):
    TrackingArchive.instances.clear()
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[DEFAULT]\nlanguage=English\n[AI]\ntext_model_short=stub/short\ntext_model_long=stub/long\ntext_threshold_words=100\nimage_model=stub/vision\ntag_model=stub/tagger\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "out.json"
    csv_path = tmp_path / "out.csv"
    export_dir = tmp_path / "export"

    monkeypatch.setattr(core_module, "autoPDFtagger", TrackingArchive)
    monkeypatch.setattr(cli_module.os, "isatty", lambda *_: True)
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "autoPDFtagger",
            "--config-file",
            str(config_path),
            str(tmp_path / "input.pdf"),
            "--keep-above",
            "8",
            "--keep-below",
            "4",
            "-f",
            "-t",
            "-i",
            "-c",
            "--json",
            str(json_path),
            "--csv",
            str(csv_path),
            "--export",
            str(export_dir),
            "--list",
        ],
    )

    cli_module.main()

    assert TrackingArchive.instances, "CLI did not instantiate archive"
    archive = TrackingArchive.instances[-1]

    assert ("keep_incomplete", 8) in archive.calls
    assert ("keep_complete", 4) in archive.calls
    assert "file_analysis" in archive.calls
    assert "ai_text_analysis" in archive.calls
    assert "ai_image_analysis" in archive.calls
    assert "ai_tag_analysis" in archive.calls
    assert ("json_file", str(json_path)) in archive.calls
    assert ("csv_file", str(csv_path)) in archive.calls
    assert ("export_to_folder", str(export_dir)) in archive.calls
    assert "create_new_filenames" in archive.calls
    assert "print_file_list" in archive.calls


def test_cli_prints_json_to_stdout(tmp_path, monkeypatch, capsys):
    TrackingArchive.instances.clear()
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[DEFAULT]\nlanguage=English\n[AI]\ntext_model_short=stub/short\ntext_model_long=stub/long\ntext_threshold_words=100\nimage_model=stub/vision\ntag_model=stub/tagger\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(core_module, "autoPDFtagger", TrackingArchive)
    monkeypatch.setattr(cli_module.os, "isatty", lambda *_: True)
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "autoPDFtagger",
            "--config-file",
            str(config_path),
            str(tmp_path / "input.pdf"),
            "--json",
        ],
    )

    cli_module.main()

    archive = TrackingArchive.instances[-1]
    assert "export_to_json" in archive.calls
    captured = capsys.readouterr()
    assert captured.out.strip() == "[]"


def test_cli_prints_stats(tmp_path, monkeypatch, capsys):
    TrackingArchive.instances.clear()
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[DEFAULT]\nlanguage=English\n[AI]\ntext_model_short=stub/short\ntext_model_long=stub/long\ntext_threshold_words=100\nimage_model=stub/vision\ntag_model=stub/tagger\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "out.json"

    monkeypatch.setattr(core_module, "autoPDFtagger", TrackingArchive)
    monkeypatch.setattr(cli_module.os, "isatty", lambda *_: True)
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "autoPDFtagger",
            "--config-file",
            str(config_path),
            str(tmp_path / "input.pdf"),
            "--json",
            str(json_path),
            "--calc-stats",
        ],
    )

    cli_module.main()

    archive = TrackingArchive.instances[-1]
    assert "get_stats" in archive.calls
    out = capsys.readouterr().out
    assert "Total Documents: 1" in out


def test_cli_missing_config_raises(tmp_path, monkeypatch):
    missing = tmp_path / "missing.ini"
    monkeypatch.setattr(cli_module.os, "isatty", lambda *_: True)
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "autoPDFtagger",
            "--config-file",
            str(missing),
        ],
    )

    with pytest.raises(FileNotFoundError):
        cli_module.main()
