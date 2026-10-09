import { describe, expect, it } from "vitest";

import { statusView } from "@/components/realtime-status";

describe("statusView", () => {
  it("shows online only when live frames flow", () => {
    expect(statusView({ connected: true, fallback: false }).label).toBe("Онлайн");
  });

  it("shows polling when SSE gave up", () => {
    const view = statusView({ connected: false, fallback: true });
    expect(view.label).toBe("Резервный опрос");
    expect(view.dot).toContain("amber");
  });

  it("shows offline while reconnecting", () => {
    const view = statusView({ connected: false, fallback: false });
    expect(view.label).toBe("Нет соединения");
    expect(view.dot).toContain("red");
  });
});
