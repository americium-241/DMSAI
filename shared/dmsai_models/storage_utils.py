"""
Storage path utilities.

Design contract
---------------
* The ``storage_path`` column in the ``document`` table stores a path that is
  **relative to ``DMSAI_STORAGE_ROOT``** (e.g. ``2026/05/abc123.pdf``).
  This keeps the DB portable: the same database can be used in any checkout
  or on any machine as long as ``DMSAI_STORAGE_ROOT`` points to the files.

* ``dmsai.py`` always resolves ``DMSAI_STORAGE_ROOT`` to an absolute path
  (relative to the project root) before spawning child processes, so the env
  var is always absolute at runtime.

* ``resolve_storage_path(relative)`` converts a relative DB value to an
  absolute OS path.  It also accepts already-absolute paths for backward
  compatibility with databases created before this convention was introduced.

* ``to_relative_storage_path(absolute)`` is the inverse: given an absolute
  file path, strip the storage root prefix so only the portable relative part
  is stored in the DB.
"""
from __future__ import annotations

import os
from pathlib import Path


def _storage_root() -> Path:
    """Return the configured storage root as an absolute Path.

    Priority:
    1. ``DMSAI_STORAGE_ROOT`` env var  (set to absolute by dmsai.py)
    2. ``./data/storage/documents`` relative to CWD  (fallback for tests)
    """
    raw = os.environ.get("DMSAI_STORAGE_ROOT", "")
    if raw:
        p = Path(raw)
        return p.resolve() if not p.is_absolute() else p
    return Path("data/storage/documents").resolve()


def resolve_storage_path(path: str | None) -> str:
    """Return an absolute OS path for a document.

    * If ``path`` is already absolute (legacy or machine-local), return as-is.
    * If ``path`` is relative, join it with ``DMSAI_STORAGE_ROOT``.
    * If ``path`` is ``None`` / empty, return ``""``.
    """
    if not path:
        return ""
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str(_storage_root() / p)


def to_relative_storage_path(absolute_path: str) -> str:
    """Convert an absolute path to a path relative to DMSAI_STORAGE_ROOT.

    If the path is not under the storage root (unusual), return the original
    so nothing is silently lost.
    """
    if not absolute_path:
        return absolute_path
    try:
        rel = Path(absolute_path).relative_to(_storage_root())
        # Always use forward slashes in the DB for cross-platform portability
        return rel.as_posix()
    except ValueError:
        return absolute_path
