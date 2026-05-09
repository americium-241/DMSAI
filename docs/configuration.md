# DMSAI Configuration Reference

DMSAI has two layers of configuration:

1. **Environment variables** (`.env`) — machine-specific secrets and paths, loaded at startup.
2. **SystemConfig** (database) — runtime settings editable from the admin UI without restarting services.

---

## Environment file (`.env`)

Copy `.env.example` to `.env` before starting. The file is gitignored and never committed.

`DMSAI_JWT_SECRET` and `DMSAI_INTERNAL_API_KEY` are **auto-generated** on first run if they are still at their placeholder values — you do not need to set them manually for a local setup.

### All supported keys

| Key | Default | Description |
|---|---|---|
| `DMSAI_DB_URL` | `postgresql+psycopg://dmsai:dmsai@localhost:5432/dmsai` | SQLAlchemy database URL (PostgreSQL only) |
| `DMSAI_STORAGE_ROOT` | `./data/storage/documents` | Document file storage root |
| `DMSAI_INBOX_DIR` | `./data/inbox` | Directory-watch input folder |
| `DMSAI_PROCESSED_DIR` | `./data/processed` | Files moved here after ingestion |
| `DMSAI_MODELS_DIR` | `./data/models` | Local model cache (if any) |
| `DMSAI_JWT_SECRET` | *(auto-generated)* | Signs JWT access tokens |
| `DMSAI_INTERNAL_API_KEY` | *(auto-generated)* | Protects internal gateway callbacks (bucket auto-assign) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `LLM_MODEL` | `gemma3:27b` | Default LLM model for all nodes |
| `GEMINI_API_KEY` | *(empty)* | Gemini API key (only needed for LiteLLM/Gemini) |
| `GRAFANA_ADMIN_PASSWORD` | *(empty)* | Grafana admin password for the monitoring stack |

### Docker URL overrides

When running in Docker Compose these are set automatically — do not override them in `.env` unless you have a custom deployment:

| Key | Docker value |
|---|---|
| `INGESTION_NODE_URL` | `http://ingestion:8010` |
| `CONVERSION_NODE_URL` | `http://conversion:8011` |
| `STORAGE_NODE_URL` | `http://storage:8012` |
| `OCR_NODE_URL` | `http://ocr:8013` |
| `ENTITY_EXTRACTION_NODE_URL` | `http://entity_extraction:8015` |
| `CLASSIFICATION_NODE_URL` | `http://classification:8016` |
| `ENTITY_RESOLUTION_NODE_URL` | `http://entity_resolution:8017` |
| `FIELD_EXTRACTION_NODE_URL` | `http://field_extraction:8018` |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` |

---

## SystemConfig (database / admin UI)

These settings are stored in the `system_config` database table and are editable from **Admin → LLM Settings** and **Admin → General Settings** in the UI. Changes take effect immediately without restarting services (the UI triggers a service reload).

### LLM provider

| Key | Default | Description |
|---|---|---|
| `llm_provider` | `ollama` | `ollama` or `litellm` |
| `llm_model` | `gemma3:27b` | Model name passed to the provider |
| `ollama_base_url` | `http://localhost:11434` | Ollama API base URL (overrides env at runtime) |
| `litellm_base_url` | `http://localhost:4000` | LiteLLM proxy URL |
| `litellm_api_key` | *(empty)* | Gemini / cloud API key (stored in DB, injected into LiteLLM) |

### LLM prompts

All node prompts are configurable. Changing a prompt and clicking **Save + Restart** in the LLM Settings page applies it immediately.

| Key | Node | Description |
|---|---|---|
| `ocr_prompt` | OCR | System prompt for vision OCR extraction |
| `entity_extraction_prompt` | Entity Extraction | Prompt for named entity detection |
| `classification_prompt` | Classification | Prompt for document classification |
| `entity_resolution_prompt` | Entity Resolution | Prompt for entity deduplication |
| `field_extraction_prompt` | Field Extraction | Prompt for structured field extraction |

### Confidence thresholds

| Key | Default | Description |
|---|---|---|
| `ocr_confidence_threshold` | `0.5` | Minimum OCR confidence to proceed |
| `entity_confidence_threshold` | `0.6` | Minimum entity confidence to keep |
| `classification_confidence_threshold` | `0.5` | Minimum classification confidence |
| `field_confidence_threshold` | `0.5` | Minimum field confidence to store |

### Ingestion

| Key | Default | Description |
|---|---|---|
| `ingestion_watch_enabled` | `true` | Enable directory polling |
| `ingestion_watch_directory` | `./data/inbox` | Directory to watch |
| `ingestion_processed_directory` | `./data/processed` | Destination after ingestion |
| `ingestion_poll_interval_seconds` | `5` | Poll interval in seconds |
| `ingestion_email_enabled` | `false` | Enable IMAP email ingestion |
| `ingestion_email_imap_host` | *(empty)* | IMAP server hostname |
| `ingestion_email_imap_port` | `993` | IMAP port |
| `ingestion_email_imap_user` | *(empty)* | IMAP username |
| `ingestion_email_imap_password` | *(empty)* | IMAP password |
| `ingestion_email_imap_tls` | `true` | Use TLS |
| `ingestion_email_folder` | `INBOX` | Mailbox folder to poll |
| `ingestion_email_poll_interval_seconds` | `60` | Email poll interval |
| `ingestion_email_mark_seen` | `true` | Mark ingested emails as read |

### Document lifecycle / archive

| Key | Default | Description |
|---|---|---|
| `archive_retention_days` | `90` | Days before archived PDFs are gzip-compressed |
| `trash_retention_days` | `30` | Days before trashed documents appear in the purge list |
| `archive_compression_enabled` | `true` | Enable automatic PDF compression during compaction |

---

## Auth configuration (`api_gateway/config/auth.yaml`)

Static defaults for authentication features. Edit this file before first start or override individual values from **Admin → General Settings → Auth** in the UI.

```yaml
# Registration
registration_enabled: true
require_email_verification: false

# JWT
jwt_expire_minutes: 1440    # 24 hours

# LDAP (leave host empty to disable)
ldap_host: ""
ldap_port: 389
ldap_bind_dn: ""
ldap_bind_password: ""
ldap_user_search_base: ""
ldap_user_search_filter: "(mail={email})"

# SMTP (for email verification)
smtp_host: ""
smtp_port: 587
smtp_user: ""
smtp_password: ""
smtp_from: "noreply@dmsai.local"
smtp_tls: true
```

---

## LiteLLM proxy (`litellm_config.yaml`)

Defines which cloud models are available when `llm_provider = litellm`.

```yaml
model_list:
  - model_name: gemini/gemini-3-flash-preview
    litellm_params:
      model: gemini/gemini-3-flash-preview
      api_key: os.environ/GEMINI_API_KEY
```

Add more models by appending entries. The `api_key` value uses the `os.environ/KEY_NAME` syntax to read from the environment at startup — never hardcode keys in this file.

---

## Node routing (`nodes/*/config/routing.yaml`)

Defines where each node sends its output after processing. You generally do not need to edit these.

Example (`nodes/ocr_node/config/routing.yaml`):
```yaml
output:
  - url: http://localhost:8015/process   # entity_extraction_node
    timeout: 30
```

Docker-specific routing configs (using service names instead of `localhost`) live in `docker/routing/`.

---

## Node local config (`nodes/*/config/local_config.yaml`)

Node-specific overrides for paths and ports. Updated automatically by the `setup` command for relative paths.

Example (`nodes/ingestion_node/config/local_config.yaml`):
```yaml
port: 8010
inbox_dir: ./data/inbox
processed_dir: ./data/processed
```
