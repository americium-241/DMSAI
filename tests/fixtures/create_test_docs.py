"""
Generates minimal synthetic test documents in example_docs/.

Uses only Pillow (already a project dependency) to produce:
  - invoice_sample.pdf   – a single-page PDF containing invoice-like text
  - invoice_sample.jpg   – a JPEG version of the same image

Pillow can serialise an RGB Image directly to PDF, which produces a
valid PDF that PyMuPDF / Fitz can open and rasterise for OCR.
"""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent


def _draw_text_on_image(img, text: str, x: int, y: int, color=(0, 0, 0)):
    """Naive bitmap font: draw each character as a 5×7 pixel dot grid."""
    px = img.load()
    col = 0
    row = 0
    for ch in text:
        if ch == "\n":
            col = 0
            row += 1
            continue
        cx = x + col * 7
        cy = y + row * 10
        for dy in range(6):
            for dx in range(5):
                nx = cx + dx
                ny = cy + dy
                w, h = img.size
                if 0 <= nx < w and 0 <= ny < h:
                    if dy in (0, 5) or dx in (0, 4):
                        px[nx, ny] = color
        col += 1
        if col > 60:
            col = 0
            row += 1


def create_test_jpeg(dest: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 800, 1000
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    invoice_text = dedent("""\
        INVOICE

        Invoice Number: INV-2026-001
        Date:           2026-04-15
        Due Date:       2026-05-15

        From:
          ACME Corporation
          12 Rue de la Paix, 75002 Paris
          Tax ID: FR12345678901
          Email:  contact@acme-corp.fr

        To:
          John Doe
          john.doe@example.com

        Description                  Qty   Unit Price   Total
        ---------------------------------------------------------
        Software Development Service  1     1000.00      1000.00
        Consulting                    1      200.00       200.00
        ---------------------------------------------------------
        Subtotal                                         1000.00
        Tax (20%)                                         200.00
        Total Amount:                                    1200.00

        Payment Terms: Net 30
        Bank: IBAN FR76 1234 5678 9012 3456 7890 123
    """)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    y = 40
    for line in invoice_text.splitlines():
        draw.text((40, y), line, fill=(0, 0, 0), font=font)
        y += 20

    img.save(str(dest), "JPEG", quality=95)


def create_test_pdf(dest: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 612, 792
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    invoice_text = dedent("""\
        INVOICE  INV-2026-001

        ACME Corporation — Tax ID FR12345678901
        12 Rue de la Paix, 75002 Paris
        contact@acme-corp.fr

        To: John Doe  john.doe@example.com

        Date: 2026-04-15   Due: 2026-05-15

        Software Development Service   1000.00
        Consulting                      200.00
        Tax (20%)                       200.00
        Total Amount:                  1200.00

        Payment Terms: Net 30
    """)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    y = 40
    for line in invoice_text.splitlines():
        draw.text((40, y), line, fill=(0, 0, 0), font=font)
        y += 24

    img.save(str(dest), "PDF", resolution=72)


def ensure_example_docs(example_docs_dir: Path) -> None:
    """Create synthetic example documents if the directory is empty."""
    example_docs_dir.mkdir(parents=True, exist_ok=True)

    existing = [
        p for p in example_docs_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".pdf", ".tiff", ".bmp"}
    ]
    if existing:
        return

    create_test_jpeg(example_docs_dir / "invoice_sample.jpg")
    create_test_pdf(example_docs_dir / "invoice_sample.pdf")
