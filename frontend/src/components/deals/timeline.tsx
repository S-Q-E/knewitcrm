import { useState } from "react";

import type { TimelineItem, TimelineKind } from "@/api/timeline";
import { TIMELINE_FILTERS, useTimeline } from "@/api/timeline";
import { Button } from "@/components/ui/button";
import { formatDate, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

function ItemBody({ item }: { item: TimelineItem }) {
  const data = item.data as Record<string, unknown>;
  switch (item.kind) {
    case "message": {
      const incoming = data.direction === "in";
      return (
        <div
          className={cn(
            "max-w-[85%] rounded-lg px-3 py-2 text-sm",
            incoming
              ? "bg-slate-100 dark:bg-slate-800"
              : "ml-auto bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900",
          )}
        >
          <p className="mb-1 text-[11px] opacity-70">
            {String(data.author_name ?? "")} ·{" "}
            {(data.direction as string) === "in" ? "входящее" : "бот"}
            {data.stage_at_moment ? ` · ${String(data.stage_at_moment)}` : ""}
          </p>
          <p className="whitespace-pre-wrap">{String(data.body ?? "")}</p>
          <p className="mt-1 text-[11px] opacity-70">
            {formatDate(item.at)}
            {typeof data.response_time_ms === "number"
              ? ` · ответ ${data.response_time_ms} мс`
              : ""}
          </p>
        </div>
      );
    }
    case "event":
      return (
        <p className="text-sm">
          <span className="font-medium">{String(data.event_type)}</span>
          {data.from_stage || data.to_stage ? (
            <span className="text-slate-500">
              {" "}
              {String(data.from_stage ?? "—")} → {String(data.to_stage ?? "—")}
            </span>
          ) : null}
          <span className="ml-2 text-xs text-slate-400">{formatRelative(item.at)}</span>
        </p>
      );
    case "stage": {
      const to = data.to_stage as { name?: string } | null;
      const from = data.from_stage as { name?: string } | null;
      return (
        <p className="text-sm">
          Стадия: <span className="font-medium">{to?.name ?? "—"}</span>
          {from?.name ? <span className="text-slate-500"> (была: {from.name})</span> : null}{" "}
          <span className="text-xs text-slate-400">
            · {String(data.source)} · {String(data.changed_by_name ?? "бот")}
          </span>
        </p>
      );
    }
    case "note":
      return (
        <div className="text-sm">
          <p className="font-medium">
            Заметка{data.pinned ? " (закреплена)" : ""}{" "}
            <span className="font-normal text-slate-500">{String(data.author_name ?? "")}</span>
          </p>
          <p className="whitespace-pre-wrap">{String(data.body ?? "")}</p>
        </div>
      );
    case "task": {
      const done = Boolean(data.done_at);
      return (
        <p className="text-sm">
          <span className={cn("font-medium", done && "line-through")}>
            Задача: {String(data.title ?? "")}
          </span>{" "}
          <span className="text-xs text-slate-500">
            {String(data.type)} · {String(data.assignee_name ?? "без исполнителя")}
            {done ? " · выполнена" : data.due_at ? ` · до ${formatDate(String(data.due_at))}` : ""}
          </span>
        </p>
      );
    }
    default:
      return (
        <p className="text-sm text-slate-500">
          {String(data.action ?? item.kind)}{" "}
          <span className="text-xs text-slate-400">{String(data.actor_name ?? "")}</span>
        </p>
      );
  }
}

export function Timeline({ dealId }: { dealId: string }) {
  const [kinds, setKinds] = useState<TimelineKind[]>([
    "message",
    "event",
    "stage",
    "note",
    "task",
    "activity",
  ]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<TimelineItem[]>([]);
  const query = useTimeline(dealId, kinds, cursor);

  const items = cursor ? loaded : (query.data?.items ?? []);
  const showMore = () => {
    if (query.data) {
      setLoaded((prev) => [...prev, ...query.data.items]);
      setCursor(query.data.next_cursor);
    }
  };
  const switchKinds = (next: TimelineKind[]) => {
    setKinds(next);
    setCursor(null);
    setLoaded([]);
  };

  return (
    <div>
      <div className="flex flex-wrap gap-1">
        {TIMELINE_FILTERS.map((filter) => {
          const active = kinds.includes(filter.id);
          return (
            <button
              key={filter.id}
              type="button"
              onClick={() =>
                switchKinds(
                  active ? kinds.filter((kind) => kind !== filter.id) : [...kinds, filter.id],
                )
              }
              className={cn(
                "rounded-full px-2.5 py-1 text-xs",
                active
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
              )}
            >
              {filter.label}
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {query.isPending && items.length === 0 && (
          <div className="flex flex-col gap-2" aria-label="Загрузка ленты">
            {[0, 1, 2].map((index) => (
              <div
                key={index}
                className="h-12 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800"
              />
            ))}
          </div>
        )}
        {query.isError && (
          <p className="text-sm text-red-600">
            Не удалось загрузить ленту.{" "}
            <button type="button" className="underline" onClick={() => query.refetch()}>
              Повторить
            </button>
          </p>
        )}
        {items.map((item) => (
          <div
            key={item.key}
            data-timeline-kind={item.kind}
            className="rounded-lg border border-slate-100 p-2 dark:border-slate-800"
          >
            <ItemBody item={item} />
          </div>
        ))}
        {!query.isPending && items.length === 0 && !query.isError && (
          <p className="text-sm text-slate-500">Пока пусто.</p>
        )}
      </div>

      {query.data?.next_cursor && (
        <Button
          variant="secondary"
          size="sm"
          className="mt-2"
          onClick={showMore}
          disabled={query.isFetching}
        >
          Показать старше
        </Button>
      )}
    </div>
  );
}
