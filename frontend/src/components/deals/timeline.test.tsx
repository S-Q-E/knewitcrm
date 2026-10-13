// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ItemBody } from "@/components/deals/timeline";

afterEach(() => cleanup());

function messageItem(data: Record<string, unknown>) {
  return { kind: "message", at: "2026-10-09T10:00:00Z", data };
}

describe("ItemBody message direction label", () => {
  it("labels a manager outgoing message as manager, not bot", () => {
    render(
      <ItemBody
        item={messageItem({
          direction: "out",
          author_kind: "manager",
          author_name: "Иван",
          body: "Здравствуйте!",
        })}
      />,
    );
    expect(screen.getByText(/менеджер/)).toBeDefined();
    expect(screen.queryByText(/· бот/)).toBeNull();
  });

  it("keeps labeling a bot outgoing message as bot", () => {
    render(
      <ItemBody
        item={messageItem({
          direction: "out",
          author_kind: "bot",
          author_name: "Бот",
          body: "Здравствуйте!",
        })}
      />,
    );
    expect(screen.getByText(/· бот/)).toBeDefined();
  });

  it("labels an incoming message as incoming", () => {
    render(
      <ItemBody
        item={messageItem({
          direction: "in",
          author_kind: "client",
          author_name: "Клиент",
          body: "Привет!",
        })}
      />,
    );
    expect(screen.getByText(/входящее/)).toBeDefined();
  });
});
