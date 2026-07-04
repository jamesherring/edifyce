#!/usr/bin/env node
/*
 * screenshot.cjs — drive a headless Chromium against the running Edifyce
 * server and save a screenshot. Handles this sandbox's two gotchas:
 *
 *   1. Playwright is installed globally, not in this repo — we resolve it
 *      from `npm root -g` instead of a local node_modules.
 *   2. FastAPI's /docs (Swagger UI) and /redoc pull JS/CSS from
 *      cdn.jsdelivr.net, which the sandbox network policy blocks (403 on
 *      CONNECT). We intercept those requests and serve the assets from a
 *      local cache, vendored on demand from the npm registry (allowed).
 *
 * Usage:
 *   node screenshot.cjs <url> <outfile.png> [--full] [--wait=<selector>]
 *
 * Examples:
 *   node screenshot.cjs http://127.0.0.1:8000/docs docs.png --full
 *   node screenshot.cjs http://127.0.0.1:8000/redoc redoc.png --full --wait=h1
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// --- Gotcha 1: find the globally-installed playwright -----------------------
try {
  const globalRoot = execSync('npm root -g').toString().trim();
  if (globalRoot && !module.paths.includes(globalRoot)) module.paths.push(globalRoot);
} catch (_) { /* fall through; require below will throw a clear error */ }
const { chromium } = require('playwright');

// --- args -------------------------------------------------------------------
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

// --- Gotcha 2: vendored CDN assets ------------------------------------------
// Map the basename requested from a blocked CDN to the npm package + the path
// of the file inside that package's tarball. Add entries here if a page pulls
// in another blocked asset.
const CACHE = path.join(__dirname, '.vendor-cache');
const SOURCES = {
  'swagger-ui.css':                  { pkg: 'swagger-ui-dist@5', inner: 'swagger-ui.css', type: 'text/css' },
  'swagger-ui-bundle.js':            { pkg: 'swagger-ui-dist@5', inner: 'swagger-ui-bundle.js', type: 'application/javascript' },
  'swagger-ui-standalone-preset.js': { pkg: 'swagger-ui-dist@5', inner: 'swagger-ui-standalone-preset.js', type: 'application/javascript' },
  'redoc.standalone.js':             { pkg: 'redoc', inner: 'bundles/redoc.standalone.js', type: 'application/javascript' },
};

function vendoredPath(basename) {
  const src = SOURCES[basename];
  if (!src) return null;
  const dest = path.join(CACHE, basename);
  if (fs.existsSync(dest)) return dest;
  // Vendor on demand: npm pack the package once (registry.npmjs.org is
  // allowed), then copy every SOURCES file that lives in that same package
  // so a multi-asset page (e.g. Swagger UI's css + 2 js) costs one download.
  fs.mkdirSync(CACHE, { recursive: true });
  const work = fs.mkdtempSync(path.join(CACHE, 'pack-'));
  try {
    console.error(`[vendor] fetching ${src.pkg} ...`);
    const tgz = execSync(`npm pack ${src.pkg} --silent`, { cwd: work, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().trim().split('\n').pop().trim();
    execSync(`tar xzf ${JSON.stringify(tgz)}`, { cwd: work });
    for (const [name, s] of Object.entries(SOURCES)) {
      if (s.pkg !== src.pkg) continue;
      const from = path.join(work, 'package', s.inner);
      if (fs.existsSync(from)) fs.copyFileSync(from, path.join(CACHE, name));
    }
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
  return fs.existsSync(dest) ? dest : null;
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  // Serve blocked-CDN assets from the local cache.
  await page.route(/cdn\.jsdelivr\.net|unpkg\.com/, route => {
    const basename = route.request().url().split('/').pop().split('?')[0];
    let local = null;
    try { local = vendoredPath(basename); } catch (e) { console.error(`[vendor] ${basename} failed: ${e.message}`); }
    if (local && fs.existsSync(local)) {
      return route.fulfill({ contentType: SOURCES[basename].type, body: fs.readFileSync(local) });
    }
    return route.abort();
  });

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

  console.error(`[ok] saved ${out}${failed.length ? `  (unhandled failed requests: ${failed.length})` : ''}`);
  if (failed.length) failed.slice(0, 10).forEach(u => console.error('   failed: ' + u));
})().catch(err => { console.error(err); process.exit(1); });
