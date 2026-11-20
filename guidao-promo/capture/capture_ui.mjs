import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = '/workspace/guidao-promo/assets/ui';
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => window.__viewer?.running && typeof window.__api === 'object', null, { timeout: 120000 });
await page.waitForTimeout(3500);

// select Line 2
const line2 = page.getByText('2号线', { exact: true }).first();
if (await line2.count()) { await line2.click({ force: true }); await page.waitForTimeout(1200); }
await page.waitForTimeout(1500);

const classes = await page.evaluate(() => {
  const all = [...document.querySelectorAll('body *')];
  const picked = all.filter((e) => {
    const c = typeof e.className === 'string' ? e.className : '';
    return /panel|card|dock|header|hud|overlay|rail/.test(c);
  }).slice(0, 60).map((e) => ({ tag: e.tagName, cls: e.className }));
  return picked;
});
console.log(JSON.stringify(classes, null, 1));

// transparent panel captures
await page.addStyleTag({ content: `
  canvas, .labels-layer, .header, .control-dock, .attribution, .stats-panel,
  .follow-hud, .platform-hud, .toast, .panel-rail { visibility: hidden !important; }
  html, body, #root { background: transparent !important; }
`});
await page.waitForTimeout(300);

async function shot(selector, name) {
  const el = page.locator(selector).first();
  if (!(await el.count())) { console.log('MISS', selector); return; }
  await el.screenshot({ path: path.join(OUT, name + '.png'), omitBackground: true, timeout: 60000 });
  console.log('saved', name);
}

await shot('.side-panel.line-panel', 'line_panel');
await shot('.side-panel.train-panel', 'train_panel');

// station card
await page.evaluate(() => { window.__api.focusStation('st-19'); });
await page.waitForTimeout(2500);
await shot('.station-card', 'station_card');
await shot('.app .station-card', 'station_card2');

// full page with UI for reference
await page.addStyleTag({ content: `canvas, .labels-layer { visibility: visible !important; }` });
await page.evaluate(() => { window.__api.resetView(); });
await page.waitForTimeout(1500);
await page.screenshot({ path: path.join(OUT, 'full_ui.jpg'), type: 'jpeg', quality: 90 });

await browser.close();
