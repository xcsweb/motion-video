import { chromium } from 'playwright';
import fs from 'node:fs';
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader','--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => window.__viewer?.running && typeof window.__api === 'object', null, { timeout: 120000 });
await page.waitForTimeout(3500);
await page.evaluate(() => {
  const v = window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('high'); v.renderer.setPixelRatio(1); v.resize();
  window.__grab=(exag, alt, dist, ty, angle)=>{
    v.clock.timeSec = 8*3600+30*60;
    v.api.setExaggeration(exag);
    v.camera.position.set(Math.cos(angle)*dist, alt, Math.sin(angle)*dist);
    v.cameraController.controls.target.set(0, ty, 0);
    v.cameraController.controls.update();
    const now=performance.now(); v.lastFrame=now-33.34;
    v.running=true; v.loop(now); v.running=false; cancelAnimationFrame(v.raf);
    return v.renderer.domElement.toDataURL('image/jpeg',0.95);
  };
});
const shots = [
  ['exag14_b', 1.4, 10000, 16000, 500, 2.3],
  ['exag18_b', 1.8, 12000, 17000, 800, 2.3],
  ['exag18_c', 1.8, 14000, 20000, 1000, 3.6],
];
for (const [name, exag, alt, dist, ty, ang] of shots) {
  const t0=Date.now();
  const d=await page.evaluate(([exag,alt,dist,ty,angle])=>window.__grab(exag,alt,dist,ty,angle),[exag,alt,dist,ty,ang]);
  fs.writeFileSync(`/workspace/guidao-promo/assets/3d/${name}.jpg`, Buffer.from(d.split(',')[1],'base64'));
  console.log(name, Date.now()-t0);
}
await browser.close();
