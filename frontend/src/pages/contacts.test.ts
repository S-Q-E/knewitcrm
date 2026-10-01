import { describe, expect, it } from "vitest";

import { contactQueryString, exportUrl } from "@/api/contacts";
import { autoMapping } from "@/pages/contacts";

describe("contacts helpers", () => {
  it("builds query string for filters", () => {
    expect(contactQueryString({ search: "иван", sort: "-created_at" })).toContain("search=");
    expect(contactQueryString({})).toBe("");
  });

  it("maps CSV headers to contact fields", () => {
    const mapping = autoMapping(["full_name", "phone_number", "email", "unknown_col"]);
    expect(mapping["full_name"]).toBe("name");
    expect(mapping["phone_number"]).toBe("phone");
    expect(mapping["email"]).toBe("email");
    expect(mapping["unknown_col"]).toBe("ignore");
  });

  it("builds export urls with current filters", () => {
    expect(exportUrl("contacts", "csv", "?search=x")).toBe(
      "/api/contacts/export?format=csv&search=x",
    );
    expect(exportUrl("deals", "xlsx", "")).toBe("/api/deals/export?format=xlsx");
  });
});
