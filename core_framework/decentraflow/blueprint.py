import asyncio
import httpx
import yaml
import logging
import json
import time
import inspect
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy import text
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, Type, Tuple, Callable
from pydantic import BaseModel

from .models import Task
from .json_logger import JsonFormatter
from .metrics import MetricsCollector


class ForwardingError(Exception):
    """Raised when forwarding to at least one healthy downstream peer fails."""

    pass


class NodeBlueprint:
    """
    Core building block for DecentraFlow nodes.

    Each NodeBlueprint creates a fully autonomous microservice with:
    - FastAPI HTTP server with /ingest, /health, /task/{id}, /dead-letter, /peers, /metrics
    - Local SQLite persistent queue (crash-safe)
    - Structured JSON logging (scraped externally by Promtail/Alloy → Loki)
    - Configurable worker pool for concurrent task processing
    - Exponential backoff retries with dead-letter queue
    - Backpressure (rejects ingestion when queue depth exceeds limit)
    - Optional Pydantic payload schema validation
    - Mesh health monitoring of downstream peers
    - Task processing timeout (prevents worker starvation)
    - Graceful shutdown with in-flight task drain
    - Stale task recovery on startup (crash-safe restart)
    - Forwarding failure triggers task retry (no silent data loss)
    - Automatic database cleanup (TTL-based purging)
    - Optional API key authentication (shared mesh secret)
    - Lifecycle hooks (before_process, after_process, on_failure)
    - Content-based routing via routing_func
    - Task priority (higher priority = processed first)
    - Zero-dependency Prometheus /metrics endpoint

    All settings are read from routing.yaml with sensible defaults,
    so existing nodes work without config changes.
    """

    def __init__(
        self,
        node_name: str,
        process_func,
        config_dir: str = "config",
        log_dir: str = "logs",
        payload_schema: Optional[Type[BaseModel]] = None,
        db_url: str = "sqlite:///internal_queue.db",
        routing_func: Optional[Callable] = None,
    ):
        self.node_name = node_name
        self.process_func = process_func
        self.payload_schema = payload_schema
        self.routing_func = routing_func

        # ── Load routing config ──────────────────────────────────
        with open(f"{config_dir}/routing.yaml", "r") as f:
            self.routing = yaml.safe_load(f)

        # ── Logging (structured JSON files — source of truth) ────
        # External scrapers (Promtail, Alloy) consume these files
        # and push to Loki for centralized aggregation.
        self.logger = logging.getLogger(self.node_name)
        self.logger.setLevel(logging.INFO)
        file_handler = RotatingFileHandler(
            f"{log_dir}/{self.node_name}.log", maxBytes=5_000_000, backupCount=3
        )
        file_handler.setFormatter(
            JsonFormatter(
                service_name=self.node_name,
                environment=self.routing.get("environment", "dev"),
            )
        )
        self.logger.addHandler(file_handler)

        # ── Resilience settings (all optional, backward-compatible) ─
        self.max_retries: int = self.routing.get("max_retries", 3)
        self.backoff_base: float = self.routing.get("backoff_base", 2.0)
        self.max_queue_depth: int = self.routing.get("max_queue_depth", 1000)
        self.max_workers: int = self.routing.get("max_workers", 3)
        self.health_check_interval: int = self.routing.get("health_check_interval", 30)
        self.worker_poll_interval: float = self.routing.get("worker_poll_interval", 1.0)

        # ── Production settings (Tier 1) ─────────────────────────
        self.task_timeout: float = self.routing.get("task_timeout", 300.0)
        self.shutdown_timeout: float = self.routing.get("shutdown_timeout", 30.0)
        self.task_ttl_hours: int = self.routing.get("task_ttl_hours", 72)
        self.dead_letter_ttl_hours: int = self.routing.get("dead_letter_ttl_hours", 168)
        self.cleanup_interval: float = self.routing.get("cleanup_interval", 3600.0)
        self.api_key: Optional[str] = self.routing.get("api_key", None)

        # ── Peer health map ──────────────────────────────────────
        self.peer_health: Dict[str, bool] = {
            url: True for url in self.routing.get("next_nodes", [])
        }

        # ── Async lock for worker task picking ───────────────────
        self._pick_lock = asyncio.Lock()

        # ── Graceful shutdown state ──────────────────────────────
        self._shutting_down = False
        self._active_tasks: set = set()

        # ── Lifecycle hooks (Tier 2) ─────────────────────────────
        self._hooks: Dict[str, list] = {
            "before_process": [],
            "after_process": [],
            "on_failure": [],
        }

        # ── Metrics collector (Tier 2) ───────────────────────────
        self.metrics = MetricsCollector(node_name=self.node_name)

        # ── SQLite persistent queue ──────────────────────────────
        self.engine = create_engine(db_url)
        SQLModel.metadata.create_all(self.engine)
        self._ensure_schema()

        # ── FastAPI application ──────────────────────────────────
        self.app = FastAPI(lifespan=self.lifespan)

        # ── API key authentication middleware (if configured) ────
        if self.api_key:

            @self.app.middleware("http")
            async def auth_middleware(request: Request, call_next):
                # Exempt /health and /metrics from auth (monitoring)
                if request.url.path in ("/health", "/metrics"):
                    return await call_next(request)
                key = request.headers.get("X-API-Key")
                if key != self.api_key:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid or missing API key"},
                    )
                return await call_next(request)

        self._setup_routes()

        self.logger.info(
            f"Node initialized: {self.node_name} "
            f"(routing_func={'yes' if self.routing_func else 'no'}, "
            f"priority=enabled)"
        )

    # ── Schema Migration ────────────────────────────────────────

    def _ensure_schema(self):
        """Add columns from newer versions (safe on fresh databases)."""
        migrations = [
            ("priority", "ALTER TABLE task ADD COLUMN priority INTEGER DEFAULT 0"),
        ]
        with self.engine.connect() as conn:
            for col_name, sql in migrations:
                try:
                    conn.execute(text(f"SELECT {col_name} FROM task LIMIT 1"))
                except Exception:
                    conn.execute(text(sql))
                    conn.commit()

    # ── Lifecycle Hook Registration ─────────────────────────────

    def before_process(self, func):
        """
        Register a hook called BEFORE task processing.
        Receives: (task_id: str, payload: dict)
        Can be sync or async. Errors are logged but don't stop processing.
        Usable as a decorator: @node.before_process
        """
        self._hooks["before_process"].append(func)
        return func

    def after_process(self, func):
        """
        Register a hook called AFTER successful task processing.
        Receives: (task_id: str, result_payload: dict)
        Can be sync or async. Errors are logged but don't stop processing.
        Usable as a decorator: @node.after_process
        """
        self._hooks["after_process"].append(func)
        return func

    def on_failure(self, func):
        """
        Register a hook called when a task fails (exception/timeout/forwarding).
        Receives: (task_id: str, payload: dict, error_message: str)
        Can be sync or async. Errors are logged but don't stop processing.
        Usable as a decorator: @node.on_failure
        """
        self._hooks["on_failure"].append(func)
        return func

    async def _run_hooks(self, event: str, *args):
        """Execute all registered hooks for an event. Fire-and-forget."""
        for hook in self._hooks.get(event, []):
            try:
                if inspect.iscoroutinefunction(hook):
                    await hook(*args)
                else:
                    hook(*args)
            except Exception as e:
                self.logger.error(f"Hook '{event}' error: {str(e)}")

    # ═════════════════════════════════════════════════════════════
    #  LIFECYCLE
    # ═════════════════════════════════════════════════════════════

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        self.logger.info(f"Starting Node: {self.node_name}")
        self.logger.info(
            f"Config: max_retries={self.max_retries}, max_workers={self.max_workers}, "
            f"max_queue_depth={self.max_queue_depth}, "
            f"health_check={self.health_check_interval}s, "
            f"backoff_base={self.backoff_base}s, "
            f"poll_interval={self.worker_poll_interval}s, "
            f"task_timeout={self.task_timeout}s, "
            f"shutdown_timeout={self.shutdown_timeout}s, "
            f"auth={'enabled' if self.api_key else 'disabled'}"
        )

        # ── Stale task recovery (crash-safe restart) ─────────────
        self._recover_stale_tasks()

        # Reset shutdown state (safe for repeated lifespan in tests)
        self._shutting_down = False
        self._active_tasks = set()

        # Start worker pool
        workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.max_workers)
        ]

        # Start peer health checker (only if downstream peers exist)
        health_task = None
        if self.peer_health:
            health_task = asyncio.create_task(self._health_checker())

        # Start database cleanup worker
        cleanup_task = asyncio.create_task(self._cleanup_worker())

        yield

        # ── Graceful Shutdown ────────────────────────────────────
        self._shutting_down = True
        self.logger.info(
            f"Graceful shutdown initiated "
            f"(timeout={self.shutdown_timeout}s, "
            f"in-flight={len(self._active_tasks)})..."
        )

        # Wait for in-flight tasks to complete (up to shutdown_timeout)
        shutdown_start = asyncio.get_event_loop().time()
        while self._active_tasks:
            elapsed = asyncio.get_event_loop().time() - shutdown_start
            if elapsed >= self.shutdown_timeout:
                self.logger.warning(
                    f"Shutdown timeout reached. "
                    f"{len(self._active_tasks)} task(s) still in-flight."
                )
                break
            await asyncio.sleep(0.1)

        # Cancel all background tasks
        for w in workers:
            w.cancel()
        if health_task:
            health_task.cancel()
        cleanup_task.cancel()

        # Roll back any PROCESSING tasks to PENDING for next startup
        self._rollback_processing_tasks()

        self.logger.info(f"Node {self.node_name} shut down.")

    def _recover_stale_tasks(self):
        """
        On startup, find tasks stuck in PROCESSING from a previous crash
        and reset them to PENDING so workers can retry them.
        """
        with Session(self.engine) as session:
            stale = session.exec(
                select(Task).where(Task.status == "PROCESSING")
            ).all()
            for task in stale:
                task.status = "PENDING"
                task.started_processing_at = None
            if stale:
                session.commit()
                self.logger.warning(
                    f"Recovered {len(stale)} stale PROCESSING task(s) "
                    f"from previous crash."
                )

    def _rollback_processing_tasks(self):
        """
        On shutdown, roll back PROCESSING tasks to PENDING
        so they'll be picked up on next startup.
        """
        with Session(self.engine) as session:
            orphaned = session.exec(
                select(Task).where(Task.status == "PROCESSING")
            ).all()
            for task in orphaned:
                task.status = "PENDING"
                task.started_processing_at = None
            if orphaned:
                session.commit()
                self.logger.warning(
                    f"Rolled back {len(orphaned)} in-flight task(s) "
                    f"to PENDING on shutdown."
                )

    # ═════════════════════════════════════════════════════════════
    #  ROUTES
    # ═════════════════════════════════════════════════════════════

    def _setup_routes(self):

        # ── POST /ingest — accept a task (with backpressure + validation) ─
        @self.app.post("/ingest", status_code=202)
        async def ingest_task(payload: Dict[str, Any]):
            task_id = payload.get("workflow_id")
            if not task_id:
                raise HTTPException(status_code=400, detail="Missing workflow_id")

            # Schema validation (if a schema was provided to the blueprint)
            if self.payload_schema:
                try:
                    self.payload_schema(**payload)
                except Exception as e:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Payload validation failed: {str(e)}",
                    )

            # Extract optional priority (default 0, higher = more urgent)
            priority = payload.get("priority", 0)

            with Session(self.engine) as session:
                # Backpressure: reject when the queue is saturated
                active = len(
                    session.exec(
                        select(Task).where(
                            (Task.status == "PENDING") | (Task.status == "PROCESSING")
                        )
                    ).all()
                )
                if active >= self.max_queue_depth:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Queue full ({active}/{self.max_queue_depth}). Try again later.",
                    )

                # Idempotent insert (dedup by workflow_id)
                if not session.exec(select(Task).where(Task.id == task_id)).first():
                    session.add(
                        Task(id=task_id, payload=json.dumps(payload), priority=priority)
                    )
                    session.commit()
                    self.logger.info(f"Task {task_id} queued (priority={priority}).")
                    self.metrics.inc("tasks_ingested_total")

            return {"status": "Accepted"}

        # ── GET /health — node health + queue stats + peer map ────
        @self.app.get("/health")
        async def health():
            with Session(self.engine) as session:
                pending = len(
                    session.exec(select(Task).where(Task.status == "PENDING")).all()
                )
                processing = len(
                    session.exec(select(Task).where(Task.status == "PROCESSING")).all()
                )
                dead = len(
                    session.exec(select(Task).where(Task.status == "DEAD_LETTER")).all()
                )
            return {
                "status": "healthy",
                "node": self.node_name,
                "queue": {
                    "pending": pending,
                    "processing": processing,
                    "dead_letter": dead,
                    "max_depth": self.max_queue_depth,
                },
                "peers": self.peer_health,
            }

        # ── GET /task/{task_id} — inspect a specific task ─────────
        @self.app.get("/task/{task_id}")
        async def get_task_by_id(task_id: str):
            with Session(self.engine) as session:
                task = session.exec(select(Task).where(Task.id == task_id)).first()
                if not task:
                    raise HTTPException(status_code=404, detail="Task not found")
                return {
                    "id": task.id,
                    "status": task.status,
                    "payload": json.loads(task.payload),
                    "priority": task.priority,
                    "retry_count": task.retry_count,
                    "error_message": task.error_message,
                    "created_at": str(task.created_at),
                    "processed_at": (
                        str(task.processed_at) if task.processed_at else None
                    ),
                    "started_processing_at": (
                        str(task.started_processing_at)
                        if task.started_processing_at
                        else None
                    ),
                    "next_retry_at": (
                        str(task.next_retry_at) if task.next_retry_at else None
                    ),
                }

        # ── GET /dead-letter — inspect permanently failed tasks ───
        @self.app.get("/dead-letter")
        async def list_dead_letters():
            with Session(self.engine) as session:
                tasks = session.exec(
                    select(Task).where(Task.status == "DEAD_LETTER")
                ).all()
            return [
                {
                    "id": t.id,
                    "error": t.error_message,
                    "retry_count": t.retry_count,
                    "created_at": str(t.created_at),
                }
                for t in tasks
            ]

        # ── POST /dead-letter/{id}/retry — re-queue a dead letter ─
        @self.app.post("/dead-letter/{task_id}/retry")
        async def retry_dead_letter(task_id: str):
            with Session(self.engine) as session:
                task = session.exec(
                    select(Task).where(
                        Task.id == task_id, Task.status == "DEAD_LETTER"
                    )
                ).first()
                if not task:
                    raise HTTPException(
                        status_code=404, detail="Dead letter task not found"
                    )
                task.status = "PENDING"
                task.retry_count = 0
                task.next_retry_at = None
                task.error_message = None
                session.commit()
                self.logger.info(f"Dead letter task {task_id} re-queued.")
            return {"status": "Re-queued", "task_id": task_id}

        # ── GET /peers — live peer health map ─────────────────────
        @self.app.get("/peers")
        async def peers():
            return {
                "peers": [
                    {"url": url, "healthy": healthy}
                    for url, healthy in self.peer_health.items()
                ]
            }

        # ── GET /metrics — Prometheus exposition format ───────────
        @self.app.get("/metrics")
        async def prometheus_metrics():
            # Update live gauges from the database
            with Session(self.engine) as session:
                pending = len(
                    session.exec(
                        select(Task).where(Task.status == "PENDING")
                    ).all()
                )
                processing = len(
                    session.exec(
                        select(Task).where(Task.status == "PROCESSING")
                    ).all()
                )
                dead = len(
                    session.exec(
                        select(Task).where(Task.status == "DEAD_LETTER")
                    ).all()
                )
            self.metrics.set_gauge("queue_pending", pending)
            self.metrics.set_gauge("queue_processing", processing)
            self.metrics.set_gauge("queue_dead_letter", dead)

            return PlainTextResponse(
                content=self.metrics.render(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

    # ═════════════════════════════════════════════════════════════
    #  WORKER POOL
    # ═════════════════════════════════════════════════════════════

    async def _worker(self, worker_id: int):
        """
        Independent worker coroutine.
        Each worker polls for the next ready task, processes it, and loops.
        Multiple workers run concurrently (controlled by max_workers).
        Stops picking new tasks when _shutting_down is set.
        """
        while True:
            try:
                if self._shutting_down:
                    self.logger.info(
                        f"[Worker-{worker_id}] Stopping (shutdown in progress)."
                    )
                    break
                task_data = await self._pick_next_task()
                if task_data:
                    task_id, payload_str = task_data
                    await self._process_task(task_id, payload_str, worker_id)
                else:
                    # No work available — back off to avoid busy-spinning
                    await asyncio.sleep(self.worker_poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"[Worker-{worker_id}] Loop error: {str(e)}")
                await asyncio.sleep(self.worker_poll_interval)

    async def _pick_next_task(self) -> Optional[Tuple[str, str]]:
        """
        Atomically pick the next ready task and mark it PROCESSING.
        Uses an asyncio.Lock to prevent multiple workers from grabbing
        the same task (SQLite doesn't support row-level locking).
        Records started_processing_at for timeout/stale detection.
        Tasks are ordered by priority DESC (higher priority first).
        """
        async with self._pick_lock:
            with Session(self.engine) as session:
                now = datetime.utcnow()
                task = session.exec(
                    select(Task)
                    .where(Task.status == "PENDING")
                    .where(
                        (Task.next_retry_at == None) | (Task.next_retry_at <= now)  # noqa: E711
                    )
                    .order_by(Task.priority.desc())
                    .limit(1)
                ).first()
                if task:
                    task.status = "PROCESSING"
                    task.started_processing_at = datetime.utcnow()
                    session.commit()
                    return (task.id, task.payload)
        return None

    async def _process_task(self, task_id: str, payload_str: str, worker_id: int):
        """
        Execute the node's processing function on a task.

        On success:  persist result, forward to peers, mark COMPLETED.
        On timeout:  treat as failure, increment retry or dead-letter.
        On forwarding failure: treat as failure, retry ensures delivery.
        On exception: increment retry_count, schedule backoff retry,
                      or move to DEAD_LETTER after max_retries exhausted.

        Lifecycle hooks are called at appropriate points:
          - before_process: before process_func execution
          - after_process: after successful completion
          - on_failure: after failure handling (timeout/exception/forwarding)
        """
        self.logger.info(f"[Worker-{worker_id}] Processing Task {task_id}")
        self._active_tasks.add(task_id)
        payload_dict = json.loads(payload_str)
        start_time = time.time()

        try:
            # Run before_process hooks
            await self._run_hooks("before_process", task_id, payload_dict)

            # Execute the AI/ML logic with timeout protection
            result_payload = await asyncio.wait_for(
                self.process_func(payload_dict),
                timeout=self.task_timeout,
            )

            # Forward to healthy downstream peers
            # Raises ForwardingError if any attempted delivery fails
            await self.forward_to_next(result_payload)

            # Record processing duration
            elapsed = time.time() - start_time
            self.metrics.observe("processing_duration_seconds", elapsed)

            # Mark completed and persist enriched payload
            with Session(self.engine) as session:
                task = session.exec(select(Task).where(Task.id == task_id)).first()
                if task:
                    task.payload = json.dumps(result_payload)
                    task.status = "COMPLETED"
                    task.processed_at = datetime.utcnow()
                    task.started_processing_at = None
                    session.commit()

            self.metrics.inc("tasks_completed_total")
            self.logger.info(
                f"[Worker-{worker_id}] Task {task_id} completed ({elapsed:.2f}s)."
            )

            # Run after_process hooks
            await self._run_hooks("after_process", task_id, result_payload)

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            self.metrics.observe("processing_duration_seconds", elapsed)
            self.metrics.inc("tasks_timeout_total")
            error_msg = f"Task timed out after {self.task_timeout}s"
            self.logger.error(
                f"[Worker-{worker_id}] {error_msg}: {task_id}"
            )
            self._handle_task_failure(task_id, error_msg, worker_id)
            await self._run_hooks("on_failure", task_id, payload_dict, error_msg)

        except ForwardingError as e:
            elapsed = time.time() - start_time
            self.metrics.observe("processing_duration_seconds", elapsed)
            self.metrics.inc("forwarding_errors_total")
            error_msg = str(e)
            self.logger.error(f"[Worker-{worker_id}] {error_msg}")
            self._handle_task_failure(task_id, error_msg, worker_id)
            await self._run_hooks("on_failure", task_id, payload_dict, error_msg)

        except Exception as e:
            elapsed = time.time() - start_time
            self.metrics.observe("processing_duration_seconds", elapsed)
            error_msg = str(e)
            self._handle_task_failure(task_id, error_msg, worker_id)
            await self._run_hooks("on_failure", task_id, payload_dict, error_msg)

        finally:
            self._active_tasks.discard(task_id)

    def _handle_task_failure(self, task_id: str, error_msg: str, worker_id: int):
        """
        Centralized failure handling: retry with exponential backoff
        or move to dead-letter queue after max_retries exhausted.
        """
        self.metrics.inc("tasks_failed_total")
        with Session(self.engine) as session:
            task = session.exec(select(Task).where(Task.id == task_id)).first()
            if task:
                task.retry_count += 1
                task.error_message = error_msg
                task.started_processing_at = None

                if task.retry_count >= self.max_retries:
                    # ── Dead Letter: exhausted all retries ────
                    task.status = "DEAD_LETTER"
                    self.metrics.inc("tasks_dead_letter_total")
                    self.logger.error(
                        f"[Worker-{worker_id}] Task {task_id} -> DEAD LETTER "
                        f"after {task.retry_count} attempts: {error_msg}"
                    )
                else:
                    # ── Retry: exponential backoff ────────────
                    backoff_seconds = self.backoff_base * (
                        2 ** (task.retry_count - 1)
                    )
                    task.status = "PENDING"
                    task.next_retry_at = datetime.utcnow() + timedelta(
                        seconds=backoff_seconds
                    )
                    self.metrics.inc("tasks_retried_total")
                    self.logger.warning(
                        f"[Worker-{worker_id}] Task {task_id} failed "
                        f"(attempt {task.retry_count}/{self.max_retries}), "
                        f"retry in {backoff_seconds}s: {error_msg}"
                    )

                session.commit()

    # ═════════════════════════════════════════════════════════════
    #  MESH FORWARDING
    # ═════════════════════════════════════════════════════════════

    async def forward_to_next(self, result_payload: Dict[str, Any]):
        """
        Forward the result payload to downstream peers.

        When routing_func is set, it determines the target nodes
        dynamically based on payload content (content-based routing).
        Otherwise, the static next_nodes list from routing.yaml is used.

        - Unhealthy peers (detected by health checker) are skipped.
        - If any attempted delivery fails (connection error, HTTP 4xx/5xx,
          or backpressure 429), raises ForwardingError which triggers the
          task retry/dead-letter flow.  No silent data loss.
        - Includes API key header when authentication is configured.
        - Downstream nodes dedup by workflow_id, so retries are safe.
        """
        # Determine target nodes: routing_func overrides static config
        if self.routing_func:
            try:
                result = self.routing_func(result_payload)
                if inspect.iscoroutine(result):
                    next_nodes = await result
                else:
                    next_nodes = result
            except Exception as e:
                raise ForwardingError(f"Routing function error: {str(e)}")
        else:
            next_nodes = self.routing.get("next_nodes", [])

        if not next_nodes:
            return

        failed_peers = []
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        async with httpx.AsyncClient() as client:
            for url in next_nodes:
                if not self.peer_health.get(url, True):
                    self.logger.warning(f"Skipping unhealthy peer: {url}")
                    continue
                try:
                    resp = await client.post(
                        f"{url}/ingest",
                        json=result_payload,
                        timeout=10.0,
                        headers=headers,
                    )
                    if resp.status_code == 429:
                        self.logger.warning(
                            f"Peer {url} is applying backpressure (429)."
                        )
                        failed_peers.append(url)
                    elif resp.status_code >= 400:
                        self.logger.error(
                            f"Peer {url} returned HTTP {resp.status_code}."
                        )
                        failed_peers.append(url)
                    else:
                        self.metrics.inc("tasks_forwarded_total")
                except Exception as e:
                    self.logger.error(f"Failed to forward to {url}: {str(e)}")
                    failed_peers.append(url)

        if failed_peers:
            raise ForwardingError(
                f"Forwarding failed for {len(failed_peers)}/{len(next_nodes)} "
                f"peer(s): {', '.join(failed_peers)}"
            )

    # ═════════════════════════════════════════════════════════════
    #  HEALTH MESH
    # ═════════════════════════════════════════════════════════════

    async def _health_checker(self):
        """
        Background coroutine that periodically probes /health on each
        downstream peer. Updates self.peer_health so the forwarding
        logic can skip unreachable nodes instead of wasting time on them.
        """
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._check_peers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Health checker error: {str(e)}")

    async def _check_peers(self):
        """Single round of peer health probes. Testable independently."""
        async with httpx.AsyncClient() as client:
            for url in list(self.peer_health.keys()):
                try:
                    resp = await client.get(f"{url}/health", timeout=5.0)
                    was_healthy = self.peer_health[url]
                    now_healthy = resp.status_code == 200
                    self.peer_health[url] = now_healthy

                    if was_healthy and not now_healthy:
                        self.logger.warning(
                            f"Peer DOWN: {url} (status {resp.status_code})"
                        )
                    elif not was_healthy and now_healthy:
                        self.logger.info(f"Peer RECOVERED: {url}")
                except Exception:
                    if self.peer_health[url]:
                        self.logger.warning(f"Peer UNREACHABLE: {url}")
                    self.peer_health[url] = False

    # ═════════════════════════════════════════════════════════════
    #  DATABASE CLEANUP
    # ═════════════════════════════════════════════════════════════

    async def _cleanup_worker(self):
        """
        Background coroutine that periodically purges old completed
        and dead-letter tasks to prevent unbounded SQLite growth.
        """
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                self._purge_old_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cleanup error: {str(e)}")

    def _purge_old_tasks(self):
        """Single round of old task purging. Testable independently."""
        with Session(self.engine) as session:
            now = datetime.utcnow()

            # Purge completed tasks older than TTL
            completed_cutoff = now - timedelta(hours=self.task_ttl_hours)
            old_completed = session.exec(
                select(Task).where(
                    Task.status == "COMPLETED",
                    Task.processed_at != None,  # noqa: E711
                    Task.processed_at < completed_cutoff,
                )
            ).all()

            # Purge dead-letter tasks older than DL TTL
            dl_cutoff = now - timedelta(hours=self.dead_letter_ttl_hours)
            old_dead = session.exec(
                select(Task).where(
                    Task.status == "DEAD_LETTER",
                    Task.created_at < dl_cutoff,
                )
            ).all()

            purged = len(old_completed) + len(old_dead)
            for task in old_completed + old_dead:
                session.delete(task)
            if purged:
                session.commit()
                self.logger.info(
                    f"Cleanup: purged {len(old_completed)} completed + "
                    f"{len(old_dead)} dead-letter task(s)."
                )
