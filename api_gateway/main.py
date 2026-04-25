import os

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dmsai_models import init_db

init_db()

app = FastAPI(title="DMSAI API Gateway", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

from routers.users import router as users_router
from routers.documents import router as documents_router
from routers.buckets import router as buckets_router
from routers.dashboard import router as dashboard_router
from routers.admin import router as admin_router

app.include_router(users_router)
app.include_router(documents_router)
app.include_router(buckets_router)
app.include_router(dashboard_router)
app.include_router(admin_router)

# ---------------------------------------------------------------------------
# Pipeline health (no auth needed for diagnostics)
# ---------------------------------------------------------------------------

NODE_URLS = {
    "ingestion": os.environ.get("INGESTION_NODE_URL", "http://localhost:8010"),
    "conversion": os.environ.get("CONVERSION_NODE_URL", "http://localhost:8011"),
    "storage": os.environ.get("STORAGE_NODE_URL", "http://localhost:8012"),
    "ocr": os.environ.get("OCR_NODE_URL", "http://localhost:8013"),
    "embedding": os.environ.get("EMBEDDING_NODE_URL", "http://localhost:8014"),
    "entity_extraction": os.environ.get("ENTITY_EXTRACTION_NODE_URL", "http://localhost:8015"),
    "classification": os.environ.get("CLASSIFICATION_NODE_URL", "http://localhost:8016"),
    "entity_resolution": os.environ.get("ENTITY_RESOLUTION_NODE_URL", "http://localhost:8017"),
    "field_extraction": os.environ.get("FIELD_EXTRACTION_NODE_URL", "http://localhost:8018"),
}


@app.get("/api/pipeline/health")
async def pipeline_health():
    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in NODE_URLS.items():
            try:
                resp = await client.get(f"{url}/health")
                results[name] = resp.json() if resp.status_code == 200 else {"status": "unhealthy"}
            except Exception:
                results[name] = {"status": "unreachable"}
    return results
