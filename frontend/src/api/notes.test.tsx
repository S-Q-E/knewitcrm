// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useCreateNote } from "@/api/deals";

vi.mock("@/api/client", () => ({ api: { post: vi.fn(async () => ({})) } }));

describe("useCreateNote", () => {
  it("refreshes the deal and contact timelines after saving a note", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useCreateNote(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ deal_id: "deal-1", body: "note" });
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["timeline"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["contact-timeline"] });
  });
});
