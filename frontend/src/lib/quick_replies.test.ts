import { describe, expect, it } from "vitest";

import { substituteQuickReply } from "@/lib/quick_replies";

describe("substituteQuickReply", () => {
  it("replaces every {name} occurrence", () => {
    expect(substituteQuickReply("{name}, здравствуйте! Это {name}.", "Асель")).toBe(
      "Асель, здравствуйте! Это Асель.",
    );
  });

  it("falls back to an empty string without a name", () => {
    expect(substituteQuickReply("Здравствуйте, {name}!", null)).toBe("Здравствуйте, !");
    expect(substituteQuickReply("Здравствуйте, {name}!", "  ")).toBe("Здравствуйте, !");
  });

  it("leaves bodies without the placeholder untouched", () => {
    expect(substituteQuickReply("Добрый день!", "Асель")).toBe("Добрый день!");
  });
});
