import { describe, expect, it } from "vitest";

import { ApiError, parseApiError } from "@/api/client";
import { cn, getCookie } from "@/lib/utils";

describe("cn", () => {
  it("merges tailwind classes", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
    expect(cn("text-sm", { hidden: false })).toBe("text-sm");
  });
});

describe("getCookie", () => {
  it("reads a cookie value", () => {
    document.cookie = "crm_csrf=token-123";
    expect(getCookie("crm_csrf")).toBe("token-123");
    expect(getCookie("missing")).toBeNull();
  });
});

describe("parseApiError", () => {
  it("parses the backend error envelope", () => {
    const err = parseApiError(422, {
      error: { code: "VALIDATION_ERROR", message: "Invalid request", details: [] },
    });
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("VALIDATION_ERROR");
    expect(err.status).toBe(422);
  });

  it("falls back for unknown bodies", () => {
    const err = parseApiError(500, "<html>oops</html>");
    expect(err.code).toBe("UNKNOWN_ERROR");
    expect(err.message).toContain("500");
  });
});
