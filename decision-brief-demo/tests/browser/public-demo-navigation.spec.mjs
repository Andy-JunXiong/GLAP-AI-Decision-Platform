import { expect, test } from "@playwright/test";

const navigation = (page) => page.getByRole("navigation", { name: "Product navigation" });

async function openView(page, label, heading) {
  await navigation(page).getByRole("button", { name: label, exact: true }).click();
  await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
}

async function verifyEveryIllustrativeRow(page, view, selector) {
  await openView(page, view.label, view.heading);
  const rowCount = await page.locator(selector).count();
  expect(rowCount).toBeGreaterThan(1);

  for (let index = 0; index < rowCount; index += 1) {
    await openView(page, view.label, view.heading);
    await page.locator(selector).nth(index).click();
    await expect(page.locator(".brief-page .brief-title h1")).toBeVisible();
  }
}

test("public walkthrough navigation and illustrative rows remain clickable without writes", async ({ page }) => {
  const writeRequests = [];
  const runtimeErrors = [];
  page.on("request", (request) => {
    if (!["GET", "HEAD"].includes(request.method())) {
      writeRequests.push(`${request.method()} ${request.url()}`);
    }
  });
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    runtimeErrors.push(`${request.method()} ${request.url()} failed: ${request.failure()?.errorText ?? "unknown"}`);
  });

  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "Good morning, Mia.", level: 1 })).toBeVisible();
  expect(runtimeErrors).toEqual([]);

  await openView(page, "System", "AWS System & Evidence");
  await expect(page.getByText("Read-only AWS system evidence", { exact: true })).toBeVisible();
  await expect(page.getByText("Repository architecture verified for display", { exact: true })).toBeVisible();
  await expect(page.getByText(/live AWS inspection: no/i)).toBeVisible();
  const systemNavigation = page.getByRole("navigation", { name: "System subpages" });
  const systemTabs = [
    ["Daily E2E Flow", "Signal to governed learning evidence"],
    ["AWS Overview", "Deployed service responsibilities"],
    ["Data Catalog", "Governed decision domains"],
    ["Logic & SQL", "Fail-closed decision contracts"],
    ["OPS Dashboard", "Reliability and recovery controls"],
    ["Release & Lineage", "Delivery without production authority"],
  ];
  for (const [tab, heading] of systemTabs) {
    await systemNavigation.getByRole("button", { name: tab, exact: true }).click();
    await expect(page.getByRole("heading", { name: heading, level: 2 })).toBeVisible();
  }

  await systemNavigation.getByRole("button", { name: "OPS Dashboard", exact: true }).click();
  await page.getByRole("button", { name: "Open Pipeline Health" }).click();
  await expect(page.getByRole("heading", { name: "Pipeline Health", level: 1 })).toBeVisible();

  await openView(page, "System", "AWS System & Evidence");
  await systemNavigation.getByRole("button", { name: "OPS Dashboard", exact: true }).click();
  await page.getByRole("button", { name: "Open Forecast Accuracy" }).click();
  await expect(page.getByRole("heading", { name: "Forecast Accuracy", level: 1 })).toBeVisible();

  await openView(page, "System", "AWS System & Evidence");
  await systemNavigation.getByRole("button", { name: "OPS Dashboard", exact: true }).click();
  await page.getByRole("button", { name: "Open Action Board" }).click();
  await expect(page.getByRole("heading", { name: "Action Board", level: 1 })).toBeVisible();

  await openView(page, "Action Board", "Action Board");
  await expect(page.getByText("Read-only lifecycle preview", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open decision queue" }).click();
  await expect(page.getByRole("heading", { name: "Decision queue", level: 1 })).toBeVisible();

  await openView(page, "Action Board", "Action Board");
  await page.getByRole("button", { name: "Review illustrative brief" }).click();
  await expect(page.locator(".brief-page .brief-title h1")).toBeVisible();

  await verifyEveryIllustrativeRow(
    page,
    { label: "Signals", heading: "Signal monitoring" },
    ".table-card > button.data-row",
  );
  await verifyEveryIllustrativeRow(
    page,
    { label: "Decisions", heading: "Decision queue" },
    ".decision-list > button.decision-card",
  );
  await verifyEveryIllustrativeRow(
    page,
    { label: "Shipments", heading: "Shipments & inventory" },
    ".shipment-table > button.shipment-row",
  );

  await openView(page, "Pipeline Health", "Pipeline Health");
  await expect(page.getByText("System walkthrough", { exact: true })).toBeVisible();
  await expect(page.getByText("No live health status is exposed", { exact: true })).toBeVisible();

  await openView(page, "Forecast Accuracy", "Forecast Accuracy");
  await expect(page.getByText("Readiness logic, not measured performance", { exact: true })).toBeVisible();

  expect(runtimeErrors).toEqual([]);
  expect(writeRequests).toEqual([]);
});
