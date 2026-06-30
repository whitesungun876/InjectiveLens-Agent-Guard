#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

./scripts/run_demo.sh >/dev/null
./scripts/run_app.sh >/dev/null

mkdir -p "$ROOT/artifacts"

cd "$ROOT/frontend/app"
node --input-type=commonjs <<'JS'
const { chromium } = require("playwright");

const SCREENSHOT_PATH = "/Users/lola/Desktop/mantle/artifacts/p2_6_judge_browser_smoke.png";

async function mustContain(text, expected, label) {
  if (!text.includes(expected)) {
    throw new Error(`${label} missing expected text: ${expected}`);
  }
}

async function mustNotContain(text, forbidden, label) {
  if (text.includes(forbidden)) {
    throw new Error(`${label} contained forbidden text: ${forbidden}`);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  await page.goto("http://127.0.0.1:5173/", { waitUntil: "networkidle" });

  const initialText = await page.locator("body").innerText();
  await mustContain(initialText, "MantleLens Wallet Guard", "initial page");
  await mustContain(initialText, "AI on-chain risk intelligence for Mantle wallets.", "initial page");
  await mustContain(initialText, "Review a Mantle wallet before acting.", "initial page");
  await mustContain(initialText, "Demo scenario", "initial page");
  await mustContain(initialText, "Live scan", "initial page");
  await mustContain(initialText, "Run demo scan", "initial page");
  await mustNotContain(initialText, "Load Sepolia proof sample", "initial page");
  await mustNotContain(initialText, "Use Sepolia sample wallet", "initial page");
  await mustNotContain(initialText, "Demo · Live-ready", "initial page");
  await mustNotContain(initialText, "Feedback-ready", "initial page");
  await mustNotContain(initialText, "Send to wallet", "initial page");

  const navText = await page.locator(".tabs").innerText();
  if (navText.trim() !== "Overview\nEvidence\nHistory") {
    throw new Error(`primary nav should be Overview / Evidence / History, got: ${JSON.stringify(navText)}`);
  }

  const scanConsoleHeight = await page.locator(".scan-console").evaluate((element) => Math.round(element.getBoundingClientRect().height));
  const caseMetaHeight = await page.locator('[data-testid="benchmark-case-meta"]').evaluate((element) => Math.round(element.getBoundingClientRect().height));
  if (scanConsoleHeight > 520) {
    throw new Error(`scan console is too tall for first viewport: ${scanConsoleHeight}px`);
  }
  if (caseMetaHeight > 90) {
    throw new Error(`benchmark case chips are too tall: ${caseMetaHeight}px`);
  }

  await page.getByTestId("scan-button").click();
  await page.waitForFunction(() => document.body.innerText.includes("3 suspicious on-chain signals detected"), null, { timeout: 10000 });
  let text = await page.locator("body").innerText();
  await mustContain(text, "3 suspicious on-chain signals detected", "overview");
  await mustContain(text, "60 / 100", "overview");
  await mustContain(text, "Core on-chain signals", "overview");
  await mustContain(text, "Yield concentration signal", "overview");
  await mustContain(text, "Elevated", "overview");
  await mustContain(text, "Live scan required before recording an assessment hash.", "overview proof status");
  await mustContain(text, "View replay proof", "overview proof action");
  await mustNotContain(text, "Record assessment hash", "demo overview");

  await page.getByRole("button", { name: /Simulate risk reduction/i }).first().click();
  await page.waitForFunction(() => document.body.innerText.includes("The risk model selected this action because"), null, { timeout: 10000 });
  text = await page.locator("body").innerText();
  await mustContain(text, "The risk model selected this action because", "simulation");
  await mustContain(text, "No transaction was broadcast. This is simulation-only and review-only.", "simulation");
  await mustNotContain(text, "transaction created true", "simulation");

  await page.getByTestId("tab-evidence").click();
  await page.waitForTimeout(250);
  text = await page.locator("body").innerText();
  await mustContain(text, "Evidence bundle", "evidence");
  await mustContain(text, "Next actions", "evidence");
  await mustContain(text, "View replay proof", "evidence proof action");
  await mustContain(text, "Supporting records", "evidence");
  await mustContain(text, "Expand supporting records", "evidence");
  await mustNotContain(text, "Evidence reviewed", "evidence");
  await mustNotContain(text, "Record assessment hash", "demo evidence");
  const evidenceDomText = await page.evaluate(() => document.body.textContent || "");
  await mustContain(evidenceDomText, "Replay fixture /", "evidence raw details");
  await mustContain(evidenceDomText, "Read call · no tx hash", "evidence raw details");
  await mustNotContain(text, "Fixture tx reference", "evidence");
  await mustNotContain(text, "Fixture approval reference", "evidence");

  await page.getByTestId("tab-history").click();
  await page.waitForTimeout(250);
  text = await page.locator("body").innerText();
  await mustContain(text, "Assessment history & risk trend", "history");
  await mustContain(text, "Open review items", "history");
  await mustContain(text, "Recent assessments", "history");
  await mustContain(text, "View replay proof", "history");

  await page.getByTestId("open-advanced").click();
  await page.waitForTimeout(250);
  text = await page.locator("body").innerText();
  await mustContain(text, "Benchmark case matrix", "advanced");
  await mustContain(text, "Multi-signal wallet", "advanced");
  await mustContain(text, "Quiet wallet", "advanced");
  await mustContain(text, "Critical red-flag wallet", "advanced");
  await mustContain(text, "ERC-8004-compatible registration", "advanced");
  await mustContain(text, "No identity NFT is claimed unless a contract address and token id are shown.", "advanced");
  await mustContain(text, "Formula: weighted score = sum(metric score x weight).", "advanced");
  const defiMentions = (text.match(/DeFi \/ yield exposure/g) || []).length;
  if (defiMentions > 1) {
    throw new Error(`DeFi / yield exposure should be deduplicated in advanced scoring, found ${defiMentions}`);
  }

  const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  if (horizontalOverflow) {
    throw new Error("page has horizontal overflow");
  }

  await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });
  await browser.close();

  console.log(
    JSON.stringify(
      {
        ok: true,
        scanConsoleHeight,
        caseMetaHeight,
        horizontalOverflow,
        screenshot: SCREENSHOT_PATH
      },
      null,
      2
    )
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
JS
