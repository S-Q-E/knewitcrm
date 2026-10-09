from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session
from ..errors import ApiError
from ..models import CrmContact, CrmDeal, CrmImport
from ..schemas.contacts_data import ImportJobOut, ImportPreviewOut
from ..services.activity import log_activity
from ..services.export import (
    CONTACT_EXPORT_FIELDS,
    DEAL_EXPORT_FIELDS,
    csv_stream,
    xlsx_bytes,
)
from ..services.importing import apply_mapping, parse_csv_text
from ..services.visibility import owner_condition, restrict_managers_to_own

router = APIRouter(tags=["data-exchange"])
logger = logging.getLogger(__name__)

EXPORT_LIMIT = 10000
IMPORT_STALE_AFTER = timedelta(minutes=5)
# Strong references: a task nobody holds can be garbage-collected mid-run.
_import_tasks: set[asyncio.Task] = set()

# Import uploads are small CSVs: reject anything above 2 MiB with 413.
# Other endpoints are covered by the global BodyLimitMiddleware (10 MiB).
IMPORT_MAX_BYTES = 2 * 1024 * 1024
IMPORT_CHUNK_SIZE = 64 * 1024


def _contact_row(c: CrmContact) -> dict:
    return {
        "id": str(c.id),
        "name": c.name or "",
        "phone": c.phone or "",
        "email": c.email or "",
        "whatsapp_id": c.whatsapp_id or "",
        "source": c.source or "",
        "owner_id": str(c.owner_id) if c.owner_id else "",
        "created_at": c.created_at.isoformat() if c.created_at else "",
    }


def _deal_row(d: CrmDeal) -> dict:
    return {
        "id": str(d.id),
        "title": d.title or "",
        "contact_id": str(d.contact_id),
        "pipeline_id": str(d.pipeline_id),
        "stage_id": str(d.stage_id),
        "amount": str(d.amount) if d.amount is not None else "",
        "currency": d.currency or "",
        "status": d.status or "",
        "owner_id": str(d.owner_id) if d.owner_id else "",
        "created_at": d.created_at.isoformat() if d.created_at else "",
    }


@router.get("/api/contacts/export")
async def export_contacts(
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    search: str | None = Query(default=None, max_length=255),
    source: str | None = None,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    from ..routers.contacts import normalize_phone

    stmt = select(CrmContact).where(CrmContact.deleted_at.is_(None))
    if search:
        from sqlalchemy import or_

        term = f"%{search.strip()}%"
        digits = normalize_phone(search)
        conds = [
            CrmContact.name.ilike(term),
            CrmContact.phone.ilike(term),
            CrmContact.email.ilike(term),
            CrmContact.whatsapp_id.ilike(term),
        ]
        if len(digits) >= 4:
            conds.append(func.regexp_replace(CrmContact.phone, r"\D", "", "g").like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    if source is not None:
        stmt = stmt.where(CrmContact.source == source)
    restricted = await restrict_managers_to_own(session)
    scope = owner_condition(CrmContact.owner_id, user, restricted)
    if scope is not None:
        stmt = stmt.where(scope)
    stmt = stmt.order_by(CrmContact.created_at.desc()).limit(EXPORT_LIMIT)
    rows = (await session.execute(stmt)).scalars().all()
    dicts = [_contact_row(c) for c in rows]
    await log_activity(
        session,
        user.id,
        "export",
        None,
        "contacts_export",
        {"format": format, "search": search, "source": source, "rows": len(dicts)},
    )
    await session.commit()
    if format == "csv":
        return StreamingResponse(
            csv_stream(dicts, CONTACT_EXPORT_FIELDS),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=contacts.csv"},
        )
    data = xlsx_bytes(dicts, CONTACT_EXPORT_FIELDS)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=contacts.xlsx"},
    )


@router.get("/api/deals/export")
async def export_deals(
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    pipeline_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(open|won|lost)$"),
    search: str | None = Query(default=None, max_length=255),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(CrmDeal)
        .join(CrmContact, CrmContact.id == CrmDeal.contact_id)
        .where(CrmDeal.deleted_at.is_(None), CrmContact.deleted_at.is_(None))
    )
    if pipeline_id is not None:
        stmt = stmt.where(CrmDeal.pipeline_id == pipeline_id)
    if status is not None:
        stmt = stmt.where(CrmDeal.status == status)
    if search:
        stmt = stmt.where(CrmDeal.title.ilike(f"%{search.strip()}%"))
    restricted = await restrict_managers_to_own(session)
    scope = owner_condition(CrmDeal.owner_id, user, restricted)
    if scope is not None:
        stmt = stmt.where(scope)
    stmt = stmt.order_by(CrmDeal.created_at.desc()).limit(EXPORT_LIMIT)
    rows = (await session.execute(stmt)).scalars().all()
    dicts = [_deal_row(d) for d in rows]
    await log_activity(
        session,
        user.id,
        "export",
        None,
        "deals_export",
        {
            "format": format,
            "pipeline_id": str(pipeline_id) if pipeline_id else None,
            "status": status,
            "search": search,
            "rows": len(dicts),
        },
    )
    await session.commit()
    if format == "csv":
        return StreamingResponse(
            csv_stream(dicts, DEAL_EXPORT_FIELDS),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=deals.csv"},
        )
    data = xlsx_bytes(dicts, DEAL_EXPORT_FIELDS)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=deals.xlsx"},
    )


def _decode_upload(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


async def _read_import_upload(file: UploadFile) -> bytes:
    """Read an import file in chunks, enforcing the 2 MiB limit (413)."""
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(IMPORT_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > IMPORT_MAX_BYTES:
            raise ApiError("REQUEST_TOO_LARGE", "Import file is too large (max 2 MiB)", 413)
        parts.append(chunk)
    return b"".join(parts)


@router.post("/api/contacts/import/preview", response_model=ImportPreviewOut)
async def import_preview(
    file: UploadFile = File(...),
    mapping: str = Form(default="{}"),
    user: CurrentUser = Depends(require_user),
):
    try:
        mapping_dict = json.loads(mapping or "{}")
    except ValueError:
        raise ApiError("INVALID_MAPPING", "mapping must be JSON object", 422) from None
    if not isinstance(mapping_dict, dict):
        raise ApiError("INVALID_MAPPING", "mapping must be JSON object", 422)
    raw = await _read_import_upload(file)
    try:
        header, data = parse_csv_text(_decode_upload(raw))
    except ValueError as exc:
        raise ApiError("INVALID_CSV", str(exc), 422) from None
    records, errors = apply_mapping(header, data, {str(k): str(v) for k, v in mapping_dict.items()})
    return ImportPreviewOut(
        header=header,
        total=len(data),
        valid=len(records),
        invalid=len(errors),
        preview=records[:20],
        errors=errors[:50],
    )


def _start_import_job(job_id: str, factory) -> None:
    task = asyncio.create_task(_run_import_job(job_id, factory))
    _import_tasks.add(task)
    task.add_done_callback(_import_task_done)


def _import_task_done(task: asyncio.Task) -> None:
    _import_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("import task ended with an unexpected error", exc_info=task.exception())


@router.post("/api/contacts/import", response_model=ImportJobOut, status_code=201)
async def import_start(
    request: Request,
    file: UploadFile = File(...),
    mapping: str = Form(default="{}"),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        mapping_dict = json.loads(mapping or "{}")
    except ValueError:
        raise ApiError("INVALID_MAPPING", "mapping must be JSON object", 422) from None
    raw = await _read_import_upload(file)
    try:
        header, data = parse_csv_text(_decode_upload(raw))
    except ValueError as exc:
        raise ApiError("INVALID_CSV", str(exc), 422) from None
    job = CrmImport(
        entity="contact",
        status="queued",
        total=len(data),
        mapping={"mapping": mapping_dict, "header": header, "rows": data},
        errors=[],
        created_by=user.id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await log_activity(session, user.id, "import", job.id, "import_queued", {"total": len(data)})
    await session.commit()
    factory = request.app.state.session_factory
    _start_import_job(str(job.id), factory)
    return ImportJobOut.model_validate(job)


@router.get("/api/contacts/import/{job_id}", response_model=ImportJobOut)
async def import_status(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(CrmImport, job_id)
    if job is None or (not user.is_admin and job.created_by != user.id):
        raise ApiError("NOT_FOUND", "Import job not found", 404)
    return ImportJobOut.model_validate(job)


async def _run_import_job(job_id: str, factory) -> None:
    try:
        await _execute_import_job(job_id, factory)
    except Exception:
        logger.exception("contact import failed job_id=%s", job_id)
        await _mark_import_failed(factory, job_id, "внутренняя ошибка импорта")


async def _execute_import_job(job_id: str, factory) -> None:
    from ..services.normalize import normalize_email

    async with factory() as session:
        job = await session.get(CrmImport, uuid.UUID(job_id))
        if job is None or job.status != "queued":
            return
        job.status = "running"
        await session.commit()
        payload = job.mapping or {}
        header = payload.get("header", [])
        rows = payload.get("rows", [])
        mapping_dict = payload.get("mapping", {})
        str_mapping = {str(k): str(v) for k, v in mapping_dict.items()}
        records, pre_errors = apply_mapping(header, rows, str_mapping)
        errors: list[dict] = list(pre_errors)
        ok = 0
        for idx, record in enumerate(records):
            try:
                email = record.get("email")
                if email:
                    record["email"] = normalize_email(str(email))
                async with session.begin_nested():
                    contact = CrmContact(
                        name=record.get("name"),
                        phone=record.get("phone"),
                        email=record.get("email"),
                        whatsapp_id=record.get("whatsapp_id"),
                        source=record.get("source") or "import",
                        custom={},
                    )
                    session.add(contact)
                    await session.flush()
                ok += 1
            except IntegrityError:
                errors.append({"row": idx + 2, "error": "duplicate whatsapp_id"})
            except Exception as exc:  # noqa: BLE001 - per-row report, never fail whole job
                errors.append({"row": idx + 2, "error": str(exc)})
        job.ok_count = ok
        job.error_count = len(errors)
        job.errors = errors[:200]
        job.status = "done"
        job.finished_at = datetime.now(UTC)
        await log_activity(
            session,
            job.created_by,
            "import",
            job.id,
            "import_finished",
            {"ok": ok, "errors": len(errors)},
        )
        await session.commit()


async def _mark_import_failed(factory, job_id: str, reason: str) -> None:
    async with factory() as session:
        job = await session.get(CrmImport, uuid.UUID(job_id))
        if job is None or job.status in ("done", "failed"):
            return
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
        job.errors = [{"error": reason}]
        await session.commit()


async def fail_stale_imports(factory, now: datetime | None = None) -> int:
    """Startup: jobs still queued/running after IMPORT_STALE_AFTER have no live worker."""
    cutoff = (now or datetime.now(UTC)) - IMPORT_STALE_AFTER
    async with factory() as session:
        result = await session.execute(
            update(CrmImport)
            .where(
                CrmImport.status.in_(("queued", "running")),
                CrmImport.created_at < cutoff,
            )
            .values(
                status="failed",
                finished_at=datetime.now(UTC),
                errors=[{"error": "импорт прерван перезапуском сервера"}],
            )
            .returning(CrmImport.id)
        )
        stale = result.all()
        await session.commit()
    if stale:
        logger.warning("marked %d stale import job(s) failed", len(stale))
    return len(stale)
