#!/usr/bin/env python3
"""
pdf_markdown_with_images.py

Create a Markdown rendition of a PDF that includes extracted text and image links.
Relies on pdfminer.six (the maintained Python 3 fork) for parsing.

Notes:
- OCR is not performed. Only embedded text is extracted.
- Images are exported when encodings are directly saveable (e.g., DCTDecode/JPEG, JPXDecode/JP2, CCITTFax/TIFF).
  Other encodings are dumped as .bin files unless additional processing is implemented.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple, Union

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTImage, LTFigure, LTTextContainer, LAParams


@dataclass
class Element:
    kind: str  # "text" | "image"
    page: int
    bbox: Tuple[float, float, float, float]
    text: Optional[str] = None
    image_path: Optional[str] = None


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _filter_name(filter_value: Union[str, list, object, None]) -> Optional[str]:
    if filter_value is None:
        return None
    if isinstance(filter_value, list) and len(filter_value) > 0:
        return _filter_name(filter_value[0])
    if isinstance(filter_value, bytes):
        try:
            return filter_value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    return str(filter_value)


def _image_ext_from_filter(filter_name: Optional[str]) -> str:
    if not filter_name:
        return ".bin"
    name = str(filter_name)
    if "DCTDecode" in name:
        return ".jpg"
    if "JPXDecode" in name:
        return ".jp2"
    if "CCITTFaxDecode" in name:
        return ".tiff"
    # FlateDecode and others are not trivially saveable without reconstruction
    return ".bin"


def _save_image(obj: LTImage, out_dir: str, base: str, page: int, idx: int) -> str:
    stream = getattr(obj, "stream", None)
    if stream is None:
        filename = f"{base}_p{page}_img{idx}.bin"
        out_path = os.path.join(out_dir, filename)
        with open(out_path, "wb") as fh:
            fh.write(b"")
        return out_path

    attrs = getattr(stream, "attrs", {}) or {}
    filter_name = _filter_name(attrs.get("Filter"))
    ext = _image_ext_from_filter(filter_name)
    filename = f"{base}_p{page}_img{idx}{ext}"
    out_path = os.path.join(out_dir, filename)

    get_raw = getattr(stream, "get_rawdata", None)
    get_data = getattr(stream, "get_data", None)
    data = None
    if callable(get_raw):
        try:
            data = get_raw()
        except Exception:
            data = None
    if data is None and callable(get_data):
        try:
            data = get_data()
        except Exception:
            data = None
    if data is None:
        data = b""

    with open(out_path, "wb") as fh:
        fh.write(data)
    return out_path


def _iter_layout(obj) -> Iterable[object]:
    if hasattr(obj, "_objs") and isinstance(getattr(obj, "_objs"), list):
        for o in obj._objs:  # type: ignore[attr-defined]
            yield o


def _collect_elements(layout, page_number: int, images_dir: str, base: str) -> List[Element]:
    elements: List[Element] = []
    img_counter = 0

    stack = list(_iter_layout(layout))
    while stack:
        obj = stack.pop(0)

        if isinstance(obj, LTTextContainer):
            text = obj.get_text() or ""
            text = text.strip("\n")
            if text.strip():
                elements.append(
                    Element(kind="text", page=page_number, bbox=obj.bbox, text=text)
                )
        elif isinstance(obj, LTImage):
            img_counter += 1
            out_path = _save_image(obj, images_dir, base, page_number, img_counter)
            elements.append(
                Element(kind="image", page=page_number, bbox=obj.bbox, image_path=out_path)
            )
        elif isinstance(obj, LTFigure):
            # Descend into figure contents
            stack[0:0] = list(_iter_layout(obj))
        else:
            # Generic container or other layout object: descend if possible
            stack[0:0] = list(_iter_layout(obj))

    # Sort top-to-bottom (y1 desc), then left-to-right (x0 asc)
    elements.sort(key=lambda e: (-e.bbox[3], e.bbox[0]))
    return elements


def pdf_to_markdown(
    pdf_path: str,
    images_dir: str,
    title: Optional[str] = None,
    laparams: Optional[LAParams] = None,
) -> str:
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    _ensure_dir(images_dir)

    if laparams is None:
        laparams = LAParams()

    md_lines: List[str] = []
    if title:
        md_lines.append(f"# {title}")
        md_lines.append("")

    for page_no, layout in enumerate(extract_pages(pdf_path, laparams=laparams), start=1):
        md_lines.append(f"\n## Page {page_no}")
        elements = _collect_elements(layout, page_no, images_dir, base)
        for el in elements:
            if el.kind == "text" and el.text:
                md_lines.append(el.text)
            elif el.kind == "image" and el.image_path:
                rel_path = os.path.relpath(el.image_path, start=os.path.dirname(os.path.abspath(images_dir)) or ".")
                alt = f"{base} p{el.page} image"
                md_lines.append(f"![{alt}]({rel_path.replace(os.sep, '/')})")

    return "\n\n".join(md_lines).strip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="PDF → Markdown with extracted images (pdfminer.six)")
    p.add_argument("pdf", help="Input PDF path")
    p.add_argument("-o", "--output", help="Output Markdown file (default: stdout)")
    p.add_argument(
        "-I",
        "--images-dir",
        default=None,
        help="Directory to write extracted images (default: <pdf_dir>/<pdf_stem>_images)",
    )
    p.add_argument("--title", default=None, help="Optional title for the Markdown document")
    args = p.parse_args(argv)

    pdf_path = os.path.abspath(args.pdf)
    if not os.path.isfile(pdf_path):
        print(f"Input not found: {args.pdf}", file=sys.stderr)
        return 2

    if args.images_dir:
        images_dir = args.images_dir
        if not os.path.isabs(images_dir):
            images_dir = os.path.abspath(images_dir)
    else:
        pdf_dir = os.path.dirname(pdf_path)
        pdf_stem = os.path.splitext(os.path.basename(pdf_path))[0]
        images_dir = os.path.join(pdf_dir, f"{pdf_stem}_images")

    md = pdf_to_markdown(pdf_path, images_dir=images_dir, title=args.title)

    if args.output:
        out_path = os.path.abspath(args.output)
        out_dir = os.path.dirname(out_path)
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(md)
    else:
        sys.stdout.write(md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

