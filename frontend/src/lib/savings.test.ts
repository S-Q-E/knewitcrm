import { describe, expect, it } from "vitest";

import { estimateSavings } from "@/lib/savings";

describe("estimateSavings", () => {
  it("computes hours and money from dialogs and hourly cost", () => {
    const result = estimateSavings({
      automatedDialogs: 100,
      avgResponseMs: 5000,
      minutesPerInquiry: 8,
      hourlyCostUsd: 25,
      baselineMinutes: 120,
    });
    expect(result.hoursSaved).toBeCloseTo(13.33, 2);
    expect(result.moneySavedUsd).toBeCloseTo(333.33, 2);
    expect(result.botSeconds).toBe(5);
    expect(result.speedupX).toBeCloseTo(1440, 1); // 120 min / 5 s
  });

  it("handles zeros", () => {
    const result = estimateSavings({
      automatedDialogs: 0,
      avgResponseMs: 0,
      minutesPerInquiry: 8,
      hourlyCostUsd: 25,
      baselineMinutes: 120,
    });
    expect(result.hoursSaved).toBe(0);
    expect(result.moneySavedUsd).toBe(0);
    expect(result.botSeconds).toBe(0);
    // botSeconds = 0 -> speedup is undefined, not Infinity.
    expect(result.speedupX).toBeNull();
  });

  it("returns null speed metrics when response data is missing", () => {
    const result = estimateSavings({
      automatedDialogs: 10,
      avgResponseMs: null,
      minutesPerInquiry: 8,
      hourlyCostUsd: 25,
      baselineMinutes: 120,
    });
    expect(result.botSeconds).toBeNull();
    expect(result.speedupX).toBeNull();
    // Time/money still compute from dialogs and hourly cost.
    expect(result.hoursSaved).toBeCloseTo(1.33, 2);
    expect(result.moneySavedUsd).toBeCloseTo(33.33, 2);
  });
});
