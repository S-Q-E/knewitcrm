import { expect, test } from "@playwright/test";

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin-test@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "admin-test-password-1";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Пароль").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/deals");
}

test("deal drawer shows messages and events", async ({ page }) => {
  await login(page);

  const columns = page.getByRole("region", { name: /./ });
  const card = columns.first().locator("article").first();
  await expect(card).toBeVisible();
  const dealId = (await card.getAttribute("data-deal-id")) as string;

  // Drawer from the board.
  await card.click();
  const drawer = page.getByRole("dialog", { name: "Карточка сделки" });
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('[data-timeline-kind="message"]').first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(drawer.locator('[data-timeline-kind="event"]').first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(drawer.getByText("Данные от бота")).toBeVisible();
  await drawer.getByRole("button", { name: "Закрыть" }).click();
  await expect(drawer).toBeHidden();

  // Standalone page shows the same stream.
  await page.goto(`/deals/${dealId}`);
  await expect(page.locator('[data-timeline-kind="message"]').first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.locator('[data-timeline-kind="stage"]').first()).toBeVisible({
    timeout: 10_000,
  });
});
