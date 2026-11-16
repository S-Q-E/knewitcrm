import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useDialog, useDialogs } from "@/api/timeline";
import { ChatPanel } from "@/components/dialogs/chat-panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

type Filter = "all" | "mine" | "unassigned" | "unread" | "needs_reply";

export function DialogsPage() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  // The selected dialog lives in the URL (?wa=), so the browser back button
  // returns to the list, while a /dialogs?wa= link from a deal opens the chat.
  const selected = params.get("wa");

  const dialogs = useDialogs({
    assigned: filter === "mine" || filter === "unassigned" ? filter : undefined,
    unread: filter === "unread",
    needsReply: filter === "needs_reply",
    search: search || undefined,
  });
  const dialog = useDialog(selected);

  const totalUnread = dialogs.data?.items.reduce((sum, item) => sum + item.unread_count, 0) ?? 0;
  useEffect(() => {
    document.title = totalUnread > 0 ? `(${totalUnread}) TCS Leasing CRM` : "TCS Leasing CRM";
    return () => {
      document.title = "TCS Leasing CRM";
    };
  }, [totalUnread]);

  const open = (whatsappId: string) => {
    // Push, not replace: browser back returns to the list.
    setParams({ wa: whatsappId });
  };

  const back = () => {
    setParams({});
  };

  return (
    <div className="flex h-[calc(100dvh-14rem-env(safe-area-inset-bottom))] flex-col gap-3 md:h-[calc(100vh-9rem)] md:flex-row">
      <aside
        className={cn("w-full flex-col gap-2 md:flex md:max-w-xs", selected ? "hidden" : "flex")}
      >
        <div className="flex flex-nowrap gap-1 overflow-x-auto pb-1">
          {(
            [
              ["all", "All"],
              ["mine", "Mine"],
              ["unassigned", "Unassigned"],
              ["unread", "Unread"],
              ["needs_reply", "Needs reply"],
            ] as [Filter, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setFilter(id)}
              className={cn(
                "min-h-9 shrink-0 rounded-full px-2.5 py-1 text-xs",
                filter === id
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search dialogs"
        />
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          {dialogs.isPending && <p className="text-sm text-slate-500">Loading…</p>}
          {dialogs.data?.items.map((item) => (
            <button
              key={item.whatsapp_id}
              type="button"
              onClick={() => open(item.whatsapp_id)}
              className={cn(
                "rounded-lg border p-2 text-left text-sm",
                selected === item.whatsapp_id
                  ? "border-slate-400 bg-white dark:border-slate-500 dark:bg-slate-900"
                  : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">
                  {item.contact_name ?? item.contact_phone ?? item.whatsapp_id}
                </span>
                <span className="flex items-center gap-1">
                  {item.needs_reply && (
                    <span className="rounded-full bg-amber-100 px-1.5 text-[11px] text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                      awaiting reply
                    </span>
                  )}
                  {item.unread_count > 0 && (
                    <span className="rounded-full bg-slate-900 px-1.5 text-[11px] text-white dark:bg-slate-100 dark:text-slate-900">
                      {item.unread_count}
                    </span>
                  )}
                </span>
              </span>
              <span className="block truncate text-xs text-slate-500">
                {item.last_message?.content ?? "No messages"}
              </span>
              <span className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-400">
                {item.last_message ? formatRelative(item.last_message.created_at) : ""}
                {item.bot_paused ? " · bot paused" : " · bot replying"}
                {item.assignee_name ? ` · ${item.assignee_name}` : ""}
              </span>
            </button>
          ))}
          {!dialogs.isPending && (dialogs.data?.total ?? 0) === 0 && (
            <p className="text-sm text-slate-500">No dialogs.</p>
          )}
        </div>
      </aside>

      <section
        className={cn(
          "min-h-0 flex-1 flex-col rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
          selected ? "flex" : "hidden md:flex",
        )}
      >
        {!selected || !dialog.data ? (
          <p className="m-auto hidden text-sm text-slate-500 md:block">Select a dialog on the left.</p>
        ) : (
          <>
            <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Back to list"
                onClick={back}
                className="md:hidden"
              >
                <ArrowLeft className="h-5 w-5" />
              </Button>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">
                  {dialog.data.contact_name ?? dialog.data.whatsapp_id}
                </p>
                <p className="flex flex-wrap items-center gap-1 text-xs text-slate-500">
                  <span>{dialog.data.assignee_name ?? "Unassigned"}</span>
                  <span className="text-[11px] text-slate-400">· Changed in the deal card</span>
                </p>
              </div>
            </header>
            <ChatPanel
              key={dialog.data.whatsapp_id}
              whatsappId={dialog.data.whatsapp_id}
              contactName={dialog.data.contact_name}
            />
          </>
        )}
      </section>
    </div>
  );
}
