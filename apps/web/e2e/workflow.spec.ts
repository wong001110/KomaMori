import { deflateSync } from "node:zlib";

import { expect, test } from "@playwright/test";

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
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // truecolor RGB
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = width * 3 + 1;
  const raw = Buffer.alloc(stride * height, 255);
  for (let y = 0; y < height; y += 1) raw[y * stride] = 0; // PNG filter byte

  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0))
  ]);
}

const WHITE_PAGE = whitePng(320, 480);

test("manual localization reaches a Ready reader from the real UI", async ({ page }) => {
  await page.goto("/");

  await page.getByPlaceholder("Series title").fill("E2E Series");
  await page.getByLabel("Source language").fill("ja");
  await page.locator("form.stack-form").getByRole("button", { name: "Add" }).click();
  await expect(page.getByRole("heading", { name: "E2E Series" })).toBeVisible();

  await page.locator("form.chapter-form input[name=number]").fill("1");
  await page.getByPlaceholder("Chapter title").fill("Chapter 1");
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
  await page.getByLabel("Type").selectOption("dialogue");
  await page.getByLabel("Source OCR").fill("こんにちは");
  await page.getByLabel("en localization").fill("Hello from E2E");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved and reusable")).toBeVisible();

  await page.getByRole("button", { name: "Read" }).click();
  await expect(page.locator(".readiness-badge")).toHaveText("Ready");
  await expect(page.locator(".reader-overlay")).toContainText("Hello from E2E");
});
