import { deflateSync } from "node:zlib";

import { expect, test, type Page } from "@playwright/test";

function crc32(buffer: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type: string, data: Buffer): Buffer {
  const typeBuffer = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])));
  return Buffer.concat([length, typeBuffer, data, checksum]);
}

function whitePng(width: number, height: number): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = width * 3 + 1;
  const raw = Buffer.alloc(stride * height, 255);
  for (let y = 0; y < height; y += 1) raw[y * stride] = 0;

  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0))
  ]);
}

const WHITE_PAGE = whitePng(320, 480);

async function createSeries(page: Page, title: string) {
  await page.goto("/");
  await page.getByPlaceholder("Series title").fill(title);
  await page.getByLabel("Source language").fill("ja");
  await page.locator("form.stack-form").getByRole("button", { name: "Add" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
}

async function openFreshWorkbench(page: Page, seriesTitle: string, chapterLabel: string, sortOrder: number) {
  await createSeries(page, seriesTitle);
  await page.getByLabel("New chapter display label").fill(chapterLabel);
  await page.getByLabel("New chapter sort order").fill(String(sortOrder));
  await page.getByPlaceholder("Chapter title").fill(`Chapter ${chapterLabel}`);
  await page.getByRole("button", { name: "Add chapter" }).click();
  await page.locator('input[name="pages"]').setInputFiles({
    name: "001.png",
    mimeType: "image/png",
    buffer: WHITE_PAGE
  });
  await page.getByRole("button", { name: "Import pages / CBZ" }).click();
  await expect(page.getByText("1 pages ready")).toBeVisible();
  await page.getByRole("button", { name: "Open workbench" }).click();
  await expect(page.getByText("Localization workbench")).toBeVisible();
  await expect(page.getByRole("heading", { name: `#${chapterLabel} Chapter ${chapterLabel}` })).toBeVisible();
}

async function drawRegion(page: Page) {
  await page.getByRole("button", { name: "+ Add region" }).click();
  const stage = page.locator(".manga-stage");
  const box = await stage.boundingBox();
  expect(box).not.toBeNull();
  if (!box) throw new Error("Manga stage has no layout box");
  await page.mouse.move(box.x + box.width * 0.20, box.y + box.height * 0.20);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.42, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByLabel("Type")).toBeVisible();
}

test("chapter display labels are independent from numeric sort order", async ({ page }) => {
  await createSeries(page, "E2E Chapter Identity");
  await page.getByLabel("New chapter display label").fill("Extra");
  await page.getByLabel("New chapter sort order").fill("10.5");
  await page.getByPlaceholder("Chapter title").fill("Bonus story");
  await page.getByRole("button", { name: "Add chapter" }).click();

  await expect(page.getByText("#Extra")).toBeVisible();
  await expect(page.getByText("order 10.5")).toBeVisible();

  await page.getByLabel("Chapter display label", { exact: true }).fill("Prologue");
  await page.getByLabel("Chapter sort order", { exact: true }).fill("0.25");
  await page.getByRole("button", { name: "Save chapter" }).click();

  await expect(page.getByText("#Prologue")).toBeVisible();
  await expect(page.getByText("order 0.25")).toBeVisible();
});

test("manual localization reaches a Ready reader from the real UI", async ({ page }) => {
  await openFreshWorkbench(page, "E2E Series", "Extra", 1);
  await drawRegion(page);

  await page.getByLabel("Type").selectOption("dialogue");
  await page.getByLabel("Source OCR").fill("こんにちは");
  await page.getByLabel("en localization").fill("Hello from E2E");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved and reusable")).toBeVisible();

  await page.getByRole("button", { name: "Read" }).click();
  await expect(page.locator(".readiness-badge")).toHaveText("Ready");
  await expect(page.getByText("#Extra Chapter Extra")).toBeVisible();
  await expect(page.locator(".reader-overlay")).toContainText("Hello from E2E");
});

test("an unresolved unknown region cannot present a locale as Ready", async ({ page }) => {
  await openFreshWorkbench(page, "E2E Unknown Gate", "11", 11);
  await drawRegion(page);

  await expect(page.getByLabel("Type")).toHaveValue("unknown");
  await page.getByLabel("Source OCR").fill("未分類");
  await page.getByLabel("en localization").fill("Unclassified");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved; release review still required")).toBeVisible();

  await page.getByRole("button", { name: "Read" }).click();
  await expect(page.locator(".readiness-badge")).toHaveText("Partial");
  await expect(page.locator(".readiness-badge")).not.toHaveText("Ready");
});

test("a blocking locked-term QA error cannot present a locale as Ready", async ({ page }) => {
  await openFreshWorkbench(page, "E2E QA Gate", "12", 12);

  await page.getByPlaceholder("Source term").fill("こんにちは");
  await page.getByPlaceholder("en term").fill("Greetings");
  await page.getByRole("button", { name: "Lock" }).click();
  await expect(page.getByText("こんにちは")).toBeVisible();

  await drawRegion(page);
  await page.getByLabel("Type").selectOption("dialogue");
  await page.getByLabel("Source OCR").fill("こんにちは");
  await page.getByLabel("en localization").fill("Hello");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved; release review still required")).toBeVisible();

  await page.getByRole("button", { name: "Read" }).click();
  await expect(page.locator(".readiness-badge")).toHaveText("Review");
  await expect(page.locator(".readiness-badge")).not.toHaveText("Ready");
});
