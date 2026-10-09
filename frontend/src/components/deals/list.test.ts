import { describe, expect, it } from "vitest";

import { dealSortField } from "@/components/deals/list";

describe("dealSortField", () => {
  it("sorts only by fields the backend accepts", () => {
    expect(dealSortField("amount")).toBe("amount");
    expect(dealSortField("updated")).toBe("updated_at");
    expect(dealSortField("title")).toBeNull();
    expect(dealSortField("contact")).toBeNull();
    expect(dealSortField("owner")).toBeNull();
    expect(dealSortField("tags")).toBeNull();
  });
});
