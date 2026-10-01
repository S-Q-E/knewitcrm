from __future__ import annotations

import re

_DIGITS = re.compile(r"\D+")


def normalize_phone(value: str | None) -> str:
    """Normalize phone/whatsapp to digits.

    - strips non-digits, drops `@c.us` / `@lid` style suffixes implicitly
    - converts leading 8 -> 7 for 11-digit KZ/RU numbers
    - returns "" when nothing usable remains
    """
    if not value:
        return ""
    digits = _DIGITS.sub("", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def normalize_whatsapp(value: str | None) -> str:
    """whatsapp_id like `79991234567@c.us` -> normalized digits."""
    if not value:
        return ""
    local = value.split("@")[0].strip()
    return normalize_phone(local)


def normalize_email(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def phone_key(value: str | None) -> str | None:
    digits = normalize_phone(value)
    return digits if len(digits) >= 7 else None


def contact_keys(
    phone: str | None, whatsapp_id: str | None, email: str | None
) -> dict[str, str | None]:
    """Grouping keys used for duplicate detection."""
    from_wa = normalize_whatsapp(whatsapp_id)
    from_phone = normalize_phone(phone)
    # whatsapp digits and phone digits live in the same space; prefer the longest.
    merged_phone: str | None = None
    candidates = [d for d in (from_phone, from_wa) if len(d) >= 7]
    if candidates:
        merged_phone = max(candidates, key=len)
    mail = normalize_email(email) or None
    return {"phone": merged_phone, "email": mail}
