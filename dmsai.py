#!/usr/bin/env python3
"""
DMSAI CLI - manage the full application stack.

Usage:
    python dmsai.py setup              First-time setup (.env, secrets, PostgreSQL)
    python dmsai.py start              Start all services (runs setup automatically if needed)
    python dmsai.py stop               Stop all services
    python dmsai.py restart            Restart all services
    python dmsai.py status             Show service status
    python dmsai.py logs <service>     Tail the log of a service
    python dmsai.py clean-db           Wipe all data for a fresh start

Options:
    --skip-litellm       Don't start the LiteLLM proxy
    --only <svc,...>     Only start/stop these services (comma-separated)
"""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
ENV_FILE = ROOT / ".env"


def _load_dotenv() -> None:
    """Load .env file into os.environ (simple parser, no dependency needed)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Resolve relative path env vars to absolute (relative to project root) so that
# all child processes receive absolute paths regardless of their working directory.
# Without this, nodes running in nodes/XXX_node/ would misinterpret
# DMSAI_STORAGE_ROOT=./data/storage/documents as being relative to *their* CWD,
# which would cause "file not found" errors when subsequent nodes try to read the
# storage path saved in the DB.
for _path_key in ("DMSAI_STORAGE_ROOT", "DMSAI_INBOX_DIR", "DMSAI_PROCESSED_DIR", "DMSAI_MODELS_DIR"):
    _val = os.environ.get(_path_key, "")
    if _val and not os.path.isabs(_val):
        os.environ[_path_key] = str((ROOT / _val).resolve())

SERVICES: list[dict] = [
    {"name": "ingestion",          "port": 8010, "kind": "node", "dir": "nodes/ingestion_node"},
    {"name": "conversion",         "port": 8011, "kind": "node", "dir": "nodes/conversion_node"},
    {"name": "storage",            "port": 8012, "kind": "node", "dir": "nodes/storage_node"},
    {"name": "ocr",                "port": 8013, "kind": "node", "dir": "nodes/ocr_node"},
    {"name": "entity_extraction",  "port": 8015, "kind": "node", "dir": "nodes/entity_extraction_node"},
    {"name": "classification",     "port": 8016, "kind": "node", "dir": "nodes/classification_node"},
    {"name": "entity_resolution",  "port": 8017, "kind": "node", "dir": "nodes/entity_resolution_node"},
    {"name": "field_extraction",   "port": 8018, "kind": "node", "dir": "nodes/field_extraction_node"},
    {"name": "api_gateway",        "port": 8080, "kind": "gateway", "dir": "api_gateway"},
    {"name": "litellm",            "port": 4000, "kind": "litellm", "dir": "."},
    {"name": "frontend",           "port": 5173, "kind": "frontend", "dir": "frontend"},
]

# ---------------------------------------------------------------------------
# Terminal colors (works on Windows 10+ with VT support)
# ---------------------------------------------------------------------------

def _enable_vt():
    """Enable ANSI escape codes on Windows."""
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

_enable_vt()

RESET  = "\033[0m"

RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
GRAY   = "\033[90m"

def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"

# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def is_port_open(port: int, timeout: float = 0.5) -> bool:
    for family, addr in [
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET6, "::1"),
    ]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((addr, port))
                return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            continue
    return False


_port_pid_cache: dict[int, list[int]] = {}


def _refresh_port_pids(ports: list[int]) -> None:
    """Batch-query all port->PID mappings in a single PowerShell call."""
    _port_pid_cache.clear()
    for p in ports:
        _port_pid_cache[p] = []
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetTCPConnection -ErrorAction SilentlyContinue | "
                 "Select-Object LocalPort, OwningProcess | "
                 "ForEach-Object { \"$($_.LocalPort)|$($_.OwningProcess)\" }"],
                text=True, stderr=subprocess.DEVNULL,
            )
            port_set = set(ports)
            for line in out.strip().splitlines():
                parts = line.strip().split("|")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    lport, pid = int(parts[0]), int(parts[1])
                    if lport in port_set and pid > 0:
                        _port_pid_cache.setdefault(lport, []).append(pid)
    except Exception:
        pass


def _pids_on_port(port: int) -> list[int]:
    if port in _port_pid_cache:
        return _port_pid_cache[port]
    _refresh_port_pids([port])
    return _port_pid_cache.get(port, [])


def kill_port(port: int) -> bool:
    pids = _pids_on_port(port)
    killed = False
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            killed = True
        except Exception:
            pass
    return killed


def kill_ports_batch(ports: list[int]) -> None:
    """Kill all processes on the given ports efficiently."""
    _refresh_port_pids(ports)
    for port in ports:
        pids = _port_pid_cache.get(port, [])
        for pid in pids:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

# ---------------------------------------------------------------------------
# DB helpers (read SystemConfig for LiteLLM key)
# ---------------------------------------------------------------------------

def _read_db_config(key: str) -> str:
    """Read a single value from the SystemConfig table, or return ''."""
    try:
        sys.path.insert(0, str(ROOT / "shared"))
        from sqlmodel import Session, select
        from dmsai_models.connection import get_engine
        from dmsai_models.models import SystemConfig
        with Session(get_engine()) as s:
            row = s.exec(select(SystemConfig).where(SystemConfig.key == key)).first()
            return row.value if row else ""
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def _log_path(name: str) -> Path:
    return LOG_DIR / f"{name}.log"


def start_service(svc: dict) -> None:
    name = svc["name"]
    port = svc["port"]
    kind = svc["kind"]
    work_dir = ROOT / svc["dir"]

    if is_port_open(port):
        print(f"  {_c('SKIP', YELLOW)}  {name:<24} already on :{port}")
        return

    LOG_DIR.mkdir(exist_ok=True)
    log = _log_path(name)

    # Ensure per-node logs/ dir exists (decentraflow writes internal task logs there)
    if kind == "node":
        (work_dir / "logs").mkdir(exist_ok=True)

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    if kind == "node":
        cmd = f"uvicorn main:app --port {port}"
    elif kind == "gateway":
        cmd = f"uvicorn main:app --host 0.0.0.0 --port {port}"
    elif kind == "litellm":
        cfg = ROOT / "litellm_config.yaml"
        cmd = f"litellm --config \"{cfg}\" --port {port}"
        api_key = _read_db_config("litellm_api_key")
        if api_key:
            # Pass the stored key as the env var for every common provider —
            # the user only has one key, and litellm_config.yaml references
            # the right one (os.environ/GEMINI_API_KEY etc.).
            env["GEMINI_API_KEY"] = api_key
            env["GOOGLE_API_KEY"] = api_key
            env["OPENAI_API_KEY"] = api_key
            env["ANTHROPIC_API_KEY"] = api_key
            env["COHERE_API_KEY"] = api_key
    elif kind == "frontend":
        cmd = "npm run dev"
    else:
        return

    with open(log, "w") as lf:
        if sys.platform == "win32":
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                cmd, shell=True, cwd=str(work_dir), env=env,
                stdin=subprocess.DEVNULL,
                stdout=lf, stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen(
                cmd, shell=True, cwd=str(work_dir), env=env,
                stdin=subprocess.DEVNULL,
                stdout=lf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    print(f"  {_c('START', CYAN)}  {name:<24} :{port}  -> {log.name}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(services: list[dict], skip_litellm: bool) -> None:
    print(f"\n{_c('=== Starting DMSAI ===', CYAN)}\n")

    # Auto-run first-time setup silently if .env is missing
    if not ENV_FILE.exists():
        print(f"  {_c('First run — running setup...', YELLOW)}\n")
        cmd_setup()
        print()

    for svc in services:
        if skip_litellm and svc["kind"] == "litellm":
            print(f"  {_c('SKIP', YELLOW)}  litellm              (--skip-litellm)")
            continue
        start_service(svc)

    print(f"\n  Waiting for services to be ready...", end="", flush=True)
    for _ in range(8):
        time.sleep(1)
        print(".", end="", flush=True)
    print()

    cmd_status(services)


def cmd_stop(services: list[dict]) -> None:
    print(f"\n{_c('=== Stopping DMSAI ===', CYAN)}\n")

    running = [s for s in services if is_port_open(s["port"])]
    not_running = [s for s in services if s not in running]

    for svc in not_running:
        print(f"  {_c('--', GRAY)}     {svc['name']:<24} not running")

    if not running:
        print(f"\n  {_c('Nothing to stop.', GREEN)}\n")
        return

    kill_ports_batch([s["port"] for s in running])
    for svc in running:
        print(f"  {_c('STOP', RED)}   {svc['name']:<24} :{svc['port']}")

    for attempt in range(3):
        time.sleep(2)
        still = [s for s in running if is_port_open(s["port"])]
        if not still:
            break
        if attempt < 2:
            kill_ports_batch([s["port"] for s in still])

    if still:
        print()
        for s in still:
            print(f"  {_c('WARN', RED)}   {s['name']} still on :{s['port']}")
    else:
        print(f"\n  {_c('All services stopped.', GREEN)}")
    print()


def cmd_restart(services: list[dict], skip_litellm: bool) -> None:
    cmd_stop(services)
    time.sleep(2)
    cmd_start(services, skip_litellm)


def cmd_status(services: list[dict]) -> None:
    print(f"\n{_c('=== DMSAI Status ===', CYAN)}\n")
    header = f"  {'SERVICE':<24} {'PORT':<8} STATUS"
    print(_c(header, GRAY))
    print(_c("  " + "-" * 46, GRAY))

    up_count = 0
    total = len(services)
    for svc in services:
        alive = is_port_open(svc["port"])
        if alive:
            up_count += 1
        tag = _c("UP", GREEN) if alive else _c("DOWN", RED)
        print(f"  {svc['name']:<24} {svc['port']:<8} {tag}")

    color = GREEN if up_count == total else YELLOW if up_count > 0 else RED
    print(f"\n  {_c(f'{up_count} / {total} services running', color)}")

    gw_up = is_port_open(8080)
    fe_up = is_port_open(5173)
    if gw_up and fe_up:
        print(f"\n  App:   {_c('http://localhost:5173', CYAN)}")
        print(f"  API:   {_c('http://localhost:8080/api', CYAN)}")
        print(f"  Docs:  {_c('http://localhost:8080/docs', CYAN)}")

    print(f"\n  Logs: {_c(str(LOG_DIR), GRAY)}\n")


def cmd_logs(services: list[dict], target: str) -> None:
    matches = [s for s in services if target in s["name"]]
    if not matches:
        names = ", ".join(s["name"] for s in services)
        print(f"{_c('Error:', RED)} unknown service '{target}'. Available: {names}")
        sys.exit(1)

    log = _log_path(matches[0]["name"])
    if not log.exists():
        print(f"{_c('Error:', RED)} no log file at {log}")
        sys.exit(1)

    print(f"{_c(f'=== {log.name} (last 60 lines, then live) ===', CYAN)}\n")
    try:
        lines = log.read_text(errors="replace").splitlines()
        for line in lines[-60:]:
            print(line)
        print(_c("--- live tail (Ctrl+C to quit) ---", GRAY))

        with open(log, "r", errors="replace") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.3)
    except KeyboardInterrupt:
        print()


def cmd_setup(silent: bool = False) -> bool:
    """First-time setup: create .env, generate secrets, bootstrap PostgreSQL.

    PostgreSQL is the only supported production database.  This command:
    1. Copies .env.example to .env if missing.
    2. Generates DMSAI_JWT_SECRET / DMSAI_INTERNAL_API_KEY if still placeholders.
    3. Creates required data directories.
    4. Probes / installs / provisions PostgreSQL via scripts/postgres_setup.py.
       If auto-install fails, prints platform-specific manual instructions.

    Returns True if any change was made, False if already set up.
    """
    changed = False

    if not ENV_FILE.exists():
        example = ROOT / ".env.example"
        if not example.exists():
            print(f"  {_c('Error:', RED)} .env.example not found")
            sys.exit(1)
        import shutil
        shutil.copy(example, ENV_FILE)
        print(f"  {_c('CREATE', CYAN)}  .env (from .env.example)")
        changed = True
    elif not silent:
        print(f"  {_c('OK', GREEN)}     .env already exists")

    # Reload after possible copy
    _load_dotenv()

    # Auto-generate secrets if still at placeholder values
    import secrets as _secrets
    _lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    _updated = False
    _new_lines = []
    for line in _lines:
        stripped = line.strip()
        if stripped.startswith("DMSAI_JWT_SECRET=change-me") or stripped == "DMSAI_JWT_SECRET=":
            new_val = _secrets.token_hex(32)
            _new_lines.append(f"DMSAI_JWT_SECRET={new_val}\n")
            os.environ["DMSAI_JWT_SECRET"] = new_val
            _updated = True
            print(f"  {_c('GENERATE', CYAN)} DMSAI_JWT_SECRET (random)")
        elif stripped.startswith("DMSAI_INTERNAL_API_KEY=change-me") or stripped == "DMSAI_INTERNAL_API_KEY=":
            new_val = _secrets.token_hex(24)
            _new_lines.append(f"DMSAI_INTERNAL_API_KEY={new_val}\n")
            os.environ["DMSAI_INTERNAL_API_KEY"] = new_val
            _updated = True
            print(f"  {_c('GENERATE', CYAN)} DMSAI_INTERNAL_API_KEY (random)")
        else:
            _new_lines.append(line)
    if _updated:
        ENV_FILE.write_text("".join(_new_lines), encoding="utf-8")
        changed = True

    # Create required data directories
    for d in ["data/inbox", "data/processed", "data/storage/documents", "data/models", "logs"]:
        path = ROOT / d
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            print(f"  {_c('MKDIR', CYAN)}  {d}")
            changed = True

    # Create per-node logs/ subdirectories (decentraflow writes internal logs there)
    nodes_dir = ROOT / "nodes"
    if nodes_dir.exists():
        for node_dir in nodes_dir.iterdir():
            if node_dir.is_dir():
                node_logs = node_dir / "logs"
                if not node_logs.exists():
                    node_logs.mkdir(parents=True, exist_ok=True)
                    changed = True

    # PostgreSQL bootstrap — always attempted, idempotent.  Probes localhost,
    # installs natively if needed (winget / brew / apt / dnf), creates the
    # dmsai role + database, and rewrites .env to point at it.  Falls back
    # to printing manual instructions if anything fails.
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from postgres_setup import bootstrap, platform_install_hint  # noqa: WPS433
    except Exception as e:  # pragma: no cover — only happens with broken installs
        print(f"  {_c('Error:', RED)} could not import postgres_setup helper: {e}")
        return changed

    if not silent:
        print()
        print(f"  {_c('PostgreSQL setup', CYAN)}")

    pg_url = "postgresql+psycopg://dmsai:dmsai@localhost:5432/dmsai"
    ok = bootstrap()
    if ok:
        _new_lines = []
        switched = False
        env_text = ENV_FILE.read_text(encoding="utf-8")
        for line in env_text.splitlines(keepends=True):
            if line.startswith("DMSAI_DB_URL=") and "postgresql" not in line:
                _new_lines.append("# " + line)
                _new_lines.append(f"DMSAI_DB_URL={pg_url}\n")
                switched = True
            else:
                _new_lines.append(line)
        if "DMSAI_DB_URL=" not in env_text:
            _new_lines.append(f"\nDMSAI_DB_URL={pg_url}\n")
            switched = True
        if switched:
            ENV_FILE.write_text("".join(_new_lines), encoding="utf-8")
            os.environ["DMSAI_DB_URL"] = pg_url
            print(f"  {_c('CONFIG', CYAN)} DMSAI_DB_URL set to PostgreSQL")
            changed = True
        else:
            _load_dotenv()
            print(f"  {_c('OK', GREEN)}     DMSAI_DB_URL already points at PostgreSQL")
    else:
        print()
        print(f"  {_c('PostgreSQL auto-install failed.', YELLOW)} Manual options:")
        for line in platform_install_hint().splitlines():
            print(f"  {_c(line, GRAY)}")
        print()
        print(f"  Or use Docker: {_c('docker compose up -d postgres', CYAN)}")
        print(f"  Then re-run:   {_c('python dmsai.py setup', CYAN)}")
        print()

    if not silent and not changed:
        print(f"  {_c('OK', GREEN)}     already set up")

    if changed and not silent:
        print(f"\n  {_c('Setup complete.', GREEN)} Review .env to set your LLM provider, then run:")
        print(f"  {_c('  python dmsai.py start', CYAN)}\n")

    return changed


def cmd_clean_db() -> None:
    """Drop every DMSAI table from PostgreSQL and clear local storage/models.

    Internal node queues (decentraflow ``internal_queue.db`` SQLite files
    inside each node directory) are also wiped because they cache the same
    document IDs as the central DB.
    """
    print(f"\n{_c('=== Clean Database ===', CYAN)}\n")
    storage_path = ROOT / "data" / "storage"
    models_path = ROOT / "data" / "models"

    running = any(is_port_open(s["port"]) for s in SERVICES)
    if running:
        print(f"  {_c('Error:', RED)} stop all services first (python dmsai.py stop)")
        sys.exit(1)

    # Drop all tables from Postgres via SQLAlchemy metadata.
    sys.path.insert(0, str(ROOT / "shared"))
    try:
        from sqlmodel import SQLModel
        from dmsai_models import models  # noqa: F401 — registers all tables on metadata
        from dmsai_models.connection import get_engine
        engine = get_engine()
        url = str(engine.url)
        SQLModel.metadata.drop_all(engine)
        print(f"  Dropped all tables on {url.split('@')[-1] if '@' in url else url}")
        # Reset the init guard so the next start re-creates + re-seeds the schema.
        import dmsai_models.connection as _cm
        _cm._INITIALIZED = False  # type: ignore[attr-defined]
    except Exception as e:
        print(f"  {_c('Error:', RED)} could not drop tables: {e}")
        print(f"  Is PostgreSQL running?  Try: {_c('python dmsai.py setup', CYAN)}")
        sys.exit(1)

    # Clear filesystem caches (storage + models)
    import shutil
    for d in [storage_path, models_path]:
        if d.exists():
            shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            print(f"  Cleared  {d}")
        else:
            print(f"  {_c('--', GRAY)}  {d} (not found)")

    # Wipe per-node decentraflow queues so stale task IDs don't leak in.
    nodes_dir = ROOT / "nodes"
    cleared_queues = 0
    if nodes_dir.exists():
        for node_dir in nodes_dir.iterdir():
            queue_db = node_dir / "internal_queue.db"
            if queue_db.exists():
                queue_db.unlink()
                cleared_queues += 1
            # Also remove the WAL/SHM sidecars
            for sfx in ("-wal", "-shm"):
                p = node_dir / f"internal_queue.db{sfx}"
                if p.exists():
                    p.unlink()
    if cleared_queues:
        print(f"  Cleared  {cleared_queues} node task queue(s)")

    print(f"\n  {_c('Database wiped. Will be re-seeded on next start.', GREEN)}\n")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dmsai",
        description="DMSAI CLI - manage the full application stack",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python dmsai.py setup                First-time setup (auto-runs on first start)
  python dmsai.py start                Start everything
  python dmsai.py start --skip-litellm Start without LiteLLM proxy
  python dmsai.py start --only ocr     Start only the OCR node
  python dmsai.py stop                 Stop everything
  python dmsai.py restart              Full restart
  python dmsai.py status               Check what's running
  python dmsai.py logs ocr             Tail the OCR node log
  python dmsai.py clean-db             Wipe DB and storage
        """,
    )
    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser(
        "setup",
        help="First-time setup: create .env, generate secrets, install/provision PostgreSQL, create data dirs",
    )

    p_start = sub.add_parser("start", help="Start all services")
    p_start.add_argument("--skip-litellm", action="store_true", help="Don't start LiteLLM proxy")
    p_start.add_argument("--only", type=str, default="", help="Comma-separated service names to start")

    p_stop = sub.add_parser("stop", help="Stop all services")
    p_stop.add_argument("--only", type=str, default="", help="Comma-separated service names to stop")

    p_restart = sub.add_parser("restart", help="Stop then start all services")
    p_restart.add_argument("--skip-litellm", action="store_true")
    p_restart.add_argument("--only", type=str, default="")

    sub.add_parser("status", help="Show service status")

    p_logs = sub.add_parser("logs", help="Tail a service log")
    p_logs.add_argument("service", help="Service name (or prefix)")

    sub.add_parser("clean-db", help="Wipe database and storage for a fresh start")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    def _filter(only: str) -> list[dict]:
        if not only:
            return list(SERVICES)
        names = [n.strip() for n in only.split(",")]
        return [s for s in SERVICES if any(n in s["name"] for n in names)]

    if args.command == "setup":
        print(f"\n{_c('=== DMSAI Setup ===', CYAN)}\n")
        cmd_setup()
    elif args.command == "start":
        svcs = _filter(args.only)
        cmd_start(svcs, args.skip_litellm)
    elif args.command == "stop":
        svcs = _filter(args.only)
        cmd_stop(svcs)
    elif args.command == "restart":
        svcs = _filter(args.only)
        cmd_restart(svcs, args.skip_litellm)
    elif args.command == "status":
        cmd_status(SERVICES)
    elif args.command == "logs":
        cmd_logs(SERVICES, args.service)
    elif args.command == "clean-db":
        cmd_clean_db()


if __name__ == "__main__":
    main()
