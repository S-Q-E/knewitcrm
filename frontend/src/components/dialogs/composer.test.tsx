// @vitest-environment happy-dom
import { describe, expect, it, vi, afterEach } from "vitest";
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ChatComposer } from "@/components/dialogs/composer";

afterEach(() => cleanup());

function Harness(props: { botPaused?: boolean; onSend?: (body: string) => void }) {
  const [draft, setDraft] = useState("");
  return (
    <ChatComposer
      botPaused={props.botPaused ?? true}
      sending={false}
      draft={draft}
      onDraftChange={setDraft}
      onSend={(body) => {
        setDraft("");
        props.onSend?.(body);
      }}
    />
  );
}

describe("ChatComposer", () => {
  it("sends on Enter and clears via parent state", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    const box = screen.getByLabelText("Сообщение клиенту");
    fireEvent.change(box, { target: { value: "Здравствуйте!" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: false });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("Здравствуйте!");
    // The harness clears the draft on send, like the dialogs page does.
    expect((screen.getByLabelText("Сообщение клиенту") as HTMLTextAreaElement).value).toBe("");
  });

  it("inserts a newline on Shift+Enter instead of sending", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    const box = screen.getByLabelText("Сообщение клиенту") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "строка" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("warns before sending while the bot is active", () => {
    render(<Harness botPaused={false} />);
    const box = screen.getByLabelText("Сообщение клиенту");
    fireEvent.change(box, { target: { value: "привет" } });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Бот отвечает клиенту прямо сейчас");
  });

  it("stays quiet while the bot is paused", () => {
    render(<Harness botPaused />);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
