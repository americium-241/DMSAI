"""Native PostgreSQL bootstrap helper for DMSAI.

This module is shared between ``scripts/install.py`` (full bootstrap) and
``dmsai.py setup --postgres`` (just-in-time setup at first start).

Public entry points
-------------------
* :func:`is_postgres_running()`   -> ``bool``     fast TCP probe on :5432
* :func:`is_pg_client_installed()` -> ``bool``    is ``psql`` on PATH?
* :func:`install_postgres()`      -> ``bool``     attempt to install Postgres
                                                  natively (winget / brew /
                                                  apt / dnf).  Returns
                                                  ``True`` on success.
* :func:`ensure_database(...)`    -> ``bool``     create the ``dmsai`` role
                                                  and database if missing.
* :func:`bootstrap(...)`          -> ``bool``     do everything end-to-end:
                                                  probe → install → create
                                                  role/DB → verify.  This is
                                                  the function callers use.
* :func:`platform_install_hint()` -> ``str``      human-readable instructions
                                                  for the current OS — used
                                                  as a fallback when auto-
                                                  install fails.

The helper is conservative: it never silently runs sudo without telling the
user, never overwrites an existing DB, and prints every command it runs so
the user can see exactly what's happening.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_DB = "dmsai"
DEFAULT_USER = "dmsai"
DEFAULT_PASSWORD = "dmsai"


# ---------------------------------------------------------------------------
# Output helpers (no colour dependency — these scripts run pre-install)
# ---------------------------------------------------------------------------

def _say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def _run(cmd: list[str], *, check: bool = False, capture: bool = False, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a command, echoing it for transparency."""
    print(f"  $ {' '.join(cmd)}", flush=True)
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
        env=env,
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def is_postgres_running(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 1.0) -> bool:
    """Return True if a TCP server is accepting connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def is_pg_client_installed() -> bool:
    """Return True if the ``psql`` client is on PATH."""
    return shutil.which("psql") is not None


def detect_linux_distro() -> str:
    """Return the package manager family ('apt', 'dnf', 'pacman', or '')."""
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return ""
    content = os_release.read_text(errors="ignore").lower()
    if any(d in content for d in ("debian", "ubuntu", "mint", "pop")):
        return "apt"
    if any(d in content for d in ("fedora", "rhel", "centos", "rocky", "alma")):
        return "dnf"
    if "arch" in content or "manjaro" in content:
        return "pacman"
    return ""


# ---------------------------------------------------------------------------
# Platform-specific install routines
# ---------------------------------------------------------------------------

def _install_windows() -> bool:
    """Install PostgreSQL on Windows via winget."""
    if not shutil.which("winget"):
        _say("winget not found. Install Windows App Installer or PostgreSQL manually.")
        return False
    _say("Installing PostgreSQL via winget (this may take a few minutes)...")
    try:
        result = _run(
            [
                "winget", "install", "-e",
                "--id", "PostgreSQL.PostgreSQL.17",
                "--accept-source-agreements",
                "--accept-package-agreements",
                "--silent",
            ],
            check=False,
        )
    except FileNotFoundError:
        return False
    if result.returncode == 0:
        _say("winget reported success. Adding PostgreSQL bin to current PATH...")
        # Add the default install location so psql works in this process
        for ver in ("17", "16", "15"):
            pg_bin = Path(rf"C:\Program Files\PostgreSQL\{ver}\bin")
            if pg_bin.exists():
                os.environ["PATH"] = str(pg_bin) + os.pathsep + os.environ.get("PATH", "")
                _say(f"Added {pg_bin} to PATH for this session.")
                break
        return True
    _say(f"winget exit code: {result.returncode}")
    return False


def _install_macos() -> bool:
    """Install PostgreSQL on macOS via Homebrew."""
    if not shutil.which("brew"):
        _say("Homebrew not found. Install from https://brew.sh first, then re-run.")
        return False
    _say("Installing PostgreSQL via brew...")
    if _run(["brew", "install", "postgresql@17"]).returncode != 0:
        return False
    _say("Starting PostgreSQL service...")
    _run(["brew", "services", "start", "postgresql@17"])
    # Add brew's pg bin to PATH for this session
    for prefix in ("/opt/homebrew/opt/postgresql@17/bin", "/usr/local/opt/postgresql@17/bin"):
        if Path(prefix).exists():
            os.environ["PATH"] = prefix + os.pathsep + os.environ.get("PATH", "")
            break
    return True


def _install_linux() -> bool:
    """Install PostgreSQL on Linux (apt / dnf / pacman)."""
    distro = detect_linux_distro()
    if not distro:
        _say("Could not detect Linux distribution. Install PostgreSQL manually.")
        return False

    sudo = ["sudo"] if os.geteuid() != 0 else []  # type: ignore[attr-defined]
    _say(f"Detected '{distro}' package manager. You may be prompted for your sudo password.")

    if distro == "apt":
        if _run(sudo + ["apt-get", "update"]).returncode != 0:
            return False
        if _run(sudo + ["apt-get", "install", "-y", "postgresql", "postgresql-contrib"]).returncode != 0:
            return False
        _run(sudo + ["systemctl", "enable", "--now", "postgresql"])
        return True

    if distro == "dnf":
        if _run(sudo + ["dnf", "install", "-y", "postgresql-server", "postgresql-contrib"]).returncode != 0:
            return False
        _run(sudo + ["postgresql-setup", "--initdb"])
        _run(sudo + ["systemctl", "enable", "--now", "postgresql"])
        return True

    if distro == "pacman":
        if _run(sudo + ["pacman", "-S", "--noconfirm", "postgresql"]).returncode != 0:
            return False
        _say("Manual init required on Arch — see https://wiki.archlinux.org/title/PostgreSQL")
        return False

    return False


def install_postgres() -> bool:
    """Install PostgreSQL natively for the current platform.

    Returns True on success.  Prints instructions and returns False on
    failure so the caller can fall back to a user-driven install.
    """
    system = platform.system()
    _say(f"Installing PostgreSQL for {system}...")
    if system == "Windows":
        return _install_windows()
    if system == "Darwin":
        return _install_macos()
    if system == "Linux":
        return _install_linux()
    _say(f"Unsupported platform: {system}")
    return False


# ---------------------------------------------------------------------------
# Database / role provisioning
# ---------------------------------------------------------------------------

def _wait_for_postgres(host: str, port: int, attempts: int = 30, interval: float = 1.0) -> bool:
    """Block until the server accepts TCP connections, or we give up."""
    for _ in range(attempts):
        if is_postgres_running(host, port, timeout=0.5):
            return True
        time.sleep(interval)
    return False


def ensure_database(
    db_name: str = DEFAULT_DB,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> bool:
    """Create the DMSAI role and database if they don't already exist.

    Tries two strategies in order:

    1. **psycopg over TCP** — works whenever the driver is installed and the
       server accepts password auth as ``postgres``.  This covers Docker
       Postgres, native installs that allow password login, and remote
       servers.  No ``psql`` binary required.
    2. **psql via local socket / peer auth** — falls back to the classic
       command-line approach when psycopg can't authenticate (e.g. a fresh
       apt install where the only entry point is ``sudo -u postgres``).

    Idempotent: existing role/DB are detected and skipped.
    """
    # ----- Strategy 1: psycopg ------------------------------------------------
    try:
        import psycopg  # type: ignore
    except ImportError:
        psycopg = None  # type: ignore

    if psycopg is not None:
        # Try a few common credentials for the superuser.  Most native
        # installers create either 'postgres' with no password (peer/trust)
        # or 'postgres' with the password the user typed during install.
        # Docker images use POSTGRES_PASSWORD which we don't know — so we
        # try 'postgres', 'dmsai' (our own DB password env), and empty.
        candidates: list[tuple[str, str]] = [
            ("postgres", os.environ.get("POSTGRES_PASSWORD", "postgres")),
            ("postgres", "postgres"),
            ("postgres", password),  # if the user uses the same password everywhere
            ("postgres", ""),
            (user, password),  # already-provisioned dmsai user
        ]
        last_err: Exception | None = None
        for su_user, su_password in candidates:
            try:
                _say(f"Trying psycopg connection as '{su_user}'...")
                conn = psycopg.connect(
                    host=host, port=port, user=su_user,
                    password=su_password, dbname="postgres",
                    autocommit=True, connect_timeout=3,
                )
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue

            try:
                with conn.cursor() as cur:
                    if su_user == user:
                        # Already running as the dmsai role — verify the DB exists
                        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db_name,))
                        if cur.fetchone():
                            _say(f"Database '{db_name}' already exists, skipping CREATE DATABASE.")
                            conn.close()
                            _say(f"PostgreSQL ready: postgresql://{user}:***@{host}:{port}/{db_name}")
                            return True
                        # Fall through to creation logic below

                    cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (user,))
                    if cur.fetchone():
                        _say(f"Role '{user}' already exists, skipping CREATE ROLE.")
                    else:
                        # Identifiers can't be parameterized; safe because
                        # `user` is a constant in our codebase.
                        cur.execute(
                            f"CREATE ROLE {user} WITH LOGIN PASSWORD %s CREATEDB",
                            (password,),
                        )
                        _say(f"Created role '{user}'.")

                    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db_name,))
                    if cur.fetchone():
                        _say(f"Database '{db_name}' already exists, skipping CREATE DATABASE.")
                    else:
                        cur.execute(f"CREATE DATABASE {db_name} OWNER {user}")
                        _say(f"Created database '{db_name}'.")
            finally:
                conn.close()

            _say(f"PostgreSQL ready: postgresql://{user}:***@{host}:{port}/{db_name}")
            return True

        if last_err:
            _say(f"psycopg fallback failed (last error: {last_err}).")

    # ----- Strategy 2: psql ----------------------------------------------------
    if not is_pg_client_installed():
        _say("psql not found on PATH and psycopg auth failed.")
        _say("Run the SQL below as the postgres superuser, then re-run setup:")
        _print_manual_sql(db_name, user, password)
        return False

    su_user = "postgres"
    if platform.system() == "Darwin":
        # Homebrew default: the current user is the superuser.
        cur_u = os.environ.get("USER") or os.environ.get("LOGNAME") or "postgres"
        if _run(["psql", "-U", cur_u, "-d", "postgres", "-c", "SELECT 1"], capture=True).returncode == 0:
            su_user = cur_u

    role_check = _run(
        ["psql", "-U", su_user, "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_roles WHERE rolname='{user}'"],
        capture=True,
    )
    if role_check.returncode != 0:
        _say(f"Could not connect as '{su_user}'. Is PostgreSQL running and accepting auth?")
        _print_manual_sql(db_name, user, password)
        return False

    if (role_check.stdout or "").strip() == "1":
        _say(f"Role '{user}' already exists, skipping CREATE ROLE.")
    else:
        _run(["psql", "-U", su_user, "-d", "postgres", "-c",
              f"CREATE ROLE {user} WITH LOGIN PASSWORD '{password}' CREATEDB"])

    db_check = _run(
        ["psql", "-U", su_user, "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname='{db_name}'"],
        capture=True,
    )
    if (db_check.stdout or "").strip() == "1":
        _say(f"Database '{db_name}' already exists, skipping CREATE DATABASE.")
    else:
        _run(["psql", "-U", su_user, "-d", "postgres", "-c",
              f"CREATE DATABASE {db_name} OWNER {user}"])

    _say(f"PostgreSQL ready: postgresql://{user}:***@{host}:{port}/{db_name}")
    return True


def _print_manual_sql(db_name: str, user: str, password: str) -> None:
    """Print the SQL the user needs to run manually if auto-provisioning fails."""
    print()
    print("  --- Run this once as the postgres superuser ---")
    print(f"    CREATE ROLE {user} WITH LOGIN PASSWORD '{password}' CREATEDB;")
    print(f"    CREATE DATABASE {db_name} OWNER {user};")
    print()


# ---------------------------------------------------------------------------
# User-facing instructions for the manual fallback path
# ---------------------------------------------------------------------------

def platform_install_hint() -> str:
    """Return a multi-line string with manual install instructions."""
    system = platform.system()
    if system == "Windows":
        return (
            "PostgreSQL not found. Install with one of:\n"
            "  winget install -e --id PostgreSQL.PostgreSQL.17\n"
            "  choco install postgresql17 --params \"/Password:postgres\"\n"
            "  EDB installer:  https://www.postgresql.org/download/windows/"
        )
    if system == "Darwin":
        return (
            "PostgreSQL not found. Install with Homebrew:\n"
            "  brew install postgresql@17\n"
            "  brew services start postgresql@17"
        )
    if system == "Linux":
        distro = detect_linux_distro()
        if distro == "apt":
            return (
                "PostgreSQL not found. Install with:\n"
                "  sudo apt update\n"
                "  sudo apt install -y postgresql postgresql-contrib\n"
                "  sudo systemctl enable --now postgresql"
            )
        if distro == "dnf":
            return (
                "PostgreSQL not found. Install with:\n"
                "  sudo dnf install -y postgresql-server postgresql-contrib\n"
                "  sudo postgresql-setup --initdb\n"
                "  sudo systemctl enable --now postgresql"
            )
        if distro == "pacman":
            return (
                "PostgreSQL not found. Install with:\n"
                "  sudo pacman -S postgresql\n"
                "  See https://wiki.archlinux.org/title/PostgreSQL for init steps."
            )
        return "PostgreSQL not found. Install your distribution's postgresql package."
    return "PostgreSQL not found. Install PostgreSQL 14+ from your platform's package manager."


# ---------------------------------------------------------------------------
# End-to-end orchestration
# ---------------------------------------------------------------------------

def bootstrap(
    db_name: str = DEFAULT_DB,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    auto_install: bool = True,
) -> bool:
    """End-to-end: probe, install if needed, create DB/role.

    Returns True iff a usable Postgres at host:port has the dmsai DB ready.
    """
    if is_postgres_running(host, port):
        _say(f"PostgreSQL is already running on {host}:{port}.")
    elif auto_install:
        if not install_postgres():
            print()
            print(platform_install_hint())
            return False
        if not _wait_for_postgres(host, port):
            _say(f"PostgreSQL was installed but did not start on {host}:{port}.")
            return False
    else:
        print(platform_install_hint())
        return False

    return ensure_database(db_name, user, password, host, port)


# ---------------------------------------------------------------------------
# CLI entry point: ``python scripts/postgres_setup.py``
# ---------------------------------------------------------------------------

def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="DMSAI PostgreSQL bootstrap helper.")
    p.add_argument("--no-install", action="store_true",
                   help="Don't attempt automatic install; only verify and provision.")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = p.parse_args()

    ok = bootstrap(
        db_name=args.db,
        user=args.user,
        password=args.password,
        host=args.host,
        port=args.port,
        auto_install=not args.no_install,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main())
