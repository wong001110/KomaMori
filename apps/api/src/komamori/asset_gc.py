from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from time import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Page, TextRegion
from .storage import AssetStore

DEFAULT_DELETE_GRACE_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class AssetAuditReport:
    referenced: list[str]
    existing_referenced: list[str]
    missing_references: list[str]
    orphan_files: list[str]
    skipped_recent_orphans: list[str]
    deleted: list[str]

    def to_dict(self) -> dict[str, list[str]]:
        return asdict(self)


def _safe_relative(store: AssetStore, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"Asset reference must be relative: {value}")
    target = (store.root / path).resolve()
    root = store.root.resolve()
    if target == root or root not in target.parents:
        raise ValueError(f"Asset reference escapes root: {value}")
    return target.relative_to(root).as_posix()


def _assert_read_only_session(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        raise ValueError("Asset GC requires a session with no pending writes")


def referenced_assets(session: Session, store: AssetStore) -> set[str]:
    refs: set[str] = set()
    for original, clean in session.execute(select(Page.original_asset, Page.clean_asset)):
        if original:
            refs.add(_safe_relative(store, str(original)))
        if clean:
            refs.add(_safe_relative(store, str(clean)))
    for (mask,) in session.execute(select(TextRegion.mask_asset)):
        if mask:
            refs.add(_safe_relative(store, str(mask)))
    return refs


def _fresh_referenced_assets(session: Session, store: AssetStore) -> set[str]:
    """Read one reference snapshot, then end its transaction before returning."""
    _assert_read_only_session(session)
    try:
        return referenced_assets(session, store)
    finally:
        # The maintenance session is read-only by contract. Ending the read
        # transaction ensures the next safety check can observe later commits.
        session.rollback()


def existing_assets(store: AssetStore) -> set[str]:
    root = store.root.resolve()
    existing: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Asset scan refuses symlink: {path}")
        if path.is_file():
            resolved = path.resolve()
            if root not in resolved.parents:
                raise ValueError(f"Asset scan escaped root: {path}")
            existing.add(resolved.relative_to(root).as_posix())
    return existing


def audit_assets(
    session: Session,
    store: AssetStore,
    *,
    delete: bool = False,
    grace_seconds: int = DEFAULT_DELETE_GRACE_SECONDS,
    now_timestamp: float | None = None,
) -> AssetAuditReport:
    """Audit asset references and optionally delete old, freshly-confirmed orphans.

    Dry-run is the default. Delete mode requires a read-only Session, ends each
    reference-read transaction before the next check, repeats the reference query
    before every unlink, and enforces an age grace period. These rules protect the
    commit-first window where a unique file can exist before its DB reference is
    committed by another connection.
    """
    if grace_seconds < 0:
        raise ValueError("grace_seconds must be >= 0")
    _assert_read_only_session(session)

    root = store.root.resolve()
    references = _fresh_referenced_assets(session, store)
    existing = existing_assets(store)
    missing = sorted(references - existing)
    orphans = sorted(existing - references)
    deleted: list[str] = []
    skipped_recent: list[str] = []

    if delete and orphans:
        cutoff = (time() if now_timestamp is None else now_timestamp) - grace_seconds
        for relative in orphans:
            current_references = _fresh_referenced_assets(session, store)
            if relative in current_references:
                continue
            target = (root / relative).resolve()
            if target == root or root not in target.parents or not target.is_file():
                continue
            if target.is_symlink():
                raise ValueError(f"Asset deletion refuses symlink: {relative}")
            if target.stat().st_mtime > cutoff:
                skipped_recent.append(relative)
                continue
            # A final fresh transaction immediately precedes unlink. This cannot
            # make SQLite + filesystem globally atomic, but it closes the stale
            # same-session snapshot bug and minimizes the commit race window.
            if relative in _fresh_referenced_assets(session, store):
                continue
            target.unlink()
            deleted.append(relative)

    return AssetAuditReport(
        referenced=sorted(references),
        existing_referenced=sorted(references & existing),
        missing_references=missing,
        orphan_files=orphans,
        skipped_recent_orphans=sorted(skipped_recent),
        deleted=sorted(deleted),
    )
