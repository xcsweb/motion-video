/* 确定性渲染工具：页面只依赖传入的 t，不使用 requestAnimationFrame */
window.RG = {
  clamp: (v, a = 0, b = 1) => Math.max(a, Math.min(b, v)),
  lerp: (a, b, p) => a + (b - a) * p,
  smooth: (p) => { p = Math.max(0, Math.min(1, p)); return p * p * (3 - 2 * p); },
  easeOut: (p) => 1 - Math.pow(1 - Math.max(0, Math.min(1, p)), 3),
  easeIn: (p) => Math.pow(Math.max(0, Math.min(1, p)), 2.2),
  /* 稳定哈希：同一输入永远同一输出 */
  hash: (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); },
  hash2: (x, y) => { const n = Math.sin(x * 127.1 + y * 311.7 + 74.7) * 43758.5453; return n - Math.floor(n); },
  wob: (t, seed = 0, amp = 1) =>
    Math.sin(t * 2.1 + seed * 3.7) * .5 + Math.sin(t * 5.3 + seed * 9.1) * .3 + Math.sin(t * 11.7 + seed) * .2 * amp,
  pad: (n, w = 2) => String(Math.floor(n)).padStart(w, '0'),
  fmt: (t, fps = 30) => {
    const f = Math.floor(t * fps), s = Math.floor(f / fps);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}:${String(f % fps).padStart(2, '0')}`;
  },
  pick: (arr, p) => arr[Math.max(0, Math.min(arr.length - 1, Math.floor(p * arr.length)))],
};

window.__boot = function (seek, duration) {
  const stage = document.getElementById('stage');
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  stage.style.transform = `scale(${scale})`;
  window.__duration = duration;

  const q = new URLSearchParams(location.search);
  const t = q.has('t') ? parseFloat(q.get('t')) : null;
  const run = (tt) => { try { seek(Math.max(0, Math.min(duration, tt))); } catch (e) { console.error(e); } };
  window.__seek = run;

  if (t !== null) {
    run(t);
    const imgs = Array.from(document.images).map(i => i.decode ? i.decode().catch(() => {}) : Promise.resolve());
    Promise.all([document.fonts.ready, ...imgs]).then(() => { window.__ready = true; });
  } else {
    const t0 = performance.now();
    const loop = () => { run(((performance.now() - t0) / 1000) % duration); requestAnimationFrame(loop); };
    run(0); loop();
  }
};
