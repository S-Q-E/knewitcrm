import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { Plus } from "lucide-react";

import type { BoardColumn, Deal } from "@/api/deals";
import { DealCard } from "@/components/deals/card";
import { Button } from "@/components/ui/button";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ColumnProps {
  column: BoardColumn;
  color: string;
  contactsById: Map<string, { name: string | null; phone: string | null }>;
  activeStageId: string | null;
  loadingMore: boolean;
  onShowMore: (stageId: string) => void;
  onQuickCreate: (stageId: string) => void;
  onOpen: (deal: Deal) => void;
  onNote: (deal: Deal) => void;
  onWrite: (deal: Deal) => void;
}

export function BoardColumnView({
  column,
  color,
  contactsById,
  activeStageId,
  loadingMore,
  onShowMore,
  onQuickCreate,
  onOpen,
  onNote,
  onWrite,
}: ColumnProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: column.stage_id,
    data: { stageId: column.stage_id },
  });
  const dealIds = column.items.map((item) => item.id);

  return (
    <section
      aria-label={column.name}
      className={cn(
        "flex max-h-full w-72 shrink-0 flex-col rounded-xl bg-slate-200/60 dark:bg-slate-900/60",
        isOver && "ring-2 ring-slate-400",
      )}
    >
      <header className="flex items-center gap-2 px-3 pb-2 pt-3">
        <span
          aria-hidden
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
        />
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{column.name}</h2>
        <span className="text-xs text-slate-500 dark:text-slate-400">{column.total}</span>
      </header>
      <p className="px-3 pb-2 text-xs text-slate-500 dark:text-slate-400">
        {formatMoney(column.amount_total)}
      </p>

      <div
        ref={setNodeRef}
        className="flex min-h-16 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2"
      >
        <SortableContext items={dealIds} strategy={verticalListSortingStrategy}>
          {column.items.map((deal) => {
            const contact = contactsById.get(deal.contact_id);
            return (
              <DealCard
                key={deal.id}
                deal={deal}
                contactName={contact?.name ?? null}
                contactPhone={contact?.phone ?? null}
                stageId={column.stage_id}
                onOpen={onOpen}
                onNote={onNote}
                onWrite={onWrite}
              />
            );
          })}
        </SortableContext>
        {column.items.length === 0 && (
          <p className="rounded-lg border border-dashed border-slate-300 p-4 text-center text-xs text-slate-400 dark:border-slate-700">
            Перетащите сделку сюда
          </p>
        )}
        {column.next_cursor && (
          <Button
            variant="secondary"
            size="sm"
            disabled={loadingMore}
            onClick={() => onShowMore(column.stage_id)}
          >
            {loadingMore ? "Загрузка…" : `Показать ещё (всего ${column.total})`}
          </Button>
        )}
      </div>

      <div className="p-2">
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => onQuickCreate(column.stage_id)}
        >
          <Plus className="h-4 w-4" /> Быстрая сделка
        </Button>
      </div>
      {activeStageId === column.stage_id && <span className="sr-only">Целевая колонка</span>}
    </section>
  );
}
