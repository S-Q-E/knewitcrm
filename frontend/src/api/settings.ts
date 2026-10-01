import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";

export interface InstanceSettings {
  restrict_managers_to_own: boolean;
  auto_pause_on_manager: boolean;
  auto_pause_on_manual_reply: boolean;
  deal_assignment_mode: "unassigned" | "round_robin";
}

export interface BotStages {
  stages: string[];
  statuses: string[];
}

export interface FailedOutboxSummary {
  id: string;
  whatsapp_id: string;
  error: string | null;
  attempts: number;
  created_at: string;
}

export interface IntegrationsStatus {
  bot_db_ok: boolean;
  bot_db_latency_ms: number | null;
  bot_db_error: string | null;
  leads_count: number | null;
  messages_count: number | null;
  events_count: number | null;
  n8n_configured: boolean;
  n8n_webhook_url: string | null;
  outbox_queued: number;
  outbox_sending: number;
  outbox_sent: number;
  outbox_failed: number;
  last_failed: FailedOutboxSummary | null;
}

export interface QuickReply {
  id: string;
  title: string;
  body: string;
  sort: number;
}

export interface OutboxJournalItem {
  id: string;
  whatsapp_id: string;
  body: string;
  sent_by: string | null;
  sent_by_name: string | null;
  status: string;
  attempts: number;
  next_attempt_at: string | null;
  error: string | null;
  provider_message_id: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface ActivityItem {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  entity: string;
  entity_id: string | null;
  action: string;
  diff: Record<string, unknown>;
  created_at: string;
}

export interface SessionItem {
  id: string;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
  expires_at: string;
  is_current: boolean;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: "admin" | "manager";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Stage {
  id: string;
  pipeline_id: string;
  name: string;
  color: string;
  sort: number;
  kind: "open" | "won" | "lost";
  bot_stage_key: string | null;
  bot_status_key: string | null;
}

export interface Pipeline {
  id: string;
  name: string;
  is_default: boolean;
  sort: number;
  stages: Stage[];
}

export interface CustomField {
  id: string;
  entity: "contact" | "deal";
  key: string;
  label: string;
  type: "text" | "number" | "date" | "select" | "multiselect" | "bool";
  options: unknown;
  required: boolean;
  sort: number;
}

export interface Tag {
  id: string;
  name: string;
  color: string | null;
}

export interface LostReason {
  id: string;
  name: string;
  sort: number;
}

export interface Automation {
  id: string;
  name: string;
  is_active: boolean;
  trigger_type: "deal_entered_stage" | "no_activity_hours";
  trigger_config: Record<string, unknown>;
  actions: { type: string; [key: string]: unknown }[];
  created_at: string;
}

// Instance settings (admin)

export function useInstanceSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<InstanceSettings>("/api/settings"),
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: Partial<InstanceSettings>) =>
      api.patch<InstanceSettings>("/api/settings", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}

export function useBotStages() {
  return useQuery({
    queryKey: ["settings", "bot-stages"],
    queryFn: () => api.get<BotStages>("/api/settings/bot-stages"),
    staleTime: 300_000,
  });
}

export function useIntegrations() {
  return useQuery({
    queryKey: ["settings", "integrations"],
    queryFn: () => api.get<IntegrationsStatus>("/api/settings/integrations"),
  });
}

// Pipelines + stages (admin mutations; reads reuse usePipelines)

export function useCreatePipeline() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; is_default?: boolean }) =>
      api.post<Pipeline>("/api/pipelines", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useUpdatePipeline() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<Pipeline>(`/api/pipelines/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useDeletePipeline() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/pipelines/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useCreateStage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { pipeline_id: string; stage: Record<string, unknown> }) =>
      api.post<Stage>(`/api/pipelines/${input.pipeline_id}/stages`, input.stage),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useUpdateStage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<Stage>(`/api/stages/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useDeleteStage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; to_stage_id?: string }) =>
      api.del(
        `/api/stages/${input.id}${input.to_stage_id ? `?to_stage_id=${input.to_stage_id}` : ""}`,
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useReorderStages() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { pipeline_id: string; ordered_ids: string[] }) =>
      api.post<Stage[]>(`/api/pipelines/${input.pipeline_id}/stages/reorder`, {
        ordered_ids: input.ordered_ids,
      }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

// Custom fields

export function useCustomFieldsAdmin(entity: "contact" | "deal") {
  return useQuery({
    queryKey: ["custom-fields", entity],
    queryFn: () =>
      api.get<{ items: CustomField[]; total: number }>(
        `/api/custom-fields?entity=${entity}&limit=200`,
      ),
  });
}

export function useCreateCustomField() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: Record<string, unknown>) =>
      api.post<CustomField>("/api/custom-fields", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["custom-fields"] });
    },
  });
}

export function useUpdateCustomField() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<CustomField>(`/api/custom-fields/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["custom-fields"] });
    },
  });
}

export function useDeleteCustomField() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/custom-fields/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["custom-fields"] });
    },
  });
}

// Tags + lost reasons (admin mutations)

export function useCreateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; color?: string | null }) =>
      api.post<Tag>("/api/tags", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useUpdateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<Tag>(`/api/tags/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useDeleteTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<{ ok: boolean; detached_from: number }>(`/api/tags/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useAllLostReasons() {
  return useQuery({
    queryKey: ["lost-reasons", "all"],
    queryFn: () => api.get<{ items: LostReason[]; total: number }>("/api/lost-reasons?limit=200"),
  });
}

export function useCreateLostReason() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; sort?: number }) =>
      api.post<LostReason>("/api/lost-reasons", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["lost-reasons"] });
    },
  });
}

export function useUpdateLostReason() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<LostReason>(`/api/lost-reasons/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["lost-reasons"] });
    },
  });
}

export function useDeleteLostReason() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/lost-reasons/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["lost-reasons"] });
    },
  });
}

// Users (admin)

export function useAdminUsers(offset: number, limit = 50) {
  return useQuery({
    queryKey: ["users-admin", offset, limit],
    queryFn: () =>
      api.get<{ items: AdminUser[]; total: number }>(`/api/users?limit=${limit}&offset=${offset}`),
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      email: string;
      name: string;
      password: string;
      role: "admin" | "manager";
    }) => api.post<AdminUser>("/api/users", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["users-admin"] });
      void queryClient.invalidateQueries({ queryKey: ["users-lite"] });
    },
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<AdminUser>(`/api/users/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["users-admin"] });
      void queryClient.invalidateQueries({ queryKey: ["users-lite"] });
    },
  });
}

// Quick replies (admin mutations; read hook lives in api/timeline)

export function useCreateQuickReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { title: string; body: string; sort?: number }) =>
      api.post<QuickReply>("/api/chats/quick-replies", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["quick-replies"] });
    },
  });
}

export function useUpdateQuickReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<QuickReply>(`/api/chats/quick-replies/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["quick-replies"] });
    },
  });
}

export function useDeleteQuickReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/chats/quick-replies/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["quick-replies"] });
    },
  });
}

// Automations (admin mutations; list is open to all authenticated users)

export function useAutomations() {
  return useQuery({
    queryKey: ["automations"],
    queryFn: () => api.get<Automation[]>("/api/automations?limit=200"),
  });
}

export function useCreateAutomation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: Record<string, unknown>) => api.post<Automation>("/api/automations", input),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["automations"] });
    },
  });
}

export function useUpdateAutomation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; patch: Record<string, unknown> }) =>
      api.patch<Automation>(`/api/automations/${input.id}`, input.patch),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["automations"] });
    },
  });
}

export function useDeleteAutomation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/automations/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["automations"] });
    },
  });
}

// Profile + sessions (all roles)

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string }) => api.patch("/api/auth/profile", input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (input: { current_password: string; new_password: string }) =>
      api.post<{ ok: boolean }>("/api/auth/change-password", input),
  });
}

export function useSessions() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: () => api.get<{ items: SessionItem[] }>("/api/auth/sessions"),
  });
}

export function useRevokeSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/auth/sessions/${id}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useRevokeOtherSessions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{ ok: boolean; revoked: number }>("/api/auth/sessions/revoke-others"),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

// Outbox journal + activity (admin)

export function useOutboxJournal(status: string, offset: number, limit = 50) {
  return useQuery({
    queryKey: ["outbox-journal", status, offset, limit],
    queryFn: () =>
      api.get<{ items: OutboxJournalItem[]; total: number }>(
        `/api/chats/outbox?status=${status}&limit=${limit}&offset=${offset}`,
      ),
  });
}

export interface ActivityFilters {
  actor_id?: string;
  entity?: string;
  action?: string;
  date_from?: string;
  date_to?: string;
}

export function useActivity(filters: ActivityFilters, offset: number, limit = 50) {
  const params = new URLSearchParams();
  if (filters.actor_id) params.set("actor_id", filters.actor_id);
  if (filters.entity) params.set("entity", filters.entity);
  if (filters.action) params.set("action", filters.action);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const key = params.toString();
  return useQuery({
    queryKey: ["activity", key],
    queryFn: () => api.get<{ items: ActivityItem[]; total: number }>(`/api/activity?${key}`),
  });
}

export function useActivityMeta() {
  return useQuery({
    queryKey: ["activity", "meta"],
    queryFn: () => api.get<{ entities: string[]; actions: string[] }>("/api/activity/entities"),
    staleTime: 300_000,
  });
}

// Local profile preferences (per browser, like the theme)

const PREFS_KEY = "knewitcrm-profile-prefs";

export interface ProfilePrefs {
  timezone: string;
  sound: boolean;
}

export const DEFAULT_PREFS: ProfilePrefs = { timezone: "Asia/Almaty", sound: true };

export function loadProfilePrefs(): ProfilePrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<ProfilePrefs>;
    return {
      timezone:
        typeof parsed.timezone === "string" && parsed.timezone
          ? parsed.timezone
          : DEFAULT_PREFS.timezone,
      sound: typeof parsed.sound === "boolean" ? parsed.sound : DEFAULT_PREFS.sound,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function saveProfilePrefs(prefs: ProfilePrefs): void {
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
}

export function formatInTimezone(iso: string, timezone: string): string {
  try {
    return new Date(iso).toLocaleString("ru-RU", { timeZone: timezone });
  } catch {
    return new Date(iso).toLocaleString("ru-RU");
  }
}
