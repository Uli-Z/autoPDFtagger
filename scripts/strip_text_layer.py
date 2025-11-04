#!/usr/bin/env python3
"""
Rasterize PDFs to remove selectable/embedded text layers, leaving only images.
Usage: python scripts/strip_text_layer.py testfiles/invoice1-scan*.pdf
"""
import sys
import os
import glob
import fitz  # PyMuPDF

def strip_text_layer(pdf_path: str, dpi: int = 200) -> None:
    src = fitz.open(pdf_path)
    out = fitz.open()
    try:
        for page in src:
            pix = page.get_pixmap(dpi=dpi)
            # Create target page with same size as source
            tp = out.new_page(width=page.rect.width, height=page.rect.height)
            # Insert rendered image scaled to page, keep aspect
            rect = tp.rect
            tp.insert_image(rect, stream=pix.tobytes("png"), keep_proportion=True)
        # Write to temp file then replace original
        tmp_path = pdf_path + ".tmp"
        out.save(tmp_path)
        out.close()
        src.close()
        os.replace(tmp_path, pdf_path)
    finally:
        try:
            out.close()
        except Exception:
            pass
        try:
            src.close()
        except Exception:
            pass

def main():
    if len(sys.argv) < 2:
        print("Usage: strip_text_layer.py <files...>")
        sys.exit(2)
    # Expand globs ourselves for portability
    paths = []
    for arg in sys.argv[1:]:
        paths.extend(glob.glob(arg))
    if not paths:
        print("No matching files.")
        sys.exit(1)
    for p in paths:
        print(f"Stripping text layer: {p}")
        strip_text_layer(p)
    print("Done.")

if __name__ == "__main__":
    main()

