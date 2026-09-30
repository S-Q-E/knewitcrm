import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/types";

export type Pipeline = components["schemas"]["PipelineOut"];
export type Stage = components["schemas"]["StageOut"];
export type Deal = components["schemas"]["DealOut"];
export type Board = components["schemas"]["BoardOut"];
export type BoardColumn = components["schemas"]["BoardColumnOut"];
export type Tag = components["schemas"]["TagOut"];
export type LostReason = components["schemas"]["LostReasonOut"];
export type LiteUser = Pick<components["schemas"]["UserOut"], "id" | "name">;

export interface DealFilters {
  search?: string;
  owner_id?: string;
  unassigned?: boolean;
  tag?: string[];
  contact_source?: string;
  created_from?: string;
  created_to?: string;
  status?: string;
}

export function toBoardParams(filters: DealFilters): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  if (filters.search) params.search = filters.search;
  if (filters.owner_id) params.owner_id = filters.owner_id;
  if (filters.unassigned) params.unassigned = "true";
  if (filters.tag?.length) params.tag = filters.tag;
  if (filters.contact_source) params.contact_source = filters.contact_source;
  if (filters.created_from) params.created_from = filters.created_from;
  if (filters.created_to) params.created_to = filters.created_to;
  return params;
}

function queryString(params: Record<string, string | string[]>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, item);
    } else {
      search.set(key, value);
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function usePipelines() {
  return useQuery({
    queryKey: ["pipelines"],
    queryFn: () => api.get<Pipeline[]>("/api/pipelines"),
  });
}

export function useBoard(
  pipelineId: string | null,
  filters: DealFilters,
  limit = 50,
  cursors: Record<string, string> = {},
) {
  const filterParams = toBoardParams(filters);
  return useQuery({
    queryKey: ["board", pipelineId, filters, limit, cursors],
    queryFn: () => {
      const params: Record<string, string | string[]> = {
        pipeline_id: pipelineId as string,
        limit: String(limit),
        ...filterParams,
      };
      if (Object.keys(cursors).length > 0) {
        params.cursors = JSON.stringify(cursors);
      }
      return api.get<Board>(`/api/deals/board${queryString(params)}`);
    },
    enabled: pipelineId !== null,
  });
}

export function useCreateDeal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      contact_id: string;
      pipeline_id: string;
      stage_id: string;
      title: string;
      amount?: number | null;
    }) => api.post<Deal>("/api/deals", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["board"] });
      void queryClient.invalidateQueries({ queryKey: ["deals"] });
    },
  });
}

export interface MoveInput {
  id: string;
  stage_id: string;
  position?: number | null;
  lost_reason_id?: string | null;
}

export function useMoveDeal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: MoveInput) =>
      api.post<Deal>(`/api/deals/${input.id}/move`, {
        stage_id: input.stage_id,
        position: input.position ?? null,
        lost_reason_id: input.lost_reason_id ?? null,
      }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["board"] });
      void queryClient.invalidateQueries({ queryKey: ["deals"] });
    },
  });
}

export function useUnlockDeal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Deal>(`/api/deals/${id}/unlock-bot`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["board"] });
      void queryClient.invalidateQueries({ queryKey: ["deals"] });
    },
  });
}

export function useUpdateDeal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<Deal>(`/api/deals/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["board"] });
      void queryClient.invalidateQueries({ queryKey: ["deals"] });
    },
  });
}

export function useBulkDeals() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      ids: string[];
      set_owner_id?: string | null;
      set_stage_id?: string | null;
      add_tag_id?: string | null;
      close_lost_reason_id?: string | null;
    }) => api.post<{ updated: number }>("/api/deals/bulk", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["board"] });
      void queryClient.invalidateQueries({ queryKey: ["deals"] });
    },
  });
}

export function useDealsList(
  filters: DealFilters & { sort?: string; limit?: number; offset?: number },
) {
  const { sort = "-created_at", limit = 50, offset = 0, ...rest } = filters;
  const params = queryString({
    ...toBoardParams(rest),
    sort,
    limit: String(limit),
    offset: String(offset),
  });
  return useQuery({
    queryKey: ["deals", filters],
    queryFn: () => api.get<{ items: Deal[]; total: number }>(`/api/deals${params}`),
  });
}

export function useTags() {
  return useQuery({
    queryKey: ["tags"],
    queryFn: () => api.get<{ items: Tag[]; total: number }>("/api/tags?limit=200"),
  });
}

export function useUsersLite() {
  return useQuery({
    queryKey: ["users-lite"],
    queryFn: () => api.get<{ items: LiteUser[] }>("/api/users"),
  });
}

export function useLostReasons() {
  return useQuery({
    queryKey: ["lost-reasons"],
    queryFn: () => api.get<{ items: LostReason[]; total: number }>("/api/lost-reasons?limit=100"),
  });
}

export function useCreateNote() {
  return useMutation({
    mutationFn: (input: { deal_id?: string; contact_id?: string; body: string }) =>
      api.post(`/api/notes`, input),
  });
}

export interface SavedView {
  id: string;
  user_id: string | null;
  entity: string;
  name: string;
  filters: DealFilters;
  is_shared: boolean;
  created_at: string;
}

export function useSavedViews() {
  return useQuery({
    queryKey: ["saved-views"],
    queryFn: () => api.get<{ items: SavedView[]; total: number }>("/api/saved-views?entity=deal"),
  });
}

export function useCreateSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; filters: DealFilters }) =>
      api.post<SavedView>("/api/saved-views", { entity: "deal", ...input }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["saved-views"] });
    },
  });
}

export function useDeleteSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/saved-views/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["saved-views"] });
    },
  });
}

export function useContactSearch(term: string) {
  return useQuery({
    queryKey: ["contacts-search", term],
    queryFn: () =>
      api.get<{
        items: { id: string; name: string | null; phone: string | null }[];
        total: number;
      }>(`/api/contacts?search=${encodeURIComponent(term)}&limit=10`),
    enabled: term.trim().length >= 2,
  });
}

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

export function useDeal(id: string | null) {
  return useQuery({
    queryKey: ["deal", id],
    queryFn: () => api.get<Deal>(`/api/deals/${id}`),
    enabled: id !== null,
  });
}

export function useContact(id: string | null) {
  return useQuery({
    queryKey: ["contact", id],
    queryFn: () => api.get<Contact>(`/api/contacts/${id}`),
    enabled: id !== null,
  });
}

export interface CustomFieldDef {
  id: string;
  entity: string;
  key: string;
  label: string;
  type: string;
  options: unknown;
  required: boolean;
  sort: number;
}

export function useCustomFields(entity: string) {
  return useQuery({
    queryKey: ["custom-fields", entity],
    queryFn: () =>
      api.get<{ items: CustomFieldDef[]; total: number }>(
        `/api/custom-fields?entity=${entity}&limit=100`,
      ),
  });
}

export function useSetDealTags() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; tag_ids: string[] }) =>
      api.put<Tag[]>(`/api/deals/${input.id}/tags`, { tag_ids: input.tag_ids }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["board"] });
      void queryClient.invalidateQueries({ queryKey: ["deals"] });
      void queryClient.invalidateQueries({ queryKey: ["deal"] });
    },
  });
}
