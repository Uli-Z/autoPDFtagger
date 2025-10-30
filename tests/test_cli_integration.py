import json
import shutil
from pathlib import Path
import sys

import pytest

import autoPDFtagger.main as cli_module


def _copy_testfiles(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    source = project_root / "testfiles"
    dest = tmp_path / "fixtures"
    shutil.copytree(source, dest)
    return dest


def _load_output(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {entry["file_name"]: entry for entry in data}


def _assert_matches_fixture(output, fixture_dir, task):
    for file_name, entry in output.items():
        pdf_path = fixture_dir / file_name
        expected_path = pdf_path.with_name(f"{pdf_path.stem}.{task}.json")
        if not expected_path.exists():
            continue
        with expected_path.open("r", encoding="utf-8") as handle:
            expected = json.load(handle)["response"]
        for key, value in expected.items():
            if key in {"creation_date", "creation_date_confidence"}:
                continue
            actual = entry.get(key)
            if isinstance(value, list):
                assert isinstance(actual, list), f"{file_name}: expected list for '{key}'"
                for item in value:
                    assert item in actual, f"{file_name}: list '{key}' missing {item!r}"
            else:
                assert actual == value, f"{file_name}: field '{key}' mismatch"


def test_cli_mock_workflow_logs_and_exports(tmp_path, monkeypatch):
    fixture_dir = _copy_testfiles(tmp_path)
    config_path = fixture_dir / "test_config.conf"
    pdf_files = sorted(
        [
            path
            for path in fixture_dir.glob("*.pdf")
            if (path.with_name(f"{path.stem}.text.json")).exists()
        ]
    )
    text_out = fixture_dir / "text_output.json"
    image_out = fixture_dir / "image_output.json"
    log_path = fixture_dir / "logs" / "ai.log"

    monkeypatch.setattr(cli_module.os, "isatty", lambda *_: True)
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)
    monkeypatch.setattr(sys.stdin, "read", lambda: "")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "autoPDFtagger",
            "--config-file",
            str(config_path),
            "--base-directory",
            str(fixture_dir),
            "--ai-text-analysis",
            "--json",
            str(text_out),
            "--debug-ai-log",
            str(log_path),
            *[str(path) for path in pdf_files],
        ],
    )
    cli_module.main()

    text_output = _load_output(text_out)
    _assert_matches_fixture(text_output, fixture_dir, "text")

    # Ensure log contains entries for text analysis
    log_records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert any(record["task"] == "text" for record in log_records)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "autoPDFtagger",
            "--config-file",
            str(config_path),
            str(text_out),
            "--ai-image-analysis",
            "--json",
            str(image_out),
            "--debug-ai-log",
            str(log_path),
        ],
    )
    cli_module.main()

    image_output = _load_output(image_out)
    assert image_output, "image analysis should produce output entries"

    log_records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    image_records = [record for record in log_records if record["task"] == "image"]
    assert image_records, "no image analysis entries were logged"

    expected_by_path = {}
    for pdf_path in pdf_files:
        expected_path = pdf_path.with_name(f"{pdf_path.stem}.image.json")
        if expected_path.exists():
            with expected_path.open("r", encoding="utf-8") as handle:
                expected_by_path[str(pdf_path)] = json.load(handle)["response"]

    for abs_path, expected in expected_by_path.items():
        matching = next((record for record in image_records if record["document"] == abs_path), None)
        assert matching is not None, f"missing image log for {abs_path}"
        actual = json.loads(matching["response"])
        assert actual == expected
