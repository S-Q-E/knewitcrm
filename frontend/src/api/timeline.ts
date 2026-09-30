import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
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
  return useQuery({
    queryKey: ["lead-messages", whatsappId],
    queryFn: () =>
      api.get<{
        items: {
          id: number;
          direction: string;
          content: string | null;
          stage_at_moment: string | null;
          created_at: string;
        }[];
      }>(`/api/leads/${encodeURIComponent(whatsappId as string)}/messages?limit=500`),
    enabled: whatsappId !== null,
  });
}
