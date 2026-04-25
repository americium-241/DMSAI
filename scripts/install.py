#!/usr/bin/env python3
"""
DMSAI native installer — cross-platform (Windows, Linux, macOS).

Usage:
    python scripts/install.py

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


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    total = 5

    print()
    print("=== DMSAI Native Installer ===")
    print(f"    Python: {sys.executable}")
    print(f"    Root:   {root}")
    print()

    # 1 — Environment file
    _step(1, total, "Environment file")
    env_file = root / ".env"
    example_file = root / ".env.example"
    if not env_file.exists():
        shutil.copy(example_file, env_file)
        print("  Created .env from .env.example")
        print("  ⚠  Edit .env and set DMSAI_JWT_SECRET, DMSAI_INTERNAL_API_KEY, and your LLM keys.")
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

    # 5 — Frontend
    _step(5, total, "Frontend dependencies (npm install)")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    if not shutil.which(npm_cmd) and not shutil.which("npm"):
        print("  WARNING: npm not found. Skipping frontend install.")
        print("           Install Node.js 18+ from https://nodejs.org and re-run.")
    else:
        _run(npm_cmd if shutil.which(npm_cmd) else "npm", "install", cwd=root / "frontend")

    # Done
    print()
    print("=== Installation complete ===")
    print()
    print("Next steps:")
    print("  1. Edit .env  — set DMSAI_JWT_SECRET, DMSAI_INTERNAL_API_KEY, and your LLM keys.")
    print("  2. Start the stack:   python dmsai.py start")
    print("  3. Open the app:      http://localhost:5173")
    print("  4. Default admin:     admin@dmsai.com / admin123")
    print()


if __name__ == "__main__":
    main()
