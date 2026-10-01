from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
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

router = APIRouter(tags=["data-exchange"])

EXPORT_LIMIT = 10000


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
    stmt = stmt.order_by(CrmContact.created_at.desc()).limit(EXPORT_LIMIT)
    rows = (await session.execute(stmt)).scalars().all()
    dicts = [_contact_row(c) for c in rows]
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
    stmt = select(CrmDeal).where(CrmDeal.deleted_at.is_(None))
    if pipeline_id is not None:
        stmt = stmt.where(CrmDeal.pipeline_id == pipeline_id)
    if status is not None:
        stmt = stmt.where(CrmDeal.status == status)
    if search:
        stmt = stmt.where(CrmDeal.title.ilike(f"%{search.strip()}%"))
    stmt = stmt.order_by(CrmDeal.created_at.desc()).limit(EXPORT_LIMIT)
    rows = (await session.execute(stmt)).scalars().all()
    dicts = [_deal_row(d) for d in rows]
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
    raw = await file.read()
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
    raw = await file.read()
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
    asyncio.create_task(_run_import_job(str(job.id), factory))
    return ImportJobOut.model_validate(job)


@router.get("/api/contacts/import/{job_id}", response_model=ImportJobOut)
async def import_status(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(CrmImport, job_id)
    if job is None:
        raise ApiError("NOT_FOUND", "Import job not found", 404)
    return ImportJobOut.model_validate(job)


async def _run_import_job(job_id: str, factory) -> None:
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
            except Exception as exc:  # noqa: BLE001 - per-row report, never fail whole job
                errors.append({"row": idx + 2, "error": str(exc)})
        job.ok_count = ok
        job.error_count = len(errors)
        job.errors = errors[:200]
        job.status = "done"
        job.finished_at = datetime.now(UTC)
        await session.commit()
