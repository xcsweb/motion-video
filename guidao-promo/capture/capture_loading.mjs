import { chromium } from 'playwright';
import fs from 'node:fs';
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader','--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.route('**/data/cq/**', async route => {
  await new Promise(r => setTimeout(r, 5000));
  await route.continue();
});
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
for (let i=0;i<3;i++){
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `/workspace/guidao-promo/assets/ui/loading_0${i+1}.png`, timeout: 60000 });
  console.log('saved loading', i+1);
}
await browser.close();
