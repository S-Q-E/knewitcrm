// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { backoffDelay, invalidationFor, useEventStream } from "@/api/stream";
import { Toaster, ToastProvider } from "@/components/toast";
import { playPing } from "@/lib/sound";

vi.mock("@/api/auth", () => ({ useMe: () => ({ data: { id: "me-1" } }) }));
vi.mock("@/lib/sound", () => ({ playPing: vi.fn() }));

type Listener = (event: { data: string }) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, Listener[]>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: Listener) {
    const list = this.listeners.get(type) ?? [];
    list.push(handler);
    this.listeners.set(type, list);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    for (const handler of this.listeners.get(type) ?? []) {
      handler({ data: JSON.stringify(data) });
    }
  }

  fail() {
    this.onerror?.();
  }
}

function renderHook(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Toaster />
        <Probe />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function Probe() {
  useEventStream();
  return null;
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.clearAllMocks();
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("backoffDelay", () => {
  it("doubles from 1s and caps at 30s", () => {
    expect(backoffDelay(0)).toBe(1000);
    expect(backoffDelay(1)).toBe(2000);
    expect(backoffDelay(4)).toBe(16000);
    expect(backoffDelay(5)).toBe(30000);
    expect(backoffDelay(99)).toBe(30000);
    expect(backoffDelay(-3)).toBe(1000);
  });
});

describe("invalidationFor", () => {
  it("maps every stream event to query keys", () => {
    expect(invalidationFor({ type: "new_message", data: { whatsapp_id: "w" } })).toContainEqual([
      "lead-messages",
      "w",
    ]);
    expect(invalidationFor({ type: "new_message", data: {} })).toEqual([["dialogs"], ["timeline"]]);
    expect(invalidationFor({ type: "deal_moved", data: {} })).toContainEqual(["board"]);
    expect(invalidationFor({ type: "deal_updated", data: {} })).toContainEqual(["deals"]);
    expect(invalidationFor({ type: "task_created", data: {} })).toContainEqual(["tasks"]);
    expect(invalidationFor({ type: "notification", data: {} })).toEqual([["notifications"]]);
    expect(invalidationFor({ type: "bot_paused", data: { whatsapp_id: "w" } })).toContainEqual([
      "dialog",
      "w",
    ]);
    expect(invalidationFor({ type: "outbox_status", data: { whatsapp_id: "w" } })).toContainEqual([
      "outbox",
      "w",
    ]);
    expect(invalidationFor({ type: "something_new", data: {} })).toEqual([]);
  });
});

describe("useEventStream", () => {
  it("opens one stream and invalidates on events", () => {
    const queryClient = new QueryClient();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    queryClient.setQueryData(["dialog", "wa-1"], { assigned_to: "someone-else" });
    renderHook(queryClient);

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/stream");

    FakeEventSource.instances[0].emit("new_message", {
      whatsapp_id: "wa-1",
      direction: "in",
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["dialogs"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["lead-messages", "wa-1"] });
    expect(playPing).not.toHaveBeenCalled();
  });

  it("pings and toasts incoming messages in own dialogs", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["dialog", "wa-9"], { assigned_to: "me-1" });
    renderHook(queryClient);

    act(() => {
      FakeEventSource.instances[0].emit("new_message", {
        whatsapp_id: "wa-9",
        direction: "in",
      });
    });
    expect(playPing).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Новое сообщение в вашем диалоге")).toBeTruthy();
  });

  it("reconnects with backoff and falls back to polling", () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    renderHook(queryClient);

    expect(FakeEventSource.instances).toHaveLength(1);
    for (let i = 0; i < 6; i++) {
      FakeEventSource.instances[FakeEventSource.instances.length - 1].fail();
      vi.runOnlyPendingTimers();
    }
    // Six failures: five reconnects, then the polling fallback.
    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(5);
    spy.mockClear();
    vi.advanceTimersByTime(15000);
    expect(spy).toHaveBeenCalledWith({ queryKey: ["dialogs"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["notifications"] });
  });
});
