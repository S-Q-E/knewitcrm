import { describe, expect, it } from "vitest";

import { importJobPollInterval } from "@/api/contacts";

describe("importJobPollInterval", () => {
  it("keeps polling while the job is queued or running", () => {
    expect(importJobPollInterval({ data: { status: "queued" }, error: null })).toBe(1000);
    expect(importJobPollInterval({ data: { status: "running" }, error: null })).toBe(1000);
  });

  it("stops on a terminal status", () => {
    expect(importJobPollInterval({ data: { status: "done" }, error: null })).toBe(false);
    expect(importJobPollInterval({ data: { status: "failed" }, error: null })).toBe(false);
  });

  it("stops after a request error instead of retrying every second", () => {
    expect(importJobPollInterval({ data: undefined, error: new Error("404") })).toBe(false);
  });
});
