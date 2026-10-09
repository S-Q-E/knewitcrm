import { describe, expect, it } from "vitest";

import { type LeadMessage, mergeLeadMessages } from "@/api/timeline";

function message(id: number): LeadMessage {
  return {
    id,
    direction: "in",
    message_type: "chat",
    content: `msg-${id}`,
    stage_at_moment: null,
    created_at: "2026-10-09T10:00:00Z",
  };
}

describe("mergeLeadMessages", () => {
  it("puts older pages before the newest window", () => {
    const merged = mergeLeadMessages([message(1), message(2)], [message(3), message(4)]);
    expect(merged.map((item) => item.id)).toEqual([1, 2, 3, 4]);
  });

  it("keeps a message that appears in both lists once, from the newer list", () => {
    const newest = [{ ...message(3), content: "fresh" }, message(4)];
    const merged = mergeLeadMessages([message(2), message(3)], newest);
    expect(merged.map((item) => item.id)).toEqual([2, 3, 4]);
    expect(merged[1].content).toBe("fresh");
  });
});
