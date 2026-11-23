#!/usr/bin/env node
/**
 * 真途宣传片 · 原型状态采集
 *
 * 1. 本地静态服务 zhentu 原型（默认 ../zhentu，可用 ZT_ROOT 覆盖）
 * 2. Playwright 打开 430×932，2x 截图
 * 3. 把原型里在线生成的图片请求，替换成本地固定素材，保证每次截图一致
 *
 * 产物：assets/screens/*.png 与 capture/manifest.json
 */
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const ZT_ROOT = process.env.ZT_ROOT || path.resolve(ROOT, '..', 'zhentu');
const OUT = path.join(ROOT, 'assets', 'screens');
const IMG = path.join(ROOT, 'assets', 'img');
const PORT = 8765;
fs.mkdirSync(OUT, { recursive: true });

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml' };

const server = http.createServer((req, res) => {
  const urlPath = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  let file = path.join(ZT_ROOT, urlPath === '/' ? 'index.html' : urlPath);
  if (!file.startsWith(ZT_ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404); res.end('not found'); return;
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
  fs.createReadStream(file).pipe(res);
});
await new Promise(r => server.listen(PORT, '127.0.0.1', r));

// 原型里的图片 prompt -> 本地素材
const imageRules = [
  [/bioluminescence|蓝眼泪/i, 'bioluminescence.jpg'],
  [/Pingtan|beach|coast|island|wind turbine|sea|bay/i, 'pingtan.jpg'],
  [/Sideng|dusk/i, 'shaxi_dusk.jpg'],
  [/morning mist/i, 'shaxi_morning.jpg'],
  [/Shaxi/i, 'shaxi_cover.jpg'],
  [/Nuodeng/i, 'nuodeng.jpg'],
  [/hillside Bai/i, 'bai_village.jpg'],
  [/hams/i, 'hams.jpg'],
  [/ticket|receipt|price|fare/i, 'evidence_ticket_c.jpg'],
  [/map|location|alley/i, 'map_thumb.jpg'],
  [/hotel|room price|booking/i, 'evidence_price_board_c.jpg'],
  [/bus stop/i, 'pingtan.jpg'],
  [/market|mushroom|food|dish|banquet|meal|cafe|shopfront|notice/i, 'shaxi_dusk.jpg'],
];
function pickImage(url) {
  let prompt = '';
  try { prompt = new URL(url).searchParams.get('prompt') || ''; } catch {}
  for (const [re, file] of imageRules) if (re.test(prompt)) return path.join(IMG, file);
  return path.join(IMG, 'shaxi_cover.jpg');
}

const browser = await chromium.launch({ channel: 'chromium', args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none', '--force-color-profile=srgb'] });
const page = await browser.newPage({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2 });
const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push(String(e)));

await page.route('https://trae-api-cn.mchost.guru/**', route => {
  const file = pickImage(route.request().url());
  if (!fs.existsSync(file)) return route.abort();
  return route.fulfill({ status: 200, headers: { 'content-type': 'image/jpeg', 'access-control-allow-origin': '*' }, body: fs.readFileSync(file) });
});

const manifest = [];
async function shot(name) {
  await page.waitForTimeout(350);
  await page.screenshot({ path: path.join(OUT, name + '.png') });
  manifest.push({ name, at: new Date().toISOString() });
  console.log('shot', name);
}
async function go(hash, wait = 750) {
  await page.evaluate(h => { location.hash = h; }, hash);
  await page.waitForTimeout(wait);
}

await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(2500);

// 01–03 发现页
await shot('01_home');
for (let i = 1; i <= 2; i++) {
  await page.evaluate(step => {
    const l = document.getElementById('feedList');
    if (l) l.scrollTo({ top: l.clientHeight * step, behavior: 'instant' });
  }, i);
  await page.waitForTimeout(900);
  await shot(`0${i + 1}_home_card${i + 1}`);
}

// 04 目的地页
await go('#/destination/shaxi', 1200);
await shot('04_destination');

// 05–09 信息卡 + 投票（sx-4：5/6，投票后正好 6/6）
await go('#/fact/sx-4', 1000);
await shot('05_fact_pending');
await page.click('[data-act="vote-real-open"]');
await page.waitForTimeout(700);
await shot('06_vote_sheet');
await page.click('[data-act="vote-submit"]');
await page.waitForTimeout(900);
await shot('07_vote_success');
await page.click('[data-act="vote-done"]');
await page.waitForTimeout(900);
await shot('08_fact_after');

// 10 消息中心
await go('#/messages', 900);
await shot('09_messages');

// 11–13 行程向导
await go('#/plan', 800);
await shot('10_plan_step1');
await page.click('[data-act="plan-next"]');
await page.waitForTimeout(600);
await shot('11_plan_step2');
await page.click('[data-act="plan-next"]');
await page.waitForTimeout(600);
await shot('12_plan_step3');

// 14 三个版本
await page.click('[data-act="plan-generate"]');
await page.waitForTimeout(2600);
await shot('13_variants');

// 15–16 行程详情 + 路线播放
await page.locator('[data-act="variant-use"]').first().click();
await page.waitForTimeout(3200);
await shot('14_trip');
const playBtn = page.locator('.day-play-btn').first();
if (await playBtn.count()) {
  await playBtn.click();
  await page.waitForTimeout(900);
  const pause = page.locator('#playToggle');
  if (await pause.count()) { try { await pause.click(); } catch {} }
  await page.waitForTimeout(400);
  await shot('15_play');
  const close = page.locator('[data-act="sheet-close"]');
  if (await close.count()) { try { await close.click(); } catch {} }
}

// 17–18 核实与听证
await go('#/vote', 900);
await shot('16_vote');
await page.click('[data-act="vote-mode"][data-val="hearing"]');
await page.waitForTimeout(700);
await shot('17_hearing');

// 19 我的
await go('#/profile', 800);
await shot('18_profile');

fs.writeFileSync(path.join(ROOT, 'capture', 'manifest.json'), JSON.stringify({ ztRoot: ZT_ROOT, viewport: '430x932@2x', shots: manifest, errors: errors.slice(0, 20) }, null, 2));
console.log('errors', errors.slice(0, 6));
await browser.close();
server.close();
