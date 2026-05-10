#!/usr/bin/env python3
"""
DMSAI native installer — cross-platform (Windows, Linux, macOS).

Usage:
    python scripts/install.py

Installs Python dependencies, the frontend, and PostgreSQL natively
(winget on Windows, brew on macOS, apt/dnf on Linux), then provisions
the dmsai role + database and wires up .env.

Requires Python 3.11+ and npm (for the frontend).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _step(n: int, total: int, msg: str) -> None:
    print(f"\n[{n}/{total}] {msg}", flush=True)


def _run(*args: str, cwd: Path | None = None) -> None:
    """Run a command, streaming output, and raise on non-zero exit."""
    cmd = list(args)
    print("  $", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"\nERROR: command failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def _ensure_postgres_in_env(env_file: Path) -> None:
    """Make sure DMSAI_DB_URL in .env points at PostgreSQL.

    Comments out any non-postgres URL and appends the default postgres URL
    if one isn't already present.  Idempotent.
    """
    if not env_file.exists():
        return
    pg_url = "postgresql+psycopg://dmsai:dmsai@localhost:5432/dmsai"
    text = env_file.read_text(encoding="utf-8")
    new_lines: list[str] = []
    has_pg = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("DMSAI_DB_URL=postgres"):
            has_pg = True
            new_lines.append(line)
        elif stripped.startswith("DMSAI_DB_URL="):
            new_lines.append("# " + line)
        else:
            new_lines.append(line)
    if not has_pg:
        new_lines.append(f"\nDMSAI_DB_URL={pg_url}\n")
    new_text = "".join(new_lines)
    if new_text != text:
        env_file.write_text(new_text, encoding="utf-8")
        print(f"  DMSAI_DB_URL set to {pg_url}")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    total = 7

    print()
    print("=== DMSAI Native Installer ===")
    print(f"    Python: {sys.executable}")
    print(f"    Root:   {root}")
    print(f"    DB:     PostgreSQL (native)")
    print()

    # 1 — Environment file
    _step(1, total, "Environment file")
    env_file = root / ".env"
    example_file = root / ".env.example"
    if not env_file.exists():
        shutil.copy(example_file, env_file)
        print("  Created .env from .env.example")
        print("  Edit .env and set your LLM provider keys (DMSAI_JWT_SECRET / DMSAI_INTERNAL_API_KEY are auto-generated).")
    else:
        print("  .env already exists, skipping.")

    # 2 — Shared Python packages
    _step(2, total, "Shared Python packages (core_framework + shared)")
    _run(sys.executable, "-m", "pip", "install", "-e", "core_framework", "-e", "shared", cwd=root)

    # 3 — API gateway
    _step(3, total, "API gateway dependencies")
    _run(sys.executable, "-m", "pip", "install", "-r", "api_gateway/requirements.txt", cwd=root)

    # 4 — Pipeline nodes
    _step(4, total, "Pipeline node dependencies")
    nodes_dir = root / "nodes"
    for node_dir in sorted(nodes_dir.iterdir()):
        req = node_dir / "requirements.txt"
        if node_dir.is_dir() and req.exists():
            print(f"  {node_dir.name}")
            _run(sys.executable, "-m", "pip", "install", "-r", str(req), cwd=root)

    # 4b — LiteLLM proxy (separate extra that is NOT in node requirements)
    _step(5, total, "LiteLLM proxy dependencies")
    litellm_req = root / "requirements-litellm.txt"
    if litellm_req.exists():
        _run(sys.executable, "-m", "pip", "install", "-r", str(litellm_req), cwd=root)
    else:
        _run(sys.executable, "-m", "pip", "install", "litellm[proxy]>=1.40", cwd=root)

    # 6 — Frontend
    _step(6, total, "Frontend dependencies (npm install)")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    if not shutil.which(npm_cmd) and not shutil.which("npm"):
        print("  WARNING: npm not found. Skipping frontend install.")
        print("           Install Node.js 18+ from https://nodejs.org and re-run.")
    else:
        _run(npm_cmd if shutil.which(npm_cmd) else "npm", "install", cwd=root / "frontend")

    # 7 — PostgreSQL (always)
    _step(7, total, "PostgreSQL native install + database provisioning")
    sys.path.insert(0, str(root / "scripts"))
    from postgres_setup import bootstrap, platform_install_hint  # noqa: E402

    ok = bootstrap()
    if ok:
        _ensure_postgres_in_env(env_file)
    else:
        print()
        print("  PostgreSQL setup did not complete automatically.")
        print("  Manual install instructions for your platform:")
        print()
        for line in platform_install_hint().splitlines():
            print(f"  {line}")
        print()
        print("  After installing Postgres manually, finish with:")
        print("    python dmsai.py setup")
        sys.exit(1)

    # Done
    print()
    print("=== Installation complete ===")
    print()
    print("Next steps:")
    print("  1. Edit .env  — set your LLM provider keys (Ollama works out of the box).")
    print("  2. Start the stack:   python dmsai.py start")
    print("  3. Open the app:      http://localhost:5173")
    print("  4. Default admin:     admin@dmsai.com / admin123")
    print()


if __name__ == "__main__":
    main()
