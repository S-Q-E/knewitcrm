import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { DialogSummary } from "@/api/timeline";
import {
  useDialog,
  useDialogs,
  useLeadMessages,
  useMarkRead,
  useUpdateDialog,
} from "@/api/timeline";
import { useUsersLite } from "@/api/deals";
import { useToast, toastError } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDate, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

type Filter = "all" | "mine" | "unassigned" | "unread";

export function DialogsPage() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(params.get("wa"));
  const { push } = useToast();
  const markRead = useMarkRead();
  const updateDialog = useUpdateDialog();
  const users = useUsersLite();

  const dialogs = useDialogs({
    assigned: filter === "all" || filter === "unread" ? undefined : filter,
    unread: filter === "unread",
    search: search || undefined,
  });
  const dialog = useDialog(selected);
  const messages = useLeadMessages(selected);

  useEffect(() => {
    if (selected) {
      markRead.mutate(selected);
      setParams(selected ? { wa: selected } : {}, { replace: true });
    }
    // Mark read once per opened dialog; params sync keeps deep links working.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const open = (whatsappId: string) => setSelected(whatsappId);

  const assign = (whatsappId: string, userId: string) => {
    updateDialog.mutate(
      { whatsapp_id: whatsappId, patch: { assigned_to: userId || null } },
      { onError: (error) => toastError(push, error) },
    );
  };

  const togglePause = (current: DialogSummary) => {
    updateDialog.mutate(
      { whatsapp_id: current.whatsapp_id, patch: { bot_paused: !current.bot_paused } },
      { onError: (error) => toastError(push, error) },
    );
  };

  const sendDisabled = (event: React.FormEvent) => {
    event.preventDefault();
    push({ title: "Отправка появится на следующем шаге", variant: "default" });
  };

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col gap-3 md:flex-row">
      <aside className="flex w-full flex-col gap-2 md:max-w-xs">
        <div className="flex flex-wrap gap-1">
          {(
            [
              ["all", "Все"],
              ["mine", "Мои"],
              ["unassigned", "Без ответственного"],
              ["unread", "Непрочитанные"],
            ] as [Filter, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setFilter(id)}
              className={cn(
                "rounded-full px-2.5 py-1 text-xs",
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
          placeholder="Поиск диалога"
        />
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          {dialogs.isPending && <p className="text-sm text-slate-500">Загрузка…</p>}
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
                {item.unread_count > 0 && (
                  <span className="rounded-full bg-slate-900 px-1.5 text-[11px] text-white dark:bg-slate-100 dark:text-slate-900">
                    {item.unread_count}
                  </span>
                )}
              </span>
              <span className="block truncate text-xs text-slate-500">
                {item.last_message?.content ?? "Нет сообщений"}
              </span>
              <span className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-400">
                {item.last_message ? formatRelative(item.last_message.created_at) : ""}
                {item.bot_paused ? " · бот на паузе" : " · бот отвечает"}
                {item.assignee_name ? ` · ${item.assignee_name}` : ""}
              </span>
            </button>
          ))}
          {!dialogs.isPending && (dialogs.data?.total ?? 0) === 0 && (
            <p className="text-sm text-slate-500">Диалогов нет.</p>
          )}
        </div>
      </aside>

      <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        {!selected || !dialog.data ? (
          <p className="m-auto text-sm text-slate-500">Выберите диалог слева.</p>
        ) : (
          <>
            <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">
                  {dialog.data.contact_name ?? dialog.data.whatsapp_id}
                </p>
                <p className="text-xs text-slate-500">
                  {dialog.data.bot_paused ? "Бот на паузе" : "Бот отвечает"}
                  {dialog.data.assignee_name ? ` · ${dialog.data.assignee_name}` : ""}
                </p>
              </div>
              <select
                aria-label="Ответственный"
                value={dialog.data.assigned_to ?? ""}
                onChange={(event) => assign(dialog.data.whatsapp_id, event.target.value)}
                className="h-8 rounded-md border border-slate-200 bg-white px-1 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="">Без ответственного</option>
                {users.data?.items.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => dialog.data && togglePause(dialog.data)}
              >
                {dialog.data.bot_paused ? "Включить бота" : "Пауза бота"}
              </Button>
            </header>

            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
              {messages.isPending && <p className="text-sm text-slate-500">Загрузка…</p>}
              {messages.data?.items.map((message) => (
                <div
                  key={message.id}
                  className={cn(
                    "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                    message.direction === "in"
                      ? "bg-slate-100 dark:bg-slate-800"
                      : "ml-auto bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900",
                  )}
                >
                  <p className="whitespace-pre-wrap">{message.content ?? ""}</p>
                  <p className="mt-1 text-[11px] opacity-70">
                    {message.stage_at_moment ? `${message.stage_at_moment} · ` : ""}
                    {formatDate(message.created_at)}
                  </p>
                </div>
              ))}
            </div>

            <form
              onSubmit={sendDisabled}
              className="border-t border-slate-200 p-3 dark:border-slate-800"
            >
              <div className="rounded-md border border-dashed border-slate-300 p-2 text-xs text-slate-500 dark:border-slate-700">
                Быстрые ответы появятся здесь (шаблоны пока не настроены).
              </div>
              <div className="mt-2 flex gap-2">
                <Input placeholder="Сообщение клиенту…" aria-label="Сообщение клиенту" />
                <Button type="submit">Отправить</Button>
              </div>
            </form>
          </>
        )}
      </section>
    </div>
  );
}
