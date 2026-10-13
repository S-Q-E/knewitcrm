import { expect, test, type Page } from "@playwright/test";

// Этап A мобильной адаптации: проверки в телефонном вьюпорте.
// Десктопные спеки рядом не трогаем; этот файл гоняется той же командой `npm run e2e`.
test.use({
  viewport: { width: 375, height: 667 },
  hasTouch: true,
  isMobile: true,
});

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "mobile-test@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "mobile-test-password-1";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Пароль").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/deals");
}

async function expectNoPageOverflow(page: Page, where: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `horizontal overflow on ${where}`).toBeLessThanOrEqual(1);
}

test("mobile: login has no horizontal overflow", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Войти" })).toBeVisible();
  await expectNoPageOverflow(page, "/login");
});

test("mobile: main screens have no horizontal overflow", async ({ page }) => {
  await login(page);
  for (const path of ["/deals", "/tasks", "/contacts", "/dialogs", "/analytics"]) {
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    await expectNoPageOverflow(page, path);
  }
  // Нижний таб-бар виден, боковой панели нет.
  await expect(page.getByRole("navigation", { name: "Основная навигация" })).toBeVisible();
});

test("mobile: dialogs list -> chat -> back", async ({ page }) => {
  await login(page);
  await page.goto("/dialogs");

  const rows = page.locator("aside button", { hasText: /бот (на паузе|отвечает)/ });
  await expect(rows.first()).toBeVisible({ timeout: 15_000 });

  // В списке чат скрыт, виден только список.
  await expect(page.getByLabel("Сообщение клиенту")).toBeHidden();

  await rows.first().click();
  await expect(page).toHaveURL(/wa=/);

  // В чате список скрыт, есть кнопка «Назад», композер и «Отправить» видны.
  const back = page.getByRole("button", { name: "Назад к списку" });
  await expect(back).toBeVisible();
  const composer = page.getByLabel("Сообщение клиенту");
  await expect(composer).toBeVisible();
  const send = page.getByRole("button", { name: "Отправить" });
  await expect(send).toBeVisible();
  const box = await send.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(667);
  await expectNoPageOverflow(page, "/dialogs?wa=");

  await back.click();
  await expect(page).toHaveURL(/\/dialogs$/);
  await expect(rows.first()).toBeVisible();
  await expect(composer).toBeHidden();
});
