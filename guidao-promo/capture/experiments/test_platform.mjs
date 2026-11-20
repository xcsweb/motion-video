import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
const OUT = '/workspace/guidao-promo/assets/3d/platform_test';
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 960, height: 540 }, deviceScaleFactor: 1 });
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => window.__viewer?.running && window.__api, null, { timeout: 120000 });
await page.waitForTimeout(2500);
await page.evaluate(() => {
  const v = window.__viewer;
  cancelAnimationFrame(v.raf); v.running = false; v.clock.paused = true;
  v.autoDegraded = true; v.applyQuality('medium'); v.renderer.setPixelRatio(1); v.resize();
  v.camera.fov = 52; v.camera.updateProjectionMatrix();
});

const S = 12942;
const cases = [
  { name: 'i_end_150_look_train', t: 28328, camBack: -80, lat: 5.8, look: 'train' },
  { name: 'j_end_150_look_track', t: 28328, camBack: -80, lat: 5.8, look: 'track' },
  { name: 'k_mid_100_look_train', t: 28336, camBack: -10, lat: 5.8, look: 'train' },
  { name: 'l_edge_100_look_train', t: 28336, camBack: -10, lat: 4.6, look: 'train' },
];
for (const c of cases) {
  const d = await page.evaluate(({ c, S }) => {
    const v = window.__viewer;
    const geo = v.transit.geometries.get('6');
    v.clock.timeSec = c.t;
    const trains = v.timetable.sample(c.t);
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
    const sm = { x: 0, y: 0, z: 0, tx: 0, tz: 0 };
    geo.sampleAt(S + c.camBack, sm);
    v.camera.position.set(sm.x + sm.tz * c.lat, sm.y + 3.0, sm.z - sm.tx * c.lat);
    if (c.look === 'train') {
      const pose = v.trains.poseOf(tr, v.transit.geometries);
      v.camera.lookAt(pose.x, pose.y + 1.6, pose.z);
    } else {
      v.camera.lookAt(sm.x + sm.tx * 120, sm.y + 1.2, sm.z + sm.tz * 120);
    }
    v.camera.updateProjectionMatrix();
    v.trains.setOverviewMode(false);
    v.trains.setLocalOnly(true);
    v.trains.setFollowedTrain(null);
    v.trains.update(trains, v.transit.geometries, v.camera);
    v.renderer.render(v.scene, v.camera);
    const trS = tr.direction === 0 ? tr.distance : geo.length - tr.distance;
    return { img: v.renderer.domElement.toDataURL('image/jpeg', 0.93), count: v.trains.visibleCount, trainS: Math.round(trS) };
  }, { c, S });
  fs.writeFileSync(path.join(OUT, `${c.name}.jpg`), Buffer.from(d.img.split(',')[1], 'base64'));
  console.log(c.name, 'vis=', d.count, 'trainS=', d.trainS);
}
await browser.close();
