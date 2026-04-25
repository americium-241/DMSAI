from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class Task(SQLModel, table=True):
    """
    Represents a single unit of work in a node's local SQLite queue.

    Lifecycle:  PENDING  ->  PROCESSING  ->  COMPLETED
                                          ->  PENDING (retry with backoff)
                                          ->  DEAD_LETTER (max retries exhausted)
    """

    id: str = Field(primary_key=True)
    payload: str
    status: str = Field(default="PENDING")

    # ── Priority (higher = more urgent, 0 = normal) ─────────
    priority: int = Field(default=0)

    # ── Retry / Dead-Letter fields ───────────────────────────
    retry_count: int = Field(default=0)
    next_retry_at: Optional[datetime] = Field(default=None)
    error_message: Optional[str] = Field(default=None)

    # ── Timestamps ───────────────────────────────────────────
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = Field(default=None)
    started_processing_at: Optional[datetime] = Field(default=None)
