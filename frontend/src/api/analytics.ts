import { useQuery } from "@tanstack/react-query";

import { api, CSRF_COOKIE, CSRF_HEADER } from "@/api/client";
import { getCookie } from "@/lib/utils";

export interface AnalyticsFilters {
  date_from?: string;
  date_to?: string;
  pipeline_id?: string;
  owner_id?: string;
  granularity?: "day" | "week";
}

export interface FunnelStage {
  stage_id: string;
  name: string;
  kind: string;
  reached: number;
  current: number;
  conversion_from_prev: number | null;
  avg_hours_on_stage: number | null;
  is_bottleneck: boolean;
}

export interface DynamicsBucket {
  bucket: string;
  new_leads: number;
  trials: number;
  won: number;
  won_sum: number;
  lost: number;
}

export interface LostReasonSlice {
  reason_id: string | null;
  reason: string;
  count: number;
}

export interface ManagerRow {
  user_id: string;
  name: string;
  deals_in_work: number;
  won: number;
  lost: number;
  conversion: number | null;
  won_sum: number;
  avg_first_response_hours: number | null;
  tasks_done: number;
  tasks_overdue: number;
}

export interface BotStats {
  messages_in: number;
  messages_out: number;
  avg_response_time_ms: number | null;
  tokens_total: number;
  tokens_by_day: { bucket: string; tokens: number }[];
  handover_count: number;
  handover_share: number | null;
  manager_status_now: number;
  closed_without_manager: number;
  closed_without_manager_share: number | null;
  top_objections: { objection: string; count: number }[];
  abandoned_by_stage: { stage: string; count: number; share: number | null }[];
}

export interface SourceRow {
  source: string;
  contacts: number;
  won: number;
  won_sum: number;
}

export interface TagRow {
  tag_id: string;
  tag: string;
  deals: number;
  won: number;
  won_sum: number;
}

export interface AnalyticsOverview {
  meta: {
    date_from: string;
    date_to: string;
    granularity: string;
    pipeline_id: string;
    owner_id: string | null;
    currency: string;
    timezone: string;
  };
  funnel: {
    stages: FunnelStage[];
    total_entered: number;
    total_finished: number;
    overall_conversion: number | null;
    cohort_deals: number;
  };
  summary: {
    new_leads: number;
    trials_booked: number;
    won_count: number;
    won_sum: number;
    avg_check: number;
    lost_count: number;
    lost_by_reason: LostReasonSlice[];
    dynamics: DynamicsBucket[];
  };
  managers: ManagerRow[];
  bot: BotStats;
  sources: SourceRow[];
  tags: TagRow[];
}

export type AnalyticsSection =
  | "funnel"
  | "dynamics"
  | "managers"
  | "objections"
  | "abandoned"
  | "sources"
  | "tags"
  | "lost_reasons";

export function buildAnalyticsParams(filters: AnalyticsFilters): string {
  const params = new URLSearchParams();
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.pipeline_id) params.set("pipeline_id", filters.pipeline_id);
  if (filters.owner_id) params.set("owner_id", filters.owner_id);
  if (filters.granularity) params.set("granularity", filters.granularity);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function useAnalyticsOverview(filters: AnalyticsFilters) {
  return useQuery({
    queryKey: ["analytics", "overview", filters],
    queryFn: () =>
      api.get<AnalyticsOverview>(`/api/analytics/overview${buildAnalyticsParams(filters)}`),
    staleTime: 30_000,
  });
}

export async function downloadAnalyticsCsv(
  section: AnalyticsSection,
  filters: AnalyticsFilters,
): Promise<void> {
  const params = new URLSearchParams(buildAnalyticsParams(filters).slice(1));
  params.set("section", section);
  const headers = new Headers();
  const token = getCookie(CSRF_COOKIE);
  if (token) headers.set(CSRF_HEADER, token);
  const response = await fetch(`/api/analytics/export?${params.toString()}`, {
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Не удалось выгрузить отчёт (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `analytics_${section}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export interface DrillDeal {
  id: string;
  title: string;
  amount: number | null;
  status: string;
  owner_id: string | null;
  created_at: string;
}

export function useDrillDeals(stageId: string | null, filters: AnalyticsFilters, offset: number) {
  const limit = 20;
  return useQuery({
    queryKey: ["analytics", "drill", stageId, filters, offset],
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("stage_id", stageId as string);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      if (filters.pipeline_id) params.set("pipeline_id", filters.pipeline_id);
      if (filters.owner_id) params.set("owner_id", filters.owner_id);
      if (filters.date_from) params.set("created_from", `${filters.date_from}T00:00:00+06:00`);
      if (filters.date_to) params.set("created_to", `${filters.date_to}T23:59:59+06:00`);
      return api.get<{ items: DrillDeal[]; total: number }>(`/api/deals?${params.toString()}`);
    },
    enabled: stageId !== null,
  });
}
