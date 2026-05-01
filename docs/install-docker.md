# Installing DMSAI with Docker Compose

Docker Compose is the recommended way to run DMSAI. All services, the database, and file storage are managed as containers — no Python or Node.js installation required on the host.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / macOS) or Docker Engine + Docker Compose plugin (Linux)
- An LLM provider — Ollama running locally **or** a cloud API key (Gemini, OpenAI…)

---

## Step 1 — Clone and configure

```bash
git clone https://github.com/americium-241/DMSAI.git
cd DMSAI
cp .env.example .env
```

The `.env.example` defaults work out of the box for a local Ollama setup. Secrets (`DMSAI_JWT_SECRET`, `DMSAI_INTERNAL_API_KEY`) are auto-generated on the first container start — you do not need to edit them manually.

**If you are using a cloud LLM**, also set:

```env
GEMINI_API_KEY=your-key-here
```

---

## Step 2 — Start the stack

```bash
docker compose up -d
```

First run builds all images from source (may take a few minutes). Subsequent starts are instant.

Open **http://localhost:5173** once all containers are healthy.

Default login: `admin@dmsai.com` / `admin123`

---

## Step 3 — Pull an LLM model

If you are using local Ollama (default):

```bash
ollama pull gemma3:27b
# or a smaller model:  ollama pull qwen2.5vl:7b
```

Ollama must be running on the **host machine**. The compose file routes `OLLAMA_BASE_URL` to `host.docker.internal:11434` automatically, so containers can reach it.

---

## Optional profiles

### Run Ollama inside Docker

Useful if you do not want to install Ollama on the host:

```bash
docker compose --profile ollama up -d
# Then pull a model once (downloads into a persistent volume):
docker exec dmsai-ollama ollama pull gemma3:27b
```

### Enable Grafana + Loki monitoring

```bash
docker compose --profile monitoring up -d
# Grafana: http://localhost:3000
# Default Grafana password: set GRAFANA_ADMIN_PASSWORD in .env
```

### Everything at once

```bash
docker compose --profile ollama --profile monitoring up -d
```

---

## Useful operations

```bash
# Status of all containers
docker compose ps

# Tail logs for a specific service
docker compose logs -f ocr
docker compose logs -f api_gateway

# Stop all containers (data is preserved in volumes)
docker compose down

# Stop and wipe all data (fresh start)
docker compose down -v

# Rebuild images after code changes
docker compose build --parallel
docker compose up -d

# Open a shell in a container
docker compose exec api_gateway bash
```

---

## Services and ports

| Service | Port | Notes |
|---|---:|---|
| Frontend | 5173 | React UI |
| API Gateway | 8080 | REST API + Swagger (`/docs`) |
| Ingestion | 8010 | Internal |
| Conversion | 8011 | Internal |
| Storage | 8012 | Internal |
| OCR | 8013 | Internal |
| Entity Extraction | 8015 | Internal |
| Classification | 8016 | Internal |
| Entity Resolution | 8017 | Internal |
| Field Extraction | 8018 | Internal |
| LiteLLM | 4000 | Only needed for cloud LLM |
| Grafana | 3000 | `--profile monitoring` only |
| Loki | 3100 | `--profile monitoring` only |

---

## Data persistence

All runtime data is stored in Docker named volumes:

| Volume | Contents |
|---|---|
| `dmsai_db` | SQLite database |
| `dmsai_storage` | Uploaded and converted documents |
| `dmsai_ollama` | Downloaded Ollama models (`--profile ollama`) |

These volumes survive `docker compose down`. Use `docker compose down -v` to remove them.

---

## Troubleshooting

**Containers start but pipeline doesn't process documents:**
Check that Ollama is running and the model is pulled. Inspect OCR node logs:
```bash
docker compose logs ocr
```

**`host.docker.internal` does not resolve (Linux):**
Add this to the node services in `docker-compose.yml`:
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**Login fails after `docker compose down -v`:**
The database was wiped. Restart the stack — it auto-seeds the default org and admin user on first start.

**Port already in use:**
Stop any native DMSAI services first: `python dmsai.py stop`
