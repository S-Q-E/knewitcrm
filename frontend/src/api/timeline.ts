import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { useStreamStatus } from "@/api/stream";
import type { components } from "@/api/types";

export type TimelineItem = components["schemas"]["TimelineItemOut"];

export type TimelineKind = "message" | "event" | "stage" | "note" | "task" | "activity";

export const TIMELINE_FILTERS: { id: TimelineKind; label: string }[] = [
  { id: "message", label: "Сообщения" },
  { id: "event", label: "События" },
  { id: "stage", label: "Стадии" },
  { id: "note", label: "Заметки" },
  { id: "task", label: "Задачи" },
  { id: "activity", label: "Системные" },
];

export function useTimeline(dealId: string | null, kinds: TimelineKind[], cursor: string | null) {
  return useQuery({
    queryKey: ["timeline", dealId, kinds, cursor],
    queryFn: () => {
      const params = new URLSearchParams({ limit: "50", types: kinds.join(",") });
      if (cursor) {
        params.set("cursor", cursor);
      }
      return api.get<{ items: TimelineItem[]; next_cursor: string | null }>(
        `/api/deals/${dealId}/timeline?${params.toString()}`,
      );
    },
    enabled: dealId !== null,
  });
}

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      deal_id?: string;
      contact_id?: string;
      title: string;
      type?: string;
      due_at?: string | null;
      assignee_id?: string | null;
    }) => api.post(`/api/tasks`, input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
}

export interface DialogSummary {
  whatsapp_id: string;
  contact_id: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  bot_paused: boolean;
  assigned_to: string | null;
  assignee_name: string | null;
  unread_count: number;
  last_read_at: string | null;
  last_message: { direction: string; content: string | null; created_at: string } | null;
}

export interface DialogFilters {
  assigned?: string;
  unread?: boolean;
  search?: string;
}

export function useDialogs(filters: DialogFilters) {
  const params = new URLSearchParams({ limit: "100" });
  if (filters.assigned) params.set("assigned", filters.assigned);
  if (filters.unread) params.set("unread", "true");
  if (filters.search) params.set("search", filters.search);
  return useQuery({
    queryKey: ["dialogs", filters],
    queryFn: () => api.get<{ items: DialogSummary[]; total: number }>(`/api/dialogs?${params}`),
  });
}

export function useDialog(whatsappId: string | null) {
  return useQuery({
    queryKey: ["dialog", whatsappId],
    queryFn: () =>
      api.get<DialogSummary>(`/api/dialogs/${encodeURIComponent(whatsappId as string)}`),
    enabled: whatsappId !== null,
  });
}

export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (whatsappId: string) =>
      api.post(`/api/dialogs/${encodeURIComponent(whatsappId)}/read`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["dialogs"] });
      void queryClient.invalidateQueries({ queryKey: ["dialog"] });
    },
  });
}

export function useUpdateDialog() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { whatsapp_id: string; patch: Record<string, unknown> }) =>
      api.patch<DialogSummary>(
        `/api/dialogs/${encodeURIComponent(input.whatsapp_id)}`,
        input.patch,
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["dialogs"] });
      void queryClient.invalidateQueries({ queryKey: ["dialog"] });
    },
  });
}

export function useLeadMessages(whatsappId: string | null) {
  const { connected } = useStreamStatus();
  return useQuery({
    queryKey: ["lead-messages", whatsappId],
    queryFn: () =>
      api.get<{
        items: {
          id: number;
          direction: string;
          message_type: string;
          content: string | null;
          stage_at_moment: string | null;
          created_at: string;
        }[];
      }>(`/api/dialogs/${encodeURIComponent(whatsappId as string)}/messages?limit=500`),
    enabled: whatsappId !== null,
    // Live updates arrive over SSE; poll only as a fallback while offline.
    refetchInterval: connected ? false : 5000,
  });
}

export interface OutboxItem {
  id: string;
  whatsapp_id: string;
  body: string;
  sent_by: string | null;
  status: "queued" | "sent" | "failed";
  attempts: number;
  next_attempt_at: string | null;
  error: string | null;
  provider_message_id: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface QuickReply {
  id: string;
  title: string;
  body: string;
  sort: number;
}

export function useOutbox(whatsappId: string | null) {
  const { connected } = useStreamStatus();
  return useQuery({
    queryKey: ["outbox", whatsappId],
    queryFn: () =>
      api.get<{ items: OutboxItem[]; total: number }>(
        `/api/chats/${encodeURIComponent(whatsappId as string)}/outbox?limit=100`,
      ),
    enabled: whatsappId !== null,
    // Live updates arrive over SSE; poll only as a fallback while offline.
    refetchInterval: connected ? false : 3000,
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { whatsapp_id: string; body: string }) =>
      api.post<OutboxItem>(`/api/chats/${encodeURIComponent(input.whatsapp_id)}/messages`, {
        body: input.body,
      }),
    onSettled: (_data, _error, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["outbox", variables.whatsapp_id] });
      void queryClient.invalidateQueries({ queryKey: ["lead-messages", variables.whatsapp_id] });
      void queryClient.invalidateQueries({ queryKey: ["dialog", variables.whatsapp_id] });
      void queryClient.invalidateQueries({ queryKey: ["dialogs"] });
    },
  });
}

export function useRetryOutbox() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { whatsapp_id: string; outbox_id: string }) =>
      api.post<OutboxItem>(`/api/chats/outbox/${input.outbox_id}/retry`),
    onSettled: (_data, _error, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["outbox", variables.whatsapp_id] });
    },
  });
}

export function useQuickReplies() {
  return useQuery({
    queryKey: ["quick-replies"],
    queryFn: () => api.get<{ items: QuickReply[] }>(`/api/chats/quick-replies`),
    staleTime: 60000,
  });
}

export function usePauseBot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (whatsappId: string) =>
      api.post<DialogSummary>(`/api/chats/${encodeURIComponent(whatsappId)}/bot/pause`),
    onSettled: (_data, _error, whatsappId) => {
      void queryClient.invalidateQueries({ queryKey: ["dialog", whatsappId] });
      void queryClient.invalidateQueries({ queryKey: ["dialogs"] });
    },
  });
}

export function useResumeBot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (whatsappId: string) =>
      api.post<DialogSummary>(`/api/chats/${encodeURIComponent(whatsappId)}/bot/resume`),
    onSettled: (_data, _error, whatsappId) => {
      void queryClient.invalidateQueries({ queryKey: ["dialog", whatsappId] });
      void queryClient.invalidateQueries({ queryKey: ["dialogs"] });
    },
  });
}
