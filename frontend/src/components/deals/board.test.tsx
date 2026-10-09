// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DealsBoard } from "@/components/deals/board";
import { ToastProvider } from "@/components/toast";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api/client", () => ({ api: { get, post: vi.fn(), put: vi.fn(), patch: vi.fn() } }));

const STAGE = "11111111-1111-4111-8111-111111111111";
const PIPELINE = "22222222-2222-4222-8222-222222222222";

function deal(index: number) {
  return {
    id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    contact_id: "33333333-3333-4333-8333-333333333333",
    pipeline_id: PIPELINE,
    stage_id: STAGE,
    title: `Deal ${index}`,
    amount: null,
    currency: "KZT",
    owner_id: null,
    status: "open",
    position: index,
    tags: [],
    updated_at: "2026-10-09T10:00:00Z",
    created_at: "2026-10-09T10:00:00Z",
  };
}

function page(from: number, to: number, nextCursor: string | null) {
  const items = Array.from({ length: to - from + 1 }, (_, i) => deal(from + i));
  return {
    pipeline_id: PIPELINE,
    columns: [
      {
        stage_id: STAGE,
        name: "Stage",
        kind: "open",
        total: 120,
        amount_total: 0,
        next_cursor: nextCursor,
        items,
      },
    ],
  };
}

afterEach(() => {
  cleanup();
  get.mockReset();
});

describe("DealsBoard pagination", () => {
  it("keeps every loaded page visible after several 'show more' clicks", async () => {
    get.mockImplementation(async (url: string) => {
      if (url.includes("cursors=") && url.includes("cursor-2")) {
        return page(51, 100, "cursor-3");
      }
      if (url.includes("cursors=") && url.includes("cursor-3")) {
        return page(101, 120, null);
      }
      return page(1, 50, "cursor-2");
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <DealsBoard
            pipelineId={PIPELINE}
            pipelineName="Main"
            stageKind={new Map([[STAGE, "open"]])}
            stageColor={new Map([[STAGE, "#888"]])}
            filters={{}}
            contactsById={new Map()}
            onQuickCreate={vi.fn()}
            onOpen={vi.fn()}
            onNote={vi.fn()}
            onWrite={vi.fn()}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );

    await screen.findByText("Deal 1", {}, { timeout: 10000 });
    fireEvent.click(await screen.findByRole("button", { name: /Показать ещё/ }));
    await screen.findByText("Deal 51");
    fireEvent.click(await screen.findByRole("button", { name: /Показать ещё/ }));
    await screen.findByText("Deal 120");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    await waitFor(() => expect(screen.queryByRole("button", { name: /Показать ещё/ })).toBeNull());
    expect(screen.getByText("Deal 1")).toBeTruthy();
    expect(screen.getByText("Deal 51")).toBeTruthy();
    expect(screen.getByText("Deal 120")).toBeTruthy();
  }, 20000);
});
