"""Cross-dialect SQL helpers.

DMSAI runs on PostgreSQL in production and SQLite in tests.  These two
engines disagree on a handful of common functions (date formatting being
the worst offender: SQLite has ``strftime``, Postgres has ``to_char``).

Use the helpers in this module instead of calling ``func.strftime`` or
``func.to_char`` directly so the same query works on both back-ends.
"""

from __future__ import annotations

from sqlalchemy import func

from .connection import get_engine


def _is_postgres() -> bool:
    return get_engine().dialect.name == "postgresql"


def date_str(col):
    """Format a timestamp column as ``YYYY-MM-DD`` (string).

    Used for daily grouping/trend queries.  Returns a string in both
    dialects so Python-side dict lookups by date string work uniformly.
    """
    if _is_postgres():
        return func.to_char(col, "YYYY-MM-DD")
    return func.strftime("%Y-%m-%d", col)


def year_week_str(col):
    """Format a timestamp column as ``YYYY-WW`` (year + week number).

    SQLite uses ``%Y-%W`` (week starts Monday, 00-53).
    Postgres uses ``IYYY-IW`` (ISO 8601 week-numbering year + ISO week).

    The exact week numbering can differ by one near year boundaries, but
    weekly trend charts work the same way on both engines.
    """
    if _is_postgres():
        return func.to_char(col, "IYYY-IW")
    return func.strftime("%Y-%W", col)
