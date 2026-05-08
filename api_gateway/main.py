import os

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dmsai_models import init_db

init_db()

_DESCRIPTION = """
DMSAI is a self-hosted AI document management system.
Upload a document and the pipeline automatically extracts text (OCR), classifies it,
resolves named entities, and extracts structured fields — all powered by a local or
cloud LLM.

## Quick links

| URL | Purpose |
|-----|---------|
| `http://localhost:5173` | Web UI |
| `http://localhost:8080/docs` | **This page** (Swagger UI) |
| `http://localhost:8080/redoc` | ReDoc reference |
| `http://localhost:8080/api/pipeline/health` | Pipeline health check (no auth) |

## Authentication

All endpoints (except `/api/auth/login`, `/api/auth/register`, and `/api/pipeline/health`)
require a **Bearer token**.

```
POST /api/auth/login
{ "email": "admin@dmsai.com", "password": "admin123" }
→ { "access_token": "eyJ..." }

Authorization: Bearer eyJ...
```

## Typical workflow

1. `POST /api/upload` — upload a document
2. `GET /api/pipeline/health` — confirm pipeline is healthy
3. `GET /api/documents/{id}` — poll until `status == "COMPLETED"`
4. `GET /api/documents/{id}/fields` — read extracted fields
5. `GET /api/documents/{id}/entities` — read resolved entities
6. `GET /api/documents/{id}/pdf` — download the normalized PDF
"""

_TAGS = [
    {
        "name": "auth",
        "description": "Login, register, email verification, and current-user endpoints.",
    },
    {
        "name": "users",
        "description": "User and organization management (admin/manager roles).",
    },
    {
        "name": "documents",
        "description": (
            "Upload, search, and read documents. "
            "Each document carries OCR text, classification labels, confidence scores, "
            "extracted fields, and linked entities."
        ),
    },
    {
        "name": "buckets",
        "description": (
            "Buckets are rule-based document collections. "
            "Rules can match on classification label, field values, entity names, "
            "confidence thresholds, or OCR content."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Entity catalogue, canonical fields and document classes, system configuration, "
            "quality metrics, and service restart controls."
        ),
    },
    {
        "name": "dashboard",
        "description": "Aggregated statistics and recent activity feed.",
    },
    {
        "name": "archive",
        "description": (
            "Document lifecycle: archive, trash, restore, permanent deletion, "
            "storage compaction, and version snapshots."
        ),
    },
    {
        "name": "collaboration",
        "description": "Threaded notes and comments on documents and entities.",
    },
    {
        "name": "pipeline",
        "description": "Pipeline health check across all processing nodes.",
    },
]

app = FastAPI(
    title="DMSAI API",
    version="0.3.0",
    description=_DESCRIPTION,
    openapi_tags=_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "DMSAI",
        "url": "https://github.com/americium-241/DMSAI",
    },
    license_info={
        "name": "See repository for license details",
        "url": "https://github.com/americium-241/DMSAI",
    },
)

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
from routers.collaboration import router as collaboration_router
from routers.archive import router as archive_router
from routers.setup import router as setup_router

app.include_router(setup_router)   # public — no auth required
app.include_router(users_router)
app.include_router(documents_router)
app.include_router(buckets_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(collaboration_router)
app.include_router(archive_router)

# ---------------------------------------------------------------------------
# Pipeline health (no auth needed for diagnostics)
# ---------------------------------------------------------------------------

NODE_URLS = {
    "ingestion": os.environ.get("INGESTION_NODE_URL", "http://localhost:8010"),
    "conversion": os.environ.get("CONVERSION_NODE_URL", "http://localhost:8011"),
    "storage": os.environ.get("STORAGE_NODE_URL", "http://localhost:8012"),
    "ocr": os.environ.get("OCR_NODE_URL", "http://localhost:8013"),
    "entity_extraction": os.environ.get("ENTITY_EXTRACTION_NODE_URL", "http://localhost:8015"),
    "classification": os.environ.get("CLASSIFICATION_NODE_URL", "http://localhost:8016"),
    "entity_resolution": os.environ.get("ENTITY_RESOLUTION_NODE_URL", "http://localhost:8017"),
    "field_extraction": os.environ.get("FIELD_EXTRACTION_NODE_URL", "http://localhost:8018"),
}


@app.get(
    "/api/pipeline/health",
    tags=["pipeline"],
    summary="Pipeline health",
    description=(
        "Returns the health of every pipeline node including queue depths and peer connectivity. "
        "No authentication required — safe to use as a readiness probe."
    ),
)
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
