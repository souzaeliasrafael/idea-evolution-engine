import { expect, test } from "@playwright/test";

test("creates and evaluates an idea through the real frontend and backend", async ({ page }) => {
  const uniqueName = `E2E idea ${Date.now()}`;

  await page.goto("/new");
  await page.getByLabel("Nome do projeto").fill(uniqueName);
  await page
    .getByLabel("Descreva sua ideia")
    .fill("Uma ferramenta que testa hipóteses de produto antes da implementação.");
  await page.getByLabel("Orçamento máximo de IA (opcional)").fill("1,00");
  await page.getByRole("button", { name: "Iniciar avaliação" }).click();

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: uniqueName })).toBeVisible();
  await expect(page.getByText("Conceito atual")).toBeVisible();
  await expect(page.getByText("Decisão atual")).toBeVisible();
  await expect(page.getByText("Operação")).toBeVisible();
  await expect(page.getByRole("link", { name: "Baixar relatório" })).toBeVisible();
});

test("shows the provider-independent financial dashboard", async ({ page }) => {
  await page.goto("/finance");

  await expect(
    page.getByRole("heading", { name: "Estimativas rápidas. Faturas reconciliadas." }),
  ).toBeVisible();
  await expect(page.getByText("Reconciliação oficial")).toBeVisible();
  await expect(page.getByText("OpenAI", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Por modelo" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Por projeto" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Adicionar custo manual" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Registrar custo" })).toBeVisible();
});
