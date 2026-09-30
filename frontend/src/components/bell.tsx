import { useNavigate } from "react-router-dom";

import type { Notification } from "@/api/tasks";
import { useNotifications, useReadAllNotifications, useReadNotification } from "@/api/tasks";
import { useToast, toastError } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<string, string> = {
  deal_assigned: "Сделка назначена",
  task_overdue: "Просроченная задача",
  task_due_soon: "Задача скоро",
  manager_handover: "Клиент ждёт менеджера",
  dialog_message: "Новое сообщение",
  locked_stage: "Бот упёрся в блокировку",
  automation: "Автоматизация",
};

function target(notification: Notification): string | null {
  const payload = notification.payload;
  if (typeof payload.deal_id === "string") {
    return `/deals/${payload.deal_id}`;
  }
  if (typeof payload.whatsapp_id === "string") {
    return `/dialogs?wa=${encodeURIComponent(payload.whatsapp_id)}`;
  }
  if (typeof payload.task_id === "string") {
    return "/tasks";
  }
  return null;
}

export function BellBadge() {
  const query = useNotifications(true);
  const count = query.data?.unread_total ?? 0;
  if (count === 0) {
    return null;
  }
  return (
    <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
      {count > 99 ? "99+" : count}
    </span>
  );
}

export function BellDropdown({ onClose }: { onClose: () => void }) {
  const { push } = useToast();
  const navigate = useNavigate();
  const list = useNotifications(false);
  const readOne = useReadNotification();
  const readAll = useReadAllNotifications();

  const open = (notification: Notification) => {
    if (!notification.read_at) {
      readOne.mutate(notification.id);
    }
    const to = target(notification);
    onClose();
    if (to) {
      navigate(to);
    }
  };

  return (
    <div className="absolute right-0 z-20 mt-2 max-h-96 w-80 overflow-y-auto rounded-md border border-slate-200 bg-white p-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-center justify-between px-2 py-1">
        <p className="font-medium">Уведомления</p>
        {(list.data?.unread_total ?? 0) > 0 && (
          <button
            type="button"
            className="text-xs text-slate-500 underline"
            onClick={() =>
              readAll.mutate(undefined, { onError: (error) => toastError(push, error) })
            }
          >
            Прочитать все
          </button>
        )}
      </div>
      {(list.data?.items ?? []).map((notification) => (
        <button
          key={notification.id}
          type="button"
          onClick={() => open(notification)}
          className={cn(
            "block w-full rounded px-2 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800",
            !notification.read_at && "bg-slate-50 dark:bg-slate-800/60",
          )}
        >
          <span className="font-medium">{TYPE_LABEL[notification.type] ?? notification.type}</span>
          <span className="block truncate text-xs text-slate-500">
            {typeof notification.payload.text === "string"
              ? notification.payload.text
              : typeof notification.payload.title === "string"
                ? notification.payload.title
                : ""}
          </span>
          <span className="block text-[11px] text-slate-400">
            {formatRelative(notification.created_at)}
          </span>
        </button>
      ))}
      {(list.data?.items.length ?? 0) === 0 && !list.isPending && (
        <p className="px-2 py-3 text-slate-500">Пока нет уведомлений.</p>
      )}
      <Button variant="ghost" size="sm" className="mt-1 w-full" onClick={onClose}>
        Закрыть
      </Button>
    </div>
  );
}
