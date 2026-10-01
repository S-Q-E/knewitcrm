import { describe, expect, it } from "vitest";

import {
  DEFAULT_PREFS,
  formatInTimezone,
  loadProfilePrefs,
  saveProfilePrefs,
} from "@/api/settings";

describe("profile prefs", () => {
  it("falls back to defaults when storage is empty or corrupt", () => {
    localStorage.clear();
    expect(loadProfilePrefs()).toEqual(DEFAULT_PREFS);
    localStorage.setItem("knewitcrm-profile-prefs", "not-json{{{");
    expect(loadProfilePrefs()).toEqual(DEFAULT_PREFS);
  });

  it("round-trips timezone and sound", () => {
    localStorage.clear();
    saveProfilePrefs({ timezone: "UTC", sound: false });
    expect(loadProfilePrefs()).toEqual({ timezone: "UTC", sound: false });
  });
});

describe("formatInTimezone", () => {
  it("formats the same instant differently per timezone", () => {
    // Asia/Almaty is UTC+5 year-round (no DST since 2024).
    const almaty = formatInTimezone("2026-01-01T00:00:00Z", "Asia/Almaty");
    const utc = formatInTimezone("2026-01-01T00:00:00Z", "UTC");
    expect(almaty).toContain("05:00");
    expect(utc).toContain("00:00");
  });
});
