# Installing DMSAI on Windows (Native)

This guide covers a native installation on Windows using PowerShell. No Docker required.

---

## Prerequisites

| Requirement | Minimum | Download |
|---|---|---|
| Python | 3.11 | https://www.python.org/downloads/ |
| Node.js | 18 LTS | https://nodejs.org/ |
| Git | any | https://git-scm.com/ |
| Ollama *(or cloud key)* | latest | https://ollama.com/ |

> **Tip:** Install Python with the *"Add Python to PATH"* checkbox checked.

---

## Step 1 — Clone the repository

```powershell
git clone https://github.com/americium-241/DMSAI.git
cd DMSAI
```

---

## Step 2 — Install dependencies

Run the PowerShell install script (installs all Python packages and frontend npm dependencies):

```powershell
.\scripts\install.ps1
```

If you prefer a Python-only approach (works on any platform):

```powershell
python .\scripts\install.py
```

---

## Step 3 — Start the application

```powershell
python .\dmsai.py start
```

On the **first run**, this automatically:
- Creates `.env` from `.env.example`
- Generates `DMSAI_JWT_SECRET` and `DMSAI_INTERNAL_API_KEY`
- Creates required `data/` directories

Open **http://localhost:5173** · login `admin@dmsai.com` / `admin123`

---

## Step 4 — Pull an LLM model

With Ollama running, pull a model in a separate terminal:

```powershell
ollama pull gemma3:27b
# Smaller alternatives:
# ollama pull gemma3:12b     (~8 GB VRAM)
# ollama pull qwen2.5vl:7b   (~5 GB VRAM)
# ollama pull llava:7b       (~4 GB VRAM)
```

The default `.env` already points to `http://localhost:11434` — no further configuration needed.

---

## CLI reference

```powershell
python .\dmsai.py setup          # first-time setup (also auto-runs on first start)
python .\dmsai.py start          # start all services
python .\dmsai.py stop           # stop all services
python .\dmsai.py restart        # full restart
python .\dmsai.py status         # show service status + URLs
python .\dmsai.py logs ocr       # tail the OCR service log
python .\dmsai.py logs api_gateway
python .\dmsai.py clean-db       # wipe DB + storage for a fresh start
```

Start without LiteLLM (if you are not using a cloud LLM):

```powershell
python .\dmsai.py start --skip-litellm
```

---

## Using Gemini / LiteLLM (cloud)

Edit `.env` and add your key:

```env
GEMINI_API_KEY=your-key-here
```

Then in the admin **LLM Settings** page, set:
- Provider → `litellm`
- Model → `gemini/gemini-3-flash-preview`
- LiteLLM base URL → `http://localhost:4000`

`python .\dmsai.py start` will launch the LiteLLM proxy automatically alongside all other services.

---

## Data locations

| Path | Contents |
|---|---|
| `data\dmsai.db` | SQLite database |
| `data\storage\` | Uploaded and converted documents |
| `data\inbox\` | Directory-watch input folder |
| `data\processed\` | Files moved here after ingestion |
| `logs\` | Service log files |

---

## Troubleshooting

**`python` command not found:**
Make sure Python is on `PATH`. Try `py` instead of `python`, or re-install Python with the *"Add to PATH"* option.

**`npm` command not found:**
Re-install Node.js from https://nodejs.org and re-run the install script.

**Port already in use:**
Find which process owns the port and close it, or use `--only` to start only the conflicting service:
```powershell
python .\dmsai.py start --only frontend
```

**Service fails to start (check the log):**
```powershell
python .\dmsai.py logs ocr
```

**Script execution policy error:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**LiteLLM fails to start:**
Start without it and configure a local Ollama model instead:
```powershell
python .\dmsai.py start --skip-litellm
```
