import { describe, expect, it } from "vitest";

import { formatMoney, formatPhone, initials, positionBetween } from "@/lib/format";

describe("formatMoney", () => {
  it("formats USD without decimals", () => {
    const text = formatMoney(120000, "USD");
    expect(text).toContain("120");
    expect(text).toContain("$");
  });

  it("renders a dash for missing amounts", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });
});

describe("formatPhone", () => {
  it("uses the contact phone when present", () => {
    expect(formatPhone("+7 707 966 76 03")).toBe("+7 707 966 76 03");
  });

  it("falls back to the digits of the WhatsApp id", () => {
    expect(formatPhone(null, "77079667603@c.us")).toBe("+7 707 966 76 03");
    expect(formatPhone("", "77079667603@c.us")).toBe("+7 707 966 76 03");
  });

  it("returns null when there is nothing to format", () => {
    expect(formatPhone(null, null)).toBeNull();
    expect(formatPhone(undefined, "")).toBeNull();
    expect(formatPhone("—")).toBeNull();
  });

  it("does not render a Telegram chat id as a phone number", () => {
    expect(formatPhone(null, "tg:123456789")).toBeNull();
    expect(formatPhone("+1 215 555 0100", "tg:123456789")).toBe("+12155550100");
  });
});

describe("initials", () => {
  it("takes first letters", () => {
    expect(initials("Aigerim Testova")).toBe("AT");
    expect(initials(null)).toBe("?");
  });
});

describe("positionBetween", () => {
  it("computes midpoints and edges", () => {
    expect(positionBetween(null, null)).toBe(1);
    expect(positionBetween(null, 4)).toBe(3);
    expect(positionBetween(4, null)).toBe(5);
    expect(positionBetween(1, 3)).toBe(2);
  });
});
