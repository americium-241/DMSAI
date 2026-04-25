#!/usr/bin/env python3
"""
DMSAI CLI - manage the full application stack.

Usage:
    python dmsai.py start           Start all services
    python dmsai.py stop            Stop all services
    python dmsai.py restart         Restart all services
    python dmsai.py status          Show service status
    python dmsai.py logs <service>  Tail the log of a service
    python dmsai.py clean-db        Wipe all data for a fresh start

Options:
    --skip-litellm      Don't start the LiteLLM proxy
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

SERVICES: list[dict] = [
    {"name": "ingestion",          "port": 8010, "kind": "node", "dir": "nodes/ingestion_node"},
    {"name": "conversion",         "port": 8011, "kind": "node", "dir": "nodes/conversion_node"},
    {"name": "storage",            "port": 8012, "kind": "node", "dir": "nodes/storage_node"},
    {"name": "ocr",                "port": 8013, "kind": "node", "dir": "nodes/ocr_node"},
    {"name": "embedding",          "port": 8014, "kind": "node", "dir": "nodes/embedding_node"},
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
            env["GEMINI_API_KEY"] = api_key
            env["GOOGLE_API_KEY"] = api_key
    elif kind == "frontend":
        cmd = "npm run dev"
    else:
        return

    with open(log, "w") as lf:
        if sys.platform == "win32":
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                cmd, shell=True, cwd=str(work_dir), env=env,
                stdout=lf, stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen(
                cmd, shell=True, cwd=str(work_dir), env=env,
                stdout=lf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    print(f"  {_c('START', CYAN)}  {name:<24} :{port}  -> {log.name}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(services: list[dict], skip_litellm: bool) -> None:
    print(f"\n{_c('=== Starting DMSAI ===', CYAN)}\n")
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
        print(f"\n  App:  {_c('http://localhost:5173', CYAN)}")
        print(f"  API:  {_c('http://localhost:8080/api', CYAN)}")

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


def cmd_clean_db() -> None:
    print(f"\n{_c('=== Clean Database ===', CYAN)}\n")
    db_path = ROOT / "data" / "dmsai.db"
    storage_path = ROOT / "data" / "storage"
    models_path = ROOT / "data" / "models"

    running = any(is_port_open(s["port"]) for s in SERVICES)
    if running:
        print(f"  {_c('Error:', RED)} stop all services first (python dmsai.py stop)")
        sys.exit(1)

    if db_path.exists():
        db_path.unlink()
        print(f"  Deleted {db_path}")
    else:
        print(f"  {_c('--', GRAY)}  {db_path} (not found)")

    import shutil
    for d in [storage_path, models_path]:
        if d.exists():
            shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            print(f"  Cleared  {d}")
        else:
            print(f"  {_c('--', GRAY)}  {d} (not found)")

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

    if args.command == "start":
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
