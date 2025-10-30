import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from autoPDFtagger.PDFDocument import PDFDocument
from autoPDFtagger.llm_client import run_chat, run_vision
from autoPDFtagger.config import config
from autoPDFtagger import mock_provider


def _lang() -> str:
    try:
        return config.get("DEFAULT", "language", fallback="English")
    except Exception:
        return "English"


def _json_guard(text: str) -> str:
    if not text:
        return "{}"
    # Try to extract JSON object
    try:
        # If it's valid JSON already, return as-is
        json.loads(text)
        return text
    except Exception:
        # Heuristic: find braces
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return "{}"


def analyze_text(
    doc: PDFDocument,
    model_short: str = "",
    model_long: str = "",
    threshold_words: int = 100,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Analyze OCR/text content and return (json_str, usage).
    If models are empty, returns (None, {cost:0}).
    """
    text = doc.get_pdf_text() or ""
    words = len(text.split())

    chosen_model = None
    if model_short and model_long:
        chosen_model = model_short if words <= threshold_words else model_long
    elif model_short:
        chosen_model = model_short
    elif model_long:
        chosen_model = model_long
    else:
        logging.info("Text analysis skipped (no model configured)")
        return None, {"cost": 0.0}

    if mock_provider.is_mock_model(chosen_model):
        response, usage = mock_provider.fetch(doc, "text", context={"words": words})
        return response, usage

    logging.info(f"Using model '{chosen_model}' for text ({words} words, threshold={threshold_words})")

    system = (
        "You are a helpful assistant analyzing OCR outputs. It's important "
        "to remember that these outputs may represent only a part of the document. "
        "Provide the following information:\n"
        "1. Creation date of the document.\n"
        "2. A short title of 3-4 words.\n"
        "3. A meaningful summary of 3-4 sentences.\n"
        "4. Creator/Issuer\n"
        "5. Suitable keywords/tags related to the content.\n"
        "6. Rate the importance of the document on a scale from 0 (unimportant) to 10 (vital).\n"
        "7. Rate your confidence for each of the above points on a scale from 0 (no information) over 5 (few hints) to 10 (very sure). "
        f"You always answer in {_lang()} language. For gathering information, you use the given filename, pathname and OCR-analyzed text. "
        "You always answer in a specified JSON format."
    )

    user = (
        "Analyze the following document context and extend the existing information by keeping this JSON format: "
        + doc.to_api_json()
        + "\nContext info: \n"
        + doc.get_short_description()
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    try:
        text_temperature = float(config.get("AI", "text_temperature", fallback="0.3"))
    except Exception:
        text_temperature = 0.3

    try:
        answer, usage = run_chat(
            chosen_model,
            messages,
            json_mode=True,
            temperature=text_temperature,
        )
        return _json_guard(answer), usage
    except Exception as e:
        logging.error(f"Text analysis failed: {e}")
        return None, {"cost": 0.0}


def _select_images_for_analysis(doc: PDFDocument) -> List[str]:
    images: List[str] = []
    try:
        doc.analyze_document_images()
        if doc.image_coverage is None:
            return images

        if doc.image_coverage < 100:
            # Non-scanned: pick up to 3 largest images across document
            all_imgs = [image for page in doc.images for image in page]
            sorted_imgs = sorted(
                all_imgs,
                key=lambda img: img.get("original_width", 0) * img.get("original_height", 0),
                reverse=True,
            )
            for img in sorted_imgs[:3]:
                b64 = doc.get_png_image_base64_by_xref(img.get("xref"))
                if b64:
                    images.append(b64)
        else:
            # Scanned: pick the largest image per page (first two pages)
            for page in doc.pages[:2]:
                xref = page.get("max_img_xref")
                if xref:
                    b64 = doc.get_png_image_base64_by_xref(xref)
                    if b64:
                        images.append(b64)
    except Exception as e:
        logging.error(f"Error preparing images for analysis: {e}")
    return images


def analyze_images(doc: PDFDocument, model: str = "") -> Tuple[Optional[str], Dict[str, Any]]:
    """Analyze images in the document with a vision-capable model.
    Returns (json_str, usage). If model is empty or unsupported, skip.
    """
    if not model:
        logging.info("Image analysis skipped (no model configured)")
        return None, {"cost": 0.0}

    imgs = _select_images_for_analysis(doc)
    if not imgs:
        logging.info("No images selected for analysis; skipping")
        return None, {"cost": 0.0}

    if mock_provider.is_mock_model(model):
        response, usage = mock_provider.fetch(doc, "image", context={"image_count": len(imgs)})
        return response, usage

    prompt = (
        "You are a helpful assistant analyzing images inside of documents. Based on the shown images, provide:"
        " creation date, 3-4 word title, 3-4 sentence summary, creator/issuer, suitable keywords/tags,"
        " importance 0-10, and per-field confidence 0-10. "
        f"Always answer in {_lang()}. Keep the exact JSON format provided in the input."
        " Extend this JSON consistently: " + doc.to_api_json()
    )

    try:
        # Optional temperature override via config
        try:
            temp_str = config.get('AI', 'image_temperature', fallback='0.8')
            temperature = float(temp_str)
        except Exception:
            temperature = 0.8
        answer, usage = run_vision(model, prompt, imgs, temperature=temperature)
        return _json_guard(answer), usage
    except Exception as e:
        logging.warning(f"Vision model error or unsupported: {e}")
        return None, {"cost": 0.0}


def analyze_tags(tags: List[str], model: str = "") -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Suggest tag replacements/unification.
    Returns (replacements, usage). If model empty, returns identity mapping and zero cost.
    """
    if not model:
        logging.info("Tag analysis skipped (no model configured)")
        return [], {"cost": 0.0}

    system = (
        "You are a helpful assistant for unifying and normalizing tags/keywords. "
        f"Always answer in {_lang()}. Output must be a JSON list of objects with keys 'original' and 'replacement'."
    )
    user = (
        "Given the following unique tags across a document collection, propose replacements to normalize synonyms,"
        " merge duplicates, correct case, and simplify taxonomy (replace with empty string to drop).\n\n"
        + json.dumps(tags)
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        answer, usage = run_chat(model, messages, json_mode=True)
        text = _json_guard(answer)
        try:
            data = json.loads(text)
            if isinstance(data, list):
                # Minimal validation
                cleaned = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    orig = str(item.get("original", ""))
                    repl = str(item.get("replacement", ""))
                    cleaned.append({"original": orig, "replacement": repl})
                return cleaned, usage
        except Exception:
            pass
        # Fallback: no valid suggestions
        return [], usage
    except Exception as e:
        logging.error(f"Tag analysis failed: {e}")
        return [], {"cost": 0.0}
