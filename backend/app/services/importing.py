from __future__ import annotations

import csv
import io
import uuid

CONTACT_IMPORTABLE = ("name", "phone", "email", "whatsapp_id", "source")


def parse_csv_text(text: str, max_rows: int = 2000) -> tuple[list[str], list[list[str]]]:
    sample = text[:100000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("empty csv")
    header, data = rows[0], rows[1:]
    if len(data) > max_rows:
        raise ValueError(f"too many rows (max {max_rows})")
    return [h.strip() for h in header], data


def apply_mapping(
    header: list[str], rows: list[list[str]], mapping: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    """Map CSV columns to contact fields. Returns (records, row_errors)."""
    records: list[dict] = []
    errors: list[dict] = []
    for idx, row in enumerate(rows, start=2):
        record: dict[str, str | None] = {}
        padded = row + [""] * (len(header) - len(row))
        for col, field in mapping.items():
            if field in (None, "", "ignore"):
                continue
            if field not in CONTACT_IMPORTABLE:
                errors.append({"row": idx, "error": f"unknown field {field}"})
                record = {}
                break
            try:
                pos = header.index(col)
            except ValueError:
                errors.append({"row": idx, "error": f"unknown column {col}"})
                record = {}
                break
            record[field] = padded[pos].strip() or None
        else:
            err = validate_record(record, idx)
            if err:
                errors.append(err)
            else:
                records.append(record)
            continue
        continue
    return records, errors


def validate_record(record: dict, row_no: int) -> dict | None:
    if not any(record.get(k) for k in ("name", "phone", "email", "whatsapp_id")):
        return {"row": row_no, "error": "empty row: need name, phone, email or whatsapp_id"}
    if record.get("email") and "@" not in str(record["email"]):
        return {"row": row_no, "error": "invalid email"}
    return None


def preview_from_text(
    text: str, mapping: dict[str, str], limit: int = 20
) -> dict:
    header, data = parse_csv_text(text)
    records, errors = apply_mapping(header, data, mapping)
    return {
        "header": header,
        "total": len(data),
        "valid": len(records),
        "invalid": len(errors),
        "preview": records[:limit],
        "errors": errors[:50],
    }


def new_job_id() -> uuid.UUID:
    return uuid.uuid4()
