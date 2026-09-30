import { expect, test } from "@playwright/test";

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin-test@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "admin-test-password-1";

test("kanban drag persists after reload", async ({ page }) => {
  // 1. Login through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Пароль").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/deals");

  const columns = page.getByRole("region", { name: /./ });
  const source = columns.first();
  const target = columns.nth(1);
  await expect(source).toBeVisible();
  await expect(target).toBeVisible();
  const sourceName = (await source.getAttribute("aria-label")) as string;
  const targetName = (await target.getAttribute("aria-label")) as string;

  const card = source.locator("article").first();
  await expect(card).toBeVisible();
  const title = (await card.locator("p").first().innerText()).trim();
  const dealId = (await card.getAttribute("data-deal-id")) as string;
  expect(title.length).toBeGreaterThan(0);

  // 2. Drag the card into the next column (grab the drag handle).
  const handle = card.getByTitle(/Перетащить/);
  const from = await handle.boundingBox();
  const to = await target.boundingBox();
  if (!from || !to) {
    throw new Error("could not measure drag endpoints");
  }
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  const steps = 20;
  for (let step = 1; step <= steps; step += 1) {
    await page.mouse.move(
      from.x + ((to.x + to.width / 2 - from.x) * step) / steps,
      from.y + ((to.y + to.height - 40 - from.y) * step) / steps,
      { steps: 2 },
    );
  }
  await page.mouse.up();

  await expect(target.getByText(title, { exact: false }).first()).toBeVisible({
    timeout: 10_000,
  });

  // 3. Reload: the card must stay in the target column.
  await page.reload();
  const targetAfter = page
    .getByRole("region", { name: targetName })
    .locator("article")
    .filter({ hasText: title })
    .first();
  await expect(targetAfter).toBeVisible({ timeout: 10_000 });

  // 4. Restore the seed state through the API (same logged-in context).
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "crm_csrf")?.value ?? "";
  const headers = { "X-CSRF-Token": csrf };
  const pipelines = await page.request.get("/api/pipelines");
  const stages = (await pipelines.json()) as {
    id: string;
    stages: { id: string; name: string }[];
  }[];
  const allStages = stages.flatMap((pipeline) => pipeline.stages);
  const homeStage = allStages.find((stage) => stage.name === sourceName);
  if (!homeStage) {
    throw new Error(`home stage not found: ${sourceName}`);
  }
  const back = await page.request.post(`/api/deals/${dealId}/move`, {
    headers,
    data: { stage_id: homeStage.id },
  });
  expect(back.ok()).toBeTruthy();
  const unlock = await page.request.post(`/api/deals/${dealId}/unlock-bot`, { headers });
  expect(unlock.ok()).toBeTruthy();
});
