// @vitest-environment happy-dom
import { describe, expect, it, vi, afterEach } from "vitest";
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ChatComposer } from "@/components/dialogs/composer";

const originalMatchMedia = window.matchMedia;

afterEach(() => {
  cleanup();
  window.matchMedia = originalMatchMedia;
});

function mockPointer(coarse: boolean) {
  const query = {
    matches: coarse,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  window.matchMedia = vi.fn().mockReturnValue(query) as unknown as typeof window.matchMedia;
}

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
    mockPointer(false);
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    const box = screen.getByLabelText("Message to prospect");
    fireEvent.change(box, { target: { value: "Hello!" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: false });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("Hello!");
    // The harness clears the draft on send, like the dialogs page does.
    expect((screen.getByLabelText("Message to prospect") as HTMLTextAreaElement).value).toBe("");
  });

  it("inserts a newline on Shift+Enter instead of sending", () => {
    mockPointer(false);
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    const box = screen.getByLabelText("Message to prospect") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "a line" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("on a coarse pointer Enter does not send, only the button does", () => {
    mockPointer(true);
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    const box = screen.getByLabelText("Message to prospect");
    fireEvent.change(box, { target: { value: "hello from phone" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: false });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("hello from phone");
  });

  it("warns before sending while the bot is active", () => {
    render(<Harness botPaused={false} />);
    const box = screen.getByLabelText("Message to prospect");
    fireEvent.change(box, { target: { value: "hello" } });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("The bot is replying right now");
  });

  it("stays quiet while the bot is paused", () => {
    render(<Harness botPaused />);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
