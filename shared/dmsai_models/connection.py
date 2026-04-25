import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine

_engine = None

DEFAULT_DB_URL = "sqlite:///C:/dev/DMSAI/data/dmsai.db"


def get_engine():
    global _engine
    if _engine is None:
        db_url = os.environ.get("DMSAI_DB_URL", DEFAULT_DB_URL)
        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(db_url, connect_args=connect_args)
    return _engine


def _sqlite_add_column_if_missing(engine, table: str, column: str, ddl: str) -> None:
    """Best-effort SQLite ALTER for existing databases."""
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return
    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))
        conn.commit()


def _migrate_sqlite_schema(engine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    _sqlite_add_column_if_missing(engine, "document", "confidence_details", "TEXT")
    _sqlite_add_column_if_missing(engine, "document", "pipeline_confidence", "FLOAT")
    _sqlite_add_column_if_missing(engine, "document", "classification_subcategory_label", "TEXT")
    _sqlite_add_column_if_missing(engine, "document", "classification_path", "TEXT")
    _sqlite_add_column_if_missing(engine, "canonicalfield", "scope", "VARCHAR DEFAULT 'document'")
    _sqlite_add_column_if_missing(engine, "canonicaldocumentclass", "parent_id", "TEXT")
    _sqlite_add_column_if_missing(engine, "entity", "canonical_name", "TEXT")
    _sqlite_add_column_if_missing(engine, "entityfield", "confidence_details", "TEXT")
    _sqlite_add_column_if_missing(engine, "documententity", "confidence_details", "TEXT")
    _sqlite_add_column_if_missing(engine, "documentfield", "confidence_details", "TEXT")
    _sqlite_add_column_if_missing(engine, "user", "auth_provider", "VARCHAR DEFAULT 'local'")
    _sqlite_add_column_if_missing(engine, "user", "email_verified", "BOOLEAN DEFAULT 0")
    _sqlite_add_column_if_missing(engine, "user", "email_verification_token", "TEXT")
    _sqlite_add_column_if_missing(engine, "user", "email_verification_sent_at", "TIMESTAMP")
    _sqlite_add_column_if_missing(engine, "user", "failed_login_attempts", "INTEGER DEFAULT 0")
    _sqlite_add_column_if_missing(engine, "user", "locked_until", "TIMESTAMP")


def _seed_entity_canonical_fields(engine) -> None:
    """Insert default entity-scope canonical fields if missing (idempotent)."""
    from sqlmodel import select

    from .models import CanonicalField

    defaults = [
        ("tax_id", "Tax or fiscal identifier", ["tax_number", "numero_fiscal", "tin"]),
        ("siret", "French SIRET", ["numero_siret", "siret_number"]),
        ("siren", "French SIREN", ["numero_siren"]),
        ("vat_number", "VAT number", ["vat_id", "tva_number", "vat"]),
        ("email", "Email address", ["email_address", "e_mail"]),
        ("registration_number", "Company registration", ["reg_number", "company_number", "rcs"]),
        ("address", "Postal address", ["adresse", "street_address"]),
        ("phone", "Phone number", ["telephone", "phone_number", "tel"]),
    ]
    with Session(engine) as session:
        for name, desc, aliases in defaults:
            existing = session.exec(
                select(CanonicalField).where(
                    CanonicalField.scope == "entity",
                    CanonicalField.canonical_name == name,
                )
            ).first()
            if existing:
                continue
            session.add(
                CanonicalField(
                    id=str(uuid.uuid4()),
                    scope="entity",
                    canonical_name=name,
                    description=desc,
                    document_class=None,
                    aliases=json.dumps(aliases),
                    created_at=datetime.utcnow(),
                )
            )
        session.commit()


def _seed_document_classes(engine) -> None:
    """Insert default canonical document classes if missing (idempotent)."""
    from sqlmodel import select

    from .models import CanonicalDocumentClass

    defaults = [
        ("invoice", "Commercial document detailing products or services and amounts owed", []),
        ("receipt", "Document acknowledging payment received for goods or services", []),
        ("contract", "Legally binding agreement between parties", ["agreement"]),
        ("letter", "Written message addressed to a person or organization", []),
        ("report", "Formal document presenting information, findings, or recommendations", []),
        ("form", "Structured document with fields to fill in", ["application_form"]),
        ("other", "Document that does not fit a more specific category", ["unknown", "uncategorized"]),
    ]
    with Session(engine) as session:
        for name, desc, aliases in defaults:
            existing = session.exec(
                select(CanonicalDocumentClass).where(
                    CanonicalDocumentClass.canonical_name == name,
                )
            ).first()
            if existing:
                continue
            session.add(
                CanonicalDocumentClass(
                    id=str(uuid.uuid4()),
                    parent_id=None,
                    canonical_name=name,
                    description=desc,
                    aliases=json.dumps(aliases),
                    created_at=datetime.utcnow(),
                )
            )
        session.commit()


def _seed_system_config(engine) -> None:
    """Insert default system-config rows if missing (idempotent)."""
    from sqlmodel import select
    from .models import SystemConfig

    classification_prompt = """You are a hierarchical document classification system.

Classify the document into one canonical top-level category and, when useful, one canonical subcategory below it.

Known canonical category hierarchy:
{categories}

Rules:
- Prefer existing canonical category and subcategory labels whenever they are a reasonable fit.
- Treat synonyms, translations, abbreviations, plural forms, and spelling variants as the same label.
- Do not invent near-duplicate categories. For example, "supplier_invoice", "vendor bill", and "facture" should map to "invoice" if that canonical category exists.
- Use "other" only when no specific known or new category is appropriate.
- If no known top-level category fits and a clearly reusable new category is needed, set "is_new" to true.
- If a useful subcategory exists or should be created, provide it as concise English snake_case. Otherwise use null.

Document text:
---
{ocr_text}
---

Respond with ONLY a valid JSON object:
{{
  "category": "<canonical_or_new_category_name>",
  "subcategory": "<canonical_or_new_subcategory_name_or_null>",
  "confidence": <0.0_to_1.0>,
  "evidence": "<short exact quote from the document that supports the classification, or null>",
  "alternatives": [
    {{"category": "<alternative_category>", "confidence": <0.0_to_1.0>}}
  ],
  "is_new": true/false,
  "definition": "<one-line category definition>",
  "subcategory_is_new": true/false,
  "subcategory_definition": "<one-line subcategory definition>",
  "reason": "<short reason>"
}}"""
    classification_canonical_map_prompt = """You are maintaining a canonical document category taxonomy.

Given the existing canonical categories and a proposed category, determine if the proposed category is actually the same as an existing category.

Existing canonical categories:
{categories}

Proposed category:
- Name: {category}
- Definition: {definition}

Rules:
- Match if the proposed category is a synonym, translation, abbreviation, spelling variant, plural/singular variant, or narrower duplicate of an existing category.
- Prefer an existing broad category over creating a near-duplicate.
- Only create a new canonical category when it is genuinely different from all existing categories.

Respond with ONLY a valid JSON object:
- If it matches an existing category: {{"match": "<canonical_name>", "alias": "<proposed_alias>"}}
- If it is new: {{"new": "<canonical_snake_case_name>", "description": "<one-line description>"}}"""
    entity_extraction_prompt = """Analyze the following document text and identify ALL entities present.
Entities can be: people, companies, organizations, government agencies, etc.

For each entity, provide:
- "name": the full canonical name
- "entity_type": one of "person", "company", "organization", "government", "other"
- "role": the entity's role in the document (e.g. "issuer", "recipient", "mentioned", "service_provider", "client")
- "confidence": a number from 0.0 to 1.0 indicating how confident you are in this extraction (name, type, and fields combined)
- "evidence": a short exact quote from the document that supports the entity, or null
- "fields": a dictionary of identifying attributes you can find (address, phone, email, tax_id, registration_number, website, etc.)

Return ONLY a JSON array of entities. No explanation, no markdown fences.

Document text:
{ocr_text}"""
    entity_resolution_prompt = """Determine if these two records refer to the same real-world entity.
Consider name variations, abbreviations, legal suffixes, and shared identifiers.

Entity A:
- Name: {name_a}
- Type: {type_a}
- Fields: {fields_a}

Entity B:
- Name: {name_b}
- Type: {type_b}
- Fields: {fields_b}

Respond with ONLY a valid JSON object: {{"same": true/false, "confidence": 0.0-1.0, "canonical_name": "<best canonical name for this entity>"}}"""
    field_detection_prompt = """Analyze the following document text and list ALL data fields/data points present.
Do NOT include entity-level fields (names, addresses of people/companies) -- those are already extracted.
Focus on document-level fields like: invoice_number, date, due_date, total_amount, subtotal, tax_amount,
payment_terms, reference_number, line_items, etc.

{existing_fields_hint}

Return ONLY a JSON array of field name strings. No explanation, no markdown fences.
Example: ["invoice_number", "date", "total_amount", "tax_rate"]

Document text:
{ocr_text}"""
    field_extraction_prompt = """Extract the values for the following fields from this document text.

Return ONLY a JSON object with exactly three keys:
- "values": an object mapping each field name to the extracted string value, or null if not found
- "confidences": an object mapping each field name to a number from 0.0 to 1.0 (your confidence in that extraction)
- "evidence": an object mapping each field name to a short exact quote from the document that supports the value, or null

Both objects must use the same field names as listed below.
No explanation, no markdown fences.

Fields to extract: {field_names}

Document text:
{ocr_text}"""
    field_canonical_map_prompt = """You are a data schema expert. Given a list of canonical field names and a newly detected field name, determine if the new field matches any existing canonical field.

Canonical fields:
{canonical_list}

Newly detected field name: "{field_name}"

Rules:
- Match if the new name is a synonym, translation, abbreviation, or variant of an existing canonical field.
  Examples: "total_ttc" matches "total_amount", "montant_total" matches "total_amount", "numero_facture" matches "invoice_number"
- If no match exists, suggest a good canonical English snake_case name for this field.

Respond with ONLY a valid JSON object:
- If it matches an existing field: {{"match": "<canonical_name>"}}
- If it's a new field: {{"new": "<suggested_canonical_name>", "description": "<one-line description>"}}"""

    defaults = [
        ("llm_provider", "ollama", "llm", "LLM provider: ollama or litellm"),
        ("ollama_base_url", os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"), "llm", "Ollama server base URL"),
        ("llm_model", os.environ.get("LLM_MODEL", "gemma3:27b"), "llm", "Model name for Ollama"),
        ("litellm_base_url", "http://localhost:4000", "llm", "LiteLLM proxy base URL"),
        ("litellm_api_key", os.environ.get("GEMINI_API_KEY", ""), "llm", "API key for LiteLLM proxy"),
        ("litellm_model", "", "llm", "Model identifier for LiteLLM"),
        ("llm_temperature", "0.1", "llm", "Temperature used for text LLM calls"),
        ("llm_timeout_seconds", "300", "llm", "Timeout for text LLM calls"),
        ("llm_vision_timeout_seconds", "300", "llm", "Timeout for vision LLM calls"),
        ("classification_prompt", classification_prompt, "prompts", "Prompt template for document category/subcategory classification"),
        ("classification_canonical_map_prompt", classification_canonical_map_prompt, "prompts", "Prompt template for canonical classification label mapping"),
        ("entity_extraction_prompt", entity_extraction_prompt, "prompts", "Prompt template for entity extraction"),
        ("entity_resolution_prompt", entity_resolution_prompt, "prompts", "Prompt template for entity disambiguation"),
        ("field_detection_prompt", field_detection_prompt, "prompts", "Prompt template for document field detection"),
        ("field_extraction_prompt", field_extraction_prompt, "prompts", "Prompt template for document field value extraction"),
        ("field_canonical_map_prompt", field_canonical_map_prompt, "prompts", "Prompt template for canonical field mapping"),
        ("ocr_vision_model", "", "ocr", "Vision model override for OCR (empty = use default LLM model)"),
        ("ocr_vision_prompt", "Extract ALL text from this document image exactly as it appears. Preserve the layout, line breaks, and formatting as closely as possible. Return only the extracted text, nothing else.", "ocr", "Prompt sent to vision LLM for OCR"),
        ("entity_name_match_high", "0.85", "entity_resolution", "Name similarity threshold for auto-match"),
        ("entity_name_match_low", "0.6", "entity_resolution", "Name similarity lower bound for LLM disambiguation"),
        ("entity_llm_confirm_min", "0.7", "entity_resolution", "Minimum LLM confidence to confirm entity match"),
        ("confidence_level_high", "0.85", "confidence", "Minimum score for high confidence"),
        ("confidence_level_medium", "0.6", "confidence", "Minimum score for medium confidence"),
        ("confidence_default_source_quality", "0.75", "confidence", "Default OCR source quality when no OCR confidence is available"),
        ("confidence_empty_text_with_evidence", "0.35", "confidence", "Grounding fallback when OCR text is empty but a value exists"),
        ("confidence_item_weights", "{\"llm\":0.30,\"grounding\":0.35,\"completeness\":0.15,\"source_quality\":0.10,\"agreement\":0.07,\"ambiguity\":0.03}", "confidence", "JSON weights for item-level confidence scoring"),
        ("confidence_pipeline_weights", "{\"ocr\":0.20,\"classification\":0.20,\"entity_extraction\":0.20,\"entity_resolution\":0.15,\"field_extraction\":0.25}", "confidence", "JSON weights for document pipeline confidence scoring"),
        ("classification_create_new_categories", "true", "classification", "Allow LLM classification to create new canonical document categories"),
        ("classification_new_category_min_confidence", "0.75", "classification", "Minimum confidence required before creating a new canonical document category"),
        ("low_confidence_threshold", "0.5", "buckets", "Pipeline confidence below which docs go to low-confidence bucket"),
        ("low_confidence_bucket_enabled", "false", "buckets", "Enable automatic low-confidence bucket assignment"),
        # SMTP / email verification
        ("smtp_host", "", "email", "SMTP server hostname"),
        ("smtp_port", "587", "email", "SMTP server port"),
        ("smtp_user", "", "email", "SMTP authentication username"),
        ("smtp_password", "", "email", "SMTP authentication password"),
        ("smtp_use_tls", "true", "email", "Use TLS for SMTP connection"),
        ("smtp_from_email", "noreply@dmsai.local", "email", "Sender address for outgoing emails"),
        ("smtp_from_name", "DMSAI", "email", "Sender display name"),
        ("email_verification_enabled", "false", "auth", "Require email verification on registration"),
        ("email_verification_token_expiry_hours", "24", "auth", "Hours before a verification link expires"),
        ("password_min_length", "8", "auth", "Minimum password length"),
        ("password_require_uppercase", "true", "auth", "Require at least one uppercase letter"),
        ("password_require_digit", "true", "auth", "Require at least one digit"),
        ("max_failed_logins", "5", "auth", "Lock account after N consecutive failed logins"),
        ("lockout_duration_minutes", "15", "auth", "Account lockout duration in minutes"),
        ("registration_open", "true", "auth", "Allow self-service registration (false = admin-only)"),
        # LDAP
        ("ldap_enabled", "false", "ldap", "Enable LDAP/AD authentication"),
        ("ldap_server_url", "ldap://localhost:389", "ldap", "LDAP server URL (ldap:// or ldaps://)"),
        ("ldap_bind_dn", "", "ldap", "DN used to bind for user searches (leave empty for anonymous bind)"),
        ("ldap_bind_password", "", "ldap", "Password for the bind DN"),
        ("ldap_search_base", "dc=example,dc=com", "ldap", "Base DN for user searches"),
        ("ldap_user_filter", "(uid={username})", "ldap", "LDAP filter to find user; {username} is replaced with login input"),
        ("ldap_email_attribute", "mail", "ldap", "LDAP attribute that contains the user email"),
        ("ldap_fullname_attribute", "cn", "ldap", "LDAP attribute that contains the user display name"),
        ("ldap_use_tls", "false", "ldap", "Use STARTTLS on plain LDAP connections"),
        ("ldap_require_group", "", "ldap", "Only allow users who belong to this group DN (empty = no restriction)"),
        ("ldap_group_attribute", "memberOf", "ldap", "LDAP attribute checked for group membership"),
        ("ldap_default_organization", "LDAP Users", "ldap", "Organization name for auto-provisioned LDAP users"),
        ("ldap_default_role", "user", "ldap", "Default role for auto-provisioned LDAP users (user/manager/admin)"),
    ]
    with Session(engine) as session:
        for key, value, category, description in defaults:
            existing = session.exec(
                select(SystemConfig).where(SystemConfig.key == key)
            ).first()
            if existing:
                if existing.value == "" and value:
                    existing.value = value
                    existing.description = description
                    existing.updated_at = datetime.utcnow()
                    session.add(existing)
                continue
            session.add(SystemConfig(
                key=key, value=value, category=category,
                description=description, updated_at=datetime.utcnow(),
            ))
        session.commit()


def _remove_obsolete_system_config(engine) -> None:
    """Remove config keys from retired non-LLM implementations."""
    from sqlmodel import select
    from .models import SystemConfig

    obsolete_keys = {
        "min_docs_for_clustering",      # retired KMeans classification
        "dense_embedding_model",        # retired local/sentence-transformer embedding setting
        "ocr_confidence_threshold",     # retired hybrid/DocTR threshold
        "ocr_vllm_enabled",             # OCR is always vision-LLM now
        "embedding_model",              # retired embedding node
        "embedding_provider",           # retired embedding node
    }
    with Session(engine) as session:
        rows = session.exec(select(SystemConfig).where(SystemConfig.key.in_(obsolete_keys))).all()
        for row in rows:
            session.delete(row)
        if rows:
            session.commit()


def _load_auth_yaml(engine) -> None:
    """Load auth.yaml overrides into SystemConfig (only sets values that are
    still at their default / empty state so admin-UI changes are preserved)."""
    try:
        import yaml
    except ImportError:
        return

    from sqlmodel import select
    from .models import SystemConfig

    candidates = [
        Path(os.environ.get("DMSAI_AUTH_CONFIG", "")),
        Path(__file__).resolve().parent.parent.parent / "api_gateway" / "config" / "auth.yaml",
        Path("config/auth.yaml"),
    ]
    yaml_path = None
    for p in candidates:
        if p.is_file():
            yaml_path = p
            break
    if yaml_path is None:
        return

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    with Session(engine) as session:
        for _category, kvs in data.items():
            if not isinstance(kvs, dict):
                continue
            for key, value in kvs.items():
                row = session.exec(
                    select(SystemConfig).where(SystemConfig.key == key)
                ).first()
                if row is None:
                    session.add(SystemConfig(
                        key=key, value=str(value), category=str(_category),
                        description=f"Loaded from auth.yaml",
                        updated_at=datetime.utcnow(),
                    ))
                elif row.value == "" and str(value):
                    row.value = str(value)
                    row.updated_at = datetime.utcnow()
                    session.add(row)
        session.commit()


def init_db():
    """Create all DMSAI tables if they don't exist."""
    from . import models  # noqa: F401 — registers tables with SQLModel metadata

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _migrate_sqlite_schema(engine)
    try:
        _seed_entity_canonical_fields(engine)
    except Exception as e:
        logging.getLogger("dmsai_models").warning("seed entity canonical fields failed: %s", e)
    try:
        _seed_document_classes(engine)
    except Exception as e:
        logging.getLogger("dmsai_models").warning("seed document classes failed: %s", e)
    try:
        _seed_system_config(engine)
    except Exception as e:
        logging.getLogger("dmsai_models").warning("seed system config failed: %s", e)
    try:
        _remove_obsolete_system_config(engine)
    except Exception as e:
        logging.getLogger("dmsai_models").warning("remove obsolete system config failed: %s", e)
    try:
        _load_auth_yaml(engine)
    except Exception as e:
        logging.getLogger("dmsai_models").warning("load auth.yaml failed: %s", e)


def get_session() -> Session:
    return Session(get_engine())
