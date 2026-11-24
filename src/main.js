// Q2 Pod's site: a Shanling Q2 drawn live with three.js, its screen showing Q2 Pod's screens.
// The wheel works: push ‹‹ ›› (or Return for Home, Centre or ▶❚❚ for the next screen), turn it with a
// finger or the mouse, or scroll over it. Build: npm run build (bundles this file into app.js).
import {
  WebGLRenderer, Scene, PerspectiveCamera, Group, Mesh, Shape, ExtrudeGeometry, ShapeGeometry,
  CircleGeometry, CylinderGeometry, RingGeometry, LatheGeometry, MeshStandardMaterial, MeshBasicMaterial, CanvasTexture,
  SRGBColorSpace, PMREMGenerator, Raycaster, Vector2, Vector3, DirectionalLight, NeutralToneMapping,
  LinearMipmapLinearFilter,
} from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const SCREENS = [
  ['home', 'Home'],
  ['cover-flow', 'Cover Flow'],
  ['now-playing', 'Now Playing'],
  ['lyrics', 'Synced lyrics, full screen'],
  ['albums', 'Albums'],
  ['eq', 'Advanced EQ, with an imported headphone preset'],
  ['quick-settings', 'Quick Settings'],
  ['light', 'Light Mode'],
];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (s) => document.querySelector(s);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;

// The Q2 in millimetres (docs/hardware.md: 80 x 50 x 13.5 mm). The screen is 375:320.
// The body is matte black with soft sides; the glass is a slab that stands out from the front.
const W = 50, H = 80, D = 13.5, R = 10, BEVEL = 2.4, BEVEL_D = 2.8;
const GW = 44, GINSET = 3, GR = 6, DW = 40, DH = DW * 320 / 375, GH = DH + 4.4, GT = 1.1;
const GY = H / 2 - GINSET - GH / 2;                  // glass centre
const WY = (H / 2 - GINSET - GH - H / 2) / 2, WR = 15.5, CR = 5.8; // wheel centre, wheel and Centre radii
const FRONT = D / 2;

function rounded(w, h, r) {
  const s = new Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

// The wheel's face: its four marks, and a pushed quarter shown lighter for a moment.
function drawWheel(ctx, lit) {
  const n = ctx.canvas.width, c = n / 2;
  ctx.clearRect(0, 0, n, n);
  ctx.fillStyle = '#060607';
  ctx.fillRect(0, 0, n, n);
  if (lit) {
    const a = { right: 0, bottom: Math.PI / 2, left: Math.PI, top: -Math.PI / 2 }[lit];
    ctx.fillStyle = 'rgba(255,255,255,0.07)';
    ctx.beginPath(); ctx.moveTo(c, c); ctx.arc(c, c, c, a - Math.PI / 4, a + Math.PI / 4); ctx.fill();
  }
  ctx.strokeStyle = ctx.fillStyle = '#a9a9ae';
  ctx.lineWidth = n * 0.0085; ctx.lineCap = ctx.lineJoin = 'round';
  const u = n / 95, r = n * 0.36;
  const path = (pts) => { ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); };
  // Return, at the top
  ctx.beginPath(); ctx.arc(c + u, c - r + u, 4 * u, -Math.PI / 2, Math.PI / 2); ctx.stroke();
  path([[c + u, c - r - 3 * u], [c - 4 * u, c - r - 3 * u]]);
  path([[c - 2 * u, c - r - 5.5 * u], [c - 4.5 * u, c - r - 3 * u], [c - 2 * u, c - r - 0.5 * u]]);
  path([[c + u, c - r + 5 * u], [c - 2 * u, c - r + 5 * u]]);
  // ‹‹ and ››
  for (const s of [-1, 1]) for (const k of [0, 1]) {
    const x = c + s * r + s * (k * 3.4 - 1.7) * u;
    path([[x - s * 2.2 * u, c - 3.2 * u], [x + s * 1.2 * u, c], [x - s * 2.2 * u, c + 3.2 * u]]);
  }
  // ▷||, at the bottom, in lines as on the Q2
  path([[c - 3.6 * u, c + r - 3 * u], [c, c + r], [c - 3.6 * u, c + r + 3 * u]]);
  path([[c + 1.8 * u, c + r - 3 * u], [c + 1.8 * u, c + r + 3 * u]]);
  path([[c + 3.8 * u, c + r - 3 * u], [c + 3.8 * u, c + r + 3 * u]]);
}

function start() {
  const canvas = $('#q2'), stage = $('#stage'), hero = $('#hero'), bar = $('#screenbar'), cap = $('#cap');
  let renderer;
  try {
    renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (e) {
    return false;
  }
  const lowEnd = (navigator.hardwareConcurrency || 4) <= 4;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, lowEnd ? 1.5 : 2));
  renderer.toneMapping = NeutralToneMapping;
  renderer.outputColorSpace = SRGBColorSpace;

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  const key = new DirectionalLight(0xffffff, 1.4);
  key.position.set(-60, 120, 160);
  scene.add(key);
  const rim = new DirectionalLight(0xffffff, 1.6);
  rim.position.set(80, 140, -160);
  scene.add(rim);
  const camera = new PerspectiveCamera(26, 1, 10, 2000);

  const q2 = new Group();
  scene.add(q2);
  const matte = new MeshStandardMaterial({ color: 0x0f0f10, metalness: 0.15, roughness: 0.6, envMapIntensity: 0.7 });
  const body = new ExtrudeGeometry(rounded(W - 2 * BEVEL, H - 2 * BEVEL, R - BEVEL), {
    depth: D - 2 * BEVEL_D, bevelEnabled: true, bevelThickness: BEVEL_D, bevelSize: BEVEL, bevelSegments: 10, curveSegments: 24,
  });
  body.translate(0, 0, -(D - 2 * BEVEL_D) / 2);
  q2.add(new Mesh(body, matte));

  const glassGeo = new ExtrudeGeometry(rounded(GW - 0.8, GH - 0.8, GR - 0.4), {
    depth: GT - 0.8, bevelEnabled: true, bevelThickness: 0.4, bevelSize: 0.4, bevelSegments: 4, curveSegments: 20,
  });
  const glass = new Mesh(glassGeo, new MeshStandardMaterial({ color: 0x040405, metalness: 0, roughness: 0.07, envMapIntensity: 0.7 }));
  glass.position.set(0, GY, FRONT);
  q2.add(glass);
  const TOP = FRONT + GT - 0.4; // the glass slab runs from 0.4 mm inside the body to its front

  // The screen: a canvas the screenshots are drawn into, so one can fade into the next.
  const sc = document.createElement('canvas');
  sc.width = 750; sc.height = 640;
  const sctx = sc.getContext('2d');
  sctx.fillStyle = '#000'; sctx.fillRect(0, 0, sc.width, sc.height);
  const screenTex = new CanvasTexture(sc);
  screenTex.colorSpace = SRGBColorSpace;
  screenTex.minFilter = LinearMipmapLinearFilter;
  screenTex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const sg = new ShapeGeometry(rounded(DW, DH, 1.4), 8);
  const pos = sg.attributes.position, uv = sg.attributes.uv;
  for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i) / DW + 0.5, pos.getY(i) / DH + 0.5);
  const screenMat = new MeshBasicMaterial({ map: screenTex, toneMapped: false });
  screenMat.color.setScalar(0);
  const screen = new Mesh(sg, screenMat);
  screen.position.set(0, GY, TOP + 0.01);
  q2.add(screen);

  const wc = document.createElement('canvas');
  wc.width = wc.height = 1024;
  const wctx = wc.getContext('2d');
  drawWheel(wctx, null);
  const wheelTex = new CanvasTexture(wc);
  wheelTex.colorSpace = SRGBColorSpace;
  wheelTex.anisotropy = screenTex.anisotropy;
  // The wheel stands 0.35 mm out of the body, a little glossier than it, with a dark seam round it.
  const WH = 0.35;
  const wheel = new Mesh(new CircleGeometry(WR, 128),
    new MeshStandardMaterial({ map: wheelTex, metalness: 0.1, roughness: 0.42 }));
  wheel.position.set(0, WY, FRONT + WH);
  q2.add(wheel);
  const wheelSide = new Mesh(new CylinderGeometry(WR, WR, WH, 128, 1, true),
    new MeshStandardMaterial({ color: 0x060607, metalness: 0.1, roughness: 0.42 }));
  wheelSide.rotation.x = Math.PI / 2;
  wheelSide.position.set(0, WY, FRONT + WH / 2);
  q2.add(wheelSide);
  const seam = new Mesh(new RingGeometry(WR, WR + 0.3, 128), new MeshBasicMaterial({ color: 0x000000 }));
  seam.position.set(0, WY, FRONT + 0.01);
  q2.add(seam);

  // Centre: a low, matte dark-grey dome.
  const prof = [];
  for (let i = 0; i <= 12; i++) { const a = (i / 12) * (Math.PI / 2); prof.push(new Vector2(CR - 0.5 + 0.5 * Math.cos(a), 0.5 * Math.sin(a))); }
  for (let i = 1; i <= 12; i++) { const r = (CR - 0.5) * (1 - i / 12); prof.push(new Vector2(r, 0.5 + 0.3 * (1 - (r / (CR - 0.5)) ** 2))); }
  const centre = new Mesh(new LatheGeometry(prof, 64),
    new MeshStandardMaterial({ color: 0x1f1f21, metalness: 0.1, roughness: 0.5 }));
  centre.rotation.x = Math.PI / 2;
  centre.position.set(0, WY, FRONT + 0.3);
  q2.add(centre);

  // Screens: preload, then fade the next one in over the last.
  const imgs = SCREENS.map(([f]) => { const i = new Image(); i.src = `img/${f}.png`; return i; });
  let cur = 0, from = null, fadeT = 1;
  const draw = () => {
    sctx.globalAlpha = 1;
    sctx.imageSmoothingQuality = 'high';
    if (from && from.complete) sctx.drawImage(from, 0, 0, sc.width, sc.height);
    const to = imgs[cur];
    if (to.complete) { sctx.globalAlpha = from ? fadeT : 1; sctx.drawImage(to, 0, 0, sc.width, sc.height); }
    screenTex.needsUpdate = true;
  };
  imgs[0].onload = () => { draw(); invalidate(); };
  const go = (i) => {
    from = imgs[cur];
    cur = (i + SCREENS.length) % SCREENS.length;
    fadeT = 0;
    cap.textContent = SCREENS[cur][1];
    canvas.setAttribute('aria-label', 'Q2 Pod on a Shanling Q2: ' + SCREENS[cur][1]);
    invalidate();
  };

  // Pushes: the quarter lights, the Centre button goes in.
  let litPart = null, litUntil = 0, pressUntil = 0;
  const push = (part) => {
    const now = performance.now();
    if (part === 'centre') pressUntil = now + 140;
    else { litPart = part; litUntil = now + 160; drawWheel(wctx, part); wheelTex.needsUpdate = true; }
    go(part === 'left' ? cur - 1 : part === 'top' ? 0 : cur + 1);
  };

  // Scroll: the Q2 rises from its back, turns to face you, and its screen comes on.
  let pTarget = reduced ? 1 : 0, p = pTarget;
  const readScroll = () => {
    if (reduced) return;
    const r = stage.getBoundingClientRect(), room = stage.offsetHeight - innerHeight;
    pTarget = room > 0 ? clamp(-r.top / room) : 1;
    invalidate();
  };

  let visH = 100, startY = -30, startS = 0.56, startX = 0;
  const resize = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const t = Math.tan((camera.fov * Math.PI) / 360);
    const fitH = h < 560 ? 0.62 : 0.66, fitW = 0.78;
    const dist = Math.max(H / fitH, W / fitW / camera.aspect) / (2 * t);
    camera.position.set(0, 0, dist + FRONT);
    camera.updateProjectionMatrix();
    visH = 2 * dist * t;
    // At the top of the page, the Q2 stands whole in the room under the hero text.
    const pxmm = h / visH, below = hero.offsetTop + hero.offsetHeight + 24, room = h - below - Math.max(28, h * 0.05);
    if (w >= 900) {
      // Wide: the hero text is on the left, the Q2 stands on the right.
      startS = clamp(((h - 52) * 0.78) / (H * pxmm), 0.34, 0.72);
      startY = (h / 2 - (52 + (h - 52) / 2)) / pxmm;
      startX = (Math.min(w, 980) * 0.26) / pxmm;
    } else {
      startS = clamp((room * 0.9) / (H * pxmm), 0.34, 0.7);
      startY = (h / 2 - (below + room / 2)) / pxmm;
      startX = 0;
    }
    invalidate();
  };

  // A load-in, and a lean toward the mouse pointer of a few degrees until the Q2 settles, flat, facing you.
  let intro = reduced ? 1 : 0, introT0 = 0, lean = new Vector2(), leanTo = new Vector2();
  const pose = () => {
    const k = smooth(0, 0.62, p), i = 1 - Math.pow(1 - intro, 3);
    q2.rotation.set(lerp(-0.2, 0, k) + lean.y * (1 - k), lerp(-0.62, 0, k) + lean.x * (1 - k) - 0.35 * (1 - i), 0);
    q2.position.set(lerp(startX, 0, k), lerp(startY, 0, k) - 10 * (1 - i), 0);
    q2.scale.setScalar(lerp(startS, 1, k));
    screenMat.color.setScalar(smooth(0.36, 0.6, p));
    if (!reduced) {
      const h = 1 - smooth(0.02, 0.28, p);
      hero.style.opacity = h;
      hero.style.transform = `translateY(${-70 * (1 - h)}px) scale(${lerp(0.96, 1, h)})`;
      hero.style.visibility = h < 0.01 ? 'hidden' : 'visible';
      bar.style.opacity = smooth(0.58, 0.78, p);
    }
  };

  let raf = 0, onScreen = true;
  function invalidate() { if (!raf && onScreen) raf = requestAnimationFrame(frame); }
  let last = 0;
  function frame(now) {
    raf = 0;
    const dt = Math.min(64, now - (last || now)); last = now;
    let more = false;
    const dp = pTarget - p;
    if (Math.abs(dp) > 1e-4) { p += dp * (1 - Math.pow(0.0015, dt / 1000)); more = true; } else p = pTarget;
    if (intro < 1) { introT0 = introT0 || now; intro = Math.min(1, (now - introT0) / 1400); more = true; }
    const dl = leanTo.clone().sub(lean);
    if (dl.length() > 1e-4) { lean.addScaledVector(dl, 1 - Math.pow(0.002, dt / 1000)); more = true; }
    if (fadeT < 1) { fadeT = Math.min(1, fadeT + dt / 220); draw(); if (fadeT === 1) from = null; more = true; }
    if (litPart && now > litUntil) { litPart = null; drawWheel(wctx, null); wheelTex.needsUpdate = true; }
    if (litPart) more = true;
    centre.position.z = now < pressUntil ? FRONT : FRONT + 0.3;
    if (now < pressUntil) more = true;
    pose();
    renderer.render(scene, camera);
    canvas.classList.add('ready');
    if (more) invalidate(); else last = 0;
  }

  // Which part of the wheel a pointer is on, if any.
  const ray = new Raycaster(), ndc = new Vector2();
  const partAt = (x, y) => {
    const r = canvas.getBoundingClientRect();
    ndc.set(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects([centre, wheel], false)[0];
    if (!hit) return null;
    if (hit.object === centre) return { part: 'centre', angle: 0 };
    const l = wheel.worldToLocal(hit.point.clone());
    if (Math.hypot(l.x, l.y) < CR) return { part: 'centre', angle: 0 };
    const a = Math.atan2(l.y, l.x);
    const part = Math.abs(a) < Math.PI / 4 ? 'right' : Math.abs(a) > (3 * Math.PI) / 4 ? 'left' : a > 0 ? 'top' : 'bottom';
    return { part, angle: a };
  };
  const ready = () => p > 0.5;

  // Turn with a finger or the mouse: a step for each 36 degrees, clockwise to the next screen.
  const STEP = Math.PI / 5;
  let drag = null;
  canvas.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    if (ready() && partAt(t.clientX, t.clientY)) e.preventDefault();
  }, { passive: false });
  canvas.addEventListener('pointerdown', (e) => {
    if (!ready()) return;
    const at = partAt(e.clientX, e.clientY);
    if (!at) return;
    canvas.setPointerCapture(e.pointerId);
    drag = { at, angle: at.angle, turn: 0, moved: false };
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) {
      if (e.pointerType === 'mouse' && !reduced) {
        canvas.style.cursor = ready() && partAt(e.clientX, e.clientY) ? 'pointer' : '';
        const r = canvas.getBoundingClientRect();
        leanTo.set(((e.clientX - r.left) / r.width - 0.5) * 0.14, ((e.clientY - r.top) / r.height - 0.5) * 0.1);
        invalidate();
      }
      return;
    }
    if (drag.at.part === 'centre') return;
    const r = canvas.getBoundingClientRect();
    const c = new Vector2();
    // The angle from the wheel's centre, on the screen.
    const v = wheel.getWorldPosition(new Vector3()).project(camera);
    c.set((v.x + 1) / 2 * r.width + r.left, (1 - v.y) / 2 * r.height + r.top);
    const a = Math.atan2(c.y - e.clientY, e.clientX - c.x);
    if (drag.screen === undefined) { drag.screen = a; return; }
    let d = a - drag.screen;
    if (d > Math.PI) d -= 2 * Math.PI;
    if (d < -Math.PI) d += 2 * Math.PI;
    drag.screen = a;
    drag.turn += d;
    if (Math.abs(drag.turn) > 0.25) drag.moved = true;
    while (drag.turn <= -STEP) { drag.turn += STEP; go(cur + 1); }
    while (drag.turn >= STEP) { drag.turn -= STEP; go(cur - 1); }
  });
  const end = (e) => {
    if (!drag) return;
    if (!drag.moved && e.type === 'pointerup') push(drag.at.part);
    drag = null;
  };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', end);

  // Scroll over the wheel: the screens move, the page does not.
  let wheelAcc = 0;
  canvas.addEventListener('wheel', (e) => {
    if (!ready() || !partAt(e.clientX, e.clientY)) return;
    e.preventDefault();
    wheelAcc += e.deltaY + e.deltaX;
    while (wheelAcc >= 60) { wheelAcc -= 60; go(cur + 1); }
    while (wheelAcc <= -60) { wheelAcc += 60; go(cur - 1); }
  }, { passive: false });

  canvas.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { push('left'); e.preventDefault(); }
    if (e.key === 'ArrowRight' || e.key === 'Enter' || e.key === ' ') { push('right'); e.preventDefault(); }
  });

  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(([en]) => { onScreen = en.isIntersecting; if (onScreen) invalidate(); }).observe(stage);
  addEventListener('scroll', readScroll, { passive: true });
  addEventListener('resize', readScroll);
  readScroll();
  p = pTarget;
  resize();
  return true;
}

// Without WebGL: the flat drawing, with its screen and the same buttons.
function fallback() {
  document.documentElement.classList.add('flat');
  const img = $('#flat-screen'), cap = $('#cap');
  let cur = 0;
  const go = (i) => {
    cur = (i + SCREENS.length) % SCREENS.length;
    img.src = `img/${SCREENS[cur][0]}.png`;
    cap.textContent = SCREENS[cur][1];
  };
  $('#flat-prev').addEventListener('click', () => go(cur - 1));
  $('#flat-next').addEventListener('click', () => go(cur + 1));
}

// Headings, cards and pictures come up into place the first time they show.
function reveals() {
  const els = document.querySelectorAll('.reveal');
  if (reduced || !('IntersectionObserver' in window)) { els.forEach((e) => e.classList.add('in')); return; }
  const io = new IntersectionObserver((list) => list.forEach((en) => {
    if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
  }), { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });
  els.forEach((e) => io.observe(e));
}

// The latest release's version, date and size. The page works without them.
function release() {
  fetch('https://api.github.com/repos/DiamondBond/q2-pod/releases/latest')
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((j) => {
      const date = new Date(j.published_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
      $('#meta').textContent = `Version ${j.tag_name} · ${date}`;
    })
    .catch(() => {});
}

// The App Store's list is sources.list in the firmware's repo: "owner/repo Name"; [Games] starts the games.
function apps() {
  const lists = { Apps: $('#apps-list'), Games: $('#games-list') };
  fetch('https://raw.githubusercontent.com/DiamondBond/q2-pod/main/sources.list')
    .then((r) => (r.ok ? r.text() : Promise.reject()))
    .then((t) => {
      let sec = 'Apps';
      for (const line of t.split('\n')) {
        const s = line.trim();
        if (!s || s[0] === '#') continue;
        const m = s.match(/^\[(.+)\]$/);
        if (m) { sec = m[1]; continue; }
        const [repo, ...name] = s.split(/\s+/);
        const li = document.createElement('li'), a = document.createElement('a');
        a.href = `https://github.com/${repo}`;
        a.textContent = name.join(' ') || repo.split('/')[1].replace(/^q2-/, '');
        li.appendChild(a);
        (lists[sec] || lists.Apps).appendChild(li);
      }
    })
    .catch(() => {
      document.querySelectorAll('.store h3, .store .chips').forEach((e) => (e.hidden = true));
    });
}

if (!start()) fallback();
reveals();
release();
apps();
