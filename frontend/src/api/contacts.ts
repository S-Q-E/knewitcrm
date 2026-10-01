import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { Tag } from "@/api/deals";

export interface Contact {
  id: string;
  whatsapp_id: string | null;
  name: string | null;
  phone: string | null;
  email: string | null;
  source: string | null;
  owner_id: string | null;
  custom: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  tags: Tag[];
}

export interface ContactFilters {
  search?: string;
  owner_id?: string;
  unassigned?: boolean;
  tag?: string[];
  source?: string;
  created_from?: string;
  created_to?: string;
}

export function contactQueryString(
  params: Record<string, string | string[] | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, item);
    } else {
      search.set(key, value);
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function toContactParams(filters: ContactFilters): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  if (filters.search) params.search = filters.search;
  if (filters.owner_id) params.owner_id = filters.owner_id;
  if (filters.unassigned) params.unassigned = "true";
  if (filters.tag?.length) params.tag = filters.tag;
  if (filters.source) params.source = filters.source;
  if (filters.created_from) params.created_from = filters.created_from;
  if (filters.created_to) params.created_to = filters.created_to;
  return params;
}

export function useContactsList(
  filters: ContactFilters & { sort?: string; limit?: number; offset?: number },
) {
  const { sort = "-created_at", limit = 50, offset = 0, ...rest } = filters;
  const params = contactQueryString({
    ...toContactParams(rest),
    sort,
    limit: String(limit),
    offset: String(offset),
  });
  return useQuery({
    queryKey: ["contacts", filters],
    queryFn: () => api.get<{ items: Contact[]; total: number }>(`/api/contacts${params}`),
  });
}

export function useContact(id: string | null) {
  return useQuery({
    queryKey: ["contact", id],
    queryFn: () => api.get<Contact>(`/api/contacts/${id}`),
    enabled: id !== null,
  });
}

export function useContactDeals(id: string | null) {
  return useQuery({
    queryKey: ["contact-deals", id],
    queryFn: () =>
      api.get<{ items: import("@/api/deals").Deal[]; total: number }>(
        `/api/contacts/${id}/deals?limit=100`,
      ),
    enabled: id !== null,
  });
}

export interface ContactTimelineItem {
  key: string;
  kind: string;
  at: string;
  data: Record<string, unknown>;
}

export function useContactTimeline(id: string | null) {
  return useQuery({
    queryKey: ["contact-timeline", id],
    queryFn: () =>
      api.get<{ items: ContactTimelineItem[]; next_cursor: string | null }>(
        `/api/contacts/${id}/timeline?limit=100`,
      ),
    enabled: id !== null,
  });
}

export function useUpdateContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<Contact>(`/api/contacts/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
      void queryClient.invalidateQueries({ queryKey: ["contact"] });
    },
  });
}

export function useDeleteContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<{ ok: boolean }>(`/api/contacts/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export function useRestoreContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Contact>(`/api/contacts/${id}/restore`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
      void queryClient.invalidateQueries({ queryKey: ["trash"] });
    },
  });
}

export function useBulkContacts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      ids: string[];
      set_owner_id?: string | null;
      add_tag_id?: string | null;
      delete?: boolean;
    }) => api.post<{ updated: number }>("/api/contacts/bulk", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export interface DuplicateGroup {
  key: string;
  kind: string;
  value: string;
  contact_ids: string[];
}

export function useDuplicates() {
  return useQuery({
    queryKey: ["contact-duplicates"],
    queryFn: () => api.get<{ groups: DuplicateGroup[]; total: number }>("/api/contacts/duplicates"),
  });
}

export function useMergeContacts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { winner_id: string; loser_id: string }) =>
      api.post<Contact>("/api/contacts/merge", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
      void queryClient.invalidateQueries({ queryKey: ["contact-duplicates"] });
    },
  });
}

export interface ImportPreview {
  header: string[];
  total: number;
  valid: number;
  invalid: number;
  preview: Record<string, unknown>[];
  errors: { row: number; error: string }[];
}

export interface ImportJob {
  id: string;
  entity: string;
  status: string;
  total: number;
  ok_count: number;
  error_count: number;
  errors: { row: number; error: string }[];
  created_at: string;
  finished_at: string | null;
}

export function useImportJob(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["import-job", id],
    queryFn: () => api.get<ImportJob>(`/api/contacts/import/${id}`),
    enabled: enabled && id !== null,
    refetchInterval: enabled ? 1000 : false,
  });
}

export interface TrashItem {
  kind: string;
  id: string;
  name: string | null;
  deleted_at: string | null;
}

export function useTrash(kind: string) {
  return useQuery({
    queryKey: ["trash", kind],
    queryFn: () =>
      api.get<{ items: TrashItem[]; total: number }>(`/api/trash?kind=${kind}&limit=100`),
  });
}

export interface ContactSavedView {
  id: string;
  entity: string;
  name: string;
  filters: ContactFilters;
  is_shared: boolean;
}

export function useContactSavedViews() {
  return useQuery({
    queryKey: ["saved-views-contact"],
    queryFn: () =>
      api.get<{ items: ContactSavedView[]; total: number }>("/api/saved-views?entity=contact"),
  });
}

export function useCreateContactSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; filters: ContactFilters }) =>
      api.post<ContactSavedView>("/api/saved-views", { entity: "contact", ...input }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["saved-views-contact"] });
    },
  });
}

export function useDeleteContactSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/saved-views/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["saved-views-contact"] });
    },
  });
}

export function exportUrl(entity: "contacts" | "deals", format: "csv" | "xlsx", qs: string): string {
  return `/api/${entity}/export?format=${format}${qs ? `&${qs.slice(1)}` : ""}`;
}
