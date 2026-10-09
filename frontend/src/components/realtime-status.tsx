import { useStreamStatus } from "@/api/stream";
import type { StreamStatus } from "@/api/stream";
import { cn } from "@/lib/utils";

export interface StatusView {
  label: string;
  hint: string;
  dot: string;
}

/** Header indicator text for the realtime connection (P3-6). */
export function statusView(status: StreamStatus): StatusView {
  if (status.connected) {
    return {
      label: "Онлайн",
      hint: "Обновления приходят в реальном времени",
      dot: "bg-emerald-500",
    };
  }
  if (status.fallback) {
    return {
      label: "Резервный опрос",
      hint: "Соединение недоступно: списки обновляются каждые 15 секунд",
      dot: "bg-amber-500",
    };
  }
  return {
    label: "Нет соединения",
    hint: "Переподключаемся. Списки могут отставать",
    dot: "bg-red-500",
  };
}

export function RealtimeStatus() {
  const status = useStreamStatus();
  const view = statusView(status);
  return (
    <span
      role="status"
      title={view.hint}
      aria-label={`Realtime: ${view.label}`}
      className="flex items-center gap-1.5 px-1 text-xs text-slate-500 dark:text-slate-400"
    >
      <span className={cn("h-2 w-2 rounded-full", view.dot)} aria-hidden="true" />
      <span className="hidden md:inline">{view.label}</span>
    </span>
  );
}
