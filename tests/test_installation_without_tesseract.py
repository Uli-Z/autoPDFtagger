import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_minimal_config(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            [DEFAULT]
            language = English
            [AI]
            text_model_short = stub/short
            text_model_long = stub/long
            text_threshold_words = 100
            image_model = stub/vision
            tag_model = stub/tagger
            [OCR]
            enabled = auto
            languages = eng
            [CACHE]
            enabled = false
            ttl_seconds = 0
            dir =
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _make_no_tesseract_env(base_tmp: Path) -> dict:
    """Return a copy of os.environ without any PATH entries to tesseract."""
    env = os.environ.copy()
    # Point PATH to an empty, deterministic directory to avoid picking up tesseract
    fake_bin = base_tmp / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    env["PATH"] = str(fake_bin)
    env.pop("TESSDATA_PREFIX", None)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("TERM", "dumb")
    return env


def test_cli_runs_in_empty_directory_without_tesseract(tmp_path):
    run_dir = tmp_path / "work"
    run_dir.mkdir()
    config_path = tmp_path / "auto.conf"
    _write_minimal_config(config_path)

    env = _make_no_tesseract_env(tmp_path)
    # Use the source tree via PYTHONPATH to mimic editable install behaviour
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "autoPDFtagger.main",
            "--ocr",
            "--config-file",
            str(config_path),
        ],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "WARNING:root:OCR forced but Tesseract binary not found on PATH." in result.stderr
    assert "No documents in list." in result.stderr


def test_installed_package_runs_without_tesseract(tmp_path):
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()

    install_cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--no-deps",
        str(PROJECT_ROOT),
        "--target",
        str(site_dir),
    ]
    subprocess.check_call(install_cmd)

    config_path = tmp_path / "auto.conf"
    _write_minimal_config(config_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    env = _make_no_tesseract_env(tmp_path)
    env["PYTHONPATH"] = str(site_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "autoPDFtagger.main",
            "--ocr",
            "--config-file",
            str(config_path),
        ],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "WARNING:root:OCR forced but Tesseract binary not found on PATH." in result.stderr
    assert "No documents in list." in result.stderr
