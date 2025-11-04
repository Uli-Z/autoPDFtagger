import json
import logging
from dataclasses import dataclass
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
        " tags (list), importance (0-10), per-field confidences, and alt_text."
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
        text = _json_guard(answer)
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
    """Analyze the full document by sending all text and all images together.

    Returns (json_str, usage).
    When visual_debug_path is provided, performs a dry-run: generates the
    illustrative PDF only and skips any real AI requests.
    Best-effort preserves the reading order: page-by-page text, and images
    appended in the same sequence as they appear within each page.
    """
    dry_run = visual_debug_path is not None or not model
    if not model and not visual_debug_path:
        logging.info("Combined analysis skipped (no model configured)")
        return None, {"cost": 0.0}

    # Optional: allow using mock provider for deterministic tests
    if mock_provider.is_mock_model(model):
        response, usage = mock_provider.fetch(doc, "combined", context={})
        return response, usage

    # Read knobs from config
    try:
        context_max_chars = int(config.get('AI', 'combined_text_max_chars', fallback='6000'))
    except Exception:
        context_max_chars = 6000
    try:
        max_images = int(config.get('AI', 'combined_max_images_per_pdf', fallback='12'))
    except Exception:
        max_images = 12
    try:
        image_render_max_px = int(config.get('AI', 'image_render_max_px', fallback='1536'))
    except Exception:
        image_render_max_px = 1536
    exclude_small = _cfg_bool('AI', 'combined_exclude_small_icons', fallback='true')
    try:
        min_icon_edge_cm = float(config.get('AI', 'min_icon_edge_cm', fallback='2.0'))
    except Exception:
        min_icon_edge_cm = 2.0

    def _truncate(text: str, n: int) -> str:
        text = (text or "").strip()
        return text if n <= 0 or len(text) <= n else (text[:n] + "…")

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
        max_words_in_figure = int(config.get('AI', 'combined_figure_max_words', fallback='20'))
    except Exception:
        max_words_in_figure = 20
    try:
        min_shapes_in_figure = int(config.get('AI', 'combined_figure_min_shapes', fallback='2'))
    except Exception:
        min_shapes_in_figure = 2
    capture_figures = _cfg_bool('AI', 'combined_capture_figures', fallback='true')

    total_visuals = 0
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
                if not (exclude_small and is_small):
                    if not max_images or total_visuals < max_images:
                        b64 = doc.render_page_region_png_base64(page_no - 1, bbox, max_px=image_render_max_px, coords="pdfminer")
                        if b64:
                            total_visuals += 1
                            images_b64.append(b64)
                            image_manifest_lines.append(f"[IMG {total_visuals}] page={page_no} bbox=({bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f})")
                            elements.append({"type": "image", "b64": b64, "page": page_no})
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
                if take and (not max_images or total_visuals < max_images):
                    b64 = doc.render_page_region_png_base64(page_no - 1, bbox, max_px=image_render_max_px, coords="pdfminer")
                    if b64:
                        total_visuals += 1
                        images_b64.append(b64)
                        image_manifest_lines.append(
                            f"[FIG {total_visuals}] page={page_no} bbox=({bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f})"
                        )
                        elements.append({"type": "image", "b64": b64, "page": page_no})
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
    intro = (
        "You are a helpful assistant analyzing full documents combining text and images. "
        "Use ALL provided information to infer: creation_date, a short title (3-4 words), a meaningful summary (3-4 sentences), "
        "creator/issuer, suitable tags (list), an importance score (0-10), and a confidence (0-10) for each field. "
        f"Always answer in {_lang()} and output a single JSON object with the same structure as previous runs.\n\n"
        "Existing document context (to be extended consistently):\n" + doc.to_api_json() + "\n\n"
        "The following content is provided in strict reading order (top→bottom, left→right) on each page."
    )
    parts.append({"type": "text", "text": intro})
    for el in elements:
        if el.get("type") == "text":
            txt = _truncate(el.get("text") or "", context_max_chars)
            if txt:
                parts.append({"type": "text", "text": f"[Page {el.get('page')}]\n" + txt})
        elif el.get("type") == "image":
            b64 = el.get("b64") or ""
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

    # Optional: write a visual debug PDF illustrating the prompt + image order
    if visual_debug_path:
        try:
            text_blocks = [p.get("text", "") for p in parts if p.get("type") == "text"]
            image_parts = [p.get("image_url", {}).get("url", "") for p in parts if p.get("type") == "image_url"]
            _write_visual_debug_pdf(
                visual_debug_path,
                doc,
                "\n\n".join(text_blocks),
                [],
                image_manifest_lines,
                [u[len("data:image/png;base64,"):] if u.startswith("data:image") else u for u in image_parts],
                raw_page_texts=page_texts,
            )
            logging.info("Wrote visual debug PDF: %s", visual_debug_path)
        except Exception as _e:
            logging.warning("Failed to write visual debug PDF '%s': %s", visual_debug_path, _e)

    if dry_run:
        # Skip any actual AI request when visual-debug is active (or model missing)
        return None, {"cost": 0.0, "dry_run": True, "skipped_reason": ("visual_debug" if visual_debug_path else "no_model")}

    try:
        try:
            temp_str = config.get('AI', 'combined_temperature', fallback='1')
            temperature = float(temp_str)
        except Exception:
            temperature = 1.0
        answer, usage = run_vision(model, prompt="", images_b64=[], temperature=temperature, parts=parts)
        return _json_guard(answer), usage
    except Exception as e:
        logging.warning(f"Combined analysis failed: {e}")
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
