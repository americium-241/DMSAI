# DMSAI API Reference

The DMSAI API gateway exposes a full REST API at **http://localhost:8080**.

Interactive documentation (try it live): **http://localhost:8080/docs** (Swagger UI)  
Clean reference: **http://localhost:8080/redoc**

---

## Authentication

All endpoints except `/api/auth/login`, `/api/auth/register`, and `/api/pipeline/health` require a **Bearer token**.

### Login

```http
POST /api/auth/login
Content-Type: application/json

{"email": "admin@dmsai.com", "password": "admin123"}
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

Use the token in all subsequent requests:
```
Authorization: Bearer eyJ...
```

### Register

```http
POST /api/auth/register
Content-Type: application/json

{"email": "user@example.com", "password": "secure123", "full_name": "Jane Doe"}
```

Email verification is triggered if SMTP is configured (see [configuration.md](configuration.md)).

### Current user

```http
GET /api/auth/me
Authorization: Bearer {token}
```

---

## Documents

### Upload a document

```http
POST /api/upload
Authorization: Bearer {token}
Content-Type: multipart/form-data

file=<binary>
priority=0        (optional, integer)
mode=auto         (optional: "auto" | "manual")
```

Response:
```json
{
  "status": "Accepted",
  "document_id": "d1b2c3...",
  "mode": "auto"
}
```

The document enters the pipeline immediately. Poll `GET /api/documents/{id}` until `status == "COMPLETED"`.

**Example (curl):**
```bash
curl -X POST http://localhost:8080/api/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@invoice.pdf"
```

**Example (Python requests):**
```python
import requests

token = requests.post("http://localhost:8080/api/auth/login",
    json={"email": "admin@dmsai.com", "password": "admin123"}
).json()["access_token"]

headers = {"Authorization": f"Bearer {token}"}

with open("invoice.pdf", "rb") as f:
    resp = requests.post("http://localhost:8080/api/upload",
        headers=headers, files={"file": f})
doc_id = resp.json()["document_id"]
```

---

### List documents

```http
GET /api/documents
Authorization: Bearer {token}

Query parameters:
  status         Filter by status (PENDING, COMPLETED, FAILED, …)
  classification Filter by classification label
  search         Free-text search across OCR + fields + entities
  entity_id      Filter documents containing a specific entity
  page           Page number (default 1)
  page_size      Items per page (default 20, max 100)
```

---

### Get document detail

```http
GET /api/documents/{document_id}
Authorization: Bearer {token}
```

Response includes:
```json
{
  "id": "d1b2c3...",
  "filename": "invoice.pdf",
  "status": "COMPLETED",
  "classification_label": "invoice",
  "classification_subcategory": "purchase",
  "classification_confidence": 0.97,
  "ocr_text": "INVOICE\nDate: 2024-01-15\n...",
  "confidence": 0.89,
  "confidence_details": { "ocr": 0.91, "classification": 0.97, "entity": 0.80 },
  "pdf_url": "/api/documents/d1b2c3.../pdf",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:31:05Z"
}
```

---

### Get extracted fields

```http
GET /api/documents/{document_id}/fields
Authorization: Bearer {token}
```

Response:
```json
[
  {
    "id": "f1a2b3...",
    "field_name": "invoice_number",
    "field_value": "INV-2024-0042",
    "confidence": 0.95,
    "confidence_details": { "source_snippet": "Invoice No. INV-2024-0042" }
  },
  {
    "id": "f4c5d6...",
    "field_name": "total_amount",
    "field_value": "1250.00",
    "confidence": 0.92
  }
]
```

---

### Get document entities

```http
GET /api/documents/{document_id}/entities
Authorization: Bearer {token}
```

Response:
```json
[
  {
    "link_id": "l1...",
    "entity_id": "e1a2...",
    "entity_name": "Acme Corp",
    "entity_type": "company",
    "role": "vendor",
    "confidence": 0.88
  }
]
```

---

### Download the normalized PDF

```http
GET /api/documents/{document_id}/pdf
Authorization: Bearer {token}
```

Returns the PDF file as `application/pdf`.

```bash
curl -L -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/documents/$DOC_ID/pdf -o document.pdf
```

---

### Full-text search

```http
GET /api/search?q=invoice+2024&page=1&page_size=20
Authorization: Bearer {token}
```

Searches across: OCR text, classification labels, field values, entity names.

---

### Update a document (metadata)

```http
PUT /api/documents/{document_id}
Authorization: Bearer {token}
Content-Type: application/json

{
  "classification_label": "contract",
  "classification_subcategory": "employment",
  "notes": "Manually corrected"
}
```

---

### Create / update / delete a field

```http
POST   /api/documents/{document_id}/fields
PUT    /api/documents/{document_id}/fields/{field_id}
DELETE /api/documents/{document_id}/fields/{field_id}
```

---

### Document events (processing log)

```http
GET /api/documents/{document_id}/events
Authorization: Bearer {token}
```

Returns a list of pipeline events (OCR done, entity extracted, classified, etc.) with timestamps and any error messages.

**Streaming (SSE):**
```http
GET /api/documents/{document_id}/events/stream
Authorization: Bearer {token}
```

---

### Document lifecycle

```http
# Archive / unarchive
PUT /api/documents/{document_id}        body: {"archived": true}

# Toggle workflow state
POST /api/documents/{document_id}/toggle-state

# Lock / unlock
POST /api/documents/{document_id}/auto-lock
POST /api/documents/{document_id}/auto-unlock
```

---

## Buckets

### List buckets

```http
GET /api/buckets
Authorization: Bearer {token}
```

### Create a bucket

```http
POST /api/buckets
Authorization: Bearer {token}  (manager or admin role)
Content-Type: application/json

{
  "name": "Invoices to review",
  "description": "Purchase invoices awaiting approval"
}
```

### List documents in a bucket

```http
GET /api/buckets/{bucket_id}/documents
Authorization: Bearer {token}

Query: state, page, page_size
```

### Bucket rules

```http
GET    /api/buckets/{bucket_id}/rules
POST   /api/buckets/{bucket_id}/rules
DELETE /api/buckets/{bucket_id}/rules/{rule_id}
```

Rule body example:
```json
{
  "condition_type": "classification",
  "condition_value": "invoice",
  "operator": "eq"
}
```

Supported `condition_type` values: `classification`, `subcategory`, `field_value`, `entity_name`, `confidence_gt`, `confidence_lt`, `ocr_contains`.

---

## Admin

### Quality metrics

```http
GET /api/admin/quality-metrics
Authorization: Bearer {token}  (manager+)
```

Returns average confidence scores, processing times, and per-stage statistics.

### Entities catalogue

```http
GET    /api/admin/entities               List entities (filterable by type, name, search)
GET    /api/admin/entities/{entity_id}   Entity detail
POST   /api/admin/entities/merge         Merge two entities
GET    /api/admin/entity-types           List distinct entity types
```

### Canonical document classes

```http
GET    /api/admin/canonical-document-classes
POST   /api/admin/canonical-document-classes
PUT    /api/admin/canonical-document-classes/{class_id}
```

### Canonical fields

```http
GET    /api/admin/canonical-fields
POST   /api/admin/canonical-fields
PUT    /api/admin/canonical-fields/{cf_id}
DELETE /api/admin/canonical-fields/{cf_id}
```

### System configuration

```http
GET /api/admin/system-config              List all config keys
GET /api/admin/system-config/{key}        Get one key
PUT /api/admin/system-config/{key}        Update (admin only)
```

### Service restart

```http
POST /api/admin/services/restart
Authorization: Bearer {token}  (admin only)
Content-Type: application/json

{"services": ["ocr", "classification"]}
```

---

## Pipeline health (no auth)

```http
GET /api/pipeline/health
```

Returns the health status of every pipeline node — safe to use as a readiness probe.

```json
{
  "ingestion":  {"status": "healthy"},
  "ocr":        {"status": "healthy", "queue_depth": 0},
  "classification": {"status": "healthy"}
}
```

---

## Dashboard

```http
GET /api/dashboard        Aggregated stats (document counts, confidence averages)
GET /api/activity/recent  Recent activity feed
```

---

## Error responses

All errors follow the standard FastAPI format:

```json
{"detail": "Document not found"}
```

| Code | Meaning |
|---|---|
| 401 | Missing or invalid Bearer token |
| 403 | Insufficient role (requires admin / manager) |
| 404 | Resource not found |
| 422 | Validation error (check request body) |
| 500 | Internal server error — check gateway logs |
