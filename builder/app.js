// Room Builder - the builder page.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { buildRoom, makeItem, applyItem, footprint, lightRoom, roomFrame, b2t, span, FACING, T, outsideSphere, outsideHdriId } from './scene.js';

// ================================================================== state
// append() that skips null/false, so panels can include optional parts inline
const _append = Element.prototype.append;
Element.prototype.append = function (...k) { return _append.apply(this, k.flat(Infinity).filter(x => x != null && x !== false)); };
const $ = s => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'html') e.innerHTML = v;
    else if (v === true) e.setAttribute(k, '');
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } } };
const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const uid = p => p + '-' + Math.random().toString(36).slice(2, 7);
const r2 = v => Math.round(v * 100) / 100;
const fmtTime = s => { s = Math.max(0, Math.round(s)); if (s < 90) return `${s} s`; const m = Math.round(s / 60); return m < 90 ? `${m} min` : `${(m / 60).toFixed(1)} h`; };

const QUAL = { draft: '2048 × 1024, quick check', standard: '6144 × 3072, the Igloo standard', high: '8192 × 4096, slow' };
const WALLNAMES = ['north', 'east', 'south', 'west'];
const FEATURE_LABEL = { alcove: 'Alcove', door: 'Door', window: 'Window', arch: 'Arch', kitchenette: 'Kitchenette' };

let presets = [];
let outsideCfg = { views: [], style_default: {} };
let outsideMesh = null;
let catalogue = [];                      // model.json entries
const catById = id => catalogue.find(m => m.id === id);
let spec = null;
let mode = store.get('rb_mode', 'simple');
let tab = 'room';
let sel = null;                           // {kind: 'item'|'feature'|'view', id}
let undoStack = [], redoStack = [];
let floorLimit = store.get('rb_floor_limit', 0.5);
let lastLibrary = [];

function blankSpec(room) {
  const r = room || presets[0] || { id: 'custom', width: 6, depth: 5, height: 2.4, eye: 1.12, projected: { walls: true, floor: true, ceiling: false } };
  return {
    version: 1, name: 'New room',
    room: { preset: r.id || 'custom', width: r.width, depth: r.depth, height: r.height, eye: r.eye ?? 1.12, projected: r.projected || { walls: true, floor: true, ceiling: false } },
    style: 'modern', lighting: 'day', features: [], items: [], views: [{ name: 'centre', x: 0, y: 0, yaw: 0 }], render: { quality: 'standard' },
  };
}

function snapshot() { return JSON.stringify(spec); }
let changeTimer = null, lastSnap = null;
// call after any change. structural = rebuild the panel too
function changed({ structural = false, rebuild = true, items = false } = {}) {
  if (lastSnap !== null && lastSnap !== snapshot()) { undoStack.push(lastSnap); if (undoStack.length > 120) undoStack.shift(); redoStack = []; }
  lastSnap = snapshot();
  if (rebuild) rebuildRoom();
  if (items) syncItems();
  updateWarnings();
  if (structural) renderTab();
  clearTimeout(changeTimer);
  changeTimer = setTimeout(() => { store.set('rb_draft', spec); api('/api/live', { spec }).catch(() => {}); }, 250);
  $('#roomName').value = spec.name || '';
}
function undo() { if (!undoStack.length) return; redoStack.push(snapshot()); spec = JSON.parse(undoStack.pop()); lastSnap = snapshot(); afterLoad(false); }
function redo() { if (!redoStack.length) return; undoStack.push(snapshot()); spec = JSON.parse(redoStack.pop()); lastSnap = snapshot(); afterLoad(false); }
function loadSpec(s, resetUndo = true) {
  spec = s; spec.features ||= []; spec.items ||= []; spec.views ||= [{ name: 'centre', x: 0, y: 0, yaw: 0 }];
  spec.render ||= { quality: 'standard' };
  for (const f of spec.features) f.id ||= uid(f.type);
  for (const i of spec.items) i.id ||= uid('item');
  if (resetUndo) { undoStack = []; redoStack = []; }
  lastSnap = snapshot(); sel = null; afterLoad(true);
}
function afterLoad(fit) {
  rebuildRoom(); syncItems(true); updateWarnings(); renderTab(); showInspector();
  $('#roomName').value = spec.name || '';
  if (fit) fitCamera();
  store.set('rb_draft', spec); api('/api/live', { spec }).catch(() => {});
}

function toast(msg, err = false, ms = 3500) {
  const t = $('#toast'); t.textContent = msg; t.className = err ? 'err' : ''; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}

// ================================================================== three.js view
const canvas = $('#c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x15171a);
let lights = null;
const roomHolder = new THREE.Group(); scene.add(roomHolder);
const itemHolder = new THREE.Group(); scene.add(itemHolder);
const overlay = new THREE.Group(); scene.add(overlay);
let built = null;
const itemObjs = new Map();                // item id -> group

const orthoCam = new THREE.OrthographicCamera(-5, 5, 5, -5, 0.1, 100);
orthoCam.position.set(0, 30, 0); orthoCam.up.set(0, 0, -1); orthoCam.lookAt(0, 0, 0);
const perspCam = new THREE.PerspectiveCamera(55, 1, 0.05, 200);
perspCam.position.set(6, 9, 9);
const orbit = new OrbitControls(perspCam, canvas); orbit.enableDamping = true; orbit.target.set(0, 0.8, 0);
let camMode = 'plan';
let eye = { yaw: 0, pitch: 0, fov: 75, view: 0 };
let planZoom = 1, planPan = new THREE.Vector2(0, 0);

function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  perspCam.aspect = r.width / r.height; perspCam.updateProjectionMatrix();
  updateOrtho();
}
function updateOrtho() {
  const r = canvas.getBoundingClientRect(); const a = r.width / Math.max(1, r.height);
  const F = spec ? roomFrame(spec) : { W: 8, D: 8 };
  const half = Math.max(F.W / a, F.D) / 2 * 1.55 / planZoom;
  orthoCam.left = -half * a + planPan.x; orthoCam.right = half * a + planPan.x;
  orthoCam.top = half - planPan.y; orthoCam.bottom = -half - planPan.y;   // screen up = spec north = three -z
  orthoCam.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

function activeCam() { return camMode === 'plan' ? orthoCam : perspCam; }
function fitCamera() {
  planZoom = 1; planPan.set(0, 0); updateOrtho();
  const F = roomFrame(spec);
  perspCam.position.set(F.W * 0.55, Math.max(F.W, F.D) * 1.05, F.D * 1.0); orbit.target.set(0, 0.6, 0); orbit.update();
}

function setCamMode(m) {
  camMode = m;
  document.querySelectorAll('#viewBar [data-cam]').forEach(b => b.classList.toggle('on', b.dataset.cam === m));
  orbit.enabled = m === 'orbit';
  if (m === 'eye') {
    const v = spec.views[eye.view] || spec.views[0];
    eye.yaw = (+v.yaw || 0); eye.pitch = 0;
  }
  applyVisibility();
  $('#hint').textContent = {
    plan: 'Drag a model or view marker to move it · R rotates · Delete removes · wheel zooms · right-drag pans',
    orbit: 'Drag to orbit · wheel zooms · right-drag pans · drag a selected model to move it',
    eye: 'Drag to look round · wheel changes the field of view · this is roughly the student view (the room render is 360°)',
  }[m];
}
function applyVisibility() {
  if (built) built.ceilings.visible = camMode === 'eye';
  if (outsideMesh) outsideMesh.visible = camMode !== 'plan';
  overlay.visible = camMode !== 'eye';
}

// ---------------------------------------------------------------- rebuild
function rebuildRoom() {
  if (built) { roomHolder.remove(built.root); built.root.traverse(o => { o.geometry?.dispose?.(); }); }
  built = buildRoom(spec);
  roomHolder.add(built.root);
  if (lights) scene.remove(lights);
  lights = lightRoom(scene, spec);
  if (outsideMesh) scene.remove(outsideMesh);
  outsideMesh = outsideSphere(spec, outsideCfg); scene.add(outsideMesh);
  scene.background = new THREE.Color(spec.style === 'neglected' ? 0x141210 : 0x15171a);
  applyVisibility();
  drawOverlay();
  updateOrtho();
}

async function syncItems(full = false) {
  const ids = new Set(spec.items.map(i => i.id));
  for (const [id, g] of itemObjs) if (!ids.has(id) || full) { itemHolder.remove(g); itemObjs.delete(id); }
  for (const it of spec.items) {
    const meta = catById(it.model);
    let g = itemObjs.get(it.id);
    if (g && g.userData.model !== it.model) { itemHolder.remove(g); itemObjs.delete(it.id); g = null; }
    if (!g) {
      const ph = new THREE.Group(); ph.userData.itemId = it.id; ph.userData.model = it.model; itemObjs.set(it.id, ph); itemHolder.add(ph);
      makeItem(it, meta).then(real => {
        if (itemObjs.get(it.id) !== ph) return;
        real.userData.model = it.model; itemHolder.remove(ph); itemHolder.add(real); itemObjs.set(it.id, real);
        const cur = spec.items.find(x => x.id === it.id); if (cur) applyItem(real, cur, catById(cur.model));
        drawOverlay(); updateWarnings();
      });
    } else applyItem(g, it, meta);
  }
  drawOverlay();
}

// ---------------------------------------------------------------- overlay: projected floor, footprints, view markers
function lineLoop(pts, color, z = 0.01, dashed = false) {
  const g = new THREE.BufferGeometry().setFromPoints(pts.map(([x, y]) => b2t(x, y, z)));
  const m = dashed ? new THREE.LineDashedMaterial({ color, dashSize: 0.15, gapSize: 0.1, depthTest: false }) : new THREE.LineBasicMaterial({ color, depthTest: false });
  const l = new THREE.LineLoop(g, m); if (dashed) l.computeLineDistances(); l.renderOrder = 10; return l;
}
function drawOverlay() {
  overlay.clear();
  if (!spec) return;
  const F = roomFrame(spec);
  // physical room outline, and the projected floor
  overlay.add(lineLoop([[F.X0, F.Y0], [F.X1, F.Y0], [F.X1, F.Y1], [F.X0, F.Y1]], 0x5aa2e0, 0.012, true));
  if ($('#chkFloor').checked && spec.room.projected?.floor !== false) {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(F.W, F.D).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: 0x5aa2e0, transparent: true, opacity: 0.13, depthWrite: false }));
    p.position.y = 0.006; p.renderOrder = 5; overlay.add(p);
    const inner = Math.max(0.05, floorLimit);
    if (F.W > 2 * inner && F.D > 2 * inner)
      overlay.add(lineLoop([[F.X0 + inner, F.Y0 + inner], [F.X1 - inner, F.Y0 + inner], [F.X1 - inner, F.Y1 - inner], [F.X0 + inner, F.Y1 - inner]], 0x3c6f99, 0.011, true));
  }
  // item footprints
  for (const it of spec.items) {
    const g = itemObjs.get(it.id); if (!g || !g.userData.size) continue;
    const fp = footprint(g, it, catById(it.model));
    const bad = floorDepth(fp) > floorLimit;
    const selected = sel?.kind === 'item' && sel.id === it.id;
    overlay.add(lineLoop(fp, selected ? 0xf3c27a : bad ? 0xe0605a : 0x7a8490, 0.02));
  }
  // view markers
  spec.views.forEach((v, i) => {
    const selected = sel?.kind === 'view' && sel.id === i;
    const c = new THREE.Mesh(new THREE.CircleGeometry(0.14, 24).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: selected ? 0xf3c27a : 0xe8a33d, depthTest: false }));
    c.position.copy(b2t(+v.x, +v.y, 0.03)); c.renderOrder = 20; c.userData.viewIndex = i; overlay.add(c);
    const a = (+v.yaw || 0) * Math.PI / 180;
    const tip = [+v.x + Math.sin(a) * 0.42, +v.y + Math.cos(a) * 0.42];
    const ln = new THREE.Line(new THREE.BufferGeometry().setFromPoints([b2t(+v.x, +v.y, 0.03), b2t(tip[0], tip[1], 0.03)]), new THREE.LineBasicMaterial({ color: 0xe8a33d, depthTest: false }));
    ln.renderOrder = 20; overlay.add(ln);
  });
  // selected feature highlight
  if (sel?.kind === 'feature') {
    const f = spec.features.find(x => x.id === sel.id);
    if (f && F.walls[f.wall]) {
      const [u0, u1] = span(f);
      const d = f.type === 'alcove' || f.type === 'kitchenette' ? +(f.depth ?? 0.6) : f.type === 'arch' ? T + +(f.room?.depth ?? 2) : T;
      overlay.add(lineLoop([F.w2(f.wall, u0, 0), F.w2(f.wall, u1, 0), F.w2(f.wall, u1, d), F.w2(f.wall, u0, d)], 0xf3c27a, 0.03));
    }
  }
}

// how far (m) a footprint reaches in from the physical walls onto the projected floor
function floorDepth(fp) {
  const F = roomFrame(spec);
  let deepest = -Infinity;
  for (const [x, y] of fp) deepest = Math.max(deepest, Math.min(x - F.X0, F.X1 - x, y - F.Y0, F.Y1 - y));
  return deepest;
}

// ---------------------------------------------------------------- checks
function featureProblems(f) {
  const F = roomFrame(spec), w = F.walls[f.wall]; const out = [];
  if (!w) return ['Pick a wall'];
  const [u0, u1] = span(f);
  if (u0 < w.lo - 0.001 || u1 > w.hi + 0.001) out.push('Runs past the end of the wall');
  if (f.type === 'window' && (+f.sill + +f.height) > F.RH - 0.05) out.push('Window top is above the ceiling');
  if ((f.type === 'door' || f.type === 'arch') && +(f.height ?? 2) > F.RH - 0.05) out.push('Taller than the room');
  for (const g of spec.features) {
    if (g === f || g.wall !== f.wall) continue;
    const [a, b] = span(g);
    if (a < u1 - 0.001 && b > u0 + 0.001) {
      const bothBelow = f.type === 'window' && g.type === 'window' ? false : true;
      if (bothBelow) out.push(`Overlaps the ${FEATURE_LABEL[g.type].toLowerCase()} on this wall`);
    }
  }
  return out;
}
function allWarnings() {
  const out = [];
  for (const f of spec.features) for (const p of featureProblems(f)) out.push({ text: `${FEATURE_LABEL[f.type]} (${f.wall}): ${p}`, sel: { kind: 'feature', id: f.id } });
  if (spec.room.projected?.floor !== false) for (const it of spec.items) {
    const g = itemObjs.get(it.id); if (!g || !g.userData.size) continue;
    const d = floorDepth(footprint(g, it, catById(it.model)));
    if (d > floorLimit) out.push({ text: `${catById(it.model)?.name || it.model}: reaches ${r2(d)} m onto the projected floor, so it will be smeared across the real floor`, sel: { kind: 'item', id: it.id } });
  }
  for (const it of spec.items) if (!catById(it.model)) out.push({ text: `Model "${it.model}" isn't in the library any more`, sel: { kind: 'item', id: it.id } });
  return out;
}
function updateWarnings() {
  const w = allWarnings(), box = $('#warnings');
  box.hidden = !w.length; box.innerHTML = '';
  if (w.length) {
    box.append(el('b', {}, `${w.length} thing${w.length > 1 ? 's' : ''} to check`),
      el('ul', {}, w.slice(0, 6).map(x => el('li', { style: 'cursor:pointer', onclick: () => select(x.sel) }, x.text))));
  }
  drawOverlay();
}

// ---------------------------------------------------------------- picking and dragging
const ray = new THREE.Raycaster(); const ndc = new THREE.Vector2();
const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
function setNdc(e) { const r = canvas.getBoundingClientRect(); ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); ray.setFromCamera(ndc, activeCam()); }
function floorPoint(e) { setNdc(e); const p = new THREE.Vector3(); return ray.ray.intersectPlane(floorPlane, p) ? [p.x, -p.z] : null; }
function pickAt(e) {
  setNdc(e);
  const hitsV = ray.intersectObjects(overlay.children.filter(o => o.userData.viewIndex !== undefined), false);
  if (hitsV.length) return { kind: 'view', id: hitsV[0].object.userData.viewIndex };
  const hits = ray.intersectObjects([...itemHolder.children, ...(built?.pick || [])], true);
  for (const h of hits) {
    let o = h.object;
    while (o && o.userData.itemId === undefined && o.userData.featureId === undefined) o = o.parent;
    if (!o) continue;
    if (o.userData.itemId !== undefined) return { kind: 'item', id: o.userData.itemId };
    if (o.userData.featureId !== undefined) return { kind: 'feature', id: o.userData.featureId };
  }
  // clicking a wall picks the nearest feature on it, if any
  return null;
}

let drag = null;
canvas.addEventListener('pointerdown', e => {
  if (camMode === 'eye') { drag = { kind: 'look', x: e.clientX, y: e.clientY, yaw: eye.yaw, pitch: eye.pitch }; canvas.setPointerCapture(e.pointerId); return; }
  if (e.button === 2 || e.button === 1) {
    if (camMode === 'plan') { drag = { kind: 'pan', x: e.clientX, y: e.clientY, px: planPan.x, py: planPan.y }; canvas.setPointerCapture(e.pointerId); }
    return;
  }
  const p = pickAt(e);
  if (p) {
    select(p, false);
    const fp = floorPoint(e);
    if (p.kind === 'item' && fp) {
      const it = spec.items.find(i => i.id === p.id);
      drag = { kind: 'item', id: p.id, off: [it.x - fp[0], it.y - fp[1]], moved: false };
    } else if (p.kind === 'view' && fp) {
      const v = spec.views[p.id]; drag = { kind: 'view', id: p.id, off: [v.x - fp[0], v.y - fp[1]], moved: false };
    } else if (p.kind === 'feature' && fp && camMode === 'plan') {
      const f = spec.features.find(x => x.id === p.id);
      drag = { kind: 'feature', id: p.id, start: fp, pos0: +f.pos, moved: false };
    }
    if (drag) { orbit.enabled = false; canvas.setPointerCapture(e.pointerId); }
  } else if (camMode === 'plan') {
    select(null);
  }
});
canvas.addEventListener('pointermove', e => {
  if (!drag) return;
  if (drag.kind === 'look') {
    eye.yaw = drag.yaw - (e.clientX - drag.x) * 0.25; eye.pitch = Math.max(-80, Math.min(80, drag.pitch + (e.clientY - drag.y) * 0.25)); return;
  }
  if (drag.kind === 'pan') {
    const r = canvas.getBoundingClientRect(); const ppm = r.height / (orthoCam.top - orthoCam.bottom);
    planPan.x = drag.px - (e.clientX - drag.x) / ppm; planPan.y = drag.py - (e.clientY - drag.y) / ppm; updateOrtho(); return;
  }
  const fp = floorPoint(e); if (!fp) return;
  const snap = v => e.shiftKey ? v : Math.round(v / 0.05) * 0.05;
  if (drag.kind === 'item') {
    const it = spec.items.find(i => i.id === drag.id);
    it.x = r2(snap(fp[0] + drag.off[0])); it.y = r2(snap(fp[1] + drag.off[1])); drag.moved = true;
    const g = itemObjs.get(it.id); if (g) applyItem(g, it, catById(it.model)); drawOverlay(); showInspector();
  } else if (drag.kind === 'view') {
    const v = spec.views[drag.id]; v.x = r2(snap(fp[0] + drag.off[0])); v.y = r2(snap(fp[1] + drag.off[1])); drag.moved = true; drawOverlay();
  } else if (drag.kind === 'feature') {
    const f = spec.features.find(x => x.id === drag.id); const ax = roomFrame(spec).walls[f.wall].axis === 'x' ? 0 : 1;
    f.pos = r2(snap(drag.pos0 + fp[ax] - drag.start[ax])); drag.moved = true; rebuildRoom();
  }
});
canvas.addEventListener('pointerup', () => {
  if (drag && drag.moved) { changed({ rebuild: drag.kind === 'feature', structural: tab === 'views' || tab === 'walls' }); }
  drag = null; orbit.enabled = camMode === 'orbit';
});
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('wheel', e => {
  if (camMode === 'plan') { planZoom = Math.max(0.3, Math.min(8, planZoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12))); updateOrtho(); e.preventDefault(); }
  else if (camMode === 'eye') { eye.fov = Math.max(30, Math.min(110, eye.fov + Math.sign(e.deltaY) * 4)); e.preventDefault(); }
}, { passive: false });

window.addEventListener('keydown', e => {
  if (e.target.matches('input, textarea, select')) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveRoom(); return; }
  if (!sel) return;
  if (sel.kind === 'item') {
    const it = spec.items.find(i => i.id === sel.id); if (!it) return;
    if (e.key === 'r' || e.key === 'R') { it.rot = ((+it.rot || 0) + (e.shiftKey ? -15 : 15) + 360) % 360; if (it.rot > 180) it.rot -= 360; changed({ rebuild: false, items: true }); showInspector(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { removeItem(it.id); }
    else if (e.key === 'd' || e.key === 'D') { duplicateItem(it.id); }
    else if (e.key.startsWith('Arrow')) {
      const s = e.shiftKey ? 0.01 : 0.05; e.preventDefault();
      if (e.key === 'ArrowLeft') it.x = r2(it.x - s); if (e.key === 'ArrowRight') it.x = r2(it.x + s);
      if (e.key === 'ArrowUp') it.y = r2(it.y + s); if (e.key === 'ArrowDown') it.y = r2(it.y - s);
      changed({ rebuild: false, items: true }); showInspector();
    }
  } else if (sel.kind === 'feature' && (e.key === 'Delete' || e.key === 'Backspace')) {
    spec.features = spec.features.filter(f => f.id !== sel.id); sel = null; changed({ structural: true }); showInspector();
  }
});

function select(s, switchTab = true) {
  sel = s;
  if (s && switchTab) {
    const t = { item: 'models', feature: 'walls', view: 'views' }[s.kind];
    if (t && tab !== t) { tab = t; markTabs(); }
  }
  renderTab(); showInspector(); drawOverlay();
}

// ---------------------------------------------------------------- render loop
function frame() {
  requestAnimationFrame(frame);
  if (camMode === 'orbit') orbit.update();
  if (camMode === 'eye' && spec) {
    const v = spec.views[eye.view] || spec.views[0]; const F = roomFrame(spec);
    perspCam.position.copy(b2t(+v.x, +v.y, +(v.z ?? F.eye)));
    perspCam.fov = eye.fov; perspCam.updateProjectionMatrix();
    const yaw = eye.yaw * Math.PI / 180, pitch = eye.pitch * Math.PI / 180;
    const dir = new THREE.Vector3(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch));
    perspCam.lookAt(perspCam.position.clone().add(dir));
  }
  renderer.render(scene, activeCam());
}

// ================================================================== inspector (selected model)
function showInspector() {
  const box = $('#inspector'); box.innerHTML = '';
  if (!sel || sel.kind !== 'item') { box.hidden = true; return; }
  const it = spec.items.find(i => i.id === sel.id); if (!it) { box.hidden = true; return; }
  const meta = catById(it.model) || { name: it.model };
  const g = itemObjs.get(it.id);
  const size = g?.userData.size ? g.userData.size.clone().multiplyScalar((+it.scale || 1) * (+meta.scale || 1)) : null;
  box.hidden = false;
  const num = (label, key, step, fn) => el('label', { style: 'display:flex;gap:6px;align-items:center;font-size:12px;color:var(--muted)' }, label,
    el('input', { type: 'number', step, value: it[key] ?? 0, onchange: e => { it[key] = +e.target.value; fn?.(); changed({ rebuild: false, items: true }); showInspector(); } }));
  box.append(
    el('div', { class: 'head', style: 'display:flex;gap:8px;align-items:center;margin-bottom:6px' }, el('b', { style: 'flex:1' }, meta.name), statusPill(meta.status)),
    size ? el('div', { class: 'kv' }, `Size: ${r2(size.x)} × ${r2(size.z)} m, ${r2(size.y)} m tall`) : null,
    el('div', { class: 'row' },
      el('button', { title: 'Turn left 15° (Shift+R)', onclick: () => rot(-15) }, '⟲15°'),
      el('button', { title: 'Turn right 15° (R)', onclick: () => rot(15) }, '15°⟳'),
      el('button', { onclick: () => rot(90) }, '90°'),
      el('button', { title: 'Back it against the nearest wall, facing into the room', onclick: () => toWall(it) }, 'Back to wall')),
    el('div', { class: 'row' }, el('label', { style: 'width:60px;color:var(--muted)' }, 'Scale'),
      el('input', { type: 'range', min: 0.25, max: 3, step: 0.01, value: it.scale ?? 1, class: 'grow',
        oninput: e => { it.scale = +e.target.value; applyItem(g, it, meta); drawOverlay(); }, onchange: () => { changed({ rebuild: false, items: true }); showInspector(); } }),
      el('span', { style: 'width:38px;text-align:right' }, (+(it.scale ?? 1)).toFixed(2))),
    mode === 'advanced' ? el('div', { class: 'row', style: 'flex-wrap:wrap' }, num('x', 'x', 0.05), num('y', 'y', 0.05), num('Raise', 'z', 0.01), num('Turn', 'rot', 5)) : null,
    el('div', { class: 'row' },
      el('button', { onclick: () => duplicateItem(it.id) }, 'Duplicate'),
      el('button', { class: 'danger', onclick: () => removeItem(it.id) }, 'Remove'),
      el('button', { style: 'margin-left:auto', onclick: () => select(null) }, 'Done')),
  );
  function rot(d) { it.rot = (((+it.rot || 0) + d) % 360 + 540) % 360 - 180; changed({ rebuild: false, items: true }); showInspector(); }
}

function wallTargets() {
  const F = roomFrame(spec); const out = [];
  for (const w of WALLNAMES) out.push({ wall: w, depth: 0, lo: F.walls[w].lo, hi: F.walls[w].hi });
  for (const f of spec.features) {
    if (!F.walls[f.wall]) continue;
    const [u0, u1] = span(f);
    if (f.type === 'alcove' || f.type === 'kitchenette') out.push({ wall: f.wall, depth: +(f.depth ?? 0.6) - (f.type === 'kitchenette' ? 0.6 : 0), lo: u0, hi: u1 });
    if (f.type === 'arch') out.push({ wall: f.wall, depth: T + +(f.room?.depth ?? 2) - (f.room?.type === 'kitchen' ? 0.6 : 0), lo: u0 - 2, hi: u1 + 2 });
  }
  return out;
}
function toWall(it) {
  const g = itemObjs.get(it.id); const meta = catById(it.model); if (!g?.userData.size) return;
  const F = roomFrame(spec); const s = (+it.scale || 1) * (+meta?.scale || 1);
  const halfDepth = g.userData.size.z * s / 2;
  let best = null;
  for (const t of wallTargets()) {
    const w = F.walls[t.wall]; const u = w.axis === 'x' ? it.x : it.y; if (u < t.lo - 0.3 || u > t.hi + 0.3) continue;
    const lineCoord = w.line + w.sign * t.depth;
    const cur = w.axis === 'x' ? it.y : it.x;
    const dist = Math.abs(cur - lineCoord);
    if (!best || dist < best.dist) best = { t, w, lineCoord, dist };
  }
  if (!best) return;
  it.rot = FACING[best.t.wall];
  const c = r2(best.lineCoord - best.w.sign * (halfDepth + 0.01));
  if (best.w.axis === 'x') it.y = c; else it.x = c;
  changed({ rebuild: false, items: true }); showInspector();
}
function removeItem(id) { spec.items = spec.items.filter(i => i.id !== id); if (sel?.id === id) sel = null; changed({ rebuild: false, items: true, structural: true }); showInspector(); }
function duplicateItem(id) {
  const it = spec.items.find(i => i.id === id); const c = { ...it, id: uid('item'), x: r2(it.x + 0.3), y: r2(it.y - 0.3) };
  spec.items.push(c); sel = { kind: 'item', id: c.id }; changed({ rebuild: false, items: true, structural: true }); showInspector();
}
function addItem(model) {
  const F = roomFrame(spec);
  const it = { id: uid('item'), model: model.id, x: 0, y: r2(F.D / 4), z: 0, rot: 0, scale: 1 };
  spec.items.push(it); sel = { kind: 'item', id: it.id };
  changed({ rebuild: false, items: true, structural: true }); showInspector();
  toast(`Added ${model.name}. Drag it into place, or use Back to wall.`);
}

// ================================================================== panels
function markTabs() { document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab)); }
function renderTab() {
  const body = $('#tabBody'); const scroll = body.scrollTop; body.innerHTML = '';
  ({ room: tabRoom, walls: tabWalls, models: tabModels, views: tabViews, render: tabRender, library: tabLibrary })[tab](body);
  body.scrollTop = scroll;
}
const row = (label, ...ctl) => el('div', { class: 'row' }, el('label', {}, label), ...ctl);
const statusPill = s => el('span', { class: 'pill ' + ({ 'room-tested': 'ok', untested: 'warn', rejected: 'bad' }[s] || '') }, s || 'untested');

function radio(name, options, value, onChange) {
  return el('div', { class: 'radio' }, options.map(([v, label]) => el('label', {},
    el('input', { type: 'radio', name, value: v, checked: v === value, onchange: () => onChange(v) }), el('span', {}, label))));
}
function numIn(value, step, onChange, attrs = {}) {
  return el('input', { type: 'number', step, value, ...attrs, onchange: e => onChange(+e.target.value) });
}
function slider(value, min, max, step, onInput, onChange, fmt = v => `${(+v).toFixed(2)} m`) {
  const out = el('span', { style: 'width:62px;text-align:right;font-size:12.5px' }, fmt(value));
  const s = el('input', { type: 'range', min, max, step, value, class: 'grow',
    oninput: e => { out.textContent = fmt(e.target.value); onInput(+e.target.value); }, onchange: e => onChange(+e.target.value) });
  return [s, out];
}

// ---------------------------------------------------------------- Room tab
function tabRoom(body) {
  const r = spec.room;
  const presetSel = el('select', { class: 'grow', onchange: e => {
    const p = presets.find(x => x.id === e.target.value);
    if (p) { Object.assign(r, { preset: p.id, width: p.width, depth: p.depth, height: p.height, eye: p.eye ?? 1.12, projected: { ...(p.projected || {}) } }); }
    else r.preset = 'custom';
    changed({ structural: true }); fitCamera();
  } }, presets.map(p => el('option', { value: p.id, selected: p.id === r.preset }, `${p.name}  (${p.width} × ${p.depth} m)`)),
     el('option', { value: 'custom', selected: !presets.some(p => p.id === r.preset) }, 'Custom size…'));
  const custom = !presets.some(p => p.id === r.preset);
  const dim = (label, key, min, max) => row(label, numIn(r[key], 0.01, v => { r[key] = Math.max(min, Math.min(max, v)); r.preset = 'custom'; changed({ structural: true }); fitCamera(); }, { min, max }), el('span', { class: 'note' }, 'm'));
  body.append(
    el('h3', {}, 'The physical room'),
    el('p', { class: 'note' }, 'Start from the room the scenario will run in, so the walls of the render line up with the real walls. Pick a measured room or type in your own size.'),
    row('Room', presetSel),
    dim('Width (W–E)', 'width', 2, 20), dim('Depth (S–N)', 'depth', 2, 20), dim('Height', 'height', 1.8, 6), dim('Eye height', 'eye', 0.8, 2.0),
    row('Projected on', el('label', { class: 'chk', style: 'background:none;border:0;padding:0' },
      el('input', { type: 'checkbox', checked: r.projected?.floor !== false, onchange: e => { r.projected = { ...(r.projected || {}), floor: e.target.checked }; changed({ rebuild: false }); } }), 'Floor'),
      el('label', { class: 'chk', style: 'background:none;border:0;padding:0' },
      el('input', { type: 'checkbox', checked: !!r.projected?.ceiling, onchange: e => { r.projected = { ...(r.projected || {}), ceiling: e.target.checked }; changed({ rebuild: false }); } }), 'Ceiling')),
    custom ? el('div', { class: 'row' }, el('label', {}), el('button', { onclick: saveCustomPreset }, 'Save this size as a room')) : null,
    custom ? el('p', { class: 'note warn' }, 'The render only lines up in a physical room of exactly this size. Projected into a bigger or smaller room, everything is the wrong scale: furniture lands on the floor and the top of the walls is lost. Keep the measured room size even for a smaller place such as a cell: the walls can be pushed back with alcoves but not brought in.') : null,
    el('h4', {}, 'Look'),
    row('Style', radio('style', [['modern', 'Modern'], ['neglected', 'Neglected'], ['hospital', 'Hospital'], ['court', 'Court'], ['custody', 'Custody'], ['outdoor', 'Outdoor']], spec.style, v => { spec.style = v; changed({ structural: true }); })),
    row('Light', radio('light', [['day', 'Day'], ['dusk', 'Dusk'], ['night', 'Night']], spec.lighting, v => { spec.lighting = v; changed({ structural: true }); })),
    el('p', { class: 'note' }, 'Style sets the walls, floor, ceiling, kitchen and lighting. The same layout can be rendered in every style: change it here and render again.'),
    ...outsidePanel(),
    el('h4', {}, 'Start from'),
    el('div', { class: 'addbar' },
      el('button', { onclick: () => openDialog() }, 'Saved rooms and examples'),
      el('button', { onclick: () => { if (confirm('Clear all walls features and models from this room?')) { spec.features = []; spec.items = []; changed({ structural: true, items: true }); } } }, 'Empty this room')),
  );
}
function outsidePanel() {
  spec.outside ||= {};
  const o = spec.outside;
  const cur = o.view || outsideCfg.style_default?.[spec.style] || 'garden';
  const views = outsideCfg.views || [];
  const id = outsideHdriId(spec, outsideCfg);
  const sel = el('select', { class: 'grow', onchange: e => { o.view = e.target.value; changed({ structural: true }); } },
    views.map(v => el('option', { value: v.id, selected: v.id === cur }, v.name + ((v.styles || []).includes(spec.style) ? '' : ' (other styles)'))),
    mode === 'advanced' ? el('option', { value: 'custom', selected: cur === 'custom' }, 'Any Poly Haven HDRI…') : null);
  return [
    el('h4', {}, 'Outside'),
    el('p', { class: 'note' }, 'What every window and outside door looks out on: a real 360° photo (Poly Haven, CC0) that also lights the room. Day, dusk or night follows the Light setting. Use 3D or Eye view to see it through the windows; turn it until the right part shows.'),
    row('View', sel),
    cur === 'custom' ? row('HDRI id', el('input', { type: 'text', class: 'grow', placeholder: 'e.g. urban_street_01', value: o.hdri || '', onchange: e => { o.hdri = e.target.value.trim(); changed({ structural: true }); } })) : null,
    row('Turn the view', ...slider(+o.rotation || 0, 0, 359, 5, v => { o.rotation = v; if (outsideMesh) outsideMesh.rotation.y = -v * Math.PI / 180; },
      v => { o.rotation = v; changed({ rebuild: false }); }, x => `${Math.round(x)}°`)),
    id ? el('img', { src: `/api/hdri/${encodeURIComponent(id)}.png`, alt: 'Outside view', style: 'width:100%;aspect-ratio:2;object-fit:cover;border-radius:6px;margin-top:4px;background:#0f1113' }) : null,
    id ? el('div', { class: 'note' }, el('a', { href: `https://polyhaven.com/a/${id}`, target: '_blank', rel: 'noopener' }, id), ' · Poly Haven, CC0') : null,
  ];
}
async function saveCustomPreset() {
  const name = prompt('Name for this room size', spec.name || 'My room'); if (!name) return;
  const r = spec.room;
  const p = await api('/api/presets', { room: { name, width: r.width, depth: r.depth, height: r.height, eye: r.eye, projected: r.projected } });
  presets = (await api('/api/presets')).rooms; r.preset = p.id; changed({ structural: true }); toast('Room size saved.');
}

// ---------------------------------------------------------------- Walls tab
// "From left corner": distance from the left-hand corner as you face the wall from inside the room to the feature's centre.
function leftDist(f) { const w = roomFrame(spec).walls[f.wall]; return (f.wall === 'north' || f.wall === 'west') ? +f.pos - w.lo : w.hi - +f.pos; }
function setLeftDist(f, d) { const w = roomFrame(spec).walls[f.wall]; f.pos = r2((f.wall === 'north' || f.wall === 'west') ? w.lo + d : w.hi - d); }
function wallLen(wall) { const w = roomFrame(spec).walls[wall]; return w.hi - w.lo; }

function addFeature(type) {
  const base = { id: uid(type), type, wall: 'north', pos: 0 };
  const F = roomFrame(spec);
  const defaults = {
    alcove: { width: 1.6, depth: 0.6 },
    door: { width: 0.86, height: 2.0, beyond: 'corridor', wall: 'south' },
    window: { width: 1.3, sill: 0.8, height: Math.min(1.2, F.RH - 1.0), wall: 'west' },
    arch: { width: Math.min(2.4, F.D - 0.6), height: Math.min(2.0, F.RH - 0.1), shape: 'round', wall: 'east', room: { type: 'kitchen', depth: 2.2 } },
    kitchenette: { width: Math.min(2.6, F.W - 0.6), depth: 0.65 },
  }[type];
  const f = { ...base, ...defaults };
  // find a free spot: its usual wall first, then the others, sliding along each wall
  let found = false;
  for (const w of [f.wall, ...WALLNAMES]) {
    const fw = F.walls[w]; f.wall = w;
    const steps = [];
    for (let d = 0; d <= (fw.hi - fw.lo) / 2; d += 0.1) steps.push(d, -d);
    for (const d of steps) { f.pos = r2((fw.lo + fw.hi) / 2 + d); if (!featureProblems(f).length) { found = true; break; } }
    if (found) break;
  }
  if (!found) { f.wall = defaults.wall || 'north'; f.pos = 0; toast('No free space on any wall at this width: it overlaps something. Make it narrower or move it.', true, 5000); }
  spec.features.push(f); sel = { kind: 'feature', id: f.id };
  changed({ structural: true });
}

function tabWalls(body) {
  if (spec.style === 'outdoor') {
    body.append(el('h3', {}, 'Walls'), el('p', { class: 'note' }, 'This is an outdoor scene: there are no walls. The place itself is the photo chosen under Outside on the Room tab; add benches, bins and signs on the Models tab. Keep them about 3.3 m or more from the centre so they land on the projected walls, not the floor.'));
    return;
  }
  body.append(
    el('h3', {}, 'Walls'),
    el('p', { class: 'note' }, 'Alcoves, kitchens and rooms through an arch are built beyond the real walls, so furniture can stand in them without spilling onto the projected floor. In Plan view you can drag a feature along its wall.'),
    el('div', { class: 'addbar' }, Object.entries(FEATURE_LABEL).map(([t, l]) => el('button', { onclick: () => addFeature(t) }, '+ ' + l))),
  );
  if (!spec.features.length) body.append(el('p', { class: 'note', style: 'margin-top:14px' }, 'No features yet: the room is four plain walls.'));
  const adv = mode === 'advanced';
  for (const wall of WALLNAMES) {
    const fs = spec.features.filter(f => f.wall === wall); if (!fs.length) continue;
    body.append(el('h4', {}, `${wall} wall · ${r2(wallLen(wall))} m`));
    for (const f of fs) {
      const probs = featureProblems(f);
      const card = el('div', { class: 'card' + (sel?.kind === 'feature' && sel.id === f.id ? ' sel' : '') + (probs.length ? ' err' : ''), onclick: e => { if (e.target.closest('select, button, input, label, textarea')) return;   // controls work without redrawing the card
        if (e.target === card || e.target.closest('.head')) select({ kind: 'feature', id: f.id }, false); } });
      const L = wallLen(f.wall);
      const live = () => { rebuildRoom(); drawOverlay(); };
      const commit = () => changed({ structural: true });
      const fld = (label, key, min, max, step = 0.05, obj = f) => adv
        ? row(label, numIn(obj[key], 0.01, v => { obj[key] = v; commit(); }, { min, max }), el('span', { class: 'note' }, 'm'))
        : row(label, ...slider(obj[key], min, max, step, v => { obj[key] = v; live(); }, v => { obj[key] = v; commit(); }));
      card.append(
        el('div', { class: 'head' }, el('b', {}, FEATURE_LABEL[f.type]),
          el('select', { onchange: e => { f.wall = e.target.value; commit(); } }, WALLNAMES.map(w => el('option', { value: w, selected: w === f.wall }, w))),
          el('button', { class: 'danger', title: 'Remove', onclick: () => { spec.features = spec.features.filter(x => x !== f); sel = null; commit(); } }, '✕')),
        adv ? row('From left corner', numIn(r2(leftDist(f)), 0.01, v => { setLeftDist(f, v); commit(); }), el('span', { class: 'note' }, 'm to centre'))
            : row('From left corner', ...slider(r2(leftDist(f)), 0, L, 0.05, v => { setLeftDist(f, v); live(); }, v => { setLeftDist(f, v); commit(); })),
        fld('Width', 'width', 0.4, Math.max(0.5, L)),
      );
      if (f.type === 'alcove') {
        card.append(fld('Depth', 'depth', 0.2, 4.0));
        if (+f.depth > 1.2) card.append(el('p', { class: 'note' }, 'Deep bays get their own ceiling light' + (spec.style === 'hospital' ? ', and a bed-head services panel on the back wall when deeper than 1.5 m.' : '.')));
        card.append(row('Shelves', numIn(f.shelves || 0, 1, v => { f.shelves = Math.max(0, Math.min(8, Math.round(v))); commit(); }, { min: 0, max: 8 })));
        if (adv) card.append(row('Height', numIn(f.height ?? spec.room.height, 0.01, v => { f.height = v; commit(); }), el('span', { class: 'note' }, 'm (full height = room height)')));
      }
      if (f.type === 'kitchenette') card.append(fld('Depth', 'depth', 0.62, 1.2), el('p', { class: 'note' }, 'A fitted run in a recess: base units, worktop, sink, hob, wall units and a fridge-freezer if there is room.'));
      if (f.type === 'door') {
        card.append(fld('Height', 'height', 1.8, Math.max(1.9, spec.room.height - 0.05)));
        const by = f.beyond === 'hall' ? 'corridor' : (f.beyond || 'corridor');
        card.append(row('Beyond it', radio(f.id + 'b', [['corridor', 'Corridor'], ['outside', 'Outside'], ['dark', 'Dark'], ['closed', 'Closed']], by, v => { f.beyond = v; commit(); })));
        card.append(el('p', { class: 'note' }, { corridor: spec.style === 'hospital' ? 'A ward corridor runs along the wall: handrails, panel lights, double doors and a noticeboard opposite.' : 'A hallway runs along the wall: a door to another room, a radiator and picture, and the front door at one end.',
          outside: 'Opens straight onto the outside view.', dark: 'An unlit corridor.', closed: 'The door is shut.' }[by]));
      }
      if (f.type === 'window') {
        card.append(fld('Sill height', 'sill', 0.2, spec.room.height - 0.6), fld('Height', 'height', 0.4, spec.room.height - 0.3));
        const dflt = { neglected: 'nets_curtains', hospital: 'blinds', court: 'blinds', custody: 'frosted' }[spec.style] || 'none';
        card.append(row('Dressing', radio(f.id + 'o', [['none', 'None'], ['blinds', 'Blinds'], ['curtains', 'Curtains'], ['nets_curtains', 'Nets + curtains'], ['frosted', 'Frosted']], f.dressing || dflt, v => { f.dressing = v; commit(); })));
      }
      if (f.type === 'arch') {
        f.room ||= { type: 'kitchen', depth: 2.2 };
        card.append(fld('Height', 'height', 1.6, spec.room.height - 0.05));
        card.append(row('Shape', radio(f.id + 's', [['round', 'Round top'], ['square', 'Square']], f.shape || 'round', v => { f.shape = v; commit(); })));
        card.append(row('Leads to', radio(f.id + 'r', [['kitchen', 'Kitchen'], ['recess', 'Empty room']], f.room.type || 'kitchen', v => { f.room.type = v; commit(); })));
        card.append(fld('Room depth', 'depth', 0.8, 4, 0.05, f.room));
        if (adv) {
          card.append(row('Room width', numIn(f.room.width ?? r2(+f.width + 1), 0.01, v => { f.room.width = v; commit(); }), el('span', { class: 'note' }, 'm')));
          card.append(row('Arch curve', numIn(f.rise ?? 0.2, 0.05, v => { f.rise = v; commit(); }, { min: 0.05, max: 1 }), el('span', { class: 'note' }, '0.05 flat … 1 semicircle')));
        }
      }
      for (const p of probs) card.append(el('p', { class: 'note bad' }, p));
      body.append(card);
    }
  }
}

// ---------------------------------------------------------------- Models tab
let modelsSub = 'library';
let libFilter = store.get('rb_lib_filter', { q: '', cat: '', status: 'usable', style: true });
let modelDetail = null;
let findState = { source: 'polyhaven', q: '', cat: '', maxfaces: '100000', licence: 'both', results: [], next: '', busy: false, error: '' };
let phCats = null, sfCats = null;

function tabModels(body) {
  // models in this room
  body.append(el('h3', {}, 'Models in this room'));
  if (!spec.items.length) body.append(el('p', { class: 'note' }, 'None yet. Pick from the library below; models that have worked in the room are listed first.'));
  else body.append(el('ul', { class: 'list' }, spec.items.map(it => {
    const m = catById(it.model); const g = itemObjs.get(it.id);
    const bad = g?.userData.size && floorDepth(footprint(g, it, m)) > floorLimit;
    return el('li', { class: sel?.kind === 'item' && sel.id === it.id ? 'sel' : '', onclick: () => select({ kind: 'item', id: it.id }, false) },
      el('span', { class: 'n' }, m?.name || it.model), bad ? el('span', { class: 'pill bad', title: 'On the projected floor' }, 'floor') : null,
      el('button', { class: 'danger', title: 'Remove', onclick: e => { e.stopPropagation(); removeItem(it.id); } }, '✕'));
  })));
  body.append(el('div', { class: 'subtabs', style: 'margin-top:16px' },
    el('button', { class: modelsSub === 'library' ? 'on' : '', onclick: () => { modelsSub = 'library'; renderTab(); } }, `Library (${catalogue.length})`),
    el('button', { class: modelsSub === 'find' ? 'on' : '', onclick: () => { modelsSub = 'find'; renderTab(); } }, 'Find more online')));
  if (modelsSub === 'library') libraryPanel(body); else findPanel(body);
}

function libraryPanel(body) {
  const cats = [...new Set(catalogue.map(m => m.category || 'misc'))].sort();
  const f = libFilter;
  const save = () => { store.set('rb_lib_filter', f); renderTab(); };
  body.append(
    el('div', { class: 'row' }, el('input', { type: 'text', class: 'grow', placeholder: 'Search the library', value: f.q, onchange: e => { f.q = e.target.value; save(); } }),
      el('select', { onchange: e => { f.cat = e.target.value; save(); } }, el('option', { value: '' }, 'All types'), cats.map(c => el('option', { value: c, selected: c === f.cat }, c)))),
    el('div', { class: 'row' },
      el('select', { onchange: e => { f.status = e.target.value; save(); } },
        [['usable', 'Tested + untested'], ['room-tested', 'Room-tested only'], ['untested', 'Untested only'], ['rejected', 'Rejected'], ['all', 'Everything']].map(([v, l]) => el('option', { value: v, selected: v === f.status }, l))),
      el('label', { class: 'chk', style: 'background:none;border:0;padding:0' }, el('input', { type: 'checkbox', checked: f.style, onchange: e => { f.style = e.target.checked; save(); } }), `Suits ${spec.style}`)),
  );
  const q = f.q.toLowerCase().trim();
  const list = catalogue.filter(m => {
    if (f.cat && m.category !== f.cat) return false;
    if (f.status === 'usable' && m.status === 'rejected') return false;
    if (!['usable', 'all'].includes(f.status) && m.status !== f.status) return false;
    if (f.style && m.styles && !m.styles.includes(spec.style)) return false;
    if (q && !`${m.name} ${m.id} ${(m.tags || []).join(' ')} ${m.category}`.toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => (a.status === 'room-tested' ? 0 : 1) - (b.status === 'room-tested' ? 0 : 1) || a.name.localeCompare(b.name));
  if (modelDetail && catById(modelDetail)) body.append(modelDetailCard(catById(modelDetail)));
  body.append(el('div', { class: 'grid' }, list.map(m => el('div', { class: 'tile' + (modelDetail === m.id ? ' sel' : ''), onclick: () => { modelDetail = m.id; renderTab(); }, ondblclick: () => addItem(m), title: 'Click for details, double-click to add' },
    el('img', { src: m.thumb ? `/catalogue/models/${encodeURIComponent(m.id)}/${m.thumb}` : '', alt: '', loading: 'lazy' }),
    el('div', { class: 't' }, m.name), el('div', { class: 'm' }, statusPill(m.status), m.licence?.credit_required ? el('span', { class: 'pill blue', title: 'Credit required' }, 'CC-BY') : null)))));
  if (!list.length) body.append(el('p', { class: 'note' }, 'Nothing matches. Try another filter, or find more online.'));
}

function modelDetailCard(m) {
  const lic = m.licence || {};
  const c = el('div', { class: 'card detail' });
  c.append(
    m.thumb ? el('img', { src: `/catalogue/models/${encodeURIComponent(m.id)}/${m.thumb}`, alt: '' }) : null,
    el('div', { class: 'head' }, el('b', {}, m.name)),
    el('div', { class: 'kv' }, 'Source: ', el('b', {}, lic.source || '?'), lic.url ? [' · ', el('a', { href: lic.url, target: '_blank', rel: 'noopener' }, 'page')] : null),
    el('div', { class: 'kv' }, 'Author: ', el('b', {}, lic.author || 'unknown')),
    el('div', { class: 'kv' }, 'Licence: ', el('b', {}, lic.licence || '?'), lic.credit_required ? el('span', { class: 'pill blue', style: 'margin-left:6px' }, 'credit added to each room automatically') : el('span', { class: 'pill ok', style: 'margin-left:6px' }, 'no credit needed')),
    m.polycount ? el('div', { class: 'kv' }, 'Polygons: ', el('b', {}, Number(m.polycount).toLocaleString())) : null,
    el('div', { style: 'clear:both' }),
    row('Status', el('select', { onchange: e => saveModel(m, { status: e.target.value }) },
      [['room-tested', 'Room-tested (works in the room)'], ['untested', 'Untested'], ['rejected', 'Rejected (hide it)']].map(([v, l]) => el('option', { value: v, selected: v === m.status }, l)))),
    row('Type', el('input', { type: 'text', class: 'grow', value: m.category || '', onchange: e => saveModel(m, { category: e.target.value.trim() || 'misc' }) })),
    row('Suits', el('div', { class: 'chks' }, ['modern', 'neglected', 'hospital', 'court', 'custody', 'outdoor'].map(s => el('label', { class: 'chk', style: 'background:none;border:0;padding:0' },
      el('input', { type: 'checkbox', checked: (m.styles || []).includes(s), onchange: e => { const st = new Set(m.styles || []); e.target.checked ? st.add(s) : st.delete(s); saveModel(m, { styles: [...st] }); } }), s)))),
    mode === 'advanced' ? row('Default scale', numIn(m.scale ?? 1, 0.01, v => saveModel(m, { scale: v }))) : null,
    el('div', { class: 'note' }, 'Room notes (scale checked, safe on the floor, reads from the centre…)'),
    el('textarea', { onchange: e => saveModel(m, { notes: e.target.value }) }, m.notes || ''),
    el('div', { class: 'row' }, el('button', { class: 'primary', onclick: () => addItem(m) }, 'Add to room'),
      el('button', { style: 'margin-left:auto', class: 'danger', onclick: async () => { if (!confirm(`Remove ${m.name} from the library? (It moves to catalogue/_removed.)`)) return; await api(`/api/catalogue/${m.id}/remove`, {}); catalogue = catalogue.filter(x => x.id !== m.id); modelDetail = null; renderTab(); } }, 'Remove from library')),
  );
  return c;
}
async function saveModel(m, changes) {
  try { const upd = await api('/api/catalogue/' + encodeURIComponent(m.id), changes); Object.assign(m, upd); renderTab(); syncItems(); toast('Saved.', false, 1200); }
  catch (e) { toast(e.message, true); }
}

function findPanel(body) {
  const s = findState;
  body.append(
    el('div', { class: 'subtabs' },
      el('button', { class: s.source === 'polyhaven' ? 'on' : '', onclick: () => { s.source = 'polyhaven'; s.results = []; s.cat = ''; renderTab(); } }, 'Poly Haven'),
      el('button', { class: s.source === 'sketchfab' ? 'on' : '', onclick: () => { s.source = 'sketchfab'; s.results = []; s.cat = ''; renderTab(); } }, 'Sketchfab')),
    el('p', { class: 'note' }, s.source === 'polyhaven'
      ? 'Poly Haven models are all CC0: free to use with no credit needed. Real-world scale, good quality, a smaller range.'
      : 'Only downloadable CC0 and CC-BY models are shown. CC-BY needs a credit: it is saved with the model and added to every room that uses it. Scale and quality vary, so check each one in the room before marking it room-tested.'),
  );
  if (s.source === 'sketchfab' && !status.sketchfab_token)
    body.append(el('p', { class: 'note warn' }, 'Searching works now. To import, add your free Sketchfab API token in ', el('a', { href: '#', onclick: e => { e.preventDefault(); openSettings(); } }, 'Settings'), '.'));
  const cats = s.source === 'polyhaven' ? (phCats ? Object.keys(phCats).filter(k => k !== 'all').sort() : []) : (sfCats || []).map(c => c.slug);
  const catName = c => s.source === 'polyhaven' ? c : (sfCats || []).find(x => x.slug === c)?.name || c;
  const go = () => runSearch(false);
  body.append(
    el('div', { class: 'row' }, el('input', { type: 'text', class: 'grow', placeholder: 'e.g. armchair, walking frame, kettle', value: s.q, onchange: e => (s.q = e.target.value), onkeydown: e => { if (e.key === 'Enter') { s.q = e.target.value; go(); } } }),
      el('button', { class: 'primary', onclick: go, disabled: s.busy }, s.busy ? 'Searching…' : 'Search')),
    el('div', { class: 'row' },
      el('select', { onchange: e => { s.cat = e.target.value; go(); } }, el('option', { value: '' }, 'All categories'), cats.map(c => el('option', { value: c, selected: c === s.cat }, catName(c)))),
      s.source === 'sketchfab' ? el('select', { title: 'Polygon limit', onchange: e => { s.maxfaces = e.target.value; go(); } },
        [['20000', 'Under 20k polys'], ['100000', 'Under 100k polys'], ['300000', 'Under 300k polys'], ['', 'Any size']].map(([v, l]) => el('option', { value: v, selected: v === s.maxfaces }, l))) : null),
    s.source === 'sketchfab' ? el('div', { class: 'row' }, el('select', { onchange: e => { s.licence = e.target.value; go(); } },
      [['both', 'CC0 and CC-BY'], ['cc0', 'CC0 only (no credit)'], ['by', 'CC-BY only']].map(([v, l]) => el('option', { value: v, selected: v === s.licence }, l)))) : null,
  );
  if (s.error) body.append(el('p', { class: 'note bad' }, s.error));
  body.append(el('div', { class: 'grid' }, s.results.map(r => {
    const t = el('div', { class: 'tile', title: `${r.name}\n${r.author || ''}` },
      el('img', { src: r.thumb, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }),
      el('div', { class: 't' }, r.name),
      el('div', { class: 'm' }, el('span', { class: 'pill ' + (r.licence === 'CC0' ? 'ok' : 'blue') }, r.licence),
        r.faces ? el('span', { class: 'pill' }, `${Math.round(r.faces / 1000)}k`) : null),
      el('div', { class: 'm' },
        r.in_library ? el('span', { class: 'pill ok' }, 'in library')
          : el('button', { style: 'padding:2px 8px;font-size:12px', onclick: e => { e.stopPropagation(); importModel(r, e.target); } }, 'Import'),
        el('a', { href: r.url, target: '_blank', rel: 'noopener', style: 'font-size:12px;margin-left:auto', onclick: e => e.stopPropagation() }, 'view')));
    return t;
  })));
  if (s.next && s.source === 'sketchfab') body.append(el('div', { class: 'row' }, el('button', { onclick: () => runSearch(true), disabled: s.busy }, 'More results')));
  if (!s.results.length && !s.busy && !s.error) body.append(el('p', { class: 'note' }, 'Search to see models.'));
  if (s.source === 'polyhaven' && !phCats) api('/api/polyhaven/categories').then(c => { phCats = c; if (tab === 'models' && modelsSub === 'find') renderTab(); }).catch(() => {});
  if (s.source === 'sketchfab' && !sfCats) api('/api/sketchfab/categories').then(c => { sfCats = c; if (tab === 'models' && modelsSub === 'find') renderTab(); }).catch(() => {});
}
async function runSearch(more) {
  const s = findState; s.busy = true; s.error = ''; renderTab();
  try {
    if (s.source === 'polyhaven') {
      s.results = await api(`/api/search/polyhaven?q=${encodeURIComponent(s.q)}&category=${encodeURIComponent(s.cat)}`); s.next = '';
    } else {
      const j = await api(`/api/search/sketchfab?q=${encodeURIComponent(s.q)}&category=${encodeURIComponent(s.cat)}&maxfaces=${s.maxfaces}&licence=${s.licence}&cursor=${encodeURIComponent(more ? s.next : '')}`);
      s.results = more ? s.results.concat(j.results) : j.results; s.next = j.next;
    }
  } catch (e) { s.error = e.message; }
  s.busy = false; renderTab();
}
async function importModel(r, btn) {
  btn.disabled = true; btn.textContent = 'Importing…';
  try {
    const meta = findState.source === 'polyhaven' ? await api('/api/import/polyhaven', { id: r.id }) : await api('/api/import/sketchfab', { uid: r.uid });
    meta.id ||= r.id; catalogue = catalogue.filter(m => m.id !== meta.id).concat([meta]);
    r.in_library = true; toast(`${meta.name} is in the library as untested. Add it to the room to check its size.`);
    renderTab();
  } catch (e) { btn.disabled = false; btn.textContent = 'Import'; toast(e.message, true, 6000); }
}

// ---------------------------------------------------------------- Views tab
function tabViews(body) {
  body.append(el('h3', {}, 'Views'),
    el('p', { class: 'note' }, 'Each view is one 360° image, taken from that spot at eye height. "centre" is where students stand in the room. Add a view to look into the kitchen, for example; on the room tablet it becomes another button. Drag the orange markers in Plan view; the line shows which way is the centre of the image.'),
    el('button', { onclick: () => { spec.views.push({ name: `view${spec.views.length + 1}`, x: 0, y: 0, yaw: 0 }); sel = { kind: 'view', id: spec.views.length - 1 }; changed({ structural: true, rebuild: false }); } }, '+ Add view'));
  spec.views.forEach((v, i) => {
    const c = el('div', { class: 'card' + (sel?.kind === 'view' && sel.id === i ? ' sel' : '') });
    c.append(
      el('div', { class: 'head' }, el('input', { type: 'text', value: v.name, class: 'grow', onchange: e => { v.name = e.target.value.replace(/[^\w\-]/g, '') || `view${i + 1}`; changed({ structural: true, rebuild: false }); } }),
        el('button', { onclick: () => { eye.view = i; setCamMode('eye'); } }, 'Look'),
        i > 0 ? el('button', { class: 'danger', onclick: () => { spec.views.splice(i, 1); sel = null; changed({ structural: true, rebuild: false }); } }, '✕') : null),
      row('Faces', ...slider(+v.yaw || 0, -180, 180, 5, val => { v.yaw = val; drawOverlay(); }, val => { v.yaw = val; changed({ rebuild: false }); }, x => {
        const d = ((+x % 360) + 360) % 360; return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(d / 45) % 8] + ` ${Math.round(+x)}°`; })),
      mode === 'advanced' ? row('Position', el('span', { class: 'note' }, 'x'), numIn(v.x, 0.05, val => { v.x = val; changed({ rebuild: false, structural: true }); }), el('span', { class: 'note' }, 'y'), numIn(v.y, 0.05, val => { v.y = val; changed({ rebuild: false, structural: true }); })) : null,
    );
    body.append(c);
  });
}

// ---------------------------------------------------------------- Render tab
let queue = [];
let estimateInfo = null;
function tabRender(body) {
  const q = spec.render.quality || 'standard';
  const qualities = mode === 'advanced' ? ['draft', 'standard', 'high'] : ['draft', 'standard'];
  const warns = allWarnings();
  body.append(
    el('h3', {}, 'Render'),
    el('p', { class: 'note' }, 'Blender renders each view as a full-quality 360° image on this PC. You can keep working while it renders; finished rooms go to the Library.'),
    row('Name', el('input', { type: 'text', class: 'grow', value: spec.name, onchange: e => { spec.name = e.target.value; changed({ rebuild: false }); } })),
    row('Quality', el('div', {}, radio('qual', qualities.map(k => [k, k[0].toUpperCase() + k.slice(1)]), q, v => { spec.render.quality = v; changed({ rebuild: false, structural: true }); }),
      el('div', { class: 'note' }, QUAL[q]))),
    row('Views', el('span', {}, spec.views.map(v => v.name).join(', '))),
    el('div', { class: 'note', id: 'estimate' }, 'Working out how long…'),
    warns.length ? el('p', { class: 'note warn' }, `${warns.length} thing${warns.length > 1 ? 's' : ''} to check first (see the list on the view). You can still render.`) : null,
    el('div', { class: 'row' }, el('button', { class: 'primary', onclick: startRender }, 'Render this room')),
    el('h4', {}, 'Queue'),
    el('div', { id: 'queueBox' }),
    el('h4', {}, 'See it in the room while you edit'),
    el('p', { class: 'note' }, 'Point Spouty (or an Igloo web layer) at this page to see the plain version of this room in IglooPreview as you change it:'),
    el('div', { class: 'copy' }, el('input', { type: 'text', readonly: true, value: `${location.origin}/builder/live.html` }),
      el('button', { onclick: e => { navigator.clipboard?.writeText(`${location.origin}/builder/live.html`); e.target.textContent = 'Copied'; } }, 'Copy')),
  );
  api('/api/estimate', { spec, quality: q }).then(j => {
    estimateInfo = j; const e = $('#estimate');
    if (e) e.textContent = `About ${fmtTime(j.seconds)} on this PC` + (j.ahead > 1 ? `, after ${fmtTime(j.ahead)} of renders already queued.` : '.');
  }).catch(() => {});
  drawQueue();
}
async function startRender() {
  try {
    const j = await api('/api/render', { spec, quality: spec.render.quality || 'standard', name: spec.name });
    toast(`Queued. About ${fmtTime(j.estimate)}${j.ahead > 1 ? `, starting in about ${fmtTime(j.ahead)}` : ''}.`);
    pollQueue(true);
  } catch (e) { toast(e.message, true); }
}
function drawQueue() {
  const box = $('#queueBox'); if (!box) return; box.innerHTML = '';
  const jobs = queue.slice().reverse();
  if (!jobs.length) { box.append(el('p', { class: 'note' }, 'Nothing rendering.')); return; }
  for (const j of jobs.slice(0, 10)) {
    const live = j.status === 'rendering' || j.status === 'queued';
    box.append(el('div', { class: 'card' },
      el('div', { class: 'head' }, el('b', {}, j.name), el('span', { class: 'pill ' + ({ done: 'ok', failed: 'bad', rendering: 'warn', queued: '' }[j.status] || '') }, j.status), el('span', { class: 'note' }, j.quality)),
      live ? el('div', { class: 'bar' }, el('div', { style: `width:${Math.round((j.progress || 0) * 100)}%` })) : null,
      el('div', { class: 'note' }, j.message || '',
        j.status === 'rendering' && j.eta ? ` · about ${fmtTime(j.eta)} left` : '',
        j.status === 'queued' ? ` · starts in about ${fmtTime(j.ahead || 0)}, takes about ${fmtTime(j.estimate)}` : ''),
      el('div', { class: 'row' },
        live ? el('button', { onclick: async () => { await api(`/api/queue/${j.id}/cancel`, {}); pollQueue(true); } }, 'Cancel') : null,
        j.status === 'done' ? el('button', { onclick: () => { tab = 'library'; markTabs(); renderTab(); } }, 'Open in library') : null)));
  }
  if (jobs.some(j => !['queued', 'rendering'].includes(j.status)))
    box.append(el('button', { onclick: async () => { await api('/api/queue/clear', {}); pollQueue(true); } }, 'Clear finished'));
}
let pollTimer = null;
async function pollQueue(force = false) {
  clearTimeout(pollTimer);
  try {
    const before = queue.filter(j => j.status === 'done').length;
    queue = await api('/api/queue');
    if (tab === 'render') drawQueue();
    const nowDone = queue.filter(j => j.status === 'done').length;
    if (nowDone > before && !force) { toast('A render has finished: it is in the Library.'); if (tab === 'library') renderTab(); }
  } catch { /* server not reachable */ }
  const active = queue.some(j => ['queued', 'rendering'].includes(j.status));
  pollTimer = setTimeout(pollQueue, active ? 1500 : 6000);
}

// ---------------------------------------------------------------- Library tab
function tabLibrary(body) {
  body.append(el('h3', {}, 'Library'),
    el('p', { class: 'note' }, 'Finished rooms. Download the 360° images (PNG for full quality, JPG for smaller files) with their credits, show one in IglooPreview through Spouty, or open one as a copy to make a variant.'));
  const box = el('div', { class: 'libgrid' }, el('p', { class: 'note' }, 'Loading…'));
  body.append(box);
  api('/api/library').then(list => {
    lastLibrary = list; box.innerHTML = '';
    if (!list.length) box.append(el('p', { class: 'note' }, 'No rooms rendered yet.'));
    for (const m of list) {
      const first = m.views[0];
      const base = `/library/${encodeURIComponent(m.id)}`;
      const pano = v => `/builder/pano.html?lib=${encodeURIComponent(m.id)}&view=${encodeURIComponent(v)}`;
      box.append(el('div', { class: 'card libcard' },
        el('img', { src: `${base}/thumb_${first}.jpg`, alt: '', loading: 'lazy', onerror: e => { e.target.src = `${base}/view_${first}.jpg`; } }),
        el('div', { class: 'head', style: 'margin-top:8px' }, el('b', {}, m.name), el('span', { class: 'pill' }, m.quality)),
        el('div', { class: 'kv' }, `${m.created} · ${m.style}, ${m.lighting} · ${m.resolution} · ${m.views.length} view${m.views.length > 1 ? 's' : ''} · ${fmtTime(m.render_seconds)}`),
        m.credit_required?.length ? el('div', { class: 'kv' }, el('span', { class: 'pill blue' }, 'credits must go with these images')) : null,
        el('div', { class: 'acts' },
          m.views.map(v => el('a', { href: pano(v), target: '_blank' }, el('button', {}, `View ${v}`))),
          el('a', { href: `/api/library/${encodeURIComponent(m.id)}/download.zip` }, el('button', { class: 'primary' }, 'Download all')),
          el('a', { href: `${base}/credits.md`, target: '_blank' }, el('button', {}, 'Credits')),
          el('button', { onclick: () => openCopy(m) }, 'Open as copy'),
          el('button', { onclick: () => fileLinks(m) }, 'Files…'),
          el('button', { class: 'danger', onclick: async () => { if (!confirm(`Remove "${m.name}" from the library? It moves to library/_removed.`)) return; await api(`/api/library/${m.id}/remove`, {}); renderTab(); } }, 'Remove'))));
    }
  }).catch(e => { box.innerHTML = ''; box.append(el('p', { class: 'note bad' }, e.message)); });
}
async function openCopy(m) {
  const s = await (await fetch(`/library/${encodeURIComponent(m.id)}/spec.json`)).json();
  s.name = (s.name || 'Room') + ' (copy)'; loadSpec(s); tab = 'room'; markTabs(); renderTab(); toast('Opened a copy. Change it and render again.');
}
function fileLinks(m) {
  const base = `${location.origin}/library/${encodeURIComponent(m.id)}`;
  showDialog(el('div', {},
    el('h3', {}, m.name),
    el('p', { class: 'note' }, 'Right-click a link to save it. The "raw" link shows just the image, full window: give it to Spouty to send it to IglooPreview.'),
    m.views.map(v => el('div', { class: 'card' }, el('b', {}, v),
      el('div', { class: 'acts', style: 'display:flex;gap:10px;flex-wrap:wrap;margin-top:6px' },
        el('a', { href: `${base}/view_${v}.png`, download: '' }, 'PNG'), el('a', { href: `${base}/view_${v}.jpg`, download: '' }, 'JPG'),
        el('a', { href: `/builder/pano.html?lib=${encodeURIComponent(m.id)}&view=${v}&raw=1`, target: '_blank' }, 'Raw (for Spouty)')),
      el('div', { class: 'copy', style: 'margin-top:6px' }, el('input', { type: 'text', readonly: true, value: `${location.origin}/builder/pano.html?lib=${encodeURIComponent(m.id)}&view=${v}&raw=1` })))),
    el('div', { class: 'kv' }, 'Blender scene: ', el('a', { href: `${base}/room.blend`, download: '' }, 'room.blend')),
    el('div', { class: 'acts' }, el('button', { value: 'close' }, 'Close'))));
}

// ================================================================== dialogs
function showDialog(content) { const b = $('#dlgBody'); b.innerHTML = ''; b.append(content); $('#dlg').showModal(); }
async function openDialog() {
  const rooms = await api('/api/rooms').catch(() => []);
  showDialog(el('div', {}, el('h3', {}, 'Open a room'),
    rooms.length ? el('ul', { class: 'list' }, rooms.map(r => el('li', { onclick: async () => { const s = await api('/api/rooms/' + encodeURIComponent(r.id)); $('#dlg').close(); loadSpec(s); } },
      el('span', { class: 'n' }, r.name), el('span', { class: 'note' }, r.saved)))) : el('p', { class: 'note' }, 'Nothing saved yet.'),
    el('div', { class: 'acts' }, el('button', { value: 'close' }, 'Cancel'))));
}
function newDialog() {
  showDialog(el('div', {}, el('h3', {}, 'New room'), el('p', { class: 'note' }, 'Which physical room is it for?'),
    el('ul', { class: 'list' }, presets.map(p => el('li', { onclick: () => { $('#dlg').close(); loadSpec(blankSpec(p)); } }, el('span', { class: 'n' }, p.name), el('span', { class: 'note' }, `${p.width} × ${p.depth} × ${p.height} m`))),
      el('li', { onclick: () => { $('#dlg').close(); loadSpec(blankSpec({ id: 'custom', width: 6, depth: 5, height: 2.4, eye: 1.12 })); tab = 'room'; markTabs(); renderTab(); } }, el('span', { class: 'n' }, 'Custom size…'))),
    el('div', { class: 'acts' }, el('button', { value: 'close' }, 'Cancel'))));
}
async function saveRoom() {
  try { const j = await api('/api/rooms', { spec }); toast(`Saved as "${spec.name}".`); return j; } catch (e) { toast(e.message, true); }
}
let status = {};
function openSettings() {
  const tok = el('input', { type: 'password', class: 'grow', placeholder: status.sketchfab_token ? '(saved - type to replace)' : 'paste your token' });
  const bl = el('input', { type: 'text', class: 'grow', value: status.blender || '' });
  const net = el('input', { type: 'checkbox', checked: !!status.allow_network });
  const fl = el('input', { type: 'number', step: 0.05, value: floorLimit, min: 0, max: 3 });
  showDialog(el('div', {}, el('h3', {}, 'Settings'),
    row('Blender', bl), el('p', { class: 'note' }, 'The full path to blender.exe. Found automatically if it is installed in the usual place.'),
    row('Sketchfab token', tok), el('p', { class: 'note' }, 'Needed to import from Sketchfab. Get it from ', el('a', { href: 'https://sketchfab.com/settings/password', target: '_blank', rel: 'noopener' }, 'sketchfab.com → Settings → Password & API'), '. It stays on this PC in config.json.'),
    row('Floor warning', fl, el('span', { class: 'note' }, 'm: warn when a model reaches further than this onto the projected floor')),
    row('Other devices', el('label', { class: 'chk', style: 'background:none;border:0;padding:0' }, net, 'Let other devices on this network open the builder (restart the server after changing)')),
    el('div', { class: 'acts' }, el('button', { value: 'cancel' }, 'Cancel'), el('button', { class: 'primary', value: 'ok', onclick: async e => {
      e.preventDefault();
      const body = { blender: bl.value.trim(), allow_network: net.checked }; if (tok.value.trim()) body.sketchfab_token = tok.value.trim();
      floorLimit = Math.max(0, +fl.value || 0.5); store.set('rb_floor_limit', floorLimit);
      try { await api('/api/config', body); await refreshStatus(); $('#dlg').close(); updateWarnings(); toast('Settings saved.'); } catch (err) { toast(err.message, true); }
    } }, 'Save'))));
}
async function refreshStatus() {
  try {
    status = await api('/api/status');
    const d = $('#statusDot'); d.className = 'status ' + (status.blender_found ? 'ok' : 'bad');
    d.textContent = status.blender_found ? 'Blender ready' : 'Blender not found';
    d.title = status.blender || 'Set the path in Settings';
  } catch { $('#statusDot').className = 'status bad'; $('#statusDot').textContent = 'Server not running'; }
}

// ================================================================== wiring
document.querySelectorAll('#tabs button').forEach(b => b.addEventListener('click', () => { tab = b.dataset.tab; markTabs(); renderTab(); }));
document.querySelectorAll('#viewBar [data-cam]').forEach(b => b.addEventListener('click', () => setCamMode(b.dataset.cam)));
document.querySelectorAll('.mode button').forEach(b => b.addEventListener('click', () => {
  mode = b.dataset.mode; store.set('rb_mode', mode);
  document.querySelectorAll('.mode button').forEach(x => x.classList.toggle('on', x === b));
  if (mode === 'simple' && spec.render.quality === 'high') spec.render.quality = 'standard';
  renderTab(); showInspector();
}));
$('#chkFloor').addEventListener('change', () => drawOverlay());
$('#roomName').addEventListener('change', e => { spec.name = e.target.value.trim() || 'Room'; changed({ rebuild: false }); });
$('#btnNew').addEventListener('click', newDialog);
$('#btnOpen').addEventListener('click', openDialog);
$('#btnSave').addEventListener('click', saveRoom);
$('#btnUndo').addEventListener('click', undo);
$('#btnRedo').addEventListener('click', redo);
$('#btnSettings').addEventListener('click', openSettings);

(async function init() {
  document.querySelectorAll('.mode button').forEach(x => x.classList.toggle('on', x.dataset.mode === mode));
  await refreshStatus();
  try { presets = (await api('/api/presets')).rooms; } catch { presets = []; }
  try { outsideCfg = await api('/api/outside'); } catch { /* no outside presets */ }
  try { catalogue = await api('/api/catalogue'); } catch { catalogue = []; }
  resize();
  const draft = store.get('rb_draft', null);
  if (draft && draft.room) loadSpec(draft);
  else {
    try { loadSpec(await api('/api/rooms/example:glenda_modern')); } catch { loadSpec(blankSpec()); }
  }
  setCamMode('plan');
  resize();
  frame();
  pollQueue();
})();
