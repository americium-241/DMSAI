"""
DecentraFlow — Structured JSON Log Formatter

Formats log records as machine-parseable JSON lines.
External scrapers (Promtail, Grafana Alloy, Fluentd) consume
these files and push to Loki for centralized aggregation.

Local log files remain the single source of truth — no push
dependency on any external system.  Nodes stay autonomous.
"""

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Output example:
        {"timestamp":"2024-01-01T12:00:00.123Z","level":"INFO",
         "service":"ocr_node","environment":"prod","message":"Task xyz queued."}

    Designed to be scraped by Promtail/Alloy → Loki with
    pipeline_stages: [json] for label extraction.
    """

    def __init__(self, service_name: str = "unknown", environment: str = "dev"):
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "service": self.service_name,
            "environment": self.environment,
            "message": record.getMessage(),
        }

        # Include workflow_id if present (structured correlation)
        if hasattr(record, "workflow_id"):
            log_entry["workflow_id"] = record.workflow_id

        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)

