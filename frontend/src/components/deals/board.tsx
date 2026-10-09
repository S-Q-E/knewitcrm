import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type { DragEndEvent, DragOverEvent } from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/api/client";
import type { Board, Deal, DealFilters } from "@/api/deals";
import { useBoard, useMoveDeal } from "@/api/deals";
import { BoardColumnView } from "@/components/deals/column";
import { LostReasonModal, WonConfirmModal } from "@/components/deals/modals";
import { useToast, toastError } from "@/components/toast";
import { positionBetween } from "@/lib/format";

interface BoardProps {
  pipelineId: string;
  pipelineName: string;
  stageKind: Map<string, "open" | "won" | "lost">;
  stageColor: Map<string, string>;
  filters: DealFilters;
  contactsById: Map<string, { name: string | null; phone: string | null }>;
  onQuickCreate: (stageId: string) => void;
  onOpen: (deal: Deal) => void;
  onNote: (deal: Deal) => void;
  onWrite: (deal: Deal) => void;
}

interface PendingMove {
  deal: Deal;
  stageId: string;
  position: number;
}

export function DealsBoard({
  pipelineId,
  filters,
  stageKind,
  stageColor,
  contactsById,
  onQuickCreate,
  onOpen,
  onNote,
  onWrite,
}: BoardProps) {
  const { push } = useToast();
  const queryClient = useQueryClient();
  const move = useMoveDeal();
  // Pages after the first one live in local state only; the main query key stays fixed,
  // so refetching never swaps the first page for a later one.
  const [tailCursors, setTailCursors] = useState<Record<string, string | null>>({});
  const [appended, setAppended] = useState<Record<string, Deal[]>>({});
  const [loadingMore, setLoadingMore] = useState<string | null>(null);
  const [activeStageId, setActiveStageId] = useState<string | null>(null);
  const [pendingMove, setPendingMove] = useState<PendingMove | null>(null);
  const [confirmWon, setConfirmWon] = useState<PendingMove | null>(null);

  const boardQuery = useBoard(pipelineId, filters, 50);
  const board = boardQuery.data;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const columns = useMemo(() => {
    if (!board) {
      return [];
    }
    return board.columns.map((column) => ({
      ...column,
      items: [...column.items, ...(appended[column.stage_id] ?? [])],
      next_cursor:
        column.stage_id in tailCursors ? tailCursors[column.stage_id] : column.next_cursor,
    }));
  }, [board, appended, tailCursors]);

  const findColumn = (id: string) => columns.find((column) => column.stage_id === id);

  const onDragOver = (event: DragOverEvent) => {
    const overId = event.over?.id;
    if (!overId) {
      setActiveStageId(null);
      return;
    }
    const overStage =
      findColumn(String(overId))?.stage_id ??
      columns.find((column) => column.items.some((item) => item.id === String(overId)))?.stage_id ??
      null;
    setActiveStageId(overStage);
  };

  const commitMove = (pending: PendingMove, lostReasonId?: string) => {
    move.mutate(
      {
        id: pending.deal.id,
        stage_id: pending.stageId,
        position: pending.position,
        lost_reason_id: lostReasonId ?? null,
      },
      {
        onError: (error) => {
          toastError(push, error);
          void queryClient.invalidateQueries({ queryKey: ["board"] });
        },
        onSuccess: () => {
          setAppended({});
          setTailCursors({});
        },
      },
    );
    setPendingMove(null);
    setConfirmWon(null);
  };

  const onDragEnd = (event: DragEndEvent) => {
    setActiveStageId(null);
    const { active, over } = event;
    if (!over || !board) {
      return;
    }
    const dealId = String(active.id);
    const sourceColumn = columns.find((column) => column.items.some((item) => item.id === dealId));
    const deal = sourceColumn?.items.find((item) => item.id === dealId);
    if (!sourceColumn || !deal) {
      return;
    }
    const overId = String(over.id);
    const targetColumn =
      findColumn(overId) ??
      columns.find((column) => column.items.some((item) => item.id === overId));
    if (!targetColumn) {
      return;
    }

    const siblings = targetColumn.items.filter((item) => item.id !== dealId);
    let position: number;
    if (overId === targetColumn.stage_id || siblings.length === 0) {
      position = positionBetween(
        siblings.length > 0 ? siblings[siblings.length - 1].position : null,
        null,
      );
    } else {
      const overIndex = siblings.findIndex((item) => item.id === overId);
      const before = overIndex > 0 ? siblings[overIndex - 1].position : null;
      const after = overIndex >= 0 ? siblings[overIndex].position : null;
      position = positionBetween(before, after);
    }

    // Optimistic update: move the card immediately, roll back on error.
    queryClient.setQueryData<Board>(["board", pipelineId, filters, 50, {}], (previous) => {
      if (!previous) {
        return previous;
      }
      return {
        ...previous,
        columns: previous.columns.map((column) => {
          if (column.stage_id === sourceColumn.stage_id) {
            return { ...column, items: column.items.filter((item) => item.id !== dealId) };
          }
          if (column.stage_id === targetColumn.stage_id) {
            const moved: Deal = { ...deal, stage_id: targetColumn.stage_id, position };
            const rest = column.items.filter((item) => item.id !== dealId);
            return { ...column, items: [...rest, moved].sort((a, b) => a.position - b.position) };
          }
          return column;
        }),
      };
    });

    if (sourceColumn.stage_id === targetColumn.stage_id) {
      commitMove({ deal, stageId: targetColumn.stage_id, position });
      return;
    }
    const kind = stageKind.get(targetColumn.stage_id);
    if (kind === "lost") {
      setPendingMove({ deal, stageId: targetColumn.stage_id, position });
      return;
    }
    if (kind === "won") {
      setConfirmWon({ deal, stageId: targetColumn.stage_id, position });
      return;
    }
    commitMove({ deal, stageId: targetColumn.stage_id, position });
  };

  const showMore = async (stageId: string) => {
    const column = columns.find((item) => item.stage_id === stageId);
    if (!column?.next_cursor) {
      return;
    }
    setLoadingMore(stageId);
    // Fetch the next page for this column only, then append it locally.
    try {
      const params = new URLSearchParams({
        pipeline_id: pipelineId,
        limit: "50",
        cursors: JSON.stringify({ [stageId]: column.next_cursor }),
      });
      const next = await api.get<Board>(`/api/deals/board?${params.toString()}`);
      const fresh = next.columns.find((item) => item.stage_id === stageId);
      if (fresh) {
        setAppended((prev) => ({
          ...prev,
          [stageId]: [...(prev[stageId] ?? []), ...fresh.items],
        }));
        setTailCursors((prev) => ({ ...prev, [stageId]: fresh.next_cursor ?? null }));
      }
    } finally {
      setLoadingMore(null);
    }
  };

  if (boardQuery.isPending) {
    return (
      <div className="flex gap-3 overflow-x-auto pb-4" aria-label="Загрузка">
        {[0, 1, 2, 3].map((index) => (
          <div
            key={index}
            className="h-64 w-72 shrink-0 animate-pulse rounded-xl bg-slate-200 dark:bg-slate-800"
          />
        ))}
      </div>
    );
  }

  if (boardQuery.isError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100">
        Не удалось загрузить доску.{" "}
        <button type="button" className="underline" onClick={() => boardQuery.refetch()}>
          Попробовать снова
        </button>
      </div>
    );
  }

  return (
    <>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
      >
        <div className="flex items-stretch gap-3 overflow-x-auto pb-4">
          {columns.map((column) => (
            <BoardColumnView
              key={column.stage_id}
              column={column}
              color={stageColor.get(column.stage_id) ?? "#94a3b8"}
              contactsById={contactsById}
              activeStageId={activeStageId}
              loadingMore={loadingMore === column.stage_id}
              onShowMore={showMore}
              onQuickCreate={onQuickCreate}
              onOpen={onOpen}
              onNote={onNote}
              onWrite={onWrite}
            />
          ))}
          {columns.length === 0 && (
            <p className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900">
              В воронке нет стадий.
            </p>
          )}
        </div>
      </DndContext>

      {pendingMove && (
        <LostReasonModal
          onClose={() => {
            setPendingMove(null);
            void queryClient.invalidateQueries({ queryKey: ["board"] });
          }}
          onConfirm={(reasonId) => commitMove(pendingMove, reasonId)}
        />
      )}
      {confirmWon && (
        <WonConfirmModal
          onClose={() => {
            setConfirmWon(null);
            void queryClient.invalidateQueries({ queryKey: ["board"] });
          }}
          onConfirm={() => commitMove(confirmWon)}
        />
      )}
    </>
  );
}
