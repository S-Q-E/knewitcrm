import { useState } from "react";

import type { TimelineItem, TimelineKind } from "@/api/timeline";
import { TIMELINE_FILTERS, useTimeline } from "@/api/timeline";
import { Button } from "@/components/ui/button";
import { formatDate, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

const EVENT_LABELS: Record<string, string> = {
  stage_entered: "Stage entered",
  stage_exited: "Stage exited",
  transferred_to_manager: "Transferred to manager",
  trial_booked: "Viewing booked",
  objection_raised: "Objection",
  followup_sent: "Follow-up sent",
  lead_lost: "Lead lost",
  sale_won: "Payment received",
};

const ACTIVITY_LABELS: Record<string, string> = {
  bot_paused: "Bot paused",
  bot_resumed: "Bot resumed",
  bot_stage_blocked: "Bot could not change stage: stage is locked",
  deal_created: "Deal created",
  deal_updated: "Deal updated",
  deal_assigned: "Owner assigned",
  deal_deleted: "Deal deleted",
  deal_restored: "Deal restored",
  deal_unlocked: "Stage unlocked",
  contact_created: "Contact created",
  contact_updated: "Contact updated",
  contact_merged: "Contacts merged",
  contact_deleted: "Contact deleted",
  contact_restored: "Contact restored",
  dialog_updated: "Dialog updated",
  note_created: "Note added",
  note_updated: "Note updated",
  note_deleted: "Note deleted",
  task_created: "Task created",
  task_updated: "Task updated",
  task_deleted: "Task deleted",
};

const SOURCE_LABELS: Record<string, string> = {
  bot: "bot",
  manual: "manual",
  system: "system",
};

function humanize(code: string): string {
  const text = code.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function outgoingLabel(data: Record<string, unknown>): string {
  if ((data.direction as string) === "in") {
    return "incoming";
  }
  // author_kind comes from the backend ('manager' only for message_type='manager'
  // rows, i.e. CRM outbox mirrors). Anything else outgoing keeps the old label:
  // phone-sent rows are indistinguishable from bot replies (both 'out'/'chat').
  if ((data.author_kind as string) === "manager") {
    return "manager";
  }
  return "bot";
}

export function ItemBody({ item }: { item: { kind: string; at: string; data?: unknown } }) {
  const data = (item.data ?? {}) as Record<string, unknown>;
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
            {String(data.author_name ?? "")} · {outgoingLabel(data)}
            {data.stage_at_moment ? ` · ${String(data.stage_at_moment)}` : ""}
          </p>
          <p className="whitespace-pre-wrap">{String(data.body ?? "")}</p>
          <p className="mt-1 text-[11px] opacity-70">
            {formatDate(item.at)}
            {typeof data.response_time_ms === "number"
              ? ` · response ${data.response_time_ms} ms`
              : ""}
          </p>
        </div>
      );
    }
    case "event":
      return (
        <p className="text-sm">
          <span className="font-medium">
            {EVENT_LABELS[String(data.event_type)] ??
              humanize(String(data.event_type ?? "event"))}
          </span>
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
          {from?.name ? "Stage: " : "Deal created: "}
          <span className="font-medium">{to?.name ?? "—"}</span>
          {from?.name ? <span className="text-slate-500"> (was: {from.name})</span> : null}{" "}
          <span className="text-xs text-slate-400">
            · {SOURCE_LABELS[String(data.source)] ?? String(data.source ?? "")} ·{" "}
            {String(data.changed_by_name ?? "bot")}
          </span>
        </p>
      );
    }
    case "note":
      return (
        <div className="text-sm">
          <p className="font-medium">
            Note{data.pinned ? " (pinned)" : ""}{" "}
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
            Task: {String(data.title ?? "")}
          </span>{" "}
          <span className="text-xs text-slate-500">
            {String(data.type)} · {String(data.assignee_name ?? "no assignee")}
            {done ? " · completed" : data.due_at ? ` · due ${formatDate(String(data.due_at))}` : ""}
          </span>
        </p>
      );
    }
    default:
      return (
        <p className="text-sm text-slate-500">
          {ACTIVITY_LABELS[String(data.action)] ?? humanize(String(data.action ?? item.kind))}{" "}
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
          <div className="flex flex-col gap-2" aria-label="Loading timeline">
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
            Could not load the timeline.{" "}
            <button type="button" className="underline" onClick={() => query.refetch()}>
              Retry
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
          <p className="text-sm text-slate-500">Nothing here yet.</p>
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
          Show older
        </Button>
      )}
    </div>
  );
}
