import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";

export function formatMoney(amount: number | null | undefined, currency = "KZT"): string {
  if (amount === null || amount === undefined) {
    return "—";
  }
  return new Intl.NumberFormat("ru-KZ", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  return formatDistanceToNow(new Date(iso), { addSuffix: true, locale: ru });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  return new Intl.DateTimeFormat("ru-KZ", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** Phone for a card: the contact phone, else the digits of the WhatsApp id. */
export function formatPhone(
  phone: string | null | undefined,
  whatsappId?: string | null,
): string | null {
  const fromPhone = (phone ?? "").replace(/\D/g, "");
  const fromWhatsapp = (whatsappId ?? "").split("@")[0].replace(/\D/g, "");
  const digits = fromPhone || fromWhatsapp;
  if (!digits) {
    return null;
  }
  if (digits.length === 11 && digits.startsWith("7")) {
    return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)} ${digits.slice(7, 9)} ${digits.slice(9, 11)}`;
  }
  return `+${digits}`;
}

export function initials(name: string | null | undefined): string {
  if (!name) {
    return "?";
  }
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

/** Fractional-indexing midpoint for kanban ordering. */
export function positionBetween(before: number | null, after: number | null): number {
  if (before === null && after === null) {
    return 1;
  }
  if (before === null) {
    return (after as number) - 1;
  }
  if (after === null) {
    return before + 1;
  }
  if (after - before < 1e-9) {
    return before + 1;
  }
  return (before + after) / 2;
}
