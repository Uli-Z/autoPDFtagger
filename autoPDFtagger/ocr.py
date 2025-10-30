import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


def _normalize_languages(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "eng"
    normalized = value.replace(",", "+").replace(" ", "+")
    parts = [part for part in normalized.split("+") if part]
    return "+".join(parts) if parts else "eng"


def _parse_enabled(value: str) -> str:
    if value is None:
        return "auto"
    normalized = value.strip().lower()
    truthy = {"1", "true", "yes", "on", "enabled"}
    falsy = {"0", "false", "no", "off", "disabled"}
    if normalized in truthy:
        return "force"
    if normalized in falsy:
        return "off"
    if normalized == "auto":
        return "auto"
    logging.warning("Unknown OCR enabled flag '%s'; defaulting to auto", value)
    return "auto"


@dataclass
class OCRSetup:
    runner: Optional["TesseractRunner"]


class TesseractRunner:
    def __init__(self, binary_path: str, languages: str, dpi: int = 300):
        self.binary_path = binary_path
        self.languages = languages
        self.dpi = dpi

    def extract_text_from_page(self, page) -> str:
        try:
            pix = page.get_pixmap(dpi=self.dpi)
            image_bytes = pix.tobytes("png")
            command = [
                self.binary_path,
                "stdin",
                "stdout",
                "-l",
                self.languages,
            ]
            result = subprocess.run(
                command,
                input=image_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="ignore").strip()
                logging.warning("Tesseract OCR failed (code %s): %s", result.returncode, stderr)
                return ""
            return result.stdout.decode("utf-8", errors="ignore")
        except FileNotFoundError:
            logging.error("Tesseract binary disappeared during execution.")
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning("Unexpected OCR error: %s", exc)
        return ""


def prepare_ocr_setup(
    config,
    cli_enabled: Optional[bool] = None,
    cli_languages: Optional[str] = None,
) -> OCRSetup:
    config_enabled = None
    config_languages = None
    if config.has_section("OCR"):
        config_enabled = config.get("OCR", "enabled", fallback=None)
        config_languages = config.get("OCR", "languages", fallback=None)

    mode = _parse_enabled(
        str(cli_enabled).lower() if cli_enabled is not None else (config_enabled or "auto")
    )
    languages = _normalize_languages(cli_languages or config_languages or "eng")
    binary_path = shutil.which("tesseract")

    if mode == "off":
        logging.info("OCR disabled via configuration/CLI.")
        return OCRSetup(runner=None)

    if not binary_path:
        if mode == "force":
            logging.warning("OCR forced but Tesseract binary not found on PATH.")
        else:
            logging.info("Tesseract not found on PATH; OCR unavailable.")
        return OCRSetup(runner=None)

    if mode == "force":
        logging.info("OCR forced on; using Tesseract at '%s' with languages '%s'.", binary_path, languages)
    else:
        logging.info("Tesseract detected at '%s'; OCR auto-enabled with languages '%s'.", binary_path, languages)
    runner = TesseractRunner(binary_path=binary_path, languages=languages)
    return OCRSetup(runner=runner)
