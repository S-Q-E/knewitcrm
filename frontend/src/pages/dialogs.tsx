import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { DialogSummary, LeadMessage, OutboxItem } from "@/api/timeline";
import {
  fetchOlderLeadMessages,
  mergeLeadMessages,
  useDialog,
  useDialogs,
  useLeadMessages,
  useMarkRead,
  useOutbox,
  usePauseBot,
  useQuickReplies,
  useResumeBot,
  useRetryOutbox,
  useSendMessage,
  useUpdateDialog,
} from "@/api/timeline";
import { useUsersLite } from "@/api/deals";
import { ChatComposer } from "@/components/dialogs/composer";
import { substituteQuickReply } from "@/lib/quick_replies";
import { useToast, toastError } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDate, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

type Filter = "all" | "mine" | "unassigned" | "unread" | "needs_reply";

export function DialogsPage() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(params.get("wa"));
  const [draft, setDraft] = useState("");
  const [older, setOlder] = useState<{
    whatsappId: string;
    items: LeadMessage[];
    hasMore: boolean;
  } | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const { push } = useToast();
  const markRead = useMarkRead();
  const updateDialog = useUpdateDialog();
  const pauseBot = usePauseBot();
  const resumeBot = useResumeBot();
  const sendMessage = useSendMessage();
  const retryOutbox = useRetryOutbox();
  const users = useUsersLite();

  const dialogs = useDialogs({
    assigned: filter === "mine" || filter === "unassigned" ? filter : undefined,
    unread: filter === "unread",
    needsReply: filter === "needs_reply",
    search: search || undefined,
  });
  const dialog = useDialog(selected);
  const messages = useLeadMessages(selected);
  const outbox = useOutbox(selected);
  const quickReplies = useQuickReplies();

  const totalUnread = dialogs.data?.items.reduce((sum, item) => sum + item.unread_count, 0) ?? 0;
  useEffect(() => {
    document.title = totalUnread > 0 ? `(${totalUnread}) KnewIT CRM` : "KnewIT CRM";
    return () => {
      document.title = "KnewIT CRM";
    };
  }, [totalUnread]);

  useEffect(() => {
    if (selected) {
      markRead.mutate(selected);
      setParams(selected ? { wa: selected } : {}, { replace: true });
    }
    // Mark read once per opened dialog; params sync keeps deep links working.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const open = (whatsappId: string) => {
    setDraft("");
    setSelected(whatsappId);
  };

  const assign = (whatsappId: string, userId: string) => {
    updateDialog.mutate(
      { whatsapp_id: whatsappId, patch: { assigned_to: userId || null } },
      { onError: (error) => toastError(push, error) },
    );
  };

  const togglePause = (current: DialogSummary) => {
    const mutate = current.bot_paused ? resumeBot : pauseBot;
    mutate.mutate(current.whatsapp_id, { onError: (error) => toastError(push, error) });
  };

  const send = (body: string) => {
    if (!selected) {
      return;
    }
    sendMessage.mutate(
      { whatsapp_id: selected, body },
      {
        onSuccess: () => setDraft(""),
        onError: (error) => toastError(push, error),
      },
    );
  };

  const olderForSelected = older?.whatsappId === selected ? older : null;
  const olderItems = olderForSelected?.items ?? [];
  const shownMessages = mergeLeadMessages(olderItems, messages.data?.items ?? []);
  const hasMoreOlder = olderForSelected?.hasMore ?? messages.data?.has_more ?? false;

  const loadOlder = async () => {
    const oldest = shownMessages[0];
    if (!selected || !oldest) {
      return;
    }
    setLoadingOlder(true);
    try {
      const page = await fetchOlderLeadMessages(selected, oldest.id);
      setOlder({
        whatsappId: selected,
        items: mergeLeadMessages(page.items, olderItems),
        hasMore: page.has_more,
      });
    } catch (error) {
      toastError(push, error);
    } finally {
      setLoadingOlder(false);
    }
  };

  const applyQuickReply = (body: string, contactName: string | null) => {
    setDraft(substituteQuickReply(body, contactName));
  };

  const retry = (item: OutboxItem) => {
    retryOutbox.mutate(
      { whatsapp_id: item.whatsapp_id, outbox_id: item.id },
      { onError: (error) => toastError(push, error) },
    );
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
              ["needs_reply", "Требуют ответа"],
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
                <span className="flex items-center gap-1">
                  {item.needs_reply && (
                    <span className="rounded-full bg-amber-100 px-1.5 text-[11px] text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                      ждёт ответа
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
                disabled={pauseBot.isPending || resumeBot.isPending}
                onClick={() => dialog.data && togglePause(dialog.data)}
              >
                {dialog.data.bot_paused ? "Включить бота" : "Пауза бота"}
              </Button>
            </header>

            {dialog.data.bot_paused && (
              <div className="flex items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
                <span>Бот на паузе. Клиент не получит автоматических ответов.</span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={resumeBot.isPending}
                  onClick={() => dialog.data && togglePause(dialog.data)}
                >
                  Вернуть боту
                </Button>
              </div>
            )}

            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
              {messages.isPending && <p className="text-sm text-slate-500">Загрузка…</p>}
              {hasMoreOlder && (
                <Button
                  size="sm"
                  variant="secondary"
                  className="self-center"
                  disabled={loadingOlder}
                  onClick={() => void loadOlder()}
                >
                  Показать более ранние
                </Button>
              )}
              {shownMessages.map((message) => (
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
                    {message.message_type === "manager" ? "Менеджер · " : ""}
                    {message.stage_at_moment ? `${message.stage_at_moment} · ` : ""}
                    {formatDate(message.created_at)}
                  </p>
                </div>
              ))}
              {(outbox.data?.items ?? [])
                .filter((item) => item.status !== "sent")
                .map((item) => (
                  <div
                    key={item.id}
                    className={cn(
                      "ml-auto max-w-[85%] rounded-lg px-3 py-2 text-sm",
                      item.status === "failed"
                        ? "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100"
                        : "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
                    )}
                  >
                    <p className="whitespace-pre-wrap">{item.body}</p>
                    <p className="mt-1 flex items-center gap-2 text-[11px] opacity-80">
                      {item.status === "failed" ? "Ошибка отправки" : "В очереди…"}
                      {formatDate(item.created_at)}
                      {item.status === "failed" && (
                        <button
                          type="button"
                          onClick={() => retry(item)}
                          disabled={retryOutbox.isPending}
                          title="Сообщение уже могло дойти до клиента — возможна дубль-доставка"
                          className="font-medium underline underline-offset-2"
                        >
                          Повторить (возможна дубль-доставка)
                        </button>
                      )}
                    </p>
                  </div>
                ))}
            </div>

            <div className="border-t border-slate-200 p-3 dark:border-slate-800">
              {quickReplies.data && quickReplies.data.items.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {quickReplies.data.items.map((reply) => (
                    <button
                      key={reply.id}
                      type="button"
                      title={reply.body}
                      onClick={() => applyQuickReply(reply.body, dialog.data.contact_name)}
                      className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                    >
                      {reply.title}
                    </button>
                  ))}
                </div>
              )}
              <ChatComposer
                botPaused={dialog.data.bot_paused}
                sending={sendMessage.isPending}
                draft={draft}
                onDraftChange={setDraft}
                onSend={send}
              />
            </div>
          </>
        )}
      </section>
    </div>
  );
}
