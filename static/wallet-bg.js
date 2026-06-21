(function () {
  'use strict';
  const canvas = document.getElementById('bgCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const DPR = Math.min(window.devicePixelRatio || 1, 2);

  const GAP = 96;          // 网格间距(不密不疏)
  const R = 20;            // 徽章半高(恢复成之前合适的大小)
  const BASE = 0.05;       // 静态透明度(很低, 隐约可见)
  const HOVER = 0.32;      // 鼠标附近最大透明度
  const RADIUS = 180;      // 鼠标影响半径(px)

  let pts = [];
  let W = 0, H = 0;
  const mouse = { x: -9999, y: -9999, on: false };

  function build() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    pts = [];
    let row = 0;
    for (let y = GAP * 0.5; y < H + R; y += GAP, row++) {
      const off = (row % 2) ? GAP / 2 : 0;
      for (let x = GAP * 0.5 + off; x < W + R; x += GAP) {
        const jx = (Math.random() - 0.5) * 4;
        const jy = (Math.random() - 0.5) * 4;
        const s = 0.75 + Math.random() * 0.5;
        pts.push({ x: x + jx, y: y + jy, s });
      }
    }
  }

  function diamond(x, y, r, alpha) {
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r * 0.72, y - r * 0.28);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r * 0.72, y - r * 0.28);
    ctx.closePath();
    ctx.moveTo(x - r * 0.72, y - r * 0.28);
    ctx.lineTo(x + r * 0.72, y - r * 0.28);
    ctx.moveTo(x - r * 0.34, y - r * 0.28);
    ctx.lineTo(x, y + r);
    ctx.moveTo(x + r * 0.34, y - r * 0.28);
    ctx.lineTo(x, y + r);
    ctx.strokeStyle = 'rgba(23,23,23,' + alpha + ')';
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  let raf = null;
  function draw() {
    ctx.clearRect(0, 0, W, H);
    for (const p of pts) {
      let a = BASE;
      if (mouse.on) {
        const dx = p.x - mouse.x, dy = p.y - mouse.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < RADIUS) {
          const t = 1 - d / RADIUS;
          a = BASE + (HOVER - BASE) * (t * t);
        }
      }
      diamond(p.x, p.y, R * p.s, a);
    }
    raf = null;
  }
  function schedule() { if (!raf) raf = requestAnimationFrame(draw); }

  window.addEventListener('mousemove', (e) => {
    mouse.x = e.clientX; mouse.y = e.clientY; mouse.on = true; schedule();
  }, { passive: true });
  window.addEventListener('mouseleave', () => { mouse.on = false; schedule(); });
  window.addEventListener('touchmove', (e) => {
    if (e.touches[0]) { mouse.x = e.touches[0].clientX; mouse.y = e.touches[0].clientY; mouse.on = true; schedule(); }
  }, { passive: true });
  window.addEventListener('touchend', () => { mouse.on = false; schedule(); });

  let rz = null;
  window.addEventListener('resize', () => {
    clearTimeout(rz); rz = setTimeout(() => { build(); draw(); }, 150);
  });

  build();
  draw();
})();
