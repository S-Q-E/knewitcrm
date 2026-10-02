from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Iterable

CONTACT_EXPORT_FIELDS = (
    "id",
    "name",
    "phone",
    "email",
    "whatsapp_id",
    "source",
    "owner_id",
    "created_at",
)

DEAL_EXPORT_FIELDS = (
    "id",
    "title",
    "contact_id",
    "pipeline_id",
    "stage_id",
    "amount",
    "currency",
    "status",
    "owner_id",
    "created_at",
)


def csv_stream(rows: Iterable[dict], fields: tuple[str, ...]) -> AsyncIterator[bytes]:
    """Yield UTF-8 BOM + CSV chunks (Excel-friendly)."""

    async def _gen() -> AsyncIterator[bytes]:
        yield "\ufeff".encode()
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue().encode()
        for row in rows:
            buf.seek(0)
            buf.truncate(0)
            writer.writerow({k: _cell(row.get(k)) for k in fields})
            yield buf.getvalue().encode()

    return _gen()


def _cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    # CSV/XLSX formula injection: prefix values starting with a trigger
    # character so Excel/Sheets treat them as plain text.
    if text[:1] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + text
    return text


def xlsx_bytes(rows: list[dict], fields: tuple[str, ...]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("export")
    ws.append(list(fields))
    for row in rows:
        ws.append([_cell(row.get(k)) for k in fields])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
