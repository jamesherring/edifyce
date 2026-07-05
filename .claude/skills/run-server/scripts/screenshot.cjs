#!/usr/bin/env node
/*
 * screenshot.cjs — drive a headless Chromium against a running dev server and
 * save a screenshot. Generic: point it at any URL (the Svelte frontend once it
 * exists, or any local page you want to inspect).
 *
 * Sandbox gotcha it handles: Playwright is installed *globally* in this
 * environment, not in this repo's node_modules, so a plain
 * `require('playwright')` fails with ERR_MODULE_NOT_FOUND. We resolve it via
 * `npm root -g`. Chromium is pre-installed at /opt/pw-browsers
 * (PLAYWRIGHT_BROWSERS_PATH) — never run `playwright install`.
 *
 * Usage:
 *   node screenshot.cjs <url> <outfile.png> [--full] [--wait=<css-selector>]
 *
 * Examples:
 *   node screenshot.cjs http://127.0.0.1:5173/ home.png --full
 *   node screenshot.cjs http://127.0.0.1:5173/ editor.png --wait=.proof-editor
 */

const { execSync } = require('child_process');

// Resolve the globally-installed playwright.
try {
  const globalRoot = execSync('npm root -g').toString().trim();
  if (globalRoot && !module.paths.includes(globalRoot)) module.paths.push(globalRoot);
} catch (_) { /* fall through; require below throws a clear error */ }
const { chromium } = require('playwright');

const args = process.argv.slice(2);
const url = args[0];
const out = args[1];
if (!url || !out) {
  console.error('usage: node screenshot.cjs <url> <outfile.png> [--full] [--wait=<selector>]');
  process.exit(2);
}
const fullPage = args.includes('--full');
const waitArg = args.find(a => a.startsWith('--wait='));
const waitSelector = waitArg ? waitArg.slice('--wait='.length) : null;

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  const failed = [];
  page.on('requestfailed', r => failed.push(r.url()));

  await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  if (waitSelector) {
    await page.waitForSelector(waitSelector, { timeout: 10000 }).catch(() => {
      console.error(`[warn] selector not found: ${waitSelector}`);
    });
  }
  await page.screenshot({ path: out, fullPage });
  await browser.close();

  console.error(`[ok] saved ${out}${failed.length ? `  (${failed.length} request(s) failed)` : ''}`);
  // Some external hosts (CDNs, Google Fonts, etc.) are blocked by the sandbox
  // network policy. A bundled Svelte/Vite app serves its own assets locally so
  // it still renders; only truly external references show up here.
  if (failed.length) failed.slice(0, 10).forEach(u => console.error('   failed: ' + u));
})().catch(err => { console.error(err); process.exit(1); });
