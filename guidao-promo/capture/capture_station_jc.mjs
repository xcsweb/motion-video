import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = '/workspace/guidao-promo/assets/ui';
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => window.__viewer?.running && typeof window.__api === 'object', null, { timeout: 120000 });
await page.waitForTimeout(3500);
const line2 = page.getByText('2号线', { exact: true }).first();
if (await line2.count()) { await line2.click({ force: true }); await page.waitForTimeout(1000); }
await page.evaluate(() => window.__api.focusStation('st-25'));
await page.waitForTimeout(3000);
await page.addStyleTag({ content: `
  *, *::before, *::after { animation: none !important; transition: none !important; }
  html, body, #root { background: transparent !important; }
  .header, .control-dock, .attribution, .side-panel, .panel-rail, canvas, .labels-layer { visibility: hidden !important; }
`});
await page.waitForTimeout(500);
const card = page.locator('.station-card').first();
const box = await card.boundingBox();
console.log('box', box);
if (box) {
  await page.screenshot({
    path: OUT + '/station_card_jc.png',
    clip: { x: box.x, y: box.y, width: box.width, height: box.height },
    omitBackground: true,
    animations: 'disabled',
    timeout: 60000,
  });
  console.log('saved station_card');
}
await browser.close();
