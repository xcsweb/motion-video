import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = '/workspace/guidao-promo/assets/3d/line6_platform_hd';
fs.mkdirSync(OUT, { recursive: true });
const S = 12942;
const T0 = 28328;
const DT = 0.3;
const N = 66;

const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => window.__viewer?.running && window.__api, null, { timeout: 120000 });
await page.waitForTimeout(2500);
await page.evaluate(() => {
  const v = window.__viewer;
  cancelAnimationFrame(v.raf); v.running = false; v.clock.paused = true;
  v.autoDegraded = true; v.applyQuality('medium'); v.renderer.setPixelRatio(1); v.resize();
  v.camera.fov = 52; v.camera.updateProjectionMatrix();
});

for (let i = 0; i < N; i++) {
  const t = T0 + i * DT;
  const d = await page.evaluate(({ t, S }) => {
    const v = window.__viewer;
    const geo = v.transit.geometries.get('6');
    v.clock.timeSec = t;
    const trains = v.timetable.sample(t);
    const tr = trains.find((x) => x.id === '6-1-23040');
    v.tunnel.update(geo, S + 80, 1, true);
    v.tunnel.group.visible = true;
    v.transit.group.visible = false;
    v.transit.labelGroup.visible = false;
    v.stationDetail.group.visible = false;
    v.buildings.setVisible(false);
    v.water.setVisible(false);
    v.vegetation.setVisible(false);
    v.terrain.group.visible = true;
    v.portals.group.visible = true;

    const camS = S - 10;
    const sm = { x: 0, y: 0, z: 0, tx: 0, tz: 0 };
    geo.sampleAt(camS, sm);
    v.camera.position.set(sm.x + sm.tz * 4.6, sm.y + 3.0, sm.z - sm.tx * 4.6);
    geo.sampleAt(S + 70, sm);
    v.camera.lookAt(sm.x, sm.y + 2.1, sm.z);
    v.camera.updateProjectionMatrix();

    v.trains.setOverviewMode(false);
    v.trains.setLocalOnly(true);
    v.trains.setFollowedTrain(null);
    v.trains.update(trains, v.transit.geometries, v.camera);
    v.renderer.render(v.scene, v.camera);
    return v.renderer.domElement.toDataURL('image/jpeg', 0.93);
  }, { t, S });
  fs.writeFileSync(path.join(OUT, `f_${String(i).padStart(4, '0')}.jpg`), Buffer.from(d.split(',')[1], 'base64'));
  if (i % 10 === 0) console.log(i, 't=', t.toFixed(1));
}
console.log('done');
await browser.close();
