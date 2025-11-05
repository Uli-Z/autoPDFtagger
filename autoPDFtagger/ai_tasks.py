import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from autoPDFtagger.PDFDocument import PDFDocument
from autoPDFtagger.llm_client import run_chat, run_vision
from autoPDFtagger.config import config
from autoPDFtagger import mock_provider
from autoPDFtagger.ai_common import (
    tokenize_text as _tok_est,
    apply_text_budget as _apply_budget,
    log_llm_request as _log_req,
    json_guard as _json_guard2,
    normalize_confidence_numbers as _normalize2,
)

# Backwards-compat shims for tests referencing legacy helpers
def _json_guard(text: str) -> str:
    return _json_guard2(text)


def _lang() -> str:
    try:
        return config.get("DEFAULT", "language", fallback="English")
    except Exception:
        return "English"




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

    # Apply a per-file token limit shared across analyses
    try:
        token_limit = int(config.get('AI', 'token_limit', fallback=str(1_000_000)))
    except Exception:
        token_limit = 1_000_000

    filename = getattr(doc, 'file_name', '<document>')
    budget = _apply_budget("text", filename, system, user, token_limit)
    if budget.get("abort"):
        return None, {"cost": 0.0, "dry_run": True, "skipped_reason": budget.get("reason")}
    user = budget.get("user_text", user)
    messages[1]["content"] = user
    try:
        used = int(budget.get("used_tokens") or (_tok_est(system) + _tok_est(user)))
        _log_req("text", filename, parts=0, text_tokens=used, image_tokens=None, total_tokens=used, token_limit=token_limit)
    except Exception:
        pass

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
        # Normalize confidences to 0..10 if the model returned 0..1
        text = _json_guard2(answer)
        try:
            obj = json.loads(text)
            obj = _normalize2(obj, source="text")
            text = json.dumps(obj, ensure_ascii=False)
        except Exception:
            pass
        return text, usage
    except Exception as e:
        logging.error(f"Text analysis failed: {e}")
        return None, {"cost": 0.0}


@dataclass
class ImageCandidate:
    kind: str  # 'xref' or 'page'
    page_index: int
    xref: Optional[int]
    area_ratio: float
    is_scan: bool
    words_count: int
    score: float


def _cfg_bool(section: str, key: str, fallback: str = "false") -> bool:
    try:
        val = config.get(section, key, fallback=fallback)
    except Exception:
        val = fallback
    s = str(val).strip().lower()
    return s in {"1", "true", "yes", "on"}


def _select_images_for_analysis(doc: PDFDocument) -> List[ImageCandidate]:
    candidates: List[ImageCandidate] = []
    try:
        # Configurable knobs
        try:
            max_images = int(config.get("AI", "max_images_per_pdf", fallback="3"))
        except Exception:
            max_images = 3
        try:
            scan_threshold = float(config.get("AI", "scan_coverage_threshold", fallback="0.95"))
        except Exception:
            scan_threshold = 0.95
        try:
            first_pages_priority = int(config.get("AI", "first_pages_priority", fallback="3"))
        except Exception:
            first_pages_priority = 3
        try:
            min_icon_edge_cm = float(config.get("AI", "min_icon_edge_cm", fallback="2.0"))
        except Exception:
            min_icon_edge_cm = 2.0
        group_small = _cfg_bool("AI", "group_small_images_per_page", fallback="true")
        try:
            small_group_threshold = int(config.get("AI", "small_images_group_threshold", fallback="3"))
        except Exception:
            small_group_threshold = 3
        exclude_small_icons = _cfg_bool("AI", "exclude_small_icons", fallback="true")

        doc.analyze_document_images()
        if not getattr(doc, "pages", None):
            return []

        for page_idx, page_info in enumerate(doc.pages):
            words = int(page_info.get("words_count", 0) or 0)
            page_images = doc.images[page_idx] if page_idx < len(doc.images) else []
            # Max coverage on this page
            max_cov = 0.0
            for img in page_images:
                try:
                    cov = float(img.get("page_coverage_percent", 0.0) or 0.0)
                    if cov > max_cov:
                        max_cov = cov
                except Exception:
                    pass
            is_scan_page = max_cov >= (scan_threshold * 100.0)

            # Determine small icons on this page
            small_imgs = []
            large_imgs = []
            for img in page_images:
                width_pt = img.get("width", 0.0) or 0.0
                height_pt = img.get("height", 0.0) or 0.0
                try:
                    w_cm = PDFDocument._points_to_cm(width_pt)  # type: ignore[attr-defined]
                    h_cm = PDFDocument._points_to_cm(height_pt)  # type: ignore[attr-defined]
                    is_small = min(w_cm, h_cm) < float(min_icon_edge_cm)
                except Exception:
                    is_small = False
                (small_imgs if is_small else large_imgs).append(img)

            # Group multiple small images into a page-candidate
            if group_small and len(small_imgs) >= small_group_threshold:
                # Represent as a full page render candidate
                # area_ratio ~ 1.0 for a page capture
                base = 1000.0 if page_idx < first_pages_priority else 0.0
                score = base + (1.0 / (words + 1))
                candidates.append(ImageCandidate(
                    kind="page",
                    page_index=page_idx,
                    xref=None,
                    area_ratio=1.0,
                    is_scan=is_scan_page,
                    words_count=words,
                    score=score,
                ))

            # Prefer page-candidate for scan pages
            if is_scan_page:
                base = 1000.0 if page_idx < first_pages_priority else 0.0
                score = base + (1.0 / (words + 1))
                candidates.append(ImageCandidate(
                    kind="page",
                    page_index=page_idx,
                    xref=None,
                    area_ratio=1.0,
                    is_scan=True,
                    words_count=words,
                    score=score,
                ))
            else:
                # For embedded images: add images as individual candidates (optionally excluding icons)
                images_for_candidates = list(large_imgs) if exclude_small_icons else list(large_imgs) + list(small_imgs)
                for img in images_for_candidates:
                    xref = img.get("xref")
                    try:
                        area_ratio = float(img.get("page_coverage_percent", 0.0) or 0.0) / 100.0
                    except Exception:
                        area_ratio = 0.0
                    base = 1000.0 if page_idx < first_pages_priority else 0.0
                    # Score per spec: area_ratio / (words + 1)
                    score = base + (area_ratio / (words + 1)) + (0.01 * area_ratio)
                    candidates.append(ImageCandidate(
                        kind="xref",
                        page_index=page_idx,
                        xref=xref,
                        area_ratio=area_ratio,
                        is_scan=False,
                        words_count=words,
                        score=score,
                    ))

        # Sort by score desc and keep only the top N
        candidates.sort(key=lambda c: c.score, reverse=True)
        selected = candidates[:max_images]

        # Vector fallback: if nothing selected and pages have little text, render pages
        if not selected:
            try:
                words_thr = int(config.get("AI", "vector_fallback_words_threshold", fallback="15"))
            except Exception:
                words_thr = 15
            try:
                vf_max_pages = int(config.get("AI", "vector_fallback_max_pages", fallback=str(max_images)))
            except Exception:
                vf_max_pages = max_images
            fallback_pages: List[int] = [
                idx for idx, p in enumerate(doc.pages)
                if int(p.get("words_count", 0) or 0) <= words_thr
            ]
            # Prioritize earlier pages
            fallback_pages = fallback_pages[:vf_max_pages]
            for idx in fallback_pages:
                selected.append(ImageCandidate(
                    kind="page",
                    page_index=idx,
                    xref=None,
                    area_ratio=1.0,
                    is_scan=False,
                    words_count=int(doc.pages[idx].get("words_count", 0) or 0),
                    score=999.0 - idx,
                ))

        return selected
    except Exception as e:
        logging.error(f"Error preparing images for analysis: {e}")
    return []


def analyze_images(doc: PDFDocument, model: str = "") -> Tuple[Optional[str], Dict[str, Any]]:
    """Analyze images in the document with a vision-capable model.
    Returns (json_str, usage). If model is empty or unsupported, skip.
    """
    if not model:
        logging.info("Image analysis skipped (no model configured)")
        return None, {"cost": 0.0}

    # Allow deterministic test runs using mock files next to the PDF
    if mock_provider.is_mock_model(model):
        response, usage = mock_provider.fetch(doc, "image", context=None)
        return response, usage

    # Build candidate list with scoring and then render b64 + context in order
    cands = _select_images_for_analysis(doc)
    if not cands:
        logging.info("No images selected for analysis; skipping")
        return None, {"cost": 0.0}

    if mock_provider.is_mock_model(model):
        response, usage = mock_provider.fetch(doc, "image", context={"image_count": len(cands)})
        # Attempt to inject alt-texts based on mock response structure
        try:
            items = json.loads(response)
            if isinstance(items, dict):
                items = [items]
            if isinstance(items, list):
                alts = []
                for i, item in enumerate(items[: len(cands)]):
                    title = (item or {}).get("title") or ""
                    summary = (item or {}).get("summary") or ""
                    alt_text = (item or {}).get("alt_text") or (f"{title}. {summary}" if (title or summary) else "")
                    if alt_text:
                        alts.append((cands[i].page_index, alt_text))
                if alts:
                    try:
                        # Inject synthesized alt-texts into document text for follow-up text analysis
                        doc.inject_image_alt_texts(alts)
                    except Exception:
                        pass
        except Exception:
            pass
        return response, usage

    # Config for rendering + context length
    try:
        page_render_max_px = int(config.get('AI', 'page_render_max_px', fallback='1536'))
    except Exception:
        page_render_max_px = 1536
    try:
        image_render_max_px = int(config.get('AI', 'image_render_max_px', fallback=str(page_render_max_px)))
    except Exception:
        image_render_max_px = page_render_max_px
    try:
        context_max_chars = int(config.get('AI', 'image_context_max_chars', fallback='800'))
    except Exception:
        context_max_chars = 800

    def _truncate(text: str, n: int) -> str:
        text = (text or "").strip()
        return text if len(text) <= n else (text[:n] + "…")

    # Render images in the same order as candidates and attach page text context
    images_b64: List[str] = []
    per_image_context: List[str] = []
    used_pages: List[int] = []
    for idx, c in enumerate(cands, start=1):
        page_text = doc.get_page_text(c.page_index, use_ocr_if_needed=True)
        per_image_context.append(
            f"Image {idx} (page {c.page_index + 1}; kind={c.kind}; score={c.score:.3f})\n" +
            f"Context (trimmed): {_truncate(page_text, context_max_chars)}"
        )
        if c.kind == "xref" and c.xref:
            b64 = doc.render_image_region_png_base64(c.xref, max_px=image_render_max_px)
            if not b64:
                # Fallback to raw xref extract if region render failed
                b64 = doc.get_png_image_base64_by_xref(c.xref)
        else:
            b64 = doc.render_page_png_base64(c.page_index, max_px=page_render_max_px)
        if b64:
            images_b64.append(b64)
            used_pages.append(c.page_index)

    if not images_b64:
        logging.info("Rendering failed for selected images; skipping")
        return None, {"cost": 0.0}

    # Minimal, user-oriented log: how many images from which pages
    page_counts: Dict[int, int] = {}
    for p in used_pages:
        page_counts[p + 1] = page_counts.get(p + 1, 0) + 1
    summary = ", ".join(f"page {p}: {n}" for p, n in sorted(page_counts.items()))
    logging.info("Image selection summary — %s", summary if summary else "no images")

    # Build an informative prompt that lists each image with its page-local context
    prompt = (
        "You are a helpful assistant analyzing images inside of documents."
        " For each image, produce an object with these fields:"
        " title (3-4 words), summary (3-4 sentences), creator/issuer, creation_date (if any),"
        " tags (list), importance (0-10), per-field confidences (0-10), and alt_text."
        " The alt_text must explicitly include the image Title and Summary in one or two sentences,"
        " suitable for an HTML alt attribute, and must not include tags or confidence values."
        " It should reflect both the visual content and the page-local text context. "
        f"Always answer in {_lang()}. Output must be a JSON array, one object per image,"
        " in the same order as the uploaded images."
        "\n\nDocument context (existing, to be extended consistently):\n" + doc.to_api_json() +
        "\n\nPer-image page context follows in the same order as the uploaded images:\n" +
        "\n\n".join(per_image_context)
    )

    try:
        # Optional temperature override via config
        try:
            temp_str = config.get('AI', 'image_temperature', fallback='0.8')
            temperature = float(temp_str)
        except Exception:
            temperature = 0.8
        answer, usage = run_vision(model, prompt, images_b64, temperature=temperature)
        text = _json_guard2(answer)
        # Normalize confidences in per-image objects if the model used 0..1
        try:
            obj = json.loads(text)
            obj = _normalize2(obj, source="image")
            text = json.dumps(obj, ensure_ascii=False)
        except Exception:
            pass
        # Try to extract per-image alt texts and inject into the document's text buffer
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list):
                alts = []
                for i, item in enumerate(data[: len(used_pages)]):
                    title = (item or {}).get("title") or ""
                    summary = (item or {}).get("summary") or ""
                    alt_text = (item or {}).get("alt_text") or (f"{title}. {summary}" if (title or summary) else "")
                    if alt_text:
                        alts.append((used_pages[i], alt_text))
                if alts:
                    try:
                        doc.inject_image_alt_texts(alts)
                    except Exception:
                        pass
        except Exception:
            pass
        return text, usage
    except Exception as e:
        logging.warning(f"Vision model error or unsupported: {e}")
        return None, {"cost": 0.0}


def analyze_combined(doc: PDFDocument, model: str = "", visual_debug_path: Optional[str] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    """Image analysis using the combined (text + images) algorithm.

    Returns (json_str, usage). When visual_debug_path is provided, performs a dry-run:
    generates a PDF illustrating the request (parts order) and skips real AI calls.
    Reading order is preserved page-by-page: text then images per page.
    """
    dry_run = visual_debug_path is not None or not model
    if not model and not visual_debug_path:
        logging.error("Image analysis skipped: no model configured ([AI].image_model is empty)")
        return None, {"cost": 0.0}

    # Optional: allow using mock provider for deterministic tests
    if mock_provider.is_mock_model(model):
        response, usage = mock_provider.fetch(doc, "combined", context={})
        return response, usage

    # Read knobs from config
    try:
        # No truncation by default; 0 disables trimming
        # Prefer new key image_text_max_chars; fallback to combined_text_max_chars
        context_max_chars = int(
            config.get('AI', 'image_text_max_chars', fallback=config.get('AI', 'combined_text_max_chars', fallback='0'))
        )
    except Exception:
        context_max_chars = 0
    # Token + image selection knobs
    try:
        token_limit = int(config.get('AI', 'token_limit', fallback=str(1_000_000)))
    except Exception:
        token_limit = 1_000_000
    # tokens_per_image kept only for backward compatibility (no longer used)
    try:
        tokens_per_image = int(config.get('AI', 'combined_tokens_per_image', fallback='0'))
    except Exception:
        tokens_per_image = 0
    try:
        priority_first_pages = int(
            config.get('AI', 'image_priority_first_pages', fallback=config.get('AI', 'combined_priority_first_pages', fallback='3'))
        )
    except Exception:
        priority_first_pages = 3
    try:
        page_group_threshold = int(
            config.get('AI', 'image_page_group_threshold', fallback=config.get('AI', 'combined_page_group_threshold', fallback='3'))
        )
    except Exception:
        page_group_threshold = 3
    try:
        image_render_max_px = int(config.get('AI', 'image_render_max_px', fallback='1536'))
    except Exception:
        image_render_max_px = 1536
    try:
        page_render_max_px = int(config.get('AI', 'page_render_max_px', fallback=str(image_render_max_px)))
    except Exception:
        page_render_max_px = image_render_max_px
    # Prefer new key; fallback to old combined key
    try:
        exclude_small = _cfg_bool('AI', 'image_exclude_small_icons', fallback=config.get('AI', 'combined_exclude_small_icons', fallback='true'))
    except Exception:
        exclude_small = True
    try:
        # Ignore images with min edge < 3cm by default (new key, fallback to old)
        min_icon_edge_cm = float(
            config.get('AI', 'image_small_image_min_edge_cm', fallback=config.get('AI', 'combined_small_image_min_edge_cm', fallback='3.0'))
        )
    except Exception:
        min_icon_edge_cm = 3.0

    def _truncate(text: str, n: int) -> str:
        text = (text or "").strip()
        return text if n <= 0 or len(text) <= n else (text[:n] + "…")

    # Phase A: extract elements (text/images/figures) in reading order and raw page texts
    def _extract_elements_and_candidates() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        # Build sequential text per page (forcing OCR per-page if needed for best quality)
        page_texts: List[str] = []
        try:
            doc.analyze_document_images()
            page_count = len(getattr(doc, 'pages', []) or [])
        except Exception:
            page_count = 0
        if page_count <= 0:
            flat = doc.get_pdf_text() or ""
            page_texts = [flat]
        else:
            for idx in range(page_count):
                t = doc.get_page_text(idx, use_ocr_if_needed=True)
                page_texts.append(t or "")

        elements: List[Dict[str, Any]] = []
        image_candidates: List[Dict[str, Any]] = []

        # Tame verbose third-party logging at DEBUG level
        try:
            for _name in (
                "pdfminer",
                "pdfminer.pdfparser",
                "pdfminer.psparser",
                "pdfminer.pdfinterp",
                "pdfminer.layout",
                "pdfminer.high_level",
            ):
                _lg = logging.getLogger(_name)
                _lg.setLevel(logging.WARNING)
                _lg.propagate = True
        except Exception:
            pass

        try:
            from pdfminer.high_level import extract_pages  # type: ignore
            from pdfminer.layout import LAParams, LTTextBox, LTTextLine, LTImage, LTFigure  # type: ignore
        except Exception as e:
            logging.error("pdfminer.six is required for image analysis (combined algorithm): %s", e)
            return [], [], page_texts

        try:
            char_margin = float(config.get('AI', 'image_char_margin', fallback=config.get('AI', 'combined_char_margin', fallback='2.0')))
        except Exception:
            char_margin = 2.0
        try:
            line_margin = float(config.get('AI', 'image_line_margin', fallback=config.get('AI', 'combined_line_margin', fallback='0.5')))
        except Exception:
            line_margin = 0.5
        laparams = LAParams(char_margin=char_margin, line_margin=line_margin, boxes_flow=None)

        def _iter_layout(obj):
            # Depth-first: figures yield as a single node; we may expand later based on heuristic
            if isinstance(obj, (LTTextBox, LTTextLine)):
                yield ("text", obj.bbox, obj.get_text(), None)
            elif isinstance(obj, LTImage):
                yield ("image", obj.bbox, None, None)
            elif isinstance(obj, LTFigure):
                yield ("figure", obj.bbox, None, obj)
            else:
                if hasattr(obj, "__iter__"):
                    for x in obj:
                        yield from _iter_layout(x)

        def _figure_metrics(fig) -> Dict[str, int]:
            words = 0
            imgs = 0
            shapes = 0
            stack = [fig]
            while stack:
                o = stack.pop()
                cls = o.__class__.__name__
                if cls in ("LTLine", "LTRect", "LTCurve"):
                    shapes += 1
                    continue
                if isinstance(o, LTImage):
                    imgs += 1
                    continue
                if isinstance(o, (LTTextBox, LTTextLine)):
                    try:
                        words += len((o.get_text() or "").split())
                    except Exception:
                        pass
                    stack[0:0] = list(_iter_layout(o))
                else:
                    stack[0:0] = list(_iter_layout(o))
            return {"words": words, "images": imgs, "shapes": shapes}

        try:
            max_words_in_figure = int(config.get('AI', 'image_figure_max_words', fallback=config.get('AI', 'combined_figure_max_words', fallback='20')))
        except Exception:
            max_words_in_figure = 20
        try:
            min_shapes_in_figure = int(config.get('AI', 'image_figure_min_shapes', fallback=config.get('AI', 'combined_figure_min_shapes', fallback='2')))
        except Exception:
            min_shapes_in_figure = 2
        capture_figures = _cfg_bool('AI', 'image_capture_figures', fallback=config.get('AI', 'combined_capture_figures', fallback='true'))

        img_order_counter = 0
        for page_no, layout in enumerate(extract_pages(doc.get_absolute_path(), laparams=laparams), start=1):
            page_items = []
            for item in _iter_layout(layout):
                page_items.append(item)
            i = 0
            while i < len(page_items):
                kind, bbox, text, meta = page_items[i]
                if kind == "text":
                    elements.append({"type": "text", "text": text, "page": page_no})
                    i += 1
                    continue
                if kind == "image":
                    try:
                        w_cm = PDFDocument._points_to_cm(float(bbox[2] - bbox[0]))  # type: ignore[attr-defined]
                        h_cm = PDFDocument._points_to_cm(float(bbox[3] - bbox[1]))  # type: ignore[attr-defined]
                        is_small = min(w_cm, h_cm) < float(min_icon_edge_cm)
                    except Exception:
                        is_small = False
                    if exclude_small and is_small:
                        i += 1
                        continue
                    img_order_counter += 1
                    area = float(max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
                    image_candidates.append({"id": img_order_counter, "page": page_no, "bbox": bbox, "area": area, "kind": "image"})
                    elements.append({"type": "image", "id": img_order_counter, "page": page_no})
                    i += 1
                    continue
                if kind == "figure":
                    fig = meta
                    take = False
                    if capture_figures:
                        m = _figure_metrics(fig)
                        try:
                            w_cm = PDFDocument._points_to_cm(float(bbox[2] - bbox[0]))  # type: ignore[attr-defined]
                            h_cm = PDFDocument._points_to_cm(float(bbox[3] - bbox[1]))  # type: ignore[attr-defined]
                            big_enough = min(w_cm, h_cm) >= float(min_icon_edge_cm)
                        except Exception:
                            big_enough = True
                        take = big_enough and (m.get("shapes", 0) >= min_shapes_in_figure) and (m.get("words", 0) <= max_words_in_figure)
                    if take:
                        img_order_counter += 1
                        area = float(max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
                        image_candidates.append({"id": img_order_counter, "page": page_no, "bbox": bbox, "area": area, "kind": "figure"})
                        elements.append({"type": "image", "id": img_order_counter, "page": page_no})
                        i += 1
                    else:
                        inner = []
                        for item in _iter_layout(fig):
                            inner.append(item)
                        page_items[i:i+1] = inner
                    continue
                i += 1
        return elements, image_candidates, page_texts


    # Build sequential text per page (forcing OCR per-page if needed for best quality)
    page_texts: List[str] = []
    try:
        # doc.pages is built by analyze_document_images(); but use get_page_text to ensure OCR if necessary
        # Try to detect page count by probing until empty; better approach requires opening fitz here, so reuse existing helper
        doc.analyze_document_images()
        page_count = len(getattr(doc, 'pages', []) or [])
    except Exception:
        page_count = 0

    if page_count <= 0:
        # Fallback: use the flattened document text
        flat = doc.get_pdf_text() or ""
        page_texts = [flat]
    else:
        for idx in range(page_count):
            t = doc.get_page_text(idx, use_ocr_if_needed=True)
            page_texts.append(t or "")

    # Build ordered elements (text/images/figures) using pdfminer, keep reading order
    elements: List[Dict[str, Any]] = []
    image_manifest_lines: List[str] = []
    images_b64: List[str] = []

    # Tame verbose third-party logging at DEBUG level
    try:
        for _name in (
            "pdfminer",
            "pdfminer.pdfparser",
            "pdfminer.psparser",
            "pdfminer.pdfinterp",
            "pdfminer.layout",
            "pdfminer.high_level",
        ):
            _lg = logging.getLogger(_name)
            _lg.setLevel(logging.WARNING)
            _lg.propagate = True
    except Exception:
        pass

    from pdfminer.high_level import extract_pages
    from pdfminer.layout import (
        LTImage,
        LTFigure,
        LTTextContainer,
        LAParams,
        LTLine,
        LTRect,
        LTCurve,
    )

    laparams = LAParams()

    def _iter_layout(obj):
        if hasattr(obj, "_objs") and isinstance(getattr(obj, "_objs"), list):
            for o in obj._objs:  # type: ignore[attr-defined]
                yield o

    def _collect(container, page_number: int):
        items = []
        stack = list(_iter_layout(container))
        img_idx = 0
        while stack:
            o = stack.pop(0)
            if isinstance(o, LTTextContainer):
                t = (o.get_text() or "").strip()
                if t:
                    items.append(("text", o.bbox, t, None))
            elif isinstance(o, LTImage):
                img_idx += 1
                items.append(("image", o.bbox, None, {"page": page_number, "idx": img_idx}))
            elif isinstance(o, LTFigure):
                # Keep figure as a single item for heuristic processing; don't descend now
                items.append(("figure", o.bbox, None, o))
            else:
                # Generic container: descend
                stack[0:0] = list(_iter_layout(o))
        # top-down then left-right
        items.sort(key=lambda it: (-it[1][3], it[1][0]))
        return items

    def _figure_metrics(fig) -> Dict[str, int]:
        words = 0
        imgs = 0
        shapes = 0
        stack = list(_iter_layout(fig))
        while stack:
            o = stack.pop(0)
            if isinstance(o, LTTextContainer):
                txt = (o.get_text() or "").strip()
                words += len(txt.split())
            elif isinstance(o, LTImage):
                imgs += 1
            elif isinstance(o, (LTLine, LTRect, LTCurve)):
                shapes += 1
            elif isinstance(o, LTFigure):
                stack[0:0] = list(_iter_layout(o))
            else:
                stack[0:0] = list(_iter_layout(o))
        return {"words": words, "images": imgs, "shapes": shapes}

    try:
        max_words_in_figure = int(config.get('AI', 'image_figure_max_words', fallback=config.get('AI', 'combined_figure_max_words', fallback='20')))
    except Exception:
        max_words_in_figure = 20
    try:
        min_shapes_in_figure = int(config.get('AI', 'image_figure_min_shapes', fallback=config.get('AI', 'combined_figure_min_shapes', fallback='2')))
    except Exception:
        min_shapes_in_figure = 2
    capture_figures = _cfg_bool('AI', 'image_capture_figures', fallback=config.get('AI', 'combined_capture_figures', fallback='true'))

    total_visuals = 0
    # Collect image/figure candidates without rendering to allow selection under budget
    image_candidates: List[Dict[str, Any]] = []
    img_order_counter = 0
    for page_no, layout in enumerate(extract_pages(doc.get_absolute_path(), laparams=laparams), start=1):
        page_items = _collect(layout, page_no)
        i = 0
        while i < len(page_items):
            kind, bbox, text, meta = page_items[i]
            if kind == "text":
                elements.append({"type": "text", "text": text, "page": page_no})
                i += 1
                continue
            if kind == "image":
                try:
                    w_cm = PDFDocument._points_to_cm(float(bbox[2] - bbox[0]))  # type: ignore[attr-defined]
                    h_cm = PDFDocument._points_to_cm(float(bbox[3] - bbox[1]))  # type: ignore[attr-defined]
                    is_small = min(w_cm, h_cm) < float(min_icon_edge_cm)
                except Exception:
                    is_small = False
                if exclude_small and is_small:
                    i += 1
                    continue
                img_order_counter += 1
                area = float(max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
                image_candidates.append({"id": img_order_counter, "page": page_no, "bbox": bbox, "area": area, "kind": "image"})
                elements.append({"type": "image", "id": img_order_counter, "page": page_no})
                i += 1
                continue
            if kind == "figure":
                fig = meta
                take = False
                if capture_figures:
                    m = _figure_metrics(fig)
                    try:
                        w_cm = PDFDocument._points_to_cm(float(bbox[2] - bbox[0]))  # type: ignore[attr-defined]
                        h_cm = PDFDocument._points_to_cm(float(bbox[3] - bbox[1]))  # type: ignore[attr-defined]
                        big_enough = min(w_cm, h_cm) >= float(min_icon_edge_cm)
                    except Exception:
                        big_enough = True
                    take = big_enough and (m.get("shapes", 0) >= min_shapes_in_figure) and (m.get("words", 0) <= max_words_in_figure)
                if take:
                    img_order_counter += 1
                    area = float(max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
                    image_candidates.append({"id": img_order_counter, "page": page_no, "bbox": bbox, "area": area, "kind": "figure"})
                    elements.append({"type": "image", "id": img_order_counter, "page": page_no})
                    # Do not descend into children when captured to avoid duplicates
                    i += 1
                else:
                    # Expand figure inline: replace current with collected children
                    inner = _collect(fig, page_no)
                    page_items[i:i+1] = inner
                continue
            # Unknown kind: skip
            i += 1

    # Prepare mixed parts preserving order
    parts: List[Dict[str, Any]] = []
    # Detailed instruction as before, including existing context; not duplicated elsewhere
    intro = (
        "You are a helpful assistant analyzing full documents combining text and images. "
        "Use ALL provided information to infer: creation_date, a short title (3-4 words), a meaningful summary (3-4 sentences), "
        "creator/issuer, suitable tags (list), an importance score (0-10), and a confidence (0-10) for each field. "
        f"Always answer in {_lang()} and output a single JSON object with the same structure as previous runs.\n\n"
        "Existing document context (to be extended consistently):\n" + doc.to_api_json() + "\n\n"
        "The following content is provided in strict reading order (top→bottom, left→right) on each page."
    )
    # Note: do NOT append intro here; it will be added once in the final assembly

    # Aggregate all text per page once, then emit it at the first text occurrence on that page
    page_text_map: Dict[int, str] = {}
    for el in elements:
        if el.get("type") == "text":
            p = int(el.get("page") or 0)
            txt = str(el.get("text") or "").strip()
            if not txt:
                continue
            prev = page_text_map.get(p, "")
            page_text_map[p] = (prev + ("\n\n" if prev else "") + txt)

    # Estimate token usage for intro + page texts; trim proportionally if exceeding token_limit
    def _tok_len(s: str) -> int:
        return _tok_est(s)

    text_parts: List[Tuple[int, str]] = []  # (page, text)
    for p in sorted(page_text_map.keys()):
        text_parts.append((p, f"[Page {p}]\n" + page_text_map[p]))

    intro_tokens = _tok_len(intro)
    page_tokens = [(_tok_len(t)) for _, t in text_parts]
    sum_text = intro_tokens + sum(page_tokens)
    # Hard guard: if the intro (system prompt + context) alone exceeds the limit, abort cleanly
    if intro_tokens > token_limit:
        logging.info(
            "[image budget] %s: intro exceeds limit (intro≈%d > limit=%d); aborting request",
            doc.file_name, intro_tokens, token_limit,
        )
        return None, {"cost": 0.0, "dry_run": True, "skipped_reason": "intro_exceeds_limit"}
    trimmed_happened = False
    if sum_text > token_limit:
        # Proportional trimming across pages only; keep intro intact
        budget = max(0, token_limit - intro_tokens)
        total_pages = sum(page_tokens) or 1
        new_parts: List[Tuple[int, str]] = []
        for (p, t), tok in zip(text_parts, page_tokens):
            tgt = int(tok * budget / total_pages)
            if tgt <= 0:
                continue
            # Approximate cut by char ratio
            ratio = tgt / max(1, _tok_len(t))
            cut = int(len(t) * ratio)
            new_parts.append((p, t[:max(1, cut)]))
        text_parts = new_parts
        trimmed_happened = True
        logging.info(
            "[image budget] %s: trimmed text to fit limit (used_tokens≈%d/%d)",
            doc.file_name,
            intro_tokens + sum(_tok_len(t) for _, t in text_parts), token_limit,
        )

    # Select images under remaining budget and following priority
    used_tokens = intro_tokens + sum(_tok_len(t) for _, t in text_parts)
    remaining = max(0, token_limit - used_tokens)
    per_page: Dict[int, List[Dict[str, Any]]] = {}
    for m in image_candidates:
        per_page.setdefault(int(m["page"]), []).append(m)

    candidates: List[Dict[str, Any]] = []
    for p, metas in per_page.items():
        if len(metas) >= page_group_threshold:
            candidates.append({"kind": "page", "page": p, "area": float('inf')})
        else:
            candidates.extend(metas)

    early = [c for c in candidates if int(c.get("page", 0)) <= priority_first_pages]
    # Preserve encounter order for early items (by implicit id/order)
    early.sort(key=lambda c: int(c.get("id", 0)) if c.get("kind") != "page" else -1)
    rest = [c for c in candidates if int(c.get("page", 0)) > priority_first_pages]
    rest.sort(key=lambda c: float(c.get("area", 0.0)), reverse=True)
    ordered = early + rest

    selected_pages_full: set[int] = set()
    selected_images: set[int] = set()
    # Optional per-candidate rendering overrides (for adaptive downscaling)
    # keys: ("page", page_no) or ("id", image_id)
    render_px_override: Dict[Tuple[str, int], int] = {}
    image_tokens_spent = 0
    skipped_due_budget = 0

    # Helper: estimate image token cost per OpenAI tiling guidance
    import math
    def _estimate_tokens_for_candidate(c: Dict[str, Any]) -> int:
        if tokens_per_image and tokens_per_image > 0:
            return int(tokens_per_image)
        try:
            page_idx0 = int(c.get("page", 1)) - 1
            if c.get("kind") == "page":
                # Use page dimensions
                pw = float(doc.pages[page_idx0].get("width", 0) or 0)
                ph = float(doc.pages[page_idx0].get("height", 0) or 0)
                longest = max(pw, ph)
                scale = (min(1.0, float(page_render_max_px) / float(longest)) if longest > 0 and page_render_max_px else 1.0)
                wpx = max(1, int(pw * scale))
                hpx = max(1, int(ph * scale))
            else:
                # Region bbox
                x0, y0, x1, y1 = c.get("bbox")
                rw = float(x1 - x0)
                rh = float(y1 - y0)
                longest = max(rw, rh)
                scale = (min(1.0, float(image_render_max_px) / float(longest)) if longest > 0 and image_render_max_px else 1.0)
                wpx = max(1, int(rw * scale))
                hpx = max(1, int(rh * scale))
            tiles = int(math.ceil(wpx / 512.0) * math.ceil(hpx / 512.0))
            return int(85 + 170 * tiles)
        except Exception:
            # Conservative fallback
            return 4000
    # Verbose candidate decision debug (helps understand scan pages & budgets)
    for c in ordered:
        c_tokens = _estimate_tokens_for_candidate(c)
        c_kind = str(c.get("kind"))
        c_page = int(c.get("page") or 0)
        before = remaining
        if remaining < c_tokens:
            skipped_due_budget += 1
            logging.debug(
                "[image budget] skip %s p=%d need≈%d > remaining≈%d",
                c_kind, c_page, c_tokens, before,
            )
            continue
        if c_kind == "page":
            selected_pages_full.add(c_page)
            remaining -= c_tokens
            image_tokens_spent += c_tokens
            logging.debug(
                "[image budget] take page p=%d cost≈%d → remaining≈%d",
                c_page, c_tokens, remaining,
            )
        else:
            # region/image candidate
            if c_page in selected_pages_full:
                logging.debug(
                    "[image budget] skip region on p=%d (full page already selected)",
                    c_page,
                )
                continue
            img_id = int(c.get("id") or 0)
            selected_images.add(img_id)
            remaining -= c_tokens
            image_tokens_spent += c_tokens
            logging.debug(
                "[image budget] take region id=%d p=%d cost≈%d → remaining≈%d",
                img_id, c_page, c_tokens, remaining,
            )

    if skipped_due_budget > 0:
        logging.info(
            "[image budget] %s: skipped images due to budget=%d; selected pages_full=%d, regions=%d; est_image_tokens≈%d; est_total≈%d/%d",
            doc.file_name,
            skipped_due_budget,
            len(selected_pages_full), len(selected_images), image_tokens_spent,
            used_tokens + image_tokens_spent, token_limit,
        )

    # Adaptive fallback for scan-like PDFs: if nothing fit but there are candidates, try a downscaled single image
    if not selected_pages_full and not selected_images and ordered:
        # try to fit at least a 1-tile render (≈255 tokens) or as many tiles as budget allows
        # Determine tiles we can afford within remaining (subtract a small safety of 10 tokens)
        safety = 10
        afford = max(0, remaining - safety)
        if afford >= 85 + 170 * 1:
            # choose the first candidate (prefer page if present among early set)
            best = None
            for c in ordered:
                if c.get("kind") == "page":
                    best = c
                    break
            if best is None:
                best = ordered[0]
            # Informative log: why downscaling is used
            try:
                original_tokens = int(_estimate_tokens_for_candidate(best))
            except Exception:
                original_tokens = -1
            try:
                logging.info(
                    "[image budget] no images selected; applying adaptive fallback (remaining≈%d). Best candidate: kind=%s p=%d original≈%s tokens",
                    remaining, str(best.get("kind")), int(best.get("page") or 0), ("%d" % original_tokens if original_tokens >= 0 else "unknown")
                )
            except Exception:
                pass
            # Compute minimal max_px so that tiles fit into 'afford'
            try:
                import math
                if best.get("kind") == "page":
                    pno = int(best.get("page") or 1)
                    idx0 = pno - 1
                    pw = float(doc.pages[idx0].get("width", 0) or 0)
                    ph = float(doc.pages[idx0].get("height", 0) or 0)
                    target_tiles = max(1, min(9, int((afford - 85) // 170)))
                    # derive a max_px along longest edge so tiles<=target_tiles
                    # heuristic: try to fit into sqrt(target_tiles) tiles per side
                    per_side = int(math.ceil(math.sqrt(target_tiles)))
                    longest_target = max(1, per_side * 512)
                    # ensure we don't upscale beyond configured max
                    px = int(min(page_render_max_px, longest_target))
                    render_px_override[("page", pno)] = px
                    selected_pages_full.add(pno)
                    chosen_tiles = int(per_side * per_side)
                    chosen_tokens = int(85 + 170 * chosen_tiles)
                    image_tokens_spent += chosen_tokens
                    remaining = max(0, remaining - chosen_tokens)
                    logging.info(
                        "[image budget] adaptive include: page p=%d — downscaled to ~%dpx (tiles≈%d, ≈%d tokens)",
                        pno, px, chosen_tiles, chosen_tokens,
                    )
                else:
                    # region candidate
                    pno = int(best.get("page") or 1)
                    x0, y0, x1, y1 = best.get("bbox")
                    rw = float(x1 - x0)
                    rh = float(y1 - y0)
                    target_tiles = max(1, min(9, int((afford - 85) // 170)))
                    per_side = int(math.ceil(math.sqrt(target_tiles)))
                    longest_target = max(1, per_side * 512)
                    px = int(min(image_render_max_px, longest_target))
                    img_id = int(best.get("id") or 0)
                    render_px_override[("id", img_id)] = px
                    selected_images.add(img_id)
                    chosen_tiles = int(per_side * per_side)
                    chosen_tokens = int(85 + 170 * chosen_tiles)
                    image_tokens_spent += chosen_tokens
                    remaining = max(0, remaining - chosen_tokens)
                    logging.info(
                        "[image budget] adaptive include: region id=%d p=%d — downscaled to ~%dpx (tiles≈%d, ≈%d tokens)",
                        img_id, pno, px, chosen_tiles, chosen_tokens,
                    )
            except Exception as _e:
                logging.debug("[image budget] adaptive include failed: %s", _e)
        else:
            logging.info(
                "[image budget] no images selected and adaptive fallback not possible (remaining≈%d < ~255 tokens for 1 tile)",
                remaining,
            )

    # Build final parts in page order: intro, then for each page -> text then images
    parts.append({"type": "text", "text": intro})
    trimmed_text_by_page: Dict[int, str] = {p: t for (p, t) in text_parts}
    pages_in_doc = sorted({*page_text_map.keys(), *[int(m.get('page')) for m in image_candidates]})
    for p in pages_in_doc:
        # 1) Page text (if any after trimming)
        t = trimmed_text_by_page.get(p)
        if t:
            parts.append({"type": "text", "text": t})
        # 2) Images for this page
        if p in selected_pages_full:
            # Use per-candidate override when present; otherwise page_render_max_px
            px = render_px_override.get(("page", p), page_render_max_px)
            b64 = doc.render_page_png_base64(p - 1, max_px=px) or ""
            if b64:
                parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        else:
            metas = [m for m in image_candidates if int(m["page"]) == p and int(m.get("id", 0)) in selected_images]
            metas.sort(key=lambda m: int(m.get("id", 0)))
            for m in metas:
                px = render_px_override.get(("id", int(m.get("id") or 0)), image_render_max_px)
                b64 = doc.render_page_region_png_base64(p - 1, m["bbox"], max_px=px, coords="pdfminer") or ""
                if b64:
                    parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

    # Optional: write a visual debug PDF illustrating the prompt + image order
    if visual_debug_path:
        try:
            # Log the first few part types to verify order in runtime logs
            seq = ", ".join([
                ("T" if p.get("type") == "text" else ("I" if p.get("type") == "image_url" else p.get("type", "?")))
                for p in parts[:30]
            ])
            logging.info("[image visual-debug] part sequence (first 30): %s", seq)
            _write_visual_debug_pdf_from_parts(
                visual_debug_path,
                doc,
                parts,
                raw_page_texts=None,
            )
            logging.info("Wrote visual debug PDF: %s", visual_debug_path)
        except Exception as _e:
            logging.warning("Failed to write visual debug PDF '%s': %s", visual_debug_path, _e)

    # Pre-call summary log including token estimates
    try:
        _log_req("image", doc.file_name, parts=len(parts), text_tokens=used_tokens, image_tokens=image_tokens_spent, total_tokens=used_tokens + image_tokens_spent, token_limit=token_limit)
    except Exception:
        pass

    if dry_run:
        # Skip any actual AI request when visual-debug is active (or model missing)
        reason = "visual_debug" if visual_debug_path else "no_model"
        logging.info("[image] Skipping API call (reason=%s)", reason)
        return None, {"cost": 0.0, "dry_run": True, "skipped_reason": reason}

    try:
        try:
            temp_str = config.get('AI', 'image_temperature', fallback=config.get('AI', 'combined_temperature', fallback='1'))
            temperature = float(temp_str)
        except Exception:
            temperature = 1.0
        answer, usage = run_vision(model, prompt="", images_b64=[], temperature=temperature, parts=parts)
        text = _json_guard2(answer)
        # Normalize confidences to 0..10 if needed
        try:
            obj = json.loads(text)
            obj = _normalize2(obj, source="image")
            text = json.dumps(obj, ensure_ascii=False)
        except Exception:
            pass
        return text, usage
    except Exception as e:
        logging.warning(f"Image analysis (combined algorithm) failed: {e}")
        return None, {"cost": 0.0}


def _write_visual_debug_pdf(output_path: str, doc: PDFDocument, prompt: str, per_page_blocks: List[str], manifest_lines: List[str], images_b64: List[str], raw_page_texts: Optional[List[str]] = None) -> None:
    import os
    import io
    import base64
    import fitz  # PyMuPDF

    # Ensure directory exists
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    pdf = fitz.open()

    def add_text_pages(title: str, text: str) -> None:
        # Split long text into chunks and write across multiple pages
        chunk_size = 3500  # rough; insert_textbox may still wrap within page
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)] or [""]
        for idx, chunk in enumerate(chunks, start=1):
            page = pdf.new_page(width=595, height=842)  # A4 portrait
            margin = 36
            rect = fitz.Rect(margin, margin, 595 - margin, 842 - margin)
            header = f"{title} (part {idx}/{len(chunks)})\nFile: {doc.file_name}\n"
            _ = page.insert_textbox(rect, header + chunk, fontsize=10, fontname="helv", color=(0, 0, 0))

    # Page 1..N: Prompt and per-page text summary
    per_page_text = "\n\n".join(per_page_blocks)
    add_text_pages("Combined Prompt", prompt + "\n\n---\n\nPer-page text blocks (as sent):\n\n" + per_page_text)

    # Manifest page
    manifest_text = "\n".join(manifest_lines) if manifest_lines else "(no images)"
    add_text_pages("Image Manifest (order as sent)", manifest_text)

    # Optional: one section per source page to make text visibility explicit
    if raw_page_texts:
        for i, txt in enumerate(raw_page_texts, start=1):
            add_text_pages(f"Source Page {i} Text (chars: {len(txt)})", txt or "")

    # Image pages: one image per page with a caption
    for idx, b64 in enumerate(images_b64, start=1):
        try:
            img_bytes = base64.b64decode(b64)
        except Exception:
            img_bytes = b""
        caption = manifest_lines[idx-1] if idx-1 < len(manifest_lines) else f"[IMG {idx}]"
        page = pdf.new_page(width=595, height=842)
        margin = 36
        caption_rect = fitz.Rect(margin, margin, 595 - margin, margin + 60)
        page.insert_textbox(caption_rect, f"{caption}\n(base64 length: {len(b64)})", fontsize=10, fontname="helv", color=(0, 0, 0))

        # Image rectangle (below caption)
        img_top = margin + 70
        img_rect = fitz.Rect(margin, img_top, 595 - margin, 842 - margin)
        try:
            page.insert_image(img_rect, stream=img_bytes, keep_proportion=True)
        except Exception:
            # If insertion fails, leave a note
            page.insert_textbox(img_rect, "[Failed to render image]", fontsize=12, fontname="helv", color=(1, 0, 0))

    pdf.save(output_path)
    pdf.close()


def _write_visual_debug_pdf_from_parts(output_path: str, doc: PDFDocument, parts: List[Dict[str, Any]], raw_page_texts: Optional[List[str]] = None) -> None:
    import os
    import base64
    import fitz

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    pdf = fitz.open()

    # Cover page
    cover = pdf.new_page(width=595, height=842)
    margin = 36
    rect = fitz.Rect(margin, margin, 595 - margin, 842 - margin)
    text = [
        f"File: {doc.file_name}",
        f"Parts: {len(parts)} (mixed text+images in send order)",
        "",
        "This PDF illustrates the exact image-analysis request order.",
        "Each subsequent page shows one part (text or image).",
    ]
    cover.insert_textbox(rect, "\n".join(text), fontsize=12, fontname="helv")

    # Render parts in exact order
    idx = 0
    for part in parts:
        idx += 1
        ptype = part.get("type")
        page = pdf.new_page(width=595, height=842)
        if ptype == "text":
            t = str(part.get("text") or "")
            header = f"Part {idx} — TEXT\n"
            rect = fitz.Rect(margin, margin, 595 - margin, 842 - margin)
            # paginate long text chunks across multiple pages
            chunk = 3000
            remaining = header + t
            first = True
            while remaining:
                taken, remaining = remaining[:chunk], remaining[chunk:]
                page.insert_textbox(rect, taken, fontsize=10, fontname="helv")
                if remaining:
                    page = pdf.new_page(width=595, height=842)
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url") or ""
            b64 = url[len("data:image/png;base64,"):] if url.startswith("data:image") else url
            try:
                img_bytes = base64.b64decode(b64)
            except Exception:
                img_bytes = b""
            caption_rect = fitz.Rect(margin, margin, 595 - margin, margin + 60)
            page.insert_textbox(caption_rect, f"Part {idx} — IMAGE", fontsize=10, fontname="helv")
            img_rect = fitz.Rect(margin, margin + 70, 595 - margin, 842 - margin)
            try:
                page.insert_image(img_rect, stream=img_bytes, keep_proportion=True)
            except Exception:
                page.insert_textbox(img_rect, "[Failed to render image]", fontsize=12, fontname="helv", color=(1, 0, 0))

    # Optional appendix: raw per-page texts for reference
    if raw_page_texts:
        for i, txt in enumerate(raw_page_texts, start=1):
            page = pdf.new_page(width=595, height=842)
            rect = fitz.Rect(margin, margin, 595 - margin, 842 - margin)
            header = f"Source Page {i} (chars: {len(txt or '')})\n"
            page.insert_textbox(rect, header + (txt or ""), fontsize=9, fontname="helv")

    pdf.save(output_path)
    pdf.close()


def analyze_tags(tags: List[str], model: str = "") -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Suggest tag replacements/unification.
    Returns (replacements, usage). If model empty, returns identity mapping and zero cost.
    """
    if not model:
        logging.info("Tag analysis skipped (no model configured)")
        return [], {"cost": 0.0}

    # Ensure deterministic input for caching: sort and deduplicate tags
    try:
        tags = sorted({str(t).strip() for t in tags if str(t).strip()})
    except Exception:
        tags = list(tags)

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
        text = _json_guard2(answer)
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
