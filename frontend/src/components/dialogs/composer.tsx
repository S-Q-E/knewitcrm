import { useEffect, useState } from "react";

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
  // On touch screens Enter inserts a new line and only the button sends,
  // otherwise the virtual keyboard makes multi-line text hard to type.
  const [coarsePointer, setCoarsePointer] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }
    const query = window.matchMedia("(pointer: coarse)");
    const update = () => setCoarsePointer(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
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
          The bot is replying right now — sending will pause it.
        </p>
      )}
      <div className="flex gap-2">
        <textarea
          aria-label="Message to prospect"
          value={draft}
          rows={2}
          placeholder={
            coarsePointer
              ? "Message to prospect…"
              : "Message to prospect… (Enter to send, Shift+Enter for a new line)"
          }
          disabled={sending}
          onChange={(event) => {
            setTouched(true);
            onDraftChange(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !coarsePointer) {
              event.preventDefault();
              submit();
            }
          }}
          className={cn(
            "min-h-11 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-base",
            "placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-400",
            "disabled:cursor-not-allowed disabled:opacity-60",
            "dark:border-slate-700 dark:bg-slate-900",
            "md:min-h-9 md:text-sm",
          )}
        />
        <Button
          type="button"
          onClick={submit}
          disabled={sending || trimmed.length === 0}
          className="shrink-0 self-end"
        >
          {sending ? "Sending…" : "Send"}
        </Button>
      </div>
    </div>
  );
}
