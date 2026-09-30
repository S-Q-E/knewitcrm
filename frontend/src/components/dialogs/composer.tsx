import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ChatComposerProps {
  /** False while the bot answers the client itself (warns before sending). */
  botPaused: boolean;
  sending: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: (body: string) => void;
}

export function ChatComposer({
  botPaused,
  sending,
  draft,
  onDraftChange,
  onSend,
}: ChatComposerProps) {
  const [touched, setTouched] = useState(false);
  const trimmed = draft.trim();
  const showWarning = !botPaused && touched && trimmed.length > 0;

  const submit = () => {
    if (trimmed.length === 0 || sending) {
      return;
    }
    onSend(trimmed);
  };

  return (
    <div>
      {showWarning && (
        <p
          role="alert"
          className="mb-2 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200"
        >
          Бот отвечает клиенту прямо сейчас — отправка поставит его на паузу.
        </p>
      )}
      <div className="flex gap-2">
        <textarea
          aria-label="Сообщение клиенту"
          value={draft}
          rows={2}
          placeholder="Сообщение клиенту… (Enter — отправить, Shift+Enter — перенос)"
          disabled={sending}
          onChange={(event) => {
            setTouched(true);
            onDraftChange(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          className={cn(
            "min-h-9 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm",
            "placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-400",
            "disabled:cursor-not-allowed disabled:opacity-60",
            "dark:border-slate-700 dark:bg-slate-900",
          )}
        />
        <Button type="button" onClick={submit} disabled={sending || trimmed.length === 0}>
          {sending ? "Отправка…" : "Отправить"}
        </Button>
      </div>
    </div>
  );
}
