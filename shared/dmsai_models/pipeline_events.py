"""Helpers for persisting pipeline stage events (used by worker nodes)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from .connection import get_session, init_db
from .models import PipelineEvent


def record_pipeline_event(
    document_id: str,
    stage: str,
    event_type: str,
    details: Optional[str] = None,
) -> None:
    """Insert a PipelineEvent row. Safe to call from node workers sharing the same DB."""
    init_db()
    with get_session() as session:
        ev = PipelineEvent(
            id=str(uuid.uuid4()),
            document_id=document_id,
            stage=stage,
            event_type=event_type,
            timestamp=datetime.utcnow(),
            details=details,
        )
        session.add(ev)
        session.commit()
