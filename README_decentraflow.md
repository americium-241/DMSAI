# DecentraFlow

**A brokerless, decentralized microservice framework for AI/ML pipelines in Python.**

Each node is a fully autonomous service with its own persistent queue, crash recovery, and HTTP mesh networking — no central broker, no central scheduler, no shared database.

```
┌─────────────┐    HTTP/JSON    ┌─────────────┐    HTTP/JSON    ┌─────────────┐
│  OCR Node   │ ──────────────> │  LLM Node   │ ──────────────> │ Output Node │
│ (port 8000) │                 │ (port 8001) │                 │ (port 8003) │
│  [SQLite]   │                 │  [SQLite]   │                 │  [SQLite]   │
└─────────────┘                 └─────────────┘                 └─────────────┘
       │                               │                               │
       └───────────────────────────────┴───────────────────────────────┘
                                       │
                              Promtail ─┘  (scrapes JSON log files)
                              Loki         (aggregation)
                              Grafana      (visualization + dashboards)
```

---

## Table of Contents

- [Architecture](#architecture)
- [Core Framework (`decentraflow`)](#core-framework)
  - [NodeBlueprint](#nodeblueprint)
  - [Task Model](#task-model)
  - [JsonFormatter](#jsonformatter)
  - [MetricsCollector](#metricscollector)
- [Built-in Endpoints](#built-in-endpoints)
- [Resilience Features](#resilience-features)
  - [Retries with Exponential Backoff](#retries-with-exponential-backoff)
  - [Dead Letter Queue](#dead-letter-queue)
  - [Backpressure](#backpressure)
  - [Schema Validation](#schema-validation)
  - [Concurrent Worker Pool](#concurrent-worker-pool)
  - [Health Mesh](#health-mesh)
- [Production Hardening (Tier 1)](#production-hardening-tier-1)
  - [Stale Task Recovery](#stale-task-recovery)
  - [Task Processing Timeout](#task-processing-timeout)
  - [Graceful Shutdown](#graceful-shutdown)
  - [Forwarding Failure Handling](#forwarding-failure-handling)
  - [Database Cleanup / TTL](#database-cleanup--ttl)
  - [API Key Authentication](#api-key-authentication)
- [Operational Maturity (Tier 2)](#operational-maturity-tier-2)
  - [Task Lookup by ID](#task-lookup-by-id)
  - [Prometheus Metrics Endpoint](#prometheus-metrics-endpoint)
  - [Lifecycle Hooks](#lifecycle-hooks)
  - [Content-Based Routing](#content-based-routing)
  - [Task Priority](#task-priority)
  - [Decentralized Logging](#decentralized-logging)
- [Configuration](#configuration)
- [Node Implementations](#node-implementations)
  - [OCR Node (Pipeline)](#ocr-node-pipeline)
  - [OCR Tool Node (Synchronous)](#ocr-tool-node-synchronous)
  - [Open WebUI Tool](#open-webui-tool)
- [Infrastructure Stack](#infrastructure-stack)
- [Test Suite](#test-suite)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)

---

## Architecture

DecentraFlow is built on a **brokerless peer-to-peer** philosophy. Every node:

| Principle | Implementation |
|---|---|
| **Fully autonomous** | Each node has its own SQLite queue, config, logs — survives independently |
| **No central broker** | Nodes communicate via HTTP POST, discovered through YAML routing |
| **Crash-safe** | SQLite persistence means tasks survive restarts and crashes |
| **Pluggable logic** | You supply an `async process_func(payload) -> payload` — the framework handles everything else |
| **YAML-routed mesh** | Rewire the pipeline by editing `routing.yaml` — no code changes |
| **Observable** | Structured JSON logs (scraped by Promtail → Loki), Prometheus /metrics, health endpoints |
| **Zero push dependencies** | Logs and metrics are served locally — external systems pull, nodes never push |

---

## Core Framework

The `decentraflow` package lives in `core_framework/` and is installed as a pip-editable package:

```bash
pip install -e core_framework/
```

### NodeBlueprint

The single class that bootstraps an entire microservice. Three lines of code creates a production-ready node:

```python
from decentraflow import NodeBlueprint
from src.my_logic import process_document

node = NodeBlueprint(
    node_name="my_node",
    process_func=process_document,
)
app = node.app  # FastAPI instance — run with: uvicorn main:app --port 8000
```

**What you get automatically:**

- FastAPI HTTP server with `/ingest`, `/health`, `/task/{id}`, `/dead-letter`, `/peers`, `/metrics`
- Local SQLite persistent queue with idempotent task deduplication
- Structured JSON logging (Promtail-ready, no push dependency)
- Configurable concurrent worker pool
- Exponential backoff retries with dead letter queue
- Backpressure (HTTP 429 when queue is full)
- Optional Pydantic payload schema validation
- Mesh health monitoring of downstream peers
- Task processing timeout (prevents worker starvation)
- Graceful shutdown with in-flight task drain
- Stale task recovery on startup (crash-safe restart)
- Forwarding failure triggers task retry (no silent data loss)
- Automatic database cleanup (TTL-based purging)
- Optional API key authentication (shared mesh secret)
- Lifecycle hooks (before_process, after_process, on_failure)
- Content-based routing via routing_func
- Task priority (higher priority = processed first)
- Zero-dependency Prometheus /metrics endpoint

**Constructor parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `node_name` | `str` | *required* | Unique name for logging and identification |
| `process_func` | `async (dict) -> dict` | *required* | Your AI/ML processing logic |
| `config_dir` | `str` | `"config"` | Path to directory containing `routing.yaml` |
| `log_dir` | `str` | `"logs"` | Path to directory for rotating log files |
| `payload_schema` | `Type[BaseModel]` | `None` | Optional Pydantic model for payload validation |
| `db_url` | `str` | `"sqlite:///internal_queue.db"` | SQLite database URL |
| `routing_func` | `Callable` | `None` | Optional content-based routing function |

### Task Model

Each task flows through a defined lifecycle inside the node's local SQLite database:

```
PENDING ──> PROCESSING ──> COMPLETED
                │
                ├──> PENDING (retry with exponential backoff)
                │
                └──> DEAD_LETTER (max retries exhausted)
```

**Task fields:**

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Primary key — the `workflow_id` from the payload |
| `payload` | `str` | JSON-serialized task payload (enriched after processing) |
| `status` | `str` | `PENDING` / `PROCESSING` / `COMPLETED` / `DEAD_LETTER` |
| `priority` | `int` | Task priority (0 = normal, higher = more urgent) |
| `retry_count` | `int` | Number of failed processing attempts |
| `next_retry_at` | `datetime?` | When the task becomes eligible for retry |
| `error_message` | `str?` | Last error message (preserved for dead letters) |
| `created_at` | `datetime` | Timestamp when the task was ingested |
| `processed_at` | `datetime?` | Timestamp when the task completed successfully |
| `started_processing_at` | `datetime?` | Timestamp when a worker started processing (for timeout/stale detection) |

### JsonFormatter

A structured JSON log formatter that outputs machine-parseable log lines:

```json
{"timestamp":"2024-01-01T12:00:00.123Z","level":"INFO","service":"ocr_node","environment":"prod","message":"Task xyz queued."}
```

- **Local files are the source of truth** — no push dependency on any external system
- **Machine-parseable** — Promtail/Alloy/Fluentd can scrape and extract labels
- **Structured correlation** — includes `workflow_id` when present
- **Rotating files** — 5MB per file, 3 backups (via `RotatingFileHandler`)

### MetricsCollector

A lightweight, zero-dependency Prometheus metrics collector:

- **Counters**: tasks_ingested, completed, failed, dead_letter, timeout, forwarded, retried
- **Gauges**: queue_pending, queue_processing, queue_dead_letter (live from DB)
- **Histograms**: processing_duration_seconds (with standard Prometheus buckets)
- **Thread-safe** via `threading.Lock`
- Rendered at `GET /metrics` in Prometheus exposition text format

---

## Built-in Endpoints

Every node created with `NodeBlueprint` exposes these HTTP endpoints:

| Method | Path | Status | Description |
|---|---|---|---|
| `POST` | `/ingest` | `202` | Accept a task into the local queue (with backpressure + validation + priority) |
| `GET` | `/health` | `200` | Node health, queue stats (pending/processing/dead), peer status |
| `GET` | `/task/{id}` | `200` | Inspect a specific task's full details (status, payload, error, timestamps) |
| `GET` | `/dead-letter` | `200` | List all permanently failed tasks |
| `POST` | `/dead-letter/{id}/retry` | `200` | Manually re-queue a dead-lettered task |
| `GET` | `/peers` | `200` | Live downstream peer health map |
| `GET` | `/metrics` | `200` | Prometheus exposition format metrics |

Nodes can add **custom endpoints** on top of the blueprint:

```python
@node.app.post("/ocr")
async def my_custom_endpoint(request: MyRequest):
    ...
```

---

## Resilience Features

### Retries with Exponential Backoff

When `process_func` raises an exception, the task is **not permanently failed**. Instead:

1. `retry_count` is incremented
2. A backoff delay is calculated: `backoff_base × 2^(retry_count - 1)`
3. `next_retry_at` is set in SQLite — the worker skips tasks whose retry time hasn't arrived
4. Status goes back to `PENDING`

With default `backoff_base: 2.0` and `max_retries: 3`:

| Attempt | Delay | Total elapsed |
|---|---|---|
| 1st failure | 2s | 2s |
| 2nd failure | 4s | 6s |
| 3rd failure | → DEAD_LETTER | — |

**Crash-safe**: the `next_retry_at` timestamp is persisted in SQLite, so backoff continues correctly after a restart.

### Dead Letter Queue

After `max_retries` is exhausted, the task moves to `DEAD_LETTER` status. Dead letters:

- Are **never picked up** by workers
- Are **inspectable** via `GET /dead-letter` (id, error, retry count, timestamp)
- Can be **manually re-queued** via `POST /dead-letter/{id}/retry` (resets retry count to 0)
- Preserve the **last error message** for debugging

### Backpressure

The `/ingest` endpoint counts active tasks (`PENDING` + `PROCESSING`). If the count exceeds `max_queue_depth`, it returns **HTTP 429 Too Many Requests**:

```json
{"detail": "Queue full (1000/1000). Try again later."}
```

The forwarding side is also aware — when a downstream peer returns 429, it's treated as a forwarding failure and the task is retried (not silently dropped).

### Schema Validation

Optionally validate incoming payloads against a Pydantic model **before queuing**:

```python
from pydantic import BaseModel

class OCRPayload(BaseModel):
    workflow_id: str
    file_bytes: str
    filename: str = "unknown"

node = NodeBlueprint(
    node_name="ocr_node",
    process_func=process_document,
    payload_schema=OCRPayload,  # returns 422 on invalid payloads
)
```

If no schema is provided, the node accepts any JSON — fully backward compatible.

### Concurrent Worker Pool

Multiple worker coroutines process tasks in parallel (controlled by `max_workers`). An `asyncio.Lock` prevents multiple workers from grabbing the same task (necessary because SQLite doesn't support row-level locking).

Workers are identified in logs as `[Worker-0]`, `[Worker-1]`, etc.

### Health Mesh

A background coroutine periodically probes `/health` on each downstream peer (every `health_check_interval` seconds). Results are stored in `peer_health`:

- **Healthy peer**: forwarding proceeds normally
- **Unhealthy peer**: automatically skipped during forwarding (no wasted time)
- **Recovered peer**: detected on the next health check cycle

State transitions are logged:
- `Peer DOWN: http://...` — was healthy, now unreachable
- `Peer RECOVERED: http://...` — was down, now responding
- `Skipping unhealthy peer: http://...` — during forwarding

---

## Production Hardening (Tier 1)

Six critical features that make DecentraFlow safe for real workloads. All are **opt-in via `routing.yaml`** with sensible defaults — existing nodes work without config changes.

### Stale Task Recovery

**Problem**: If a node crashes while tasks are in `PROCESSING` status, those tasks are orphaned forever — they're not `PENDING` (so workers won't pick them up) and not `COMPLETED` (so the data is lost).

**Solution**: On startup, `_recover_stale_tasks()` scans for any `PROCESSING` tasks left by a previous crash and resets them to `PENDING`. Workers then pick them up and process them normally.

```
CRASH → Node restarts → _recover_stale_tasks() → PROCESSING → PENDING → Worker picks up → COMPLETED
```

On shutdown, `_rollback_processing_tasks()` does the same for any in-flight tasks that couldn't complete within the drain period.

- **Zero config** — always active, no settings needed
- **Idempotent** — safe to call repeatedly
- **Preserves retry_count** — a crashed task doesn't reset its attempt count

### Task Processing Timeout

**Problem**: If `process_func` hangs (deadlock, infinite loop, stuck network call), the worker coroutine is consumed forever. Eventually all workers are stuck and the node stops processing entirely.

**Solution**: Every `process_func` call is wrapped in `asyncio.wait_for(process_func(payload), timeout=task_timeout)`. If the function exceeds the timeout, it's cancelled and the task enters the normal retry/dead-letter flow.

```yaml
task_timeout: 300  # 5 minutes (default)
```

| Scenario | Behavior |
|---|---|
| Fast task (< timeout) | Normal completion |
| Slow task (> timeout) | `asyncio.TimeoutError` → retry with backoff |
| Repeated timeouts | → `DEAD_LETTER` after `max_retries` |

Error messages include the timeout duration for debugging: `"Task timed out after 300.0s"`.

### Graceful Shutdown

**Problem**: On `SIGTERM` (deploy, restart, scale-down), tasks in-flight are interrupted. Without drain logic, every deployment causes data loss.

**Solution**: Three-phase shutdown:

1. **Stop picking**: `_shutting_down = True` — workers finish their current task but don't pick new ones
2. **Drain period**: Wait up to `shutdown_timeout` seconds for in-flight tasks to complete
3. **Rollback**: Any tasks still `PROCESSING` after the drain period are reset to `PENDING` for the next startup

```yaml
shutdown_timeout: 30  # seconds to wait for in-flight tasks (default)
```

The `_active_tasks` set tracks which task IDs are currently being processed, so the drain loop knows exactly when all work is done.

### Forwarding Failure Handling

**Problem**: A task's `process_func` succeeds (e.g., OCR extraction completes), but forwarding to the downstream peer fails (network error, peer down, 429 backpressure). In the old behavior, the task was marked `COMPLETED` even though the result never reached the next node — **silent data loss**.

**Solution**: Forwarding failures now raise `ForwardingError`, which is caught by `_process_task` and routed through the same retry/dead-letter logic as processing failures:

| Forwarding result | Task action |
|---|---|
| All peers: 202 | `COMPLETED` |
| Any peer: connection error | `ForwardingError` → retry |
| Any peer: HTTP 429 | `ForwardingError` → retry |
| Any peer: HTTP 5xx | `ForwardingError` → retry |
| Unhealthy peers (by health checker) | Skipped (no attempt) |

Since downstream nodes deduplicate by `workflow_id`, retried forwarding is safe — the same task won't be processed twice.

### Database Cleanup / TTL

**Problem**: Without cleanup, a node processing 1000 OCR tasks/day with ~2MB payloads per task grows its SQLite database by ~2GB/day indefinitely.

**Solution**: A background `_cleanup_worker` coroutine periodically runs `_purge_old_tasks()`, which deletes:

- `COMPLETED` tasks older than `task_ttl_hours` (default: 72 hours)
- `DEAD_LETTER` tasks older than `dead_letter_ttl_hours` (default: 168 hours / 7 days)
- `PENDING` and `PROCESSING` tasks are **never** purged

```yaml
task_ttl_hours: 72         # COMPLETED tasks purged after 3 days
dead_letter_ttl_hours: 168 # DEAD_LETTER tasks purged after 7 days
cleanup_interval: 3600     # seconds between cleanup runs (1 hour)
```

Dead letters have a longer TTL because they require human inspection.

### API Key Authentication

**Problem**: Without authentication, any machine on the network can push tasks into any node or inspect its dead letters.

**Solution**: When `api_key` is set in `routing.yaml`, a FastAPI middleware requires all requests (except `/health` and `/metrics`) to include a valid `X-API-Key` header:

```yaml
api_key: "my-shared-mesh-secret"
```

| Endpoint | Auth required? |
|---|---|
| `GET /health` | **No** (load balancers, monitoring) |
| `GET /metrics` | **No** (Prometheus scraping) |
| `POST /ingest` | Yes |
| `GET /task/{id}` | Yes |
| `GET /dead-letter` | Yes |
| `POST /dead-letter/{id}/retry` | Yes |
| `GET /peers` | Yes |

When a node forwards tasks to downstream peers, the `X-API-Key` header is included automatically. When `api_key` is `null` (default), no middleware is added — fully backward compatible.

---

## Operational Maturity (Tier 2)

Five features for operational maturity plus a logging architecture redesign. All backward-compatible with existing nodes.

### Task Lookup by ID

**Problem**: You could only see dead letters. There was no way to ask "what happened to `workflow_id: abc-123`?" — no way to inspect a specific task's status, payload, timestamps, or error history.

**Solution**: `GET /task/{id}` returns full task details:

```bash
curl http://localhost:8000/task/abc-123
```

```json
{
  "id": "abc-123",
  "status": "COMPLETED",
  "payload": {"workflow_id": "abc-123", "result": "..."},
  "priority": 5,
  "retry_count": 1,
  "error_message": null,
  "created_at": "2024-01-01 12:00:00",
  "processed_at": "2024-01-01 12:00:05",
  "started_processing_at": null,
  "next_retry_at": null
}
```

Returns **404** for unknown task IDs. Respects API key auth when configured.

### Prometheus Metrics Endpoint

**Problem**: Logs are great for debugging, but operations teams need time-series metrics: tasks processed/second, error rate, queue depth over time.

**Solution**: `GET /metrics` serves zero-dependency Prometheus exposition format. Prometheus scrapes it — the node never pushes. Fully decentralized.

```bash
curl http://localhost:8000/metrics
```

```
# HELP decentraflow_tasks_ingested_total Total tasks ingested via /ingest
# TYPE decentraflow_tasks_ingested_total counter
decentraflow_tasks_ingested_total{node="ocr_node"} 42

# HELP decentraflow_queue_pending Current number of PENDING tasks
# TYPE decentraflow_queue_pending gauge
decentraflow_queue_pending{node="ocr_node"} 3

# HELP decentraflow_processing_duration_seconds Task processing duration in seconds
# TYPE decentraflow_processing_duration_seconds histogram
decentraflow_processing_duration_seconds_bucket{node="ocr_node",le="0.1"} 15
...
```

**Available metrics:**

| Metric | Type | Description |
|---|---|---|
| `tasks_ingested_total` | counter | Tasks ingested via /ingest |
| `tasks_completed_total` | counter | Successfully completed tasks |
| `tasks_failed_total` | counter | Task processing failures |
| `tasks_dead_letter_total` | counter | Tasks moved to dead letter |
| `tasks_timeout_total` | counter | Tasks that timed out |
| `tasks_forwarded_total` | counter | Successful forwards |
| `forwarding_errors_total` | counter | Forwarding failures |
| `tasks_retried_total` | counter | Retries scheduled |
| `queue_pending` | gauge | Current PENDING tasks |
| `queue_processing` | gauge | Current PROCESSING tasks |
| `queue_dead_letter` | gauge | Current DEAD_LETTER tasks |
| `processing_duration_seconds` | histogram | Processing time distribution |

Exempt from API key auth (like `/health`) so Prometheus can scrape without credentials.

### Lifecycle Hooks

**Problem**: No way to run code before/after task processing without modifying `blueprint.py`. Common needs: inject tracing, emit webhooks, custom alerting.

**Solution**: Three hook points with decorator-style registration:

```python
node = NodeBlueprint(node_name="my_node", process_func=process)

@node.before_process
async def inject_tracing(task_id, payload):
    payload["trace_id"] = generate_trace_id()

@node.after_process
def send_webhook(task_id, result):
    requests.post("https://webhook.example.com", json=result)

@node.on_failure
async def alert_ops(task_id, payload, error_message):
    await send_slack_alert(f"Task {task_id} failed: {error_message}")
```

| Hook | When | Receives |
|---|---|---|
| `before_process` | Before `process_func` execution | `(task_id, payload_dict)` |
| `after_process` | After successful completion | `(task_id, result_payload)` |
| `on_failure` | After failure (exception/timeout/forwarding) | `(task_id, payload_dict, error_message)` |

**Design:**
- **Sync or async** — both work, async hooks are awaited
- **Fire-and-forget** — errors in hooks are logged but don't crash the pipeline
- **Multiple per event** — register as many hooks as needed
- **Decorator-friendly** — `@node.before_process` returns the original function

### Content-Based Routing

**Problem**: All results went to all `next_nodes`. No way to route based on payload content (e.g., "if language == 'fr', send to French node").

**Solution**: Optional `routing_func` parameter that dynamically determines target nodes:

```python
def route_by_language(payload):
    lang = payload.get("language", "en")
    routes = {
        "fr": ["http://french-node:8000"],
        "en": ["http://english-node:8000"],
        "de": ["http://german-node:8000"],
    }
    return routes.get(lang, ["http://default-node:8000"])

node = NodeBlueprint(
    node_name="router",
    process_func=process,
    routing_func=route_by_language,  # overrides static next_nodes
)
```

| Feature | Behavior |
|---|---|
| `routing_func=None` | Uses static `next_nodes` from YAML (default, backward compatible) |
| `routing_func` set | Calls function with result payload, uses returned URL list |
| Sync or async | Both supported (async is awaited) |
| Returns `[]` | No forwarding (task completes without forwarding) |
| Raises exception | `ForwardingError` → task retries |
| Unknown URLs | Assumed healthy (peer_health only tracks static peers) |

### Task Priority

**Problem**: All tasks were equal. No way to express "this task is urgent, process it before others."

**Solution**: Optional `priority` field in the payload (default 0, higher = more urgent):

```bash
# Normal priority (default)
curl -X POST http://localhost:8000/ingest \
  -d '{"workflow_id": "normal-1", "data": "..."}'

# Urgent task
curl -X POST http://localhost:8000/ingest \
  -d '{"workflow_id": "urgent-1", "data": "...", "priority": 10}'
```

Workers pick tasks in priority order via `ORDER BY priority DESC`. Tasks with equal priority follow insertion order.

- **Backward compatible**: default priority is 0, existing payloads work unchanged
- **Visible**: `GET /task/{id}` includes the priority field
- **Schema migration**: existing SQLite databases automatically get the priority column on startup

### Decentralized Logging

**Problem**: The original LokiHandler pushed logs directly from nodes to Loki — a runtime dependency that contradicts the brokerless philosophy. If Loki is down, log pushes fail.

**Solution**: Nodes write structured JSON log files locally. External scrapers (Promtail, Grafana Alloy) consume these files and ship them to Loki. The node has **zero runtime dependency** on any logging infrastructure.

```
Node writes JSON ──> logs/my_node.log ──> Promtail scrapes ──> Loki ──> Grafana
```

**Log format** (one JSON object per line):
```json
{"timestamp":"2024-01-01T12:00:00.123Z","level":"INFO","service":"ocr_node","environment":"prod","message":"Task xyz-123 queued (priority=5)."}
```

**Promtail** is added to `docker-compose.yml` and auto-configured to:
- Scrape all `nodes/*/logs/*.log` files
- Parse JSON and extract `level`, `service`, `environment` as Loki labels
- Push to Loki for querying in Grafana

The `LokiHandler` class is still available in the package for backward compatibility, but `NodeBlueprint` no longer uses it internally.

---

## Configuration

Each node has a `config/routing.yaml` that controls routing, resilience, and production settings:

```yaml
node_name: "my_node"
environment: "dev"

# ── Mesh Routing ─────────────────────────────────────────
next_nodes:
  - "http://localhost:8001"   # downstream peer URLs

# ── Resilience (all optional — sensible defaults) ────────
max_retries: 3              # attempts before DEAD_LETTER (default: 3)
backoff_base: 2.0           # exponential backoff base in seconds (default: 2.0)
max_queue_depth: 1000       # reject /ingest with 429 above this (default: 1000)
max_workers: 3              # concurrent worker coroutines (default: 3)
health_check_interval: 30   # seconds between peer /health probes (default: 30)
worker_poll_interval: 1.0   # seconds between worker queue polls (default: 1.0)

# ── Production Hardening (all optional — sensible defaults) ─
task_timeout: 300            # seconds before a hanging process_func is killed (default: 300)
shutdown_timeout: 30         # seconds to wait for in-flight tasks on SIGTERM (default: 30)
task_ttl_hours: 72           # COMPLETED tasks purged after this many hours (default: 72)
dead_letter_ttl_hours: 168   # DEAD_LETTER tasks purged after 7 days (default: 168)
cleanup_interval: 3600       # seconds between automatic DB cleanup runs (default: 3600)
api_key: null                # shared mesh API key (null = no auth) (default: null)
```

Nodes can also have a `config/local_config.yaml` for node-specific settings (for example, local service options).

**Note**: `loki_url` is no longer used. Logging is now decentralized (structured JSON files scraped by Promtail).

---

## Node Implementations

### OCR Node (Pipeline)

**Location**: `nodes/ocr_node/`

An asynchronous pipeline node that processes documents via the `/ingest` endpoint. Designed for mesh-style workflows where tasks flow through multiple nodes.

- **Engine**: Vision LLM OCR
- **Input**: JSON payload with base64-encoded image via `/ingest`
- **Output**: Enriched payload with `ocr_text` field, forwarded to `next_nodes`
- **Port**: `8000`

```bash
cd nodes/ocr_node
uvicorn main:app --port 8000
```

### OCR Tool Node (Synchronous)

**Location**: `nodes/ocr_tool_node/`

A **dual-mode** node that supports both mesh pipeline processing (`/ingest`) and direct synchronous tool calls (`/ocr`, `/ocr/upload`). Built for integration with Open WebUI and external APIs.

- **Engine**: Vision LLM OCR
- **Endpoints**:
  - `POST /ingest` — async mesh pipeline (from NodeBlueprint)
  - `POST /ocr` — synchronous, accepts base64 JSON, returns extracted text immediately
  - `POST /ocr/upload` — synchronous, accepts multipart file upload
  - `GET /health` — queue stats + peer status (from NodeBlueprint)
- **Port**: `8002`

```bash
cd nodes/ocr_tool_node
uvicorn main:app --host 0.0.0.0 --port 8002
```

### Open WebUI Tool

**Location**: `nodes/ocr_tool_node/openwebui_tool.py`

A Python tool definition for [Open WebUI](https://github.com/open-webui/open-webui) that lets LLMs call the OCR Tool Node. When a user uploads an image and asks to "read" or "extract text", the LLM automatically invokes this tool.

- Extracts base64 image data directly from `__messages__` (how Open WebUI passes image attachments)
- Sends images to the OCR Tool Node at `host.docker.internal:8002`
- Returns extracted text to the LLM for further processing
- Configurable via Open WebUI Valves (`OCR_NODE_URL`, `REQUEST_TIMEOUT`)

---

## Infrastructure Stack

Orchestrated via `docker-compose.yml`:

| Service | Image | Port | Purpose |
|---|---|---|---|
| **Open WebUI** | `ghcr.io/open-webui/open-webui:main` | `3080` | AI chat interface (connects to Ollama on host) |
| **Loki** | `grafana/loki:3.4.3` | `3100` | Log aggregation (receives from Promtail) |
| **Promtail** | `grafana/promtail:3.4.3` | — | Scrapes structured JSON logs from node directories |
| **Grafana** | `grafana/grafana:11.5.2` | `3000` | Log visualization, metrics dashboards |

```bash
docker compose up -d
```

| URL | Credentials |
|---|---|
| Open WebUI: `http://localhost:3080` | Create account on first launch |
| Grafana: `http://localhost:3000` | `admin` / `decentraflow` |
| Loki API: `http://localhost:3100` | — |

**Logging flow**: Nodes write JSON → Promtail scrapes → Loki stores → Grafana queries.

**Metrics flow**: Prometheus scrapes `GET /metrics` on each node → Grafana dashboards.

Loki is auto-provisioned as a Grafana data source via `monitoring/grafana/provisioning/`.

---

## Test Suite

**238 tests** covering unit, integration, end-to-end, production hardening, operational maturity, and regression (TNR):

```bash
# Setup
python -m venv .venv_test
.venv_test\Scripts\Activate.ps1          # Windows
# source .venv_test/bin/activate         # Linux/Mac
pip install -e core_framework
pip install -r requirements-test.txt

# Run
python -m pytest tests/ -v
```

| File | Tests | Type | Coverage |
|---|---|---|---|
| `test_models.py` | 11 | Unit | Task model defaults, status transitions, JSON payload |
| `test_routes.py` | 16 | Integration | `/ingest`, `/health`, `/dead-letter`, `/peers`, backpressure, schema validation |
| `test_worker.py` | 15 | Integration | Task picking, processing, retries with backoff, dead letter |
| `test_mesh.py` | 12 | Integration | Forwarding to peers, skip unhealthy, health checker probes |
| `test_loki_handler.py` | 11 | Unit | Log queuing, batch flushing, fire-and-forget, lifecycle |
| `test_e2e.py` | 15 | End-to-End | Full pipeline, retry→success, dead letter→manual retry, forwarding failure, concurrent workers |
| `test_regression.py` | 14 | TNR | Backward compat init, original behaviors, custom routes, worker-on-lifespan |
| `test_production.py` | 40 | Production | All 6 Tier 1 features (stale recovery, timeout, shutdown, forwarding, cleanup, auth) |
| `test_stale_recovery.py` | 7 | Integration | Stale task recovery: direct + E2E with lifespan |
| `test_timeout.py` | 6 | Integration | Task timeout: retry, dead-letter, error messages, E2E |
| `test_shutdown.py` | 9 | Integration | Graceful shutdown: rollback, drain, flag, restart recovery |
| `test_cleanup.py` | 8 | Integration | Database cleanup: TTL, mixed purge, independent TTLs |
| `test_auth.py` | 12 | Integration | API key: accept/reject, health exempt, forwarding headers |
| `test_task_lookup.py` | 11 | Integration | GET /task/{id}: status, payload, priority, timestamps, auth |
| `test_metrics.py` | 13 | Integration | MetricsCollector unit + /metrics endpoint, counters, gauges, histogram |
| `test_hooks.py` | 15 | Integration | Lifecycle hooks: sync/async, error isolation, decorator, E2E |
| `test_routing_func.py` | 9 | Integration | Content-based routing: sync/async, errors, fallback, E2E |
| `test_priority.py` | 9 | Integration | Task priority: model, ingestion, ordering, E2E |
| **Total** | **238** | | **All passing** |

Tests use:
- **Isolated SQLite databases** per test (via `tmp_path`)
- **Fast polling** (50ms) to avoid slow tests
- **`respx`** for HTTP mocking (forwarding, health checks)
- **Factory fixtures** (`make_node`) for clean, configurable node creation

---

## Project Structure

```
micro_service_project/
├── core_framework/                  # The decentraflow package
│   ├── decentraflow/
│   │   ├── __init__.py              # Exports: NodeBlueprint, Task, ForwardingError, JsonFormatter, MetricsCollector
│   │   ├── blueprint.py             # NodeBlueprint — the core class (~750 lines)
│   │   ├── models.py                # Task SQLModel (with priority, retry, timeout fields)
│   │   ├── json_logger.py           # Structured JSON log formatter
│   │   ├── metrics.py               # Zero-dependency Prometheus metrics collector
│   │   └── loki_handler.py          # Legacy Loki push handler (backward compat)
│   └── setup.py                     # pip install -e core_framework/
│
├── nodes/
│   ├── ocr_node/                    # Pipeline OCR node
│   │   ├── config/
│   │   │   ├── routing.yaml         # Mesh routing + resilience + production config
│   │   │   └── local_config.yaml    # Vision LLM OCR settings
│   │   ├── src/
│   │   │   └── ocr_logic.py         # Vision LLM OCR processing logic
│   │   ├── main.py                  # 3-line node entry point
│   │   └── requirements.txt
│   │
│   └── ocr_tool_node/               # Synchronous OCR tool node
│       ├── config/
│       │   ├── routing.yaml
│       │   └── local_config.yaml
│       ├── src/
│       │   └── ocr_logic.py         # Sync + async OCR logic
│       ├── main.py                  # Node + custom /ocr endpoints
│       ├── openwebui_tool.py        # Open WebUI tool definition
│       └── requirements.txt
│
├── monitoring/
│   ├── loki-config.yml              # Loki server configuration
│   ├── promtail-config.yml          # Promtail log scraper configuration
│   └── grafana/
│       └── provisioning/
│           └── datasources/
│               └── datasource.yml   # Auto-provisions Loki in Grafana
│
├── tests/                           # 238 tests
│   ├── conftest.py                  # Fixtures (make_node, client)
│   ├── helpers.py                   # Process functions + utilities
│   ├── test_models.py              # Task model unit tests
│   ├── test_routes.py              # HTTP endpoint integration tests
│   ├── test_worker.py              # Worker pool integration tests
│   ├── test_mesh.py                # Mesh forwarding + health checker tests
│   ├── test_loki_handler.py        # Loki handler unit tests
│   ├── test_e2e.py                 # End-to-end pipeline tests
│   ├── test_regression.py          # TNR backward compatibility tests
│   ├── test_production.py          # Tier 1 production hardening tests
│   ├── test_stale_recovery.py      # Stale task recovery tests
│   ├── test_timeout.py             # Task timeout tests
│   ├── test_shutdown.py            # Graceful shutdown tests
│   ├── test_cleanup.py             # Database cleanup / TTL tests
│   ├── test_auth.py                # API key authentication tests
│   ├── test_task_lookup.py         # Task lookup by ID tests
│   ├── test_metrics.py             # Prometheus metrics tests
│   ├── test_hooks.py               # Lifecycle hooks tests
│   ├── test_routing_func.py        # Content-based routing tests
│   └── test_priority.py            # Task priority tests
│
├── docker-compose.yml               # Loki + Promtail + Grafana + Open WebUI
└── requirements-test.txt            # Test dependencies
```

---

## Quick Start

### 1. Start the infrastructure

```bash
docker compose up -d
```

### 2. Create a new node

```bash
mkdir -p nodes/my_node/config nodes/my_node/logs nodes/my_node/src
```

**`nodes/my_node/config/routing.yaml`**:
```yaml
node_name: "my_node"
environment: "dev"
next_nodes: []

# Logs are written as structured JSON to logs/my_node.log
# Promtail scrapes them automatically (see docker-compose.yml)

# Production hardening (optional — sensible defaults apply)
# task_timeout: 300
# shutdown_timeout: 30
# api_key: "my-secret-key"
```

**`nodes/my_node/src/logic.py`**:
```python
async def process(payload: dict) -> dict:
    # Your AI/ML logic here
    payload["result"] = "processed"
    payload["history"] = payload.get("history", []) + ["my_node_completed"]
    return payload
```

**`nodes/my_node/main.py`**:
```python
from decentraflow import NodeBlueprint
from src.logic import process

node = NodeBlueprint(node_name="my_node", process_func=process)
app = node.app
```

### 3. Run the node

```bash
cd nodes/my_node
pip install -e ../../core_framework
uvicorn main:app --port 8000
```

### 4. Send tasks

```bash
# Normal task
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "test-001", "data": "hello"}'

# Urgent task (priority)
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "urgent-001", "data": "critical", "priority": 10}'
```

### 5. Monitor

```bash
# Queue stats
curl http://localhost:8000/health

# Inspect a specific task
curl http://localhost:8000/task/test-001

# Dead letters
curl http://localhost:8000/dead-letter

# Peer health
curl http://localhost:8000/peers

# Prometheus metrics
curl http://localhost:8000/metrics

# Logs in Grafana
open http://localhost:3000
```

### 6. Add lifecycle hooks

```python
from decentraflow import NodeBlueprint
from src.logic import process

node = NodeBlueprint(node_name="my_node", process_func=process)

@node.before_process
def log_start(task_id, payload):
    print(f"Starting {task_id}")

@node.on_failure
def alert(task_id, payload, error):
    print(f"ALERT: {task_id} failed: {error}")

app = node.app
```

### 7. Add content-based routing

```python
def route_by_type(payload):
    doc_type = payload.get("type", "default")
    return {
        "invoice": ["http://invoice-node:8000"],
        "receipt": ["http://receipt-node:8000"],
    }.get(doc_type, ["http://default-node:8000"])

node = NodeBlueprint(
    node_name="router",
    process_func=classify_document,
    routing_func=route_by_type,
)
```
