"""Comments and notes for documents and entities."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from dmsai_models import (
    Document, DocumentComment, Entity, EntityComment,
    DocumentEntity, User, DocumentAuditLog,
    get_session, init_db,
)
from auth import get_current_user

router = APIRouter(prefix="/api", tags=["collaboration"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _comment_to_dict(c: DocumentComment, author_name: str | None) -> dict:
    return {
        "id": c.id,
        "document_id": c.document_id,
        "user_id": c.user_id,
        "author_name": author_name,
        "content": c.content,
        "parent_id": c.parent_id,
        "created_at": str(c.created_at),
        "updated_at": str(c.updated_at) if c.updated_at else None,
    }


def _entity_comment_to_dict(c: EntityComment, author_name: str | None) -> dict:
    return {
        "id": c.id,
        "entity_id": c.entity_id,
        "user_id": c.user_id,
        "author_name": author_name,
        "content": c.content,
        "parent_id": c.parent_id,
        "created_at": str(c.created_at),
        "updated_at": str(c.updated_at) if c.updated_at else None,
    }


def _get_doc_or_404(session, document_id: str, user: User) -> Document:
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _verify_entity_org(session, entity_id: str, user: User) -> None:
    link = session.exec(
        select(DocumentEntity).where(DocumentEntity.entity_id == entity_id)
        .join(Document, Document.id == DocumentEntity.document_id)
        .where(Document.organization_id == user.organization_id)
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Entity not found")


def _record_audit(session, document_id: str, user_id: str, action: str, details: str | None = None) -> None:
    session.add(DocumentAuditLog(
        id=str(uuid.uuid4()),
        document_id=document_id,
        user_id=user_id,
        action=action,
        details=details,
        created_at=datetime.utcnow(),
    ))


# ---------------------------------------------------------------------------
# Document comments
# ---------------------------------------------------------------------------

class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[str] = None


class CommentUpdate(BaseModel):
    content: str


@router.get("/documents/{document_id}/comments")
async def list_document_comments(
    document_id: str,
    user: User = Depends(get_current_user),
):
    init_db()
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        comments = session.exec(
            select(DocumentComment)
            .where(DocumentComment.document_id == document_id)
            .order_by(DocumentComment.created_at)
        ).all()
        user_ids = {c.user_id for c in comments}
        users = {u.id: u for u in session.exec(select(User).where(User.id.in_(user_ids))).all()}
        return [_comment_to_dict(c, users.get(c.user_id, {}).full_name if users.get(c.user_id) else None)
                for c in comments]


@router.post("/documents/{document_id}/comments")
async def create_document_comment(
    document_id: str,
    body: CommentCreate,
    user: User = Depends(get_current_user),
):
    init_db()
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Comment content cannot be empty")
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        if body.parent_id:
            parent = session.get(DocumentComment, body.parent_id)
            if not parent or parent.document_id != document_id:
                raise HTTPException(status_code=404, detail="Parent comment not found")
        comment = DocumentComment(
            id=str(uuid.uuid4()),
            document_id=document_id,
            user_id=user.id,
            content=body.content.strip(),
            parent_id=body.parent_id,
            created_at=datetime.utcnow(),
        )
        session.add(comment)
        _record_audit(session, document_id, user.id, "comment_added",
                      f"Comment '{body.content[:80]}'" + (" (reply)" if body.parent_id else ""))
        comment_id = comment.id
        session.commit()
    return {"id": comment_id, "status": "created"}


@router.put("/documents/{document_id}/comments/{comment_id}")
async def update_document_comment(
    document_id: str,
    comment_id: str,
    body: CommentUpdate,
    user: User = Depends(get_current_user),
):
    init_db()
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Comment content cannot be empty")
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        comment = session.get(DocumentComment, comment_id)
        if not comment or comment.document_id != document_id:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment.user_id != user.id and user.role not in ("admin", "org_admin", "manager"):
            raise HTTPException(status_code=403, detail="Only the author or an admin may edit this comment")
        comment.content = body.content.strip()
        comment.updated_at = datetime.utcnow()
        session.add(comment)
        _record_audit(session, document_id, user.id, "comment_edited", f"Comment {comment_id[:8]}")
        session.commit()
    return {"status": "updated"}


@router.delete("/documents/{document_id}/comments/{comment_id}")
async def delete_document_comment(
    document_id: str,
    comment_id: str,
    user: User = Depends(get_current_user),
):
    init_db()
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        comment = session.get(DocumentComment, comment_id)
        if not comment or comment.document_id != document_id:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment.user_id != user.id and user.role not in ("admin", "org_admin", "manager"):
            raise HTTPException(status_code=403, detail="Only the author or an admin may delete this comment")
        session.delete(comment)
        _record_audit(session, document_id, user.id, "comment_deleted", f"Comment {comment_id[:8]}")
        session.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Entity comments
# ---------------------------------------------------------------------------

@router.get("/entities/{entity_id}/comments")
async def list_entity_comments(
    entity_id: str,
    user: User = Depends(get_current_user),
):
    init_db()
    with get_session() as session:
        _verify_entity_org(session, entity_id, user)
        comments = session.exec(
            select(EntityComment)
            .where(EntityComment.entity_id == entity_id)
            .order_by(EntityComment.created_at)
        ).all()
        user_ids = {c.user_id for c in comments}
        users = {u.id: u for u in session.exec(select(User).where(User.id.in_(user_ids))).all()}
        return [_entity_comment_to_dict(c, users.get(c.user_id).full_name if users.get(c.user_id) else None)
                for c in comments]


@router.post("/entities/{entity_id}/comments")
async def create_entity_comment(
    entity_id: str,
    body: CommentCreate,
    user: User = Depends(get_current_user),
):
    init_db()
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Comment content cannot be empty")
    with get_session() as session:
        _verify_entity_org(session, entity_id, user)
        if body.parent_id:
            parent = session.get(EntityComment, body.parent_id)
            if not parent or parent.entity_id != entity_id:
                raise HTTPException(status_code=404, detail="Parent comment not found")
        comment = EntityComment(
            id=str(uuid.uuid4()),
            entity_id=entity_id,
            user_id=user.id,
            content=body.content.strip(),
            parent_id=body.parent_id,
            created_at=datetime.utcnow(),
        )
        session.add(comment)
        comment_id = comment.id
        session.commit()
    return {"id": comment_id, "status": "created"}


@router.put("/entities/{entity_id}/comments/{comment_id}")
async def update_entity_comment(
    entity_id: str,
    comment_id: str,
    body: CommentUpdate,
    user: User = Depends(get_current_user),
):
    init_db()
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Comment content cannot be empty")
    with get_session() as session:
        _verify_entity_org(session, entity_id, user)
        comment = session.get(EntityComment, comment_id)
        if not comment or comment.entity_id != entity_id:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment.user_id != user.id and user.role not in ("admin", "org_admin", "manager"):
            raise HTTPException(status_code=403, detail="Only the author or an admin may edit this comment")
        comment.content = body.content.strip()
        comment.updated_at = datetime.utcnow()
        session.add(comment)
        session.commit()
    return {"status": "updated"}


@router.delete("/entities/{entity_id}/comments/{comment_id}")
async def delete_entity_comment(
    entity_id: str,
    comment_id: str,
    user: User = Depends(get_current_user),
):
    init_db()
    with get_session() as session:
        _verify_entity_org(session, entity_id, user)
        comment = session.get(EntityComment, comment_id)
        if not comment or comment.entity_id != entity_id:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment.user_id != user.id and user.role not in ("admin", "org_admin", "manager"):
            raise HTTPException(status_code=403, detail="Only the author or an admin may delete this comment")
        session.delete(comment)
        session.commit()
    return {"status": "deleted"}
