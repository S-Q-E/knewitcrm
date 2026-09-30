import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "@/api/client";
import type { Deal, DealFilters, Stage } from "@/api/deals";
import { usePipelines } from "@/api/deals";
import { DealsBoard } from "@/components/deals/board";
import { DealFiltersBar } from "@/components/deals/filters";
import { DealsListView } from "@/components/deals/list";
import { CreateDealModal, NoteModal } from "@/components/deals/modals";
import { cn } from "@/lib/utils";

function filtersFromParams(params: URLSearchParams): DealFilters {
  const tags = params.get("tags");
  return {
    search: params.get("q") ?? "",
    owner_id: params.get("owner") || undefined,
    tag: tags ? tags.split(",").filter(Boolean) : [],
    contact_source: params.get("source") || undefined,
    created_from: params.get("from") || undefined,
    created_to: params.get("to") || undefined,
  };
}

function filtersToParams(filters: DealFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.search) params.set("q", filters.search);
  if (filters.owner_id) params.set("owner", filters.owner_id);
  if (filters.tag?.length) params.set("tags", filters.tag.join(","));
  if (filters.contact_source) params.set("source", filters.contact_source);
  if (filters.created_from) params.set("from", filters.created_from);
  if (filters.created_to) params.set("to", filters.created_to);
  return params;
}

export function DealsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const pipelines = usePipelines();
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [createStageId, setCreateStageId] = useState<string | null>(null);
  const [noteDeal, setNoteDeal] = useState<Deal | null>(null);

  const filters = useMemo(() => filtersFromParams(params), [params]);
  const onFiltersChange = (next: DealFilters) => setParams(filtersToParams(next));

  const activePipeline =
    pipelines.data?.find((item) => item.id === pipelineId) ?? pipelines.data?.[0] ?? null;
  const activePipelineId = activePipeline?.id ?? null;

  const stageKind = useMemo(() => {
    const map = new Map<string, "open" | "won" | "lost">();
    for (const stage of activePipeline?.stages ?? []) {
      if (stage.kind === "open" || stage.kind === "won" || stage.kind === "lost") {
        map.set(stage.id, stage.kind);
      }
    }
    return map;
  }, [activePipeline]);
  const stageColor = useMemo(() => {
    const map = new Map<string, string>();
    for (const stage of activePipeline?.stages ?? []) {
      map.set(stage.id, stage.color);
    }
    return map;
  }, [activePipeline]);
  const stagesById = useMemo(() => {
    const map = new Map<string, Stage>();
    for (const stage of activePipeline?.stages ?? []) {
      map.set(stage.id, stage);
    }
    return map;
  }, [activePipeline]);

  const contacts = useQuery({
    queryKey: ["contacts-map"],
    queryFn: () =>
      api.get<{ items: { id: string; name: string | null; phone: string | null }[] }>(
        "/api/contacts?limit=500",
      ),
    staleTime: 60_000,
  });
  const contactsById = useMemo(() => {
    const map = new Map<string, { name: string | null; phone: string | null }>();
    for (const contact of contacts.data?.items ?? []) {
      map.set(contact.id, { name: contact.name, phone: contact.phone });
    }
    return map;
  }, [contacts.data]);

  if (pipelines.isPending) {
    return (
      <div className="flex gap-3" aria-label="Загрузка">
        {[0, 1, 2].map((index) => (
          <div
            key={index}
            className="h-64 w-72 shrink-0 animate-pulse rounded-xl bg-slate-200 dark:bg-slate-800"
          />
        ))}
      </div>
    );
  }

  if (pipelines.isError || !activePipeline || !activePipelineId) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100">
        Не удалось загрузить воронки.{" "}
        <button type="button" className="underline" onClick={() => pipelines.refetch()}>
          Попробовать снова
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Воронка"
          value={activePipelineId}
          onChange={(event) => setPipelineId(event.target.value)}
          className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm font-medium dark:border-slate-700 dark:bg-slate-900"
        >
          {pipelines.data?.map((pipeline) => (
            <option key={pipeline.id} value={pipeline.id}>
              {pipeline.name}
            </option>
          ))}
        </select>
        <div className="flex rounded-md border border-slate-200 dark:border-slate-700">
          {(["kanban", "list"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setView(mode)}
              className={cn(
                "px-3 py-1.5 text-sm",
                view === mode
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "text-slate-600 dark:text-slate-300",
              )}
            >
              {mode === "kanban" ? "Канбан" : "Список"}
            </button>
          ))}
        </div>
      </div>

      <DealFiltersBar filters={filters} onChange={onFiltersChange} />

      {view === "kanban" ? (
        <DealsBoard
          key={`board-${activePipelineId}-${JSON.stringify(filters)}`}
          pipelineId={activePipelineId}
          pipelineName={activePipeline.name}
          stageKind={stageKind}
          stageColor={stageColor}
          filters={filters}
          contactsById={contactsById}
          onQuickCreate={setCreateStageId}
          onNote={setNoteDeal}
          onWrite={(deal) => navigate(`/dialogs?deal=${deal.id}`)}
        />
      ) : (
        <DealsListView
          key={`list-${JSON.stringify(filters)}`}
          filters={filters}
          stagesById={stagesById}
          contactsById={contactsById}
        />
      )}

      {createStageId && (
        <CreateDealModal
          stageId={createStageId}
          pipelineId={activePipelineId}
          onClose={() => setCreateStageId(null)}
        />
      )}
      {noteDeal && <NoteModal deal={noteDeal} onClose={() => setNoteDeal(null)} />}
    </div>
  );
}
