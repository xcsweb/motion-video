import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = '/workspace/guidao-promo/assets/3d';
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => window.__viewer?.running && typeof window.__api === 'object', null, { timeout: 120000 });
await page.waitForTimeout(4000);

await page.evaluate(() => {
  const v = window.__viewer;
  cancelAnimationFrame(v.raf);
  v.running = false;
  v.clock.paused = true;
  v.autoDegraded = true;
  v.applyQuality('high');
  v.renderer.setPixelRatio(1);
  v.resize();

  window.__grab = (name, pose) => {
    const { x = 0, y = 200, z = 0, dist = 16000, alt = 9000, angle = 2.3, line = null, time = 8 * 3600 + 30 * 60, exag = 1 } = pose;
    v.clock.timeSec = time;
    v.api.setExaggeration(exag);
    v.transit.setSelected(line);
    if (line) {
      const info = v.transit.getLineBounds(line);
      if (info) {
        v.camera.position.set(info.center[0] + Math.cos(angle) * dist, alt, info.center[1] + Math.sin(angle) * dist);
        v.cameraController.controls.target.set(info.center[0], y, info.center[1]);
        v.cameraController.controls.update();
      }
    } else {
      v.camera.position.set(x + Math.cos(angle) * dist, alt, z + Math.sin(angle) * dist);
      v.cameraController.controls.target.set(x, y, z);
      v.cameraController.controls.update();
    }
    const now = performance.now();
    v.lastFrame = now - 33.34;
    v.running = true;
    v.loop(now);
    v.running = false;
    cancelAnimationFrame(v.raf);
    const data = v.renderer.domElement.toDataURL('image/jpeg', 0.95);
    return data;
  };
});

const poses = [
  ['hero_a', { dist: 16000, alt: 9000, angle: 2.3 }],
  ['hero_b', { dist: 13000, alt: 7000, angle: 0.5 }],
  ['hero_c', { dist: 11000, alt: 6500, angle: 3.9, x: -2000, z: 3000 }],
  ['line2', { line: '2', dist: 8000, alt: 5000, angle: 2.0 }],
  ['line6', { line: '6', dist: 10000, alt: 7000, angle: 5.2 }],
  ['exag10', { dist: 16000, alt: 9000, angle: 2.3, exag: 1.0 }],
  ['exag18', { dist: 16000, alt: 9000, angle: 2.3, exag: 1.8 }],
  ['night', { dist: 16000, alt: 9000, angle: 2.3, time: 20 * 3600 + 30 * 60 }],
  ['river', { dist: 9000, alt: 4500, angle: 1.2 }],
  ['hook3d', { dist: 14000, alt: 11000, angle: 5.8 }],
];

for (const [name, pose] of poses) {
  const t0 = Date.now();
  const data = await page.evaluate(([n, p]) => window.__grab(n, p), [name, pose]);
  fs.writeFileSync(path.join(OUT, `${name}.jpg`), Buffer.from(data.split(',')[1], 'base64'));
  console.log(name, Date.now() - t0, 'ms');
}

// 3s orbit clip at 1280x720 low quality, 30fps
await page.setViewportSize({ width: 1280, height: 720 });
await page.evaluate(() => {
  const v = window.__viewer;
  v.applyQuality('low');
  v.renderer.setPixelRatio(1);
  v.resize();
  v.buildings.group.visible = false;
  v.vegetation.group.visible = false;
});
const frames = 90;
const clipDir = path.join(OUT, 'orbit_a');
fs.mkdirSync(clipDir, { recursive: true });
const t0 = Date.now();
for (let i = 0; i < frames; i++) {
  const data = await page.evaluate((i) => {
    const v = window.__viewer;
    const angle = 2.15 + i * 0.0025;
    const dist = 16000;
    const alt = 9000 + Math.sin(i / 30) * 300;
    v.clock.timeSec = 8 * 3600 + 30 * 60 + i * 0.04;
    v.camera.position.set(Math.cos(angle) * dist, alt, Math.sin(angle) * dist);
    v.cameraController.controls.target.set(0, 200, 0);
    v.cameraController.controls.update();
    const now = performance.now();
    v.lastFrame = now - 33.34;
    v.running = true;
    v.loop(now);
    v.running = false;
    cancelAnimationFrame(v.raf);
    return v.renderer.domElement.toDataURL('image/jpeg', 0.92);
  }, i);
  fs.writeFileSync(path.join(clipDir, `f_${String(i).padStart(4, '0')}.jpg`), Buffer.from(data.split(',')[1], 'base64'));
  if (i % 15 === 0) console.log('orbit', i, '/', frames, ((Date.now() - t0) / 1000).toFixed(0) + 's');
}
console.log('orbit done', ((Date.now() - t0) / 1000).toFixed(0) + 's');
await browser.close();
