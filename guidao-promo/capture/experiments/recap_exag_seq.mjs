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
  window.__grab=(exag)=>{
    const alt=10000, dist=16000, ty=600, angle=2.3;
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
for (const [name, exag] of [['exag10_c',1.0],['exag14_c',1.4],['exag18_c',1.8]]) {
  const t0=Date.now();
  const d=await page.evaluate((e)=>window.__grab(e), exag);
  fs.writeFileSync(`/workspace/guidao-promo/assets/3d/${name}.jpg`, Buffer.from(d.split(',')[1],'base64'));
  console.log(name, Date.now()-t0);
}
await browser.close();
