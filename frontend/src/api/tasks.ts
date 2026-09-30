import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/types";

export type Task = components["schemas"]["TaskOut"];

export interface TaskFilters {
  assignee_id?: string;
  mine?: boolean;
  unassigned?: boolean;
  open_only?: boolean;
  overdue?: boolean;
  due_from?: string;
  due_to?: string;
  deal_id?: string;
  contact_id?: string;
}

function taskParams(filters: TaskFilters): string {
  const params = new URLSearchParams({ limit: "200" });
  if (filters.assignee_id) params.set("assignee_id", filters.assignee_id);
  if (filters.mine) params.set("mine", "true");
  if (filters.unassigned) params.set("unassigned", "true");
  if (filters.open_only) params.set("open_only", "true");
  if (filters.overdue) params.set("overdue", "true");
  if (filters.due_from) params.set("due_from", filters.due_from);
  if (filters.due_to) params.set("due_to", filters.due_to);
  if (filters.deal_id) params.set("deal_id", filters.deal_id);
  if (filters.contact_id) params.set("contact_id", filters.contact_id);
  return params.toString();
}

export function useTasks(filters: TaskFilters) {
  return useQuery({
    queryKey: ["tasks", filters],
    queryFn: () => api.get<{ items: Task[]; total: number }>(`/api/tasks?${taskParams(filters)}`),
  });
}

export function useCreateTaskFull() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      title: string;
      type?: string;
      deal_id?: string | null;
      contact_id?: string | null;
      assignee_id?: string | null;
      due_at?: string | null;
    }) => api.post<Task>("/api/tasks", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
}

export function useUpdateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<Task>(`/api/tasks/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
}

export function useCompleteTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) =>
      api.post<Task>(`/api/tasks/${id}/${done ? "complete" : "undone"}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
}

export function useDeleteTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/tasks/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
}

export interface Notification {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export function useNotifications(unreadOnly = false) {
  return useQuery({
    queryKey: ["notifications", unreadOnly],
    queryFn: () =>
      api.get<{ items: Notification[]; total: number; unread_total: number }>(
        unreadOnly ? "/api/notifications?unread_only=true" : "/api/notifications?limit=20",
      ),
    refetchInterval: 60_000,
  });
}

export function useReadNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/api/notifications/${id}/read`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useReadAllNotifications() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ marked: number }>("/api/notifications/read-all"),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
