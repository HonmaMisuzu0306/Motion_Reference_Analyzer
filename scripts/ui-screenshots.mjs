// Capture every top-level page of the desktop UI for before/after comparisons.
// Usage: node scripts/ui-screenshots.mjs <output-dir> [baseUrl]
// Requires the Vite dev server and the core backend to be running, and a local
// Chrome/Edge install (resolved via PLAYWRIGHT_CHROME or common Windows paths).
import { createRequire } from 'node:module';
import { existsSync, mkdirSync } from 'node:fs';
import { execSync } from 'node:child_process';
import path from 'node:path';

const require = createRequire(import.meta.url);
function loadPlaywright() {
  try { return require('playwright-core'); } catch { /* fall through */ }
  const globalRoot = execSync('npm root -g').toString().trim();
  for (const candidate of ['playwright-core', 'playwright', '@playwright/mcp/node_modules/playwright-core']) {
    try { return require(path.join(globalRoot, candidate)); } catch { /* try next */ }
  }
  throw new Error('playwright-core not found; install it with `npm i -g playwright-core`');
}

const outDir = path.resolve(process.argv[2] ?? 'docs/screenshots/after');
const baseUrl = process.argv[3] ?? 'http://localhost:1420';
const chrome = [process.env.PLAYWRIGHT_CHROME,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(p => p && existsSync(p));

mkdirSync(outDir, { recursive: true });
const { chromium } = loadPlaywright();
const browser = await chromium.launch({ executablePath: chrome });
const page = await browser.newPage({ viewport: { width: 1600, height: 960 }, deviceScaleFactor: 1 });
await page.goto(baseUrl, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

async function nav(label) {
  await page.getByRole('button', { name: label, exact: true }).first().click();
  await page.waitForTimeout(1200);
}
async function shot(name) {
  await page.screenshot({ path: path.join(outDir, `${name}.png`) });
  console.log('saved', name);
}

await nav('项目'); await shot('01-projects');
await nav('分析');
const firstShot = page.locator('.shot-row').nth(4);
if (await firstShot.count()) { await firstShot.click(); await page.waitForTimeout(1500); }
await shot('02-analysis');
await nav('参考库');
const card = page.locator('.shot-card').nth(4);
if (await card.count()) { await card.click(); await page.waitForTimeout(1500); }
await shot('03-library');
await nav('模型'); await page.waitForTimeout(1500); await shot('04-models');
await nav('设置'); await shot('05-settings');
await browser.close();
