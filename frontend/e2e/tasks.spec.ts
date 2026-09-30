import { expect, test } from "@playwright/test";

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin-test@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "admin-test-password-1";

test("tasks create and complete", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Пароль").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/deals");

  await page.goto("/tasks");
  const title = `E2E задача ${Date.now()}`;
  await page.getByRole("button", { name: "Новая задача" }).click();
  const dialog = page.getByRole("dialog", { name: "Новая задача" });
  await dialog.getByLabel("Название").fill(title);
  await dialog.getByRole("button", { name: "Сохранить" }).click();
  const row = page.locator("div", { hasText: title }).last();
  await expect(row).toBeVisible({ timeout: 10_000 });

  // Complete via checkbox: the row moves to the "Выполнено" group.
  const rowBox = page.locator("div[data-task-row]", { hasText: title });
  await rowBox.getByRole("checkbox").click();
  const doneSection = page.getByRole("region", { name: "Выполнено" });
  await expect(doneSection.getByText(title)).toBeVisible({ timeout: 10_000 });

  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "crm_csrf")?.value ?? "";
  const listed = await page.request.get("/api/tasks?limit=200");
  const tasks = (await listed.json()) as { items: { id: string; title: string }[] };
  const created = tasks.items.find((task) => task.title === title);
  if (!created) {
    throw new Error("created task not found for cleanup");
  }
  const deleted = await page.request.delete(`/api/tasks/${created.id}`, {
    headers: { "X-CSRF-Token": csrf },
  });
  expect(deleted.ok()).toBeTruthy();
});
