"""Exodus shared spaces (e.g. "Family").

A space is a named group of accounts. Items put in a space (notes and
checklists for now) are visible to and editable by every member; everything
else stays personal. Membership is the only thing that grants access: there is
no "shared with everyone" fallback.

Roles:
- ``manager``: renames the space, adds and removes members, deletes it. The
  creator starts as manager. Workspace admins can also manage every space.
- ``member``: sees and edits the space's items, and can leave.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from sqlalchemy import func

from core.database import CalendarCal, Document, Note, SessionLocal, Space, SpaceMember

MAX_NAME = 40
MAX_SPACES_PER_ACCOUNT = 20
MAX_MEMBERS = 50
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SpaceError(ValueError):
    """A request that can't be done; ``status`` is the HTTP code to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def clean_name(name) -> str:
    if not isinstance(name, str):
        raise SpaceError("Give the space a name.")
    name = " ".join(name.split())
    if not name:
        raise SpaceError("Give the space a name.")
    if len(name) > MAX_NAME or _CONTROL.search(name):
        raise SpaceError(f"Space names can be up to {MAX_NAME} plain characters.")
    return name


def space_ids_for(user: Optional[str], db=None) -> list[str]:
    """Ids of every space ``user`` belongs to (empty for single-user mode)."""
    if not user:
        return []
    own = db is None
    db = db or SessionLocal()
    try:
        return [row[0] for row in db.query(SpaceMember.space_id).filter(SpaceMember.owner == user).all()]
    finally:
        if own:
            db.close()


def is_member(user: Optional[str], space_id: Optional[str], db=None) -> bool:
    if not user or not space_id:
        return False
    own = db is None
    db = db or SessionLocal()
    try:
        return db.query(SpaceMember).filter(SpaceMember.space_id == space_id, SpaceMember.owner == user).first() is not None
    finally:
        if own:
            db.close()


def can_see_note(note: Note, user: Optional[str], db=None) -> bool:
    """Owner always; members of the note's space too. ``user`` None = single-user mode."""
    if user is None:
        return True
    if note.owner == user:
        return True
    return bool(note.space_id) and is_member(user, note.space_id, db)


def can_use_calendar(cal: CalendarCal, user: Optional[str], db=None) -> bool:
    """Calendar owner, or a member of the space a local calendar is shared in."""
    if not cal or not user:
        return False
    if cal.owner == user:
        return True
    space_id = getattr(cal, "space_id", None)
    return bool(space_id) and (getattr(cal, "source", None) or "local") == "local" and is_member(user, space_id, db)


def document_shareable(doc) -> bool:
    """Every document can be shared. Uploaded files it points at (a PDF or Word
    source, pictures) become readable to members through shared_upload_owner."""
    return True


def can_use_document(doc, user: Optional[str], db=None) -> bool:
    """A member of the space a document is shared in (owners are checked by the
    document routes themselves)."""
    space_id = getattr(doc, "space_id", None)
    return bool(user and space_id) and is_member(user, space_id, db)


def shared_upload_owner(user: Optional[str], upload_id: str, db=None) -> Optional[str]:
    """Whose upload a space member may READ, or None.

    A member may read an upload only when a note or document shared in one of
    their spaces references it, and the upload belongs to that item's owner
    (checked by the caller against the upload index). Returns the owner whose
    upload it must be. Never grants writing, and never applies to the owner.
    """
    from src.upload_handler import extract_internal_upload_ids
    if not user or not upload_id:
        return None
    own = db is None
    db = db or SessionLocal()
    try:
        member_of = space_ids_for(user, db)
        if not member_of:
            return None
        like = f"%{upload_id}%"
        candidates = []
        for note in db.query(Note).filter(Note.space_id.in_(member_of), Note.owner != user).filter(
                (Note.content.like(like)) | (Note.items.like(like)) | (Note.image_url.like(like)) | (Note.color.like(like))).all():
            if upload_id in extract_internal_upload_ids([note.content, note.items, note.image_url, note.color]):
                candidates.append(note.owner)
        for doc in db.query(Document).filter(Document.space_id.in_(member_of), Document.owner != user,
                                             Document.current_content.like(like)).all():
            if upload_id in extract_internal_upload_ids(doc.current_content or ""):
                candidates.append(doc.owner)
        owners = {o for o in candidates if o}
        return owners.pop() if len(owners) == 1 else None
    finally:
        if own:
            db.close()


def _space_or_404(db, space_id: str) -> Space:
    space = db.query(Space).filter(Space.id == space_id).first()
    if space is None:
        raise SpaceError("Space not found.", 404)
    return space


def _require_member(db, space_id: str, user: str, is_admin: bool) -> Optional[SpaceMember]:
    member = db.query(SpaceMember).filter(SpaceMember.space_id == space_id, SpaceMember.owner == user).first()
    if member is None and not is_admin:
        # Non-members can't tell a space exists.
        raise SpaceError("Space not found.", 404)
    return member


def _require_manager(db, space_id: str, user: str, is_admin: bool) -> None:
    member = _require_member(db, space_id, user, is_admin)
    if not is_admin and (member is None or member.role != "manager"):
        raise SpaceError("Only the space's managers can do that.", 403)


def _describe(db, space: Space, user: str, is_admin: bool) -> dict:
    members = (
        db.query(SpaceMember).filter(SpaceMember.space_id == space.id)
        .order_by(SpaceMember.role.asc(), SpaceMember.owner.asc()).all()
    )
    mine = next((m for m in members if m.owner == user), None)
    notes = db.query(func.count(Note.id)).filter(Note.space_id == space.id).scalar() or 0
    calendars = db.query(func.count(CalendarCal.id)).filter(CalendarCal.space_id == space.id).scalar() or 0
    documents = db.query(func.count(Document.id)).filter(Document.space_id == space.id).scalar() or 0
    return {
        "id": space.id,
        "name": space.name,
        "created_by": space.owner,
        "role": mine.role if mine else None,
        "can_manage": is_admin or bool(mine and mine.role == "manager"),
        "members": [{"username": m.owner, "role": m.role} for m in members],
        "note_count": notes,
        "calendar_count": calendars,
        "document_count": documents,
    }


def list_spaces(user: str, is_admin: bool = False) -> list[dict]:
    """Spaces the user belongs to; workspace admins see every space."""
    db = SessionLocal()
    try:
        query = db.query(Space)
        if not is_admin:
            query = query.join(SpaceMember, SpaceMember.space_id == Space.id).filter(SpaceMember.owner == user)
        spaces = query.order_by(func.lower(Space.name).asc(), Space.id.asc()).all()
        return [_describe(db, space, user, is_admin) for space in spaces]
    finally:
        db.close()


def create_space(user: str, name) -> dict:
    name = clean_name(name)
    db = SessionLocal()
    try:
        managed = db.query(func.count(SpaceMember.space_id)).filter(
            SpaceMember.owner == user, SpaceMember.role == "manager").scalar() or 0
        if managed >= MAX_SPACES_PER_ACCOUNT:
            raise SpaceError(f"You can manage up to {MAX_SPACES_PER_ACCOUNT} spaces.")
        space = Space(id=str(uuid.uuid4()), name=name, owner=user)
        db.add(space)
        db.flush()
        db.add(SpaceMember(space_id=space.id, owner=user, role="manager"))
        db.commit()
        return _describe(db, space, user, False)
    finally:
        db.close()


def rename_space(user: str, space_id: str, name, is_admin: bool = False) -> dict:
    name = clean_name(name)
    db = SessionLocal()
    try:
        space = _space_or_404(db, space_id)
        _require_manager(db, space_id, user, is_admin)
        space.name = name
        db.commit()
        return _describe(db, space, user, is_admin)
    finally:
        db.close()


def delete_space(user: str, space_id: str, is_admin: bool = False) -> None:
    """Delete a space. Nothing in it is deleted: notes, calendars and documents go back to their owners."""
    db = SessionLocal()
    try:
        space = _space_or_404(db, space_id)
        _require_manager(db, space_id, user, is_admin)
        db.query(Note).filter(Note.space_id == space_id).update({Note.space_id: None}, synchronize_session=False)
        db.query(CalendarCal).filter(CalendarCal.space_id == space_id).update(
            {CalendarCal.space_id: None}, synchronize_session=False)
        db.query(Document).filter(Document.space_id == space_id).update(
            {Document.space_id: None}, synchronize_session=False)
        db.query(SpaceMember).filter(SpaceMember.space_id == space_id).delete(synchronize_session=False)
        db.delete(space)
        db.commit()
    finally:
        db.close()


def add_member(user: str, space_id: str, username, known_users, is_admin: bool = False, role: str = "member") -> dict:
    """Add an existing account. ``known_users`` is the set of current usernames."""
    if role not in ("member", "manager"):
        raise SpaceError("Role must be member or manager.")
    username = (username or "").strip().lower() if isinstance(username, str) else ""
    if not username or username not in known_users:
        raise SpaceError("There is no account with that username.", 404)
    db = SessionLocal()
    try:
        space = _space_or_404(db, space_id)
        _require_manager(db, space_id, user, is_admin)
        existing = db.query(SpaceMember).filter(SpaceMember.space_id == space_id, SpaceMember.owner == username).first()
        if existing is not None:
            existing.role = role
        else:
            count = db.query(func.count(SpaceMember.owner)).filter(SpaceMember.space_id == space_id).scalar() or 0
            if count >= MAX_MEMBERS:
                raise SpaceError(f"A space can have up to {MAX_MEMBERS} members.")
            db.add(SpaceMember(space_id=space_id, owner=username, role=role))
        db.commit()
        return _describe(db, space, user, is_admin)
    finally:
        db.close()


def remove_member(user: str, space_id: str, username: str, is_admin: bool = False) -> None:
    """Managers remove anyone; anyone can remove themselves (leave).

    The last manager can't leave (delete the space or add another manager
    first), so a space never ends up with nobody able to manage it. Notes the
    removed person put in the space go back to being personal to them.
    """
    username = (username or "").strip().lower()
    db = SessionLocal()
    try:
        _space_or_404(db, space_id)
        if username != user:
            _require_manager(db, space_id, user, is_admin)
        else:
            _require_member(db, space_id, user, is_admin)
        target = db.query(SpaceMember).filter(SpaceMember.space_id == space_id, SpaceMember.owner == username).first()
        if target is None:
            raise SpaceError("That account isn't in this space.", 404)
        if target.role == "manager":
            managers = db.query(func.count(SpaceMember.owner)).filter(
                SpaceMember.space_id == space_id, SpaceMember.role == "manager").scalar() or 0
            if managers <= 1:
                raise SpaceError("A space needs at least one manager. Add another manager first, or delete the space.", 409)
        db.query(Note).filter(Note.space_id == space_id, Note.owner == username).update(
            {Note.space_id: None}, synchronize_session=False)
        db.query(CalendarCal).filter(CalendarCal.space_id == space_id, CalendarCal.owner == username).update(
            {CalendarCal.space_id: None}, synchronize_session=False)
        db.query(Document).filter(Document.space_id == space_id, Document.owner == username).update(
            {Document.space_id: None}, synchronize_session=False)
        db.delete(target)
        db.commit()
    finally:
        db.close()


def share_document(user: str, doc_id: str, space_id) -> dict:
    """Owner moves a text document into a space ("" or None = only me)."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None or doc.owner != user:
            raise SpaceError("Document not found.", 404)
        if space_id:
            if not is_member(user, space_id, db):
                raise SpaceError("Space not found.", 404)
            doc.space_id = space_id
        else:
            doc.space_id = None
        db.commit()
        return {"id": doc.id, "space_id": doc.space_id}
    finally:
        db.close()
