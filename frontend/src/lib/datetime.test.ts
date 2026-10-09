import { describe, expect, it } from "vitest";

import { isoToLocalInput, localInputToIso } from "@/lib/datetime";

describe("datetime-local conversion", () => {
  it("shows the local wall clock, not the UTC hours", () => {
    const iso = "2026-10-10T05:00:00.000Z";
    const local = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    expect(isoToLocalInput(iso)).toBe(
      `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}` +
        `T${pad(local.getHours())}:${pad(local.getMinutes())}`,
    );
  });

  it("round-trips without shifting the instant", () => {
    const iso = "2026-10-10T05:30:00.000Z";
    expect(localInputToIso(isoToLocalInput(iso))).toBe(iso);
  });

  it("maps empty and invalid input to empty values", () => {
    expect(isoToLocalInput(null)).toBe("");
    expect(isoToLocalInput("not a date")).toBe("");
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("garbage")).toBeNull();
  });
});
