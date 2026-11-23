/**
 * 从 Taro 小程序 H5 构建产物截取宣传片用界面（430×932 @2x）。
 * 前置：cd /tmp/zhentu/miniapp && npm run build:h5，然后在本目录跑静态服务：
 *   python3 -m http.server 8899 --bind 127.0.0.1   （cwd = /tmp/zhentu/miniapp/dist）
 * 运行：node capture_h5.mjs
 */
import { chromium } from '/workspace/zhentu-promo/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';

const BASE = 'http://127.0.0.1:8899/';
const IMG = '/workspace/zhentu-promo/assets/img';
const OUT = '/workspace/zhentu-promo/assets/screens';

const imageRules = [
  [/bioluminescence|蓝眼泪|glowing with blue/i, 'bioluminescence.jpg'],
  [/Pingtan|beach|coast|island|wind turbine|sea|bay/i, 'pingtan.jpg'],
  [/Sideng|dusk/i, 'shaxi_dusk.jpg'],
  [/morning mist|valley/i, 'shaxi_morning.jpg'],
  [/Shaxi/i, 'shaxi_cover.jpg'],
  [/Nuodeng/i, 'nuodeng.jpg'],
  [/hillside Bai/i, 'bai_village.jpg'],
  [/hams/i, 'hams.jpg'],
  [/ticket|receipt|price|fare/i, 'evidence_ticket_c.jpg'],
  [/map|location|alley/i, 'map_thumb.jpg'],
  [/hotel|room price|booking|房价/i, 'evidence_price_board_c.jpg'],
  [/bus stop/i, 'pingtan.jpg'],
  [/market|mushroom|food|dish|banquet|meal|cafe|shopfront|notice/i, 'shaxi_dusk.jpg'],
];
function pickImage(url) {
  let prompt = '';
  try { prompt = new URL(url).searchParams.get('prompt') || ''; } catch {}
  for (const [re, file] of imageRules) if (re.test(prompt)) return path.join(IMG, file);
  return path.join(IMG, 'shaxi_cover.jpg');
}

const ICON_DIR = '/tmp/zhentu/miniapp/src/assets';
const ICONS = {};
for (const name of ['tab-discover', 'tab-discover-on', 'tab-trips', 'tab-trips-on', 'tab-vote', 'tab-vote-on', 'tab-profile', 'tab-profile-on']) {
  ICONS[name] = `data:image/png;base64,${fs.readFileSync(path.join(ICON_DIR, `${name}.png`)).toString('base64')}`;
}

// 小程序 custom tabBar 在 H5 不渲染，这里按 750 设计稿等比补上，保证截图是完整界面
async function injectTabBar(page, active) {
  await page.evaluate(({ active, icons }) => {
    document.getElementById('shot-tabbar')?.remove();
    const r = window.innerWidth / 750;
    const tabs = [
      ['发现', 'tab-discover'],
      ['行程', 'tab-trips'],
      ['核实', 'tab-vote'],
      ['我的', 'tab-profile'],
    ];
    const bar = document.createElement('div');
    bar.id = 'shot-tabbar';
    Object.assign(bar.style, {
      position: 'fixed', left: '0', right: '0', bottom: '0', zIndex: '9999',
      height: `${104 * r}px`, display: 'flex', alignItems: 'flex-end',
      background: '#fffdf8', borderTop: '1px solid #e8e1d2',
    });
    const item = (label, icon, on, index) => {
      const w = document.createElement('div');
      Object.assign(w.style, { flex: '1', height: `${104 * r}px`, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' });
      const im = document.createElement('img');
      im.src = icons[`${icon}${on ? '-on' : ''}`];
      Object.assign(im.style, { width: `${46 * r}px`, height: `${46 * r}px`, objectFit: 'contain' });
      const t = document.createElement('div');
      t.textContent = label;
      Object.assign(t.style, {
        marginTop: `${4 * r}px`, fontSize: `${18 * r}px`, lineHeight: '1.2',
        color: on ? '#0e7c66' : '#7c837f', fontWeight: on ? '700' : '400',
      });
      w.append(im, t);
      return w;
    };
    bar.append(item(tabs[0][0], tabs[0][1], active === 0));
    bar.append(item(tabs[1][0], tabs[1][1], active === 1));
    const plus = document.createElement('div');
    Object.assign(plus.style, { flex: '1', height: `${104 * r}px`, display: 'flex', alignItems: 'center', justifyContent: 'center' });
    const pill = document.createElement('div');
    pill.textContent = '＋';
    Object.assign(pill.style, {
      width: `${92 * r}px`, height: `${60 * r}px`, marginTop: `${-16 * r}px`, borderRadius: `${30 * r}px`,
      background: 'linear-gradient(135deg,#d8f26a,#b6e34d)', color: '#1c2415',
      fontSize: `${38 * r}px`, fontWeight: '800', lineHeight: `${60 * r}px`, textAlign: 'center',
      boxShadow: '0 8px 22px rgba(18,26,20,0.24)',
    });
    plus.append(pill);
    bar.append(plus);
    bar.append(item(tabs[2][0], tabs[2][1], active === 2));
    bar.append(item(tabs[3][0], tabs[3][1], active === 3));
    document.body.append(bar);
  }, { active, icons: ICONS });
}

async function settle(page, ms = 1600) {
  await page.waitForTimeout(ms);
  await page.evaluate(() => Promise.all(
    [...document.images].map((img) => img.decode?.().catch(() => {}) ?? Promise.resolve())
  )).catch(() => {});
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log('shot', name);
}

const browser = await chromium.launch({
  channel: 'chromium',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-color-profile=srgb', '--font-render-hinting=none'],
});
const page = await browser.newPage({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2 });
page.on('pageerror', (e) => console.log('pageerror', String(e).slice(0, 300)));
await page.route('https://trae-api-cn.mchost.guru/**', (route) => {
  const file = pickImage(route.request().url());
  if (!fs.existsSync(file)) return route.abort();
  return route.fulfill({
    status: 200,
    headers: { 'content-type': 'image/jpeg', 'access-control-allow-origin': '*' },
    body: fs.readFileSync(file),
  });
});
const cdp = await page.context().newCDPSession(page);
async function swipeUp(times = 1) {
  for (let n = 0; n < times; n += 1) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 215, y: 780, id: 1 }] });
    for (let i = 1; i <= 10; i += 1) {
      await cdp.send('Input.dispatchTouchEvent', {
        type: 'touchMove',
        touchPoints: [{ x: 215, y: 780 - (540 * i) / 10, id: 1 }],
      });
      await page.waitForTimeout(16);
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await page.waitForTimeout(900);
  }
}

const go = async (hash) => {
  await page.goto(BASE + hash, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
  await page.evaluate(() => document.getElementById('shot-tabbar')?.remove()).catch(() => {});
  await settle(page);
};

// 01 / 03 发现页：首页 + 滑到第三张
await go('#/pages/discover/index');
await injectTabBar(page, 0);
await shot(page, '01_home');
await swipeUp(1);
await injectTabBar(page, 0);
await shot(page, '02_home_card2');
await swipeUp(1);
await injectTabBar(page, 0);
await shot(page, '03_home_card3');

// 04 目的地详情抽屉
await go('#/pages/discover/index');
await page.getByText('查看详情', { exact: false }).first().click({ timeout: 8000 }).catch((e) => console.log('detail click', e.message));
await settle(page, 1400);
await shot(page, '04_destination');

// 09 消息通知
await go('#/pages/profile/index');
await injectTabBar(page, 3);
await page.getByText('消息通知', { exact: false }).first().click({ timeout: 8000 }).catch((e) => console.log('notice click', e.message));
await settle(page, 1200);
await shot(page, '09_messages');

// 05 / 06 一条待核实信息卡
await go('#/pages/fact/index?id=sx-4');
await shot(page, '05_fact_pending');
await shot(page, '06_vote_sheet');

// 10-13 排行程
await go('#/pages/plan/index?destId=shaxi&days=2');
await shot(page, '10_plan_step1');
await page.evaluate(() => { document.body.style.transform = 'translateY(-96px)'; });
await settle(page, 400);
await page.getByText('美食', { exact: true }).first().click({ timeout: 5000 }).catch((e) => console.log('food', e.message));
await settle(page, 700);
await shot(page, '11_plan_step2');
await page.evaluate(() => { document.body.style.transform = ''; });
await settle(page, 500);
await page.getByText('生成 3 个方案', { exact: false }).first().click({ timeout: 6000 }).catch((e) => console.log('generate', e.message));
await settle(page, 1400);
await shot(page, '12_plan_step3');

// 13 三个版本：行程列表天然并列经典 / 小众 / 慢住
await go('#/pages/trips/index');
await injectTabBar(page, 1);
await shot(page, '13_variants');

// 14 行程：出发前检查
await go('#/pages/trip/index?id=trip-classic');
await page.getByText('行程工具', { exact: false }).first().click({ timeout: 8000 }).catch((e) => console.log('tools', e.message));
await settle(page, 800);
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.tool-item')].find((node) => node.innerText.includes('出发前检查'));
  el?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
});
await settle(page, 900);
await shot(page, '14_trip');

// 15 路线播放
await go('#/pages/play/index?tripId=trip-classic');
await shot(page, '15_play');

// 17 听证
await go('#/pages/vote/index');
await injectTabBar(page, 2);
await page.getByText('出行听证', { exact: false }).first().click({ timeout: 8000 }).catch((e) => console.log('hearing', e.message));
await settle(page, 1200);
await shot(page, '17_hearing');

// 18 我的
await go('#/pages/profile/index');
await injectTabBar(page, 3);
await shot(page, '18_profile');

await browser.close();
console.log('done');
