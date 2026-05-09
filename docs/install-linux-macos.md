# Installing DMSAI on Linux / macOS (Native)

This guide covers a native installation on Linux and macOS. No Docker required.

---

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| Python | 3.11 | Use pyenv or the system package manager |
| Node.js | 18 LTS | Use nvm or the system package manager |
| Git | any | Usually pre-installed |
| Ollama *(or cloud key)* | latest | https://ollama.com/ |

**macOS quick install with Homebrew:**
```bash
brew install python@3.11 node ollama
```

**Ubuntu / Debian:**
```bash
# Python 3.11
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update && sudo apt install python3.11 python3.11-venv python3.11-pip

# Node.js 18
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
```

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/americium-241/DMSAI.git
cd DMSAI
```

---

## Step 2 — Install dependencies

**Bash install script (Linux / macOS):**
```bash
bash scripts/install.sh
```

**Python cross-platform installer (any OS, no bash required):**
```bash
python3 scripts/install.py
```

Both scripts install all Python packages (shared libs, gateway, all pipeline nodes) and the frontend npm dependencies.

---

## Step 3 — Start the application

```bash
python dmsai.py start
```

On the **first run**, this automatically:
- Creates `.env` from `.env.example`
- Generates `DMSAI_JWT_SECRET` and `DMSAI_INTERNAL_API_KEY`
- Creates required `data/` directories

Open **http://localhost:5173** · login `admin@dmsai.com` / `admin123`

---

## Step 4 — Pull an LLM model

With Ollama running, pull a model:

```bash
ollama pull gemma3:27b
# Smaller alternatives:
# ollama pull gemma3:12b     (~8 GB VRAM)
# ollama pull qwen2.5vl:7b   (~5 GB VRAM, good vision quality)
# ollama pull llava:7b       (~4 GB VRAM, lightweight)
```

The default `.env` already points to `http://localhost:11434` — no further configuration needed.

---

## (Optional) Virtual environment

If you want to isolate dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python scripts/install.py
python dmsai.py start
```

---

## CLI reference

```bash
python dmsai.py setup          # first-time setup (also auto-runs on first start)
python dmsai.py start          # start all services
python dmsai.py stop           # stop all services
python dmsai.py restart        # full restart
python dmsai.py status         # show service status + URLs
python dmsai.py logs ocr       # tail the OCR service log
python dmsai.py clean-db       # wipe DB + storage for a fresh start

# Start without LiteLLM proxy (Ollama users only):
python dmsai.py start --skip-litellm

# Start a single service:
python dmsai.py start --only ocr
```

---

## Using Gemini / LiteLLM (cloud)

Edit `.env`:

```env
GEMINI_API_KEY=your-key-here
```

Then in the admin **LLM Settings** page:
- Provider → `litellm`
- Model → `gemini/gemini-3-flash-preview`
- LiteLLM base URL → `http://localhost:4000`

`python dmsai.py start` launches the LiteLLM proxy alongside all other services.

---

## Running as a background service (Linux systemd)

Create `/etc/systemd/system/dmsai.service`:

```ini
[Unit]
Description=DMSAI Document Intelligence
After=network.target ollama.service

[Service]
Type=forking
WorkingDirectory=/opt/DMSAI
ExecStart=/usr/bin/python3 /opt/DMSAI/dmsai.py start
ExecStop=/usr/bin/python3 /opt/DMSAI/dmsai.py stop
Restart=on-failure
User=dmsai

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now dmsai
```

---

## Data locations

| Path | Contents |
|---|---|
| PostgreSQL `dmsai` database | All structured DMSAI data (documents, entities, users, etc.) |
| `data/storage/` | Uploaded and converted documents |
| `data/inbox/` | Directory-watch input folder |
| `data/processed/` | Files moved here after ingestion |
| `logs/` | Service log files |

---

## Troubleshooting

**`python` not found, only `python3`:**
Either create an alias (`alias python=python3`) or call `python3 dmsai.py start` explicitly.

**`uvicorn` not found after install:**
The install script installs into the active environment. Make sure you are in the correct virtualenv (or system Python) before running `dmsai.py`.

**Permission denied on `scripts/install.sh`:**
```bash
chmod +x scripts/install.sh
```

**Service log shows LLM timeout:**
Increase Ollama's default context / timeout, or switch to a smaller model (`gemma3:12b`, `llava:7b`).

**Port already in use:**
```bash
# Find and kill the process using a port (e.g. 8013 for OCR):
lsof -ti :8013 | xargs kill -9
```
