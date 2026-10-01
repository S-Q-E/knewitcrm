import { describe, expect, it } from "vitest";

import { buildAnalyticsParams } from "@/api/analytics";

describe("buildAnalyticsParams", () => {
  it("omits empty filters", () => {
    expect(buildAnalyticsParams({})).toBe("");
  });

  it("encodes the full filter set", () => {
    const params = buildAnalyticsParams({
      date_from: "2026-02-10",
      date_to: "2026-02-20",
      pipeline_id: "pipe-1",
      owner_id: "user-1",
      granularity: "week",
    });
    expect(params).toContain("date_from=2026-02-10");
    expect(params).toContain("date_to=2026-02-20");
    expect(params).toContain("pipeline_id=pipe-1");
    expect(params).toContain("owner_id=user-1");
    expect(params).toContain("granularity=week");
  });
});
