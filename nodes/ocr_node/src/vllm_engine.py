import base64
import logging
from typing import Optional

import fitz  # PyMuPDF

from dmsai_models.llm import call_vision_llm

logger = logging.getLogger("ocr_node.vllm")


def pdf_pages_to_base64_images(pdf_bytes: bytes, dpi: int = 200) -> list[str]:
    """Render each page of a PDF to a PNG image and return as base64 strings."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images_b64 = []
    for page in doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        png_bytes = pix.tobytes("png")
        images_b64.append(base64.b64encode(png_bytes).decode())
    doc.close()
    return images_b64


async def run_vision_llm(pdf_bytes: bytes, document_id: Optional[str] = None) -> str:
    """
    Send each page of the PDF as an image to a Vision LLM
    (Ollama or LiteLLM, based on SystemConfig) and concatenate the text.
    """
    page_images = pdf_pages_to_base64_images(pdf_bytes)
    all_text_parts: list[str] = []

    for i, img_b64 in enumerate(page_images):
        try:
            text = await call_vision_llm(img_b64, stage="ocr", document_id=document_id)
            all_text_parts.append(text.strip())
            logger.info(f"Vision LLM OCR page {i+1}/{len(page_images)}: {len(text)} chars")
        except Exception as e:
            logger.error(f"Vision LLM OCR failed on page {i+1}: {e}")
            all_text_parts.append("")

    return "\n\n".join(all_text_parts)
