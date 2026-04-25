import io
import base64
from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}


def convert_image_to_pdf(image_bytes: bytes) -> bytes:
    """Convert raw image bytes (PNG, JPEG, TIFF, BMP) to a single-page PDF."""
    img = Image.open(io.BytesIO(image_bytes))

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=300)
    return buf.getvalue()


async def process_document(payload: dict) -> dict:
    """Convert the document to PDF if it isn't one already."""
    from dmsai_models import record_pipeline_event

    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "conversion", "started")
    ext = payload["original_extension"].lower()
    file_bytes_b64 = payload["file_bytes"]
    raw_bytes = base64.b64decode(file_bytes_b64)

    if ext in IMAGE_EXTENSIONS:
        pdf_bytes = convert_image_to_pdf(raw_bytes)
    elif ext == ".pdf":
        pdf_bytes = raw_bytes
    else:
        raise ValueError(f"Unsupported format for conversion: {ext}")

    payload["file_bytes"] = base64.b64encode(pdf_bytes).decode()
    payload["unified_extension"] = ".pdf"
    payload["history"] = payload.get("history", []) + ["conversion_completed"]
    if doc_id:
        record_pipeline_event(doc_id, "conversion", "completed")
    return payload
