import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useMe } from "@/api/auth";
import { useToast } from "@/components/toast";
import { playPing } from "@/lib/sound";

export interface StreamEvent {
  type: string;
  data: Record<string, unknown>;
}

export const KNOWN_STREAM_EVENTS = [
  "new_message",
  "bot_event",
  "deal_moved",
  "deal_updated",
  "task_created",
  "notification",
  "bot_paused",
  "outbox_status",
] as const;

const MAX_SSE_FAILURES = 5;
const POLL_FALLBACK_MS = 15_000;

/** Reconnect delay: 1s, 2s, 4s … capped at 30s. */
export function backoffDelay(attempt: number): number {
  return Math.min(1000 * 2 ** Math.max(0, attempt), 30000);
}

function whatsappOf(data: Record<string, unknown>): string | null {
  return typeof data.whatsapp_id === "string" ? data.whatsapp_id : null;
}

/** TanStack Query keys to refresh when a stream event arrives. */
export function invalidationFor(event: StreamEvent): string[][] {
  switch (event.type) {
    case "new_message": {
      const keys: string[][] = [["dialogs"], ["timeline"]];
      const wa = whatsappOf(event.data);
      if (wa) {
        keys.push(["lead-messages", wa], ["dialog", wa], ["outbox", wa]);
      }
      return keys;
    }
    case "bot_event":
      return [["timeline"], ["board"]];
    case "deal_moved":
    case "deal_updated":
      return [["board"], ["deals"], ["deal"], ["timeline"]];
    case "task_created":
      return [["tasks"], ["timeline"]];
    case "notification":
      return [["notifications"]];
    case "bot_paused": {
      const wa = whatsappOf(event.data);
      return wa ? [["dialog", wa], ["dialogs"]] : [["dialogs"]];
    }
    case "outbox_status": {
      const wa = whatsappOf(event.data);
      return wa
        ? [
            ["outbox", wa],
            ["lead-messages", wa],
          ]
        : [["outbox"]];
    }
    default:
      return [];
  }
}

/** Queries refreshed by the polling fallback when SSE is unavailable. */
export const FALLBACK_POLL_KEYS: string[][] = [
  ["dialogs"],
  ["board"],
  ["notifications"],
  ["timeline"],
  ["tasks"],
  ["outbox"],
  ["lead-messages"],
];

interface DialogCache {
  assigned_to?: string | null;
}

/**
 * Single realtime subscription for the whole app. Opens one EventSource to
 * /api/stream, invalidates TanStack Query caches per event, and falls back
 * to 15s polling when SSE is unavailable or keeps failing. Mount once in
 * the authenticated layout.
 */
export function useEventStream() {
  const queryClient = useQueryClient();
  const { push } = useToast();
  const me = useMe();

  useEffect(() => {
    let disposed = false;
    let failures = 0;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const invalidate = (keys: string[][]) => {
      for (const key of keys) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    };

    const handle = (event: StreamEvent) => {
      if (
        event.type === "new_message" &&
        event.data.direction === "in" &&
        typeof event.data.whatsapp_id === "string"
      ) {
        const dialog = queryClient.getQueryData<DialogCache>(["dialog", event.data.whatsapp_id]);
        if (dialog?.assigned_to && me.data && dialog.assigned_to === me.data.id) {
          playPing();
          push({ title: "Новое сообщение в вашем диалоге", variant: "default" });
        }
      }
      invalidate(invalidationFor(event));
    };

    const startPolling = () => {
      if (pollTimer || disposed) {
        return;
      }
      pollTimer = setInterval(() => invalidate(FALLBACK_POLL_KEYS), POLL_FALLBACK_MS);
    };

    const stopSource = () => {
      source?.close();
      source = null;
    };

    const connect = () => {
      if (disposed || pollTimer) {
        return;
      }
      if (typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      const next = new EventSource("/api/stream");
      source = next;
      for (const type of KNOWN_STREAM_EVENTS) {
        next.addEventListener(type, (raw) => {
          try {
            handle({ type, data: JSON.parse((raw as MessageEvent).data) });
          } catch {
            // Malformed payload: skip, keep the stream alive.
          }
        });
      }
      next.onopen = () => {
        failures = 0;
      };
      next.onerror = () => {
        stopSource();
        if (disposed) {
          return;
        }
        failures += 1;
        if (failures > MAX_SSE_FAILURES) {
          startPolling();
          return;
        }
        reconnectTimer = setTimeout(connect, backoffDelay(failures));
      };
    };

    connect();
    return () => {
      disposed = true;
      stopSource();
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      if (pollTimer) {
        clearInterval(pollTimer);
      }
    };
    // Re-subscribe when the user changes; helpers are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.data?.id]);
}
