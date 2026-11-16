import { describe, expect, it } from "vitest";

import { substituteQuickReply } from "@/lib/quick_replies";

describe("substituteQuickReply", () => {
  it("replaces every {name} occurrence", () => {
    expect(substituteQuickReply("Hello, {name}! This is {name}.", "Aigerim")).toBe(
      "Hello, Aigerim! This is Aigerim.",
    );
  });

  it("falls back to an empty string without a name", () => {
    expect(substituteQuickReply("Hello, {name}!", null)).toBe("Hello, !");
    expect(substituteQuickReply("Hello, {name}!", "  ")).toBe("Hello, !");
  });

  it("leaves bodies without the placeholder untouched", () => {
    expect(substituteQuickReply("Good afternoon!", "Aigerim")).toBe("Good afternoon!");
  });
});
