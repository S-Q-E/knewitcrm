import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarClock, Lock, MessageSquarePlus, StickyNote } from "lucide-react";

import type { Deal } from "@/api/deals";
import { formatDate, formatMoney, formatRelative, initials } from "@/lib/format";
import { cn } from "@/lib/utils";

interface DealCardProps {
  deal: Deal;
  contactName: string | null;
  contactPhone: string | null;
  stageId: string;
  onOpen: (deal: Deal) => void;
  onNote: (deal: Deal) => void;
  onWrite: (deal: Deal) => void;
}

export function DealCard({
  deal,
  contactName,
  contactPhone,
  stageId,
  onOpen,
  onNote,
  onWrite,
}: DealCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: deal.id,
    data: { deal, stageId },
  });

  return (
    <article
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-deal-id={deal.id}
      onClick={() => onOpen(deal)}
      className={cn(
        "group cursor-pointer rounded-lg border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-900",
        isDragging && "opacity-50 shadow-lg",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-medium" title={contactName ?? undefined}>
          {contactName ?? contactPhone ?? "Без имени"}
        </p>
        {deal.stage_locked && (
          <span title="Управление у менеджера">
            <Lock className="h-3.5 w-3.5 shrink-0 text-amber-500" />
          </span>
        )}
      </div>
      <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">{deal.title}</p>
      <p className="mt-1 text-sm font-semibold">{formatMoney(deal.amount, deal.currency)}</p>

      {deal.tags.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {deal.tags.slice(0, 3).map((tag) => (
            <span
              key={tag.id}
              className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300"
            >
              {tag.name}
            </span>
          ))}
        </div>
      )}

      <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
        <span
          title={deal.owner_id ? "Ответственный" : "Без ответственного"}
          className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold dark:bg-slate-700"
        >
          {initials(contactName)}
        </span>
        <span title="Последняя активность">{formatRelative(deal.updated_at)}</span>
        {deal.trial_at && (
          <span
            title={`Пробный: ${formatDate(deal.trial_at)}`}
            className="flex items-center gap-0.5"
          >
            <CalendarClock className="h-3.5 w-3.5" />
            {formatDate(deal.trial_at)}
          </span>
        )}
      </div>

      <div className="mt-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          title="Заметка"
          onClick={(event) => {
            event.stopPropagation();
            onNote(deal);
          }}
          className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <StickyNote className="h-4 w-4" />
        </button>
        <button
          type="button"
          title="Написать"
          onClick={(event) => {
            event.stopPropagation();
            onWrite(deal);
          }}
          className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <MessageSquarePlus className="h-4 w-4" />
        </button>
        <button
          type="button"
          title="Перетащить (или Tab + Пробел)"
          {...attributes}
          {...listeners}
          className="ml-auto cursor-grab rounded p-1 text-slate-400 hover:bg-slate-100 active:cursor-grabbing dark:hover:bg-slate-800"
        >
          ⋮⋮
        </button>
      </div>
    </article>
  );
}
