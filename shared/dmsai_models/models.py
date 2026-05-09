from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

class Document(SQLModel, table=True):
    """Tracks a document through the DMSAI pipeline."""

    id: str = Field(primary_key=True)
    filename: str
    original_extension: str
    source: str = Field(default="api")
    mode: str = Field(default="auto")
    organization_id: Optional[str] = Field(default=None, foreign_key="organization.id", index=True)
    storage_path: Optional[str] = Field(default=None)
    page_count: Optional[int] = Field(default=None)
    file_size_bytes: Optional[int] = Field(default=None)

    status: str = Field(default="INGESTED")

    ocr_text: Optional[str] = Field(default=None)
    ocr_confidence: Optional[float] = Field(default=None)
    ocr_method: Optional[str] = Field(default=None)

    classification_label: Optional[str] = Field(default=None)
    classification_subcategory_label: Optional[str] = Field(default=None)
    classification_path: Optional[str] = Field(default=None)
    classification_confidence: Optional[float] = Field(default=None)
    classification_method: Optional[str] = Field(default=None)
    cluster_id: Optional[int] = Field(default=None)

    confidence_details: Optional[str] = Field(default=None)
    pipeline_confidence: Optional[float] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)
    processed_at: Optional[datetime] = Field(default=None)

    archived_at: Optional[datetime] = Field(default=None)
    trashed_at: Optional[datetime] = Field(default=None)
    compressed_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# Organization and User
# ---------------------------------------------------------------------------

class Organization(SQLModel, table=True):
    """A tenant organization."""

    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Per-org retention overrides (None = use global SystemConfig default)
    archive_retention_days: Optional[int] = Field(default=None)
    trash_retention_days: Optional[int] = Field(default=None)


class UserOrganization(SQLModel, table=True):
    """Many-to-many join between User and Organization with a per-org role."""

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    organization_id: str = Field(foreign_key="organization.id", index=True)
    role: str = Field(default="user")        # admin | manager | user within this org
    is_default: bool = Field(default=False)  # the org activated on fresh login
    joined_at: datetime = Field(default_factory=datetime.utcnow)


class OrgIngestionConfig(SQLModel, table=True):
    """Per-organization ingestion source (directory watch or IMAP email inbox)."""

    id: str = Field(primary_key=True)
    organization_id: str = Field(foreign_key="organization.id", index=True)
    name: str                               # human label, e.g. "Paris HQ – Inbox"
    source_type: str                        # "directory" | "email"
    config_json: str = Field(default="{}")  # JSON with path / IMAP settings
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    """An authenticated user belonging to an organization."""

    id: str = Field(primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str = Field(default="")
    full_name: str
    role: str = Field(default="user")
    organization_id: str = Field(foreign_key="organization.id", index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = Field(default=None)
    auth_provider: str = Field(default="local")
    email_verified: bool = Field(default=False)
    email_verification_token: Optional[str] = Field(default=None)
    email_verification_sent_at: Optional[datetime] = Field(default=None)
    failed_login_attempts: int = Field(default=0)
    locked_until: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# Bucket system
# ---------------------------------------------------------------------------

class Bucket(SQLModel, table=True):
    """A named document container within an organization."""

    id: str = Field(primary_key=True)
    name: str
    description: Optional[str] = Field(default=None)
    organization_id: str = Field(foreign_key="organization.id", index=True)
    created_by: str = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BucketRule(SQLModel, table=True):
    """Auto-assignment rule. Documents matching ALL rules of a bucket get assigned."""

    id: str = Field(primary_key=True)
    bucket_id: str = Field(foreign_key="bucket.id", index=True)
    field: str
    operator: str = Field(default="equals")
    value: str


class BucketDocument(SQLModel, table=True):
    """Document assignment to a bucket with workflow state and locking."""

    id: str = Field(primary_key=True)
    bucket_id: str = Field(foreign_key="bucket.id", index=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    workflow_state: str = Field(default="open")
    locked_by: Optional[str] = Field(default=None, foreign_key="user.id")
    locked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BucketPermission(SQLModel, table=True):
    """Per-user access control on a bucket."""

    id: str = Field(primary_key=True)
    bucket_id: str = Field(foreign_key="bucket.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    permission: str = Field(default="view")


class Invitation(SQLModel, table=True):
    """One-time invitation token used to onboard a new user.

    The token is shown to the inviting admin once.  When a recipient opens
    the redeem URL, the frontend hits ``GET /api/invitations/{token}`` to
    show org/role context, then ``POST /api/invitations/{token}/redeem``
    with their chosen password and full name to create the account and
    bind the prebound permissions.

    ``bucket_grants`` is a JSON array of ``{bucket_id, permission}`` so
    invitees can be granted access to buckets that aren't in the org_admin
    bypass set (e.g. cross-org bucket access).
    """

    id: str = Field(primary_key=True)
    token: str = Field(index=True, unique=True)
    organization_id: str = Field(foreign_key="organization.id", index=True)
    role: str = Field(default="user")
    bucket_grants: str = Field(default="[]")  # JSON: [{"bucket_id":..., "permission":...}]
    invited_email: Optional[str] = Field(default=None, index=True)
    invited_by: Optional[str] = Field(default=None, foreign_key="user.id")
    full_name_hint: Optional[str] = Field(default=None)
    expires_at: datetime
    redeemed_at: Optional[datetime] = Field(default=None)
    redeemed_by_user_id: Optional[str] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Entity system
# ---------------------------------------------------------------------------

class Entity(SQLModel, table=True):
    """A real-world entity (company, person, org) that appears across documents."""

    id: str = Field(primary_key=True)
    entity_type: str
    name: str = Field(index=True)
    canonical_name: Optional[str] = Field(default=None, index=True)
    organization_id: Optional[str] = Field(default=None, foreign_key="organization.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)


class EntityField(SQLModel, table=True):
    """Key-value attributes for an entity."""

    id: str = Field(primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    field_name: str
    field_value: str
    confidence: float = Field(default=1.0)
    confidence_details: Optional[str] = Field(default=None)
    source_document_id: Optional[str] = Field(default=None)


class DocumentEntity(SQLModel, table=True):
    """Links a document to an entity with a role."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    role: str
    confidence: float = Field(default=1.0)
    confidence_details: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Field system
# ---------------------------------------------------------------------------

class DocumentField(SQLModel, table=True):
    """An extracted field value from a specific document."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    field_name: str
    field_value: Optional[str] = Field(default=None)
    confidence: float = Field(default=1.0)
    confidence_details: Optional[str] = Field(default=None)
    extraction_method: str = Field(default="auto")


class FieldDefinition(SQLModel, table=True):
    """Custom mode: a user-defined field to extract."""

    id: str = Field(primary_key=True)
    field_name: str
    definition: str
    document_class: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CanonicalField(SQLModel, table=True):
    """A canonical field name with known aliases for schema unification."""

    __table_args__ = (UniqueConstraint("scope", "canonical_name", name="uq_canonical_scope_name"),)

    id: str = Field(primary_key=True)
    scope: str = Field(default="document", index=True)
    canonical_name: str = Field(index=True)
    description: str = Field(default="")
    document_class: Optional[str] = Field(default=None)
    aliases: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Classification system
# ---------------------------------------------------------------------------

class DocumentClass(SQLModel, table=True):
    """Custom mode: a supervised class label definition."""

    id: str = Field(primary_key=True)
    name: str = Field(index=True, unique=True)
    definition: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentClassLabel(SQLModel, table=True):
    """Custom mode: training label linking a document to a class."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    class_id: str = Field(foreign_key="documentclass.id", index=True)


class CanonicalDocumentClass(SQLModel, table=True):
    """Canonical document category with aliases to avoid duplicate class labels."""

    __table_args__ = (UniqueConstraint("canonical_name", name="uq_document_class_canonical_name"),)

    id: str = Field(primary_key=True)
    parent_id: Optional[str] = Field(default=None, foreign_key="canonicaldocumentclass.id", index=True)
    canonical_name: str = Field(index=True)
    description: str = Field(default="")
    aliases: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# Comments (forum/messaging for documents and entities)
# ---------------------------------------------------------------------------

class DocumentComment(SQLModel, table=True):
    """A user note or message attached to a document, with optional threading."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    content: str
    parent_id: Optional[str] = Field(default=None, foreign_key="documentcomment.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)


class EntityComment(SQLModel, table=True):
    """A user note or message attached to an entity, with optional threading."""

    id: str = Field(primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    content: str
    parent_id: Optional[str] = Field(default=None, foreign_key="entitycomment.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# Document audit log and version snapshots
# ---------------------------------------------------------------------------

class DocumentAuditLog(SQLModel, table=True):
    """Comprehensive event log for every state-changing action on a document."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    entity_id: Optional[str] = Field(default=None, foreign_key="entity.id", index=True)
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True)
    action: str = Field(index=True)
    details: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class DocumentVersion(SQLModel, table=True):
    """Snapshot of a document's key metadata at a point in time."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    version_number: int
    created_by: Optional[str] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str = Field(default="")
    snapshot_json: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Feedback and pipeline observability
# ---------------------------------------------------------------------------


class Correction(SQLModel, table=True):
    """User correction of extracted or classified values (for model health analytics)."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    entity_id: Optional[str] = Field(default=None, foreign_key="entity.id", index=True)
    field_type: str
    field_name: Optional[str] = Field(default=None)
    original_value: Optional[str] = Field(default=None)
    corrected_value: Optional[str] = Field(default=None)
    corrected_by: str = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PipelineEvent(SQLModel, table=True):
    """Per-document pipeline stage events for live progress and activity feeds."""

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    stage: str = Field(index=True)
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    details: Optional[str] = Field(default=None)


class LLMUsage(SQLModel, table=True):
    """Per-call LLM token consumption record.

    Populated automatically by dmsai_models.llm every time call_llm() or
    call_vision_llm() is invoked.  No foreign-key on document_id so that
    analytics survive document deletion.
    """

    id: str = Field(primary_key=True)
    provider: str = Field(index=True)               # "ollama" | "litellm"
    model: str = Field(index=True)
    stage: str = Field(default="unknown", index=True)  # pipeline stage name
    call_type: str = Field(default="text")          # "text" | "vision"
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    document_id: Optional[str] = Field(default=None, index=True)  # no FK
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# Embedding storage
# ---------------------------------------------------------------------------

class DocumentEmbedding(SQLModel, table=True):
    """Semantic vector for a full document (computed from OCR text).

    The *vector* column stores a JSON-serialised list[float].  Using TEXT
    keeps the schema portable across SQLite and PostgreSQL; a migration to
    pgvector VECTOR(dim) can be applied when moving to Postgres.
    """

    id: str = Field(primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    embedding_type: str = Field(default="document", index=True)  # "document"
    model: str = Field(default="", index=True)                   # model name that produced this vector
    vector: str = Field(default="")                              # JSON list[float]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)


class EntityEmbedding(SQLModel, table=True):
    """Semantic vector for a resolved entity.

    Used by the entity-resolution node to rank candidates by cosine
    similarity *before* the LLM comparison step, reducing token spend
    without altering the resolution algorithm.
    """

    id: str = Field(primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    model: str = Field(default="", index=True)
    vector: str = Field(default="")  # JSON list[float]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# System configuration
# ---------------------------------------------------------------------------

class SystemConfig(SQLModel, table=True):
    """Key-value system configuration, editable from the admin UI."""

    key: str = Field(primary_key=True)
    value: str = Field(default="")
    category: str = Field(default="general", index=True)
    description: str = Field(default="")
    updated_at: datetime = Field(default_factory=datetime.utcnow)
