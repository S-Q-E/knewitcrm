import { describe, expect, it } from "vitest";

import { formatMoney, initials, positionBetween } from "@/lib/format";

describe("formatMoney", () => {
  it("formats KZT without decimals", () => {
    const text = formatMoney(120000, "KZT");
    expect(text).toContain("120");
    expect(text).toContain("₸");
  });

  it("renders a dash for missing amounts", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });
});

describe("initials", () => {
  it("takes first letters", () => {
    expect(initials("Айгерим Тестова")).toBe("АТ");
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
