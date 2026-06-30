#!/usr/bin/env node
import { createRequire } from "node:module";
import { mkdir, rename, rm, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..");
const requireFromFrontend = createRequire(resolve(repoRoot, "frontend/app/package.json"));
const { chromium } = requireFromFrontend("playwright");

const sourceDir = resolve(repoRoot, "scripts/demo_video_source");
const outputDir = resolve(repoRoot, "artifacts/demo-video");
const htmlPath = process.env.DEMO_VIDEO_SOURCE_HTML
  ? resolve(process.env.DEMO_VIDEO_SOURCE_HTML)
  : resolve(sourceDir, "injectivelens_demo.html");
const finalWebm = resolve(outputDir, "injectivelens_demo.webm");
const posterPng = resolve(outputDir, "injectivelens_demo_poster.png");
const durationMs = Number(process.env.DEMO_VIDEO_DURATION_MS || 132000);

if (!existsSync(htmlPath)) {
  throw new Error(`Missing demo HTML: ${htmlPath}`);
}

await mkdir(outputDir, { recursive: true });
await rm(finalWebm, { force: true });
await rm(posterPng, { force: true });

const chromeExecutable = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const launchOptions = existsSync(chromeExecutable)
  ? { headless: true, executablePath: chromeExecutable }
  : { headless: true };

const browser = await chromium.launch(launchOptions);

const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  recordVideo: {
    dir: outputDir,
    size: { width: 1920, height: 1080 },
  },
});

const page = await context.newPage();
await page.goto(pathToFileURL(htmlPath).href);
await page.waitForLoadState("load");
await page.evaluate(() => {
  window.startDemo?.();
});
await page.screenshot({ path: posterPng, fullPage: false });
await page.waitForFunction(() => window.__demoDone === true, null, {
  timeout: durationMs + 15000,
});
const video = page.video();
await page.close();
await context.close();
await browser.close();

const tempVideo = await video.path();
await rename(tempVideo, finalWebm);
const videoStat = await stat(finalWebm);
const posterStat = await stat(posterPng);

console.log(
  JSON.stringify(
    {
      ok: true,
      html: htmlPath,
      webm: finalWebm,
      webmBytes: videoStat.size,
      poster: posterPng,
      posterBytes: posterStat.size,
      durationMs,
    },
    null,
    2,
  ),
);
