'use strict';
/* Tour Builder: join Room Builder library rooms into a tour with clickable markers.
   A tour is tours/<id>.json on the Room Builder server:
   { name, description, start, items: [{id, name}],
     rooms: [{ id, name, lib, view, dims: {w, d, h, eye, preset}, intro, cardWall, end, endText,
               markers: [{ id, type: go|info|question|item, yaw, pitch, label, hidden, radius,
                           go: target, requires: [item ids], code, codePrompt, lockedText
                           info: title, text      item: item, text
                           question: text, retry, options: [{ text, correct, feedback, go, give }] }] }] }
   yaw/pitch are degrees in the 360 image: yaw 0 = image centre (the Front wall), + to the right; pitch 0 = eye height.
   Played by tour.html (here for previews, and by the scene server in the room, with the tablet). */
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const uid = (p) => p + Math.random().toString(36).slice(2, 8);
const COL = { go: '#4fd18b', info: '#5aa2e0', question: '#e8a33d', item: '#f3d36b', use: '#c58cf0' };
const TYPE_NAME = { go: 'Door / go', info: 'Info', question: 'Question', item: 'Item', use: 'Give / use' };
const WALLS = [['front', 'Front'], ['right', 'Right'], ['back', 'Back'], ['left', 'Left']];
const wallName = (yaw) => ['Back', 'Left', 'Front', 'Right', 'Back'][Math.round((((yaw + 540) % 360) - 180 + 180) / 90)];
const wrap180 = (a) => ((a + 540) % 360) - 180;
const r1 = (v) => Math.round(v * 10) / 10;

let LIB = [], PRESETS = {}, CAT = [], tour = blank(), tourId = null, dirty = false;
const catById = (id) => CAT.find((m) => m.id === id);
const catThumb = (m) => m && m.thumb ? `/catalogue/models/${encodeURIComponent(m.id)}/${m.thumb}` : '';
const itemModel = (id) => { const it = itemById(id); return it && it.model ? catById(it.model) : null; };
const has3d = (m) => m.type === 'item' && m.show3d !== false && !!itemModel(m.item);
const sel = { room: null, marker: null };
let tool = 'select', zoom = 1, zones = true;
const imgs = {};

async function api(url, body) {
  const r = await fetch(url, body === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || (d && d.error)) throw new Error((d && d.error) || r.status);
  return d;
}
function toast(t, err) {
  const el = $('toast'); el.textContent = t; el.className = err ? 'err' : ''; el.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, err ? 6000 : 2500);
}
function blank() { return { version: 1, name: 'New tour', description: '', start: null, items: [], rooms: [] }; }
const room = () => tour.rooms.find((r) => r.id === sel.room) || null;
const marker = () => { const r = room(); return (r && (r.markers || []).find((m) => m.id === sel.marker)) || null; };
const roomById = (id) => tour.rooms.find((r) => r.id === id);
const itemById = (id) => tour.items.find((i) => i.id === id);
function setDirty(d = true) { dirty = d; $('dirty').textContent = d ? '● Unsaved changes' : ''; }
const libById = (id) => LIB.find((l) => l.id === id);
const thumb = (lib, view) => `/library/${encodeURIComponent(lib)}/thumb_${encodeURIComponent(view || 'centre')}.jpg`;
const full = (lib, view) => `/library/${encodeURIComponent(lib)}/view_${encodeURIComponent(view || 'centre')}.jpg`;
const physName = (d) => d && d.preset && PRESETS[d.preset] ? PRESETS[d.preset].name.split(' (')[0] : (d ? `custom ${d.w}×${d.d}×${d.h} m` : '');

// ------------------------------------------------------------------ the physical room: what lands where (projection centre = room centre)
function surf(r, yaw) {
  const d = r.dims || {}, hw = (d.w || 6.4) / 2, hd = (d.d || 5.71) / 2, H = d.h || 2.244, E = d.eye || H / 2;
  const a = yaw * Math.PI / 180, sx = Math.abs(Math.sin(a)), cy = Math.abs(Math.cos(a));
  const dist = Math.min(sx > 1e-6 ? hw / sx : 1e9, cy > 1e-6 ? hd / cy : 1e9);
  const deg = (v) => Math.atan(v / dist) * 180 / Math.PI;
  return { dist, floor: deg(-E), top: deg(H - E), lo: deg(0.3 - E), hi: deg(H - 0.15 - E) };
}
function band(r, m) {
  const s = surf(r, m.yaw);
  if (m.pitch < s.lo) return m.pitch < s.floor ? 'is on the projected floor: move it up onto a wall' : 'is very low on the wall (under 30 cm): move it up';
  if (m.pitch > s.hi) return m.pitch > s.top ? 'is on the ceiling, which isn\'t projected: move it down' : 'is right at the top of the wall: move it down';
  return '';
}

// ------------------------------------------------------------------ checks
function gives(itemId) {
  return tour.rooms.some((r) => (r.markers || []).some((m) => (m.type === 'item' && m.take !== false && m.item === itemId) ||
    (m.type === 'question' && (m.options || []).some((o) => o.give === itemId)) || (m.type === 'use' && (m.accepts || []).some((a) => a.give === itemId))));
}
function checks() {
  const out = [];
  if (!tour.rooms.length) return [{ level: 'info', text: 'Add a room from the library to start.' }];
  const start = roomById(tour.start) ? tour.start : tour.rooms[0].id, reach = new Set([start]), q = [start];
  while (q.length) {
    const r = roomById(q.shift());
    for (const m of r.markers || []) {
      const ts = m.type === 'go' ? [m.target] : m.type === 'question' ? (m.options || []).map((o) => o.go) : m.type === 'use' ? (m.accepts || []).map((a) => a.go) : [];
      for (const t of ts) if (t && roomById(t) && !reach.has(t)) { reach.add(t); q.push(t); }
    }
  }
  for (const r of tour.rooms) {
    const rn = r.name || 'Room';
    if (!reach.has(r.id)) out.push({ level: 'warn', room: r.id, text: `${rn}: there's no way in from the start room.` });
    const exits = (r.markers || []).some((m) => (m.type === 'go' && m.target) || (m.type === 'question' && (m.options || []).some((o) => o.go)) || (m.type === 'use' && (m.accepts || []).some((a) => a.go)));
    if (!exits && !r.end) out.push({ level: 'info', room: r.id, text: `${rn}: no way out. Add a door, or tick "Ends the tour".` });
    for (const m of r.markers || []) {
      const at = { room: r.id, marker: m.id }, mn = `${rn} › ${m.label || TYPE_NAME[m.type]}`;
      if (m.type === 'go' && !roomById(m.target)) out.push({ level: 'warn', ...at, text: `${mn}: doesn't lead anywhere yet.` });
      if (m.type === 'go') for (const i of m.requires || []) if (itemById(i) && !gives(i)) out.push({ level: 'warn', ...at, text: `${mn}: needs "${itemById(i).name}", but nothing in the tour gives it.` });
      if (m.type === 'question') {
        if (!(m.text || '').trim()) out.push({ level: 'warn', ...at, text: `${mn}: no question written yet.` });
        if ((m.options || []).filter((o) => (o.text || '').trim()).length < 2) out.push({ level: 'warn', ...at, text: `${mn}: needs at least two answers.` });
      }
      if (m.type === 'item' && !itemById(m.item)) out.push({ level: 'warn', ...at, text: `${mn}: choose which item this is.` });
      if (m.type === 'info' && !(m.text || '').trim()) out.push({ level: 'info', ...at, text: `${mn}: the card is empty.` });
      if (m.type === 'use' && !(m.accepts || []).some((a) => itemById(a.item))) out.push({ level: 'warn', ...at, text: `${mn}: say which items it takes.` });
      if (m.type === 'use') for (const a of m.accepts || []) if (itemById(a.item) && !gives(a.item)) out.push({ level: 'warn', ...at, text: `${mn}: takes "${itemById(a.item).name}", but nothing in the tour gives it.` });
      const z = band(r, m); if (z) out.push({ level: 'warn', ...at, text: `${mn} ${z}.` });
    }
  }
  const phys = new Set(tour.rooms.map((r) => physName(r.dims)));
  if (phys.size > 1) out.push({ level: 'warn', text: `The rooms were built for different physical rooms (${[...phys].join(', ')}). A tour plays in one room, so use renders built for that room.` });
  return out;
}

// ------------------------------------------------------------------ live 3D objects (the same layer the player uses), drawn into the picture
let t3 = null, t3sig = '', t3room = '';
const c3 = document.createElement('canvas');
import('./tour3d.js').then((mod) => { t3 = mod.createTour3D({ canvas: c3, base: '/', cube: 512, onLoad: () => draw() }); draw(); })
  .catch((e) => console.error('3D preview is off:', e));
(function loop() { if (t3 && t3.frame()) draw(); requestAnimationFrame(loop); })();
const eyeOfR = (r) => (r && r.dims && +r.dims.eye) || 1.12;
function sync3d(r) {
  if (!t3) return;
  const url = r ? full(r.lib, r.view) : '';
  if (url !== t3room) { t3room = url; if (url) t3.setRoom(url); }
  const list = r ? (r.markers || []).filter(has3d).map((m) => ({ key: m.id, model: itemModel(m.item).id, yaw: m.yaw, dist: m.dist, h: m.h, eye: eyeOfR(r), turn: m.turn || 0, size: m.size || 1 })) : [];
  const sig = JSON.stringify(list);
  if (sig !== t3sig) { t3sig = sig; t3.sync(list); }
  const w = Math.round(cssW * Math.min(devicePixelRatio || 1, 1.5));
  if (w > 2 && c3.width !== w) t3.setSize(w, Math.round(w / 2));
}
// 3D items stand on a surface: the marker is the point under the object. Dragging keeps the height and works out the distance.
function place3d(r, m, how) {
  const eye = eyeOfR(r), wd = surf(r, m.yaw).dist, tp = Math.tan(m.pitch * Math.PI / 180);
  if (how === 'init' || m.dist == null || m.h == null) {
    m.turn = m.turn || 0; m.size = m.size || 1;
    if (m.pitch < -3) { m.dist = Math.min(wd - 0.1, Math.max(0.5, (0.75 - eye) / tp)); m.h = eye + m.dist * tp; }
    else { m.dist = Math.max(0.5, wd - 0.3); m.h = eye + m.dist * tp; }
  } else if (how === 'drag') {
    if (m.pitch < -2) { const d = (m.h - eye) / tp; m.dist = Math.min(wd - 0.05, Math.max(0.4, d)); }
    else m.h = eye + m.dist * tp;
  }
  if (how === 'drag' || how === 'fields') m.pitch = r1(Math.atan2(m.h - eye, m.dist) * 180 / Math.PI);
  m.dist = Math.round(m.dist * 100) / 100; m.h = Math.round(m.h * 100) / 100;
}

// ------------------------------------------------------------------ drawing the picture
const cv = $('pano'), ctx = cv.getContext('2d');
let cssW = 0, cssH = 0;
function getImg(r) {
  const u = full(r.lib, r.view);
  if (!imgs[u]) { const im = new Image(); im.onload = draw; im.onerror = () => { im.failed = true; draw(); }; im.src = u; imgs[u] = im; }
  return imgs[u];
}
const X = (yaw) => (yaw / 360 + 0.5) * cssW, Y = (pitch) => (0.5 - pitch / 180) * cssH;
function draw() {
  const r = room();
  $('empty').style.display = r ? 'none' : 'flex';             // (CSS display beats the hidden attribute)
  const w = Math.max(400, Math.floor(($('scroller').clientWidth - 2) * zoom)), h = Math.round(w / 2), dpr = devicePixelRatio || 1;
  if (w !== cssW || h !== cssH || cv.width !== Math.round(w * dpr)) {
    cssW = w; cssH = h; cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.width = w + 'px'; cv.style.height = h + 'px';
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  cv.style.display = r ? 'block' : 'none';
  if (!r) return;
  const im = getImg(r);
  if (im.complete && im.naturalWidth) ctx.drawImage(im, 0, 0, w, h);
  sync3d(r); if (t3 && c3.width > 2) ctx.drawImage(c3, 0, 0, w, h);
  else { ctx.fillStyle = '#1b1e22'; ctx.fillRect(0, 0, w, h); ctx.fillStyle = '#9aa3ad'; ctx.font = '14px Segoe UI, sans-serif'; ctx.fillText(im.failed ? 'Could not load this render from the library' : 'Loading the render…', 16, 24); }
  if (zones) drawZones(r, w, h);
  ctx.font = '600 12px Segoe UI, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  for (const [yaw, n] of [[-180, 'Back'], [-90, 'Left'], [0, 'Front'], [90, 'Right'], [180, 'Back']]) {
    const x = Math.min(w - 24, Math.max(24, X(yaw)));
    ctx.fillStyle = 'rgba(0,0,0,.55)'; ctx.fillRect(x - 26, 4, 52, 18); ctx.fillStyle = '#f3c27a'; ctx.fillText(n, x, 7);
  }
  for (const m of r.markers || []) drawMarker(r, m);
}
function drawZones(r, w, h) {
  const N = 180, floor = [], top = [];
  for (let i = 0; i <= N; i++) { const yaw = -180 + 360 * i / N, s = surf(r, yaw); floor.push([X(yaw), Y(s.floor)]); top.push([X(yaw), Y(s.top)]); }
  ctx.beginPath(); ctx.moveTo(0, h); for (const [x, y] of floor) ctx.lineTo(x, y); ctx.lineTo(w, h); ctx.closePath();
  ctx.fillStyle = 'rgba(232,163,61,.26)'; ctx.fill();
  ctx.beginPath(); ctx.moveTo(0, 0); for (const [x, y] of top) ctx.lineTo(x, y); ctx.lineTo(w, 0); ctx.closePath();
  ctx.fillStyle = 'rgba(0,0,0,.55)'; ctx.fill();
  ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
  ctx.strokeStyle = 'rgba(243,194,122,.9)'; ctx.beginPath(); floor.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
  ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.beginPath(); top.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
  ctx.setLineDash([]);
  ctx.font = '12px Segoe UI, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = 'rgba(255,230,190,.9)';
  ctx.fillText('projected floor: keep markers off it', X(0), (Y(surf(r, 0).floor) + h) / 2);
  ctx.fillStyle = 'rgba(255,255,255,.7)'; ctx.fillText('ceiling: not projected', X(0), Y(surf(r, 0).top) / 2 + 12);
}
function drawObj3d(r, m, hh) {                     // a 3D item: a ring round the object, a dot where it stands
  const on = m.id === sel.marker;
  for (const ox of [0, -cssW, cssW]) {
    const x = X(hh.yaw) + ox, y = Y(hh.pitch), rx = hh.rad / 360 * cssW / Math.max(0.3, Math.cos(hh.pitch * Math.PI / 180)) + 4, ry = hh.rad / 180 * cssH + 4;
    if (x < -80 || x > cssW + 80) continue;
    ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); ctx.lineWidth = on ? 3 : 2; ctx.strokeStyle = on ? '#fff' : COL.item;
    if (m.hidden) ctx.setLineDash([4, 3]); ctx.stroke(); ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(X(m.yaw) + ox, Y(m.pitch), 3, 0, Math.PI * 2); ctx.fillStyle = COL.item; ctx.fill();
    const lab = m.label || TYPE_NAME.item;
    ctx.font = '600 12px Segoe UI, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(0,0,0,.8)';
    ctx.strokeText(lab, x, y + ry + 3); ctx.fillStyle = '#fff'; ctx.fillText(lab, x, y + ry + 3);
    if (band(r, m)) { ctx.beginPath(); ctx.arc(x + rx, y - ry, 7, 0, Math.PI * 2); ctx.fillStyle = '#e0605a'; ctx.fill(); ctx.fillStyle = '#fff'; ctx.font = 'bold 10px Segoe UI, sans-serif'; ctx.textBaseline = 'middle'; ctx.fillText('!', x + rx, y - ry + 1); }
  }
}
function drawMarker(r, m) {
  const hh = has3d(m) && t3 ? t3.hit(m.id) : null;
  if (hh) return drawObj3d(r, m, hh);
  const on = m.id === sel.marker, col = COL[m.type] || '#fff';
  for (const ox of [0, -cssW, cssW]) {
    const x = X(m.yaw) + ox, y = Y(m.pitch); if (x < -60 || x > cssW + 60) continue;
    if (m.hidden && !has3d(m)) {                      // the area students must tap to find it
      const rx = (m.radius || 6) / 360 * cssW / Math.max(0.3, Math.cos(m.pitch * Math.PI / 180)), ry = (m.radius || 6) / 180 * cssH;
      ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); ctx.fillStyle = 'rgba(243,211,107,.12)'; ctx.fill();
      ctx.setLineDash([4, 3]); ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]);
    }
    if (on) { ctx.beginPath(); ctx.arc(x, y, 15, 0, Math.PI * 2); ctx.strokeStyle = '#fff'; ctx.lineWidth = 3; ctx.stroke(); }
    ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.fillStyle = 'rgba(10,14,20,.75)'; ctx.fill();
    ctx.lineWidth = 3; ctx.strokeStyle = col; if (m.hidden) ctx.setLineDash([3, 2]); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#fff'; ctx.font = 'bold 11px Segoe UI, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText({ go: (m.requires || []).length || m.code ? '🔒' : '↑', info: 'i', question: '?', item: '★', use: '☺' }[m.type] || '', x, y + 1);
    const lab = m.label || TYPE_NAME[m.type];
    ctx.font = '600 12px Segoe UI, sans-serif'; ctx.textBaseline = 'top'; ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(0,0,0,.8)';
    ctx.strokeText(lab, x, y + 15); ctx.fillStyle = '#fff'; ctx.fillText(lab, x, y + 15);
    if (band(r, m)) { ctx.beginPath(); ctx.arc(x + 11, y - 11, 7, 0, Math.PI * 2); ctx.fillStyle = '#e0605a'; ctx.fill(); ctx.fillStyle = '#fff'; ctx.font = 'bold 10px Segoe UI, sans-serif'; ctx.textBaseline = 'middle'; ctx.fillText('!', x + 11, y - 10); }
  }
}

// ------------------------------------------------------------------ placing and moving markers
let drag = null;
function at(e) {
  const b = cv.getBoundingClientRect(), u = (e.clientX - b.left) / b.width, v = (e.clientY - b.top) / b.height;
  return { x: e.clientX - b.left, y: e.clientY - b.top, yaw: r1(wrap180((u - 0.5) * 360)), pitch: r1(Math.max(-85, Math.min(85, (0.5 - v) * 180))) };
}
function hitMarker(p) {
  const r = room(); if (!r) return null;
  let best = null, bd = 16;
  for (const m of r.markers || []) for (const ox of [0, -cssW, cssW]) {
    const hh = has3d(m) && t3 ? t3.hit(m.id) : null;
    const d = hh ? Math.max(0, Math.hypot(X(hh.yaw) + ox - p.x, Y(hh.pitch) - p.y) - Math.max(6, hh.rad / 180 * cssH))
                 : Math.hypot(X(m.yaw) + ox - p.x, Y(m.pitch) - p.y);
    if (d < bd) { bd = d; best = m; }
  }
  return best;
}
function newMarker(type, yaw, pitch) {
  const m = { id: uid('m'), type, yaw, pitch, label: TYPE_NAME[type], auto: true };
  if (type === 'go') Object.assign(m, { label: 'Door', target: null, requires: [], code: '' });
  if (type === 'info') Object.assign(m, { label: 'Info', title: '', text: '' });
  if (type === 'question') Object.assign(m, { label: 'Question', text: '', retry: false, options: [{ text: '', correct: true, feedback: '' }, { text: '', correct: false, feedback: '' }] });
  if (type === 'item') {
    let it = tour.items[0];
    if (!it) { it = { id: uid('i'), name: 'Key' }; tour.items.push(it); }
    Object.assign(m, { hidden: !itemModel(it.id), radius: 6, item: it.id, label: it.name, text: '' });
  }
  if (type === 'use') Object.assign(m, { label: 'Person', text: '', accepts: [], wrongText: '' });
  return m;
}
cv.addEventListener('pointerdown', (e) => {
  const r = room(); if (!r) return;
  const p = at(e), hit = hitMarker(p);
  if (hit) { sel.marker = hit.id; drag = { m: hit, moved: false, dx: hit.yaw - p.yaw, dy: hit.pitch - p.pitch }; cv.setPointerCapture(e.pointerId); }
  else if (tool !== 'select') {
    const m = newMarker(tool, p.yaw, p.pitch); r.markers = r.markers || []; r.markers.push(m); sel.marker = m.id;
    if (has3d(m)) place3d(r, m, 'init');
    setTool('select'); setDirty(); renderLeft();
  } else sel.marker = null;
  renderRight(); draw();
});
cv.addEventListener('pointermove', (e) => {
  const p = at(e), r = room();
  if (r) { const s = surf(r, p.yaw); const where = p.pitch < s.floor ? 'projected floor' : p.pitch > s.top ? 'ceiling (not projected)' : `${wallName(p.yaw)} wall, ${((s.dist * Math.tan(p.pitch * Math.PI / 180)) + ((r.dims && r.dims.eye) || 1.12)).toFixed(2)} m up`;
    $('status').textContent = `yaw ${p.yaw}°, pitch ${p.pitch}° · ${where}` + (tool !== 'select' ? ` · click to add: ${TYPE_NAME[tool]}` : ''); }
  if (!drag) return;
  drag.moved = true;
  drag.m.yaw = r1(wrap180(p.yaw + drag.dx)); drag.m.pitch = r1(Math.max(-85, Math.min(85, p.pitch + drag.dy)));
  if (has3d(drag.m)) place3d(r, drag.m, 'drag');
  for (const k of ['yaw', 'pitch', 'dist', 'h']) { const f = $('right').querySelector(`[data-m=${k}]`); if (f) f.value = drag.m[k]; }
  draw();
});
cv.addEventListener('pointerup', () => { if (drag && drag.moved) { setDirty(); renderLeft(); renderRight(); } drag = null; });
function setTool(t) { tool = t; $('toolSeg').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.tool === t)); cv.style.cursor = t === 'select' ? 'default' : 'crosshair'; }
$('toolSeg').addEventListener('click', (e) => { const b = e.target.closest('[data-tool]'); if (b) setTool(b.dataset.tool); });
$('zoomSeg').addEventListener('click', (e) => { const b = e.target.closest('[data-z]'); if (!b) return; zoom = +b.dataset.z; $('zoomSeg').querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b)); draw(); });
$('chkZones').addEventListener('change', (e) => { zones = e.target.checked; draw(); });
addEventListener('resize', draw);

// ------------------------------------------------------------------ left panel: tour, items, rooms, this room, checks
function opts(list, cur, none) {
  return (none ? `<option value="">${esc(none)}</option>` : '') + list.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(l)}</option>`).join('');
}
function renderLeft() {
  const r = room(), ck = checks();
  const roomsOpts = tour.rooms.map((x) => [x.id, x.name || 'Room']);
  let h = `<h3>Tour</h3>
    <label class="f"><span>Description (shown in the scene list)</span><textarea data-t="description" rows="2">${esc(tour.description)}</textarea></label>
    <label class="f"><span>Starts in</span><select data-t="start">${opts(roomsOpts, tour.start || (tour.rooms[0] || {}).id)}</select></label>
    <h3>Items to find <button type="button" data-act="addItem">+ Item</button></h3>`;
  h += tour.items.length ? tour.items.map((i) => { const cm = i.model && catById(i.model);
      return `<div class="itemrow">${cm && cm.thumb ? `<img src="${esc(catThumb(cm))}" alt="">` : '<span class="noimg" title="No 3D model"></span>'}<input type="text" data-item="${esc(i.id)}" value="${esc(i.name)}" aria-label="Item name">` +
        `<button type="button" data-act="itemEdit" data-id="${esc(i.id)}" title="3D model, description and pages to read">Edit</button><button type="button" data-act="delItem" data-id="${esc(i.id)}" title="Remove this item">×</button></div>`; }).join('')
    : '<div class="small">Things to find and carry: notes, a medicine, a key. Give each one a 3D model to pick up and turn over, and pages to read. Doors can need them; people can take them.</div>';
  h += `<h3>Rooms <button type="button" data-act="addRoom">+ Room</button></h3><div class="rooms">` +
    (tour.rooms.map((x) => `<div class="room${x.id === sel.room ? ' on' : ''}" data-room="${esc(x.id)}"><img src="${thumb(x.lib, x.view)}" alt="" loading="lazy">
      <div><b>${esc(x.name || 'Room')}${x.id === (tour.start || tour.rooms[0].id) ? '<span class="badge start">start</span>' : ''}${x.end ? '<span class="badge end">end</span>' : ''}</b>
      <small>${(x.markers || []).length} markers · ${esc(physName(x.dims))}</small></div></div>`).join('') || '<div class="small">No rooms yet. Add rendered rooms from the Room Builder library.</div>') + '</div>';
  if (r) {
    const lib = libById(r.lib);
    h += `<h3>This room</h3>
      <label class="f"><span>Name</span><input type="text" data-r="name" value="${esc(r.name)}"></label>
      <div class="f"><span>Picture</span><div class="row"><span class="small" style="flex:1">${esc(lib ? lib.name : r.lib)}${r.view && r.view !== 'centre' ? ' (' + esc(r.view) + ' view)' : ''}${lib ? '' : ' – not in the library any more'}</span><button type="button" data-act="changePic">Change</button></div></div>
      <label class="f"><span>Arrival card (optional, shown when students first arrive)</span><textarea data-r="intro" rows="3">${esc(r.intro)}</textarea></label>
      <label class="f"><span>Cards and messages go on the</span><select data-r="cardWall">${opts(WALLS, r.cardWall || 'front')}</select></label>
      <label class="chk"><input type="checkbox" data-r="end"${r.end ? ' checked' : ''}> Ends the tour (shows a summary)</label>
      ${r.end ? `<label class="f"><span>End message</span><textarea data-r="endText" rows="3">${esc(r.endText)}</textarea></label>` : ''}
      <div class="row" style="flex-wrap:wrap"><button type="button" data-act="playHere">Play from here</button><button type="button" data-act="upRoom" title="Move up the list">↑</button><button type="button" data-act="downRoom" title="Move down the list">↓</button><button type="button" class="danger" data-act="delRoom" style="margin-left:auto">Remove room</button></div>`;
  }
  h += `<h3>Checks</h3><div class="checks">` + (ck.length ? ck.map((c, i) => `<div class="${c.level}" data-ck="${i}">${esc(c.text)}</div>`).join('') : '<div class="ok">All good: every room can be reached and every marker is on a wall.</div>') + '</div>';
  $('left').innerHTML = h;
  $('left')._ck = ck;
}
$('left').addEventListener('input', (e) => leftField(e, false));
$('left').addEventListener('change', (e) => leftField(e, true));
function leftField(e, isChange) {
  const el = e.target;
  if (!isChange && (el.type === 'checkbox' || el.tagName === 'SELECT')) return;
  const r = room();
  if (el.dataset.t) tour[el.dataset.t] = el.value || null;
  else if (el.dataset.item) { const it = itemById(el.dataset.item); if (!it) return; it.name = el.value;
    for (const x of tour.rooms) for (const m of x.markers || []) if (m.type === 'item' && m.item === it.id && m.auto) m.label = it.name;
    if (isChange) renderRight(); }
  else if (el.dataset.r && r) {
    const k = el.dataset.r; r[k] = el.type === 'checkbox' ? el.checked : el.value;
    if (k === 'name') for (const x of tour.rooms) for (const m of x.markers || []) if (m.type === 'go' && m.target === r.id && m.auto) m.label = r.name;
    if (k === 'end') renderLeft();
    if (k === 'name' && isChange) { renderLeft(); renderRight(); }
  } else return;
  setDirty(); draw();
  if (isChange && !el.dataset.r && !el.dataset.item) renderLeft();
}
$('left').addEventListener('click', (e) => {
  const ck = e.target.closest('[data-ck]');
  if (ck) { const c = $('left')._ck[+ck.dataset.ck]; if (c && c.room) { sel.room = c.room; sel.marker = c.marker || null; renderAll(); } return; }
  const rr = e.target.closest('[data-room]');
  if (rr) { sel.room = rr.dataset.room; sel.marker = null; renderAll(); return; }
  const b = e.target.closest('[data-act]'); if (!b) return;
  const r = room(), act = b.dataset.act;
  if (act === 'itemEdit') { itemDialog(b.dataset.id); return; }
  if (act === 'addItem') { tour.items.push({ id: uid('i'), name: `Item ${tour.items.length + 1}` }); setDirty(); renderLeft(); renderRight(); const ins = $('left').querySelectorAll('[data-item]'); if (ins.length) { ins[ins.length - 1].focus(); ins[ins.length - 1].select(); } }
  if (act === 'delItem') {
    const id = b.dataset.id, used = tour.rooms.some((x) => (x.markers || []).some((m) => m.item === id || (m.requires || []).includes(id) || (m.options || []).some((o) => o.give === id)));
    if (used && !confirm('This item is used by markers. Remove it anyway? (Doors stop needing it; item markers lose it.)')) return;
    tour.items = tour.items.filter((i) => i.id !== id);
    for (const x of tour.rooms) for (const m of x.markers || []) {
      if (m.item === id) m.item = null; if (m.requires) m.requires = m.requires.filter((i) => i !== id);
      for (const o of m.options || []) if (o.give === id) o.give = null;
      if (m.accepts) { m.accepts = m.accepts.filter((a) => a.item !== id); for (const a of m.accepts) if (a.give === id) a.give = null; }
    }
    setDirty(); renderAll();
  }
  if (act === 'addRoom') pickRoom('Add a room', (lib, view) => {
    const meta = libById(lib), nr = { id: uid('r'), name: meta.name + (view !== 'centre' ? ` (${view})` : ''), lib, view, dims: dimsOf(meta),
                                       intro: '', cardWall: 'front', end: false, endText: '', markers: [] };
    tour.rooms.push(nr); if (!tour.start) tour.start = nr.id; sel.room = nr.id; sel.marker = null; setDirty(); renderAll();
  });
  if (!r) return;
  if (act === 'changePic') pickRoom('Change the picture', (lib, view) => { r.lib = lib; r.view = view; r.dims = dimsOf(libById(lib)); setDirty(); renderAll(); });
  if (act === 'playHere') play(true, r.id);
  if (act === 'upRoom' || act === 'downRoom') {
    const i = tour.rooms.indexOf(r), j = i + (act === 'upRoom' ? -1 : 1); if (j < 0 || j >= tour.rooms.length) return;
    tour.rooms.splice(i, 1); tour.rooms.splice(j, 0, r); setDirty(); renderLeft();
  }
  if (act === 'delRoom') {
    if (!confirm(`Remove "${r.name}" and its ${(r.markers || []).length} markers from the tour? (The render stays in the library.)`)) return;
    tour.rooms = tour.rooms.filter((x) => x !== r);
    for (const x of tour.rooms) for (const m of x.markers || []) { if (m.target === r.id) m.target = null; for (const o of [...(m.options || []), ...(m.accepts || [])]) if (o.go === r.id) o.go = null; }
    if (tour.start === r.id) tour.start = tour.rooms[0] ? tour.rooms[0].id : null;
    sel.room = tour.rooms[0] ? tour.rooms[0].id : null; sel.marker = null; setDirty(); renderAll();
  }
});
function dimsOf(meta) {
  const rm = (meta && meta.room) || {}, pre = PRESETS[rm.preset];
  const h = +rm.height || (pre && pre.height) || 2.244;
  return { w: +rm.width || 6.4, d: +rm.depth || 5.71, h, eye: (pre && pre.eye) || Math.round(h / 2 * 1000) / 1000, preset: rm.preset || 'custom' };
}

// ------------------------------------------------------------------ right panel: the selected marker
function renderRight() {
  const r = room(), m = marker();
  if (!r) { $('right').innerHTML = '<h3>Markers</h3><div class="small">Add a room, then click its picture to place doors, info cards, questions and things to find.</div>'; return; }
  if (!m) {
    $('right').innerHTML = `<h3>Markers in ${esc(r.name)}</h3><div class="mlist">` +
      ((r.markers || []).map((x) => `<div data-pick="${esc(x.id)}"><i style="border-color:${COL[x.type]}"></i>${esc(x.label || TYPE_NAME[x.type])}<span class="small" style="margin-left:auto">${TYPE_NAME[x.type]}${x.hidden ? ', hidden' : ''}</span></div>`).join('') ||
       '<div class="small" style="cursor:default;background:none">None yet.</div>') +
      `</div><h3>How to</h3><div class="small">Pick a marker type above the picture, then click where it goes (a door, a sign, the thing to find). Drag markers to move them. Delete removes the selected marker.<br><br>
       Keep markers on the walls: the shaded parts land on the room's floor or the ceiling, which isn't projected.<br><br>
       <b>In the room</b> students see the markers on the walls and use the room tablet: it lists this room's markers and shows the picture to tap (hidden items are found by tapping the right spot).</div>`;
    return;
  }
  const items = tour.items.map((i) => [i.id, i.name]), rooms = tour.rooms.filter((x) => x.id !== r.id).map((x) => [x.id, x.name || 'Room']);
  const allRooms = tour.rooms.map((x) => [x.id, x.name || 'Room']);
  let h = `<h3><span class="typedot" style="border-color:${COL[m.type]}"></span>${TYPE_NAME[m.type]}<button type="button" data-act="del" class="danger">Delete</button></h3>
    <label class="f"><span>Type</span><select data-m="type">${opts(Object.entries(TYPE_NAME), m.type)}</select></label>
    <label class="f"><span>Label (under the marker and on the tablet)</span><input type="text" data-m="label" value="${esc(m.label)}"></label>
    <label class="chk"><input type="checkbox" data-m="hideLabel"${m.hideLabel ? ' checked' : ''}> Hide the label in the room (the tablet still names it)</label>
    <label class="chk"><input type="checkbox" data-m="hideRing"${m.hideRing ? ' checked' : ''}> Hide the circle in the room (still tappable; the tablet still lists it)</label>`;
  if (m.type === 'go') {
    h += `<label class="f"><span>Leads to</span><select data-m="target">${opts(rooms, m.target, '– choose a room –')}</select></label>
      <div class="f"><span>Locked until they have</span>${items.length ? items.map(([id, n]) => `<label class="chk"><input type="checkbox" data-req="${esc(id)}"${(m.requires || []).includes(id) ? ' checked' : ''}> ${esc(n)}</label>`).join('') : '<span class="small">No items yet (add them on the left).</span>'}</div>
      <label class="f"><span>Code to unlock (optional, typed on the tablet; not case sensitive)</span><input type="text" data-m="code" value="${esc(m.code)}" placeholder="e.g. 4721"></label>
      ${m.code ? `<label class="f"><span>Code card text</span><input type="text" data-m="codePrompt" value="${esc(m.codePrompt)}" placeholder="Enter the code on the tablet."></label>` : ''}
      ${(m.requires || []).length ? `<label class="f"><span>Message when locked</span><input type="text" data-m="lockedText" value="${esc(m.lockedText)}" placeholder="Locked. You need: …"></label>` : ''}`;
  }
  if (m.type === 'info') {
    h += `<label class="f"><span>Card title</span><input type="text" data-m="title" value="${esc(m.title)}" placeholder="${esc(m.label)}"></label>
      <label class="f"><span>Card text</span><textarea data-m="text" rows="6">${esc(m.text)}</textarea></label>
      <div class="small">Long text shrinks to fit the wall; about 80 words reads well.</div>`;
  }
  if (m.type === 'question') {
    h += `<label class="f"><span>Question</span><textarea data-m="text" rows="3">${esc(m.text)}</textarea></label>
      <div class="small" style="margin-bottom:8px">Tick the right answer(s) to score it, or tick none for a choice (e.g. "which room next?"). Each answer can lead to a room and can give an item.</div>`;
    (m.options || []).forEach((o, i) => {
      h += `<div class="opt"><div class="row"><b style="color:#f3c27a">${'ABCDEFGHI'[i]}</b><input type="text" data-o="${i}" data-of="text" value="${esc(o.text)}" placeholder="Answer" style="flex:1"><button type="button" data-act="delOpt" data-o="${i}" title="Remove this answer">×</button></div>
        <label class="chk"><input type="checkbox" data-o="${i}" data-of="correct"${o.correct ? ' checked' : ''}> Right answer</label>
        <label class="f"><span>Feedback</span><input type="text" data-o="${i}" data-of="feedback" value="${esc(o.feedback)}" placeholder="${o.correct ? 'Correct.' : 'Not quite.'}"></label>
        <div class="row"><select data-o="${i}" data-of="go" title="After this answer, go to">${opts(allRooms.filter(([id]) => id !== r.id), o.go, 'then stay here')}</select>
        <select data-o="${i}" data-of="give" title="This answer gives">${opts(items, o.give, 'gives nothing')}</select></div></div>`;
    });
    if ((m.options || []).length < 9) h += `<button type="button" data-act="addOpt">+ Answer</button>`;
    h += `<label class="chk" style="margin-top:8px"><input type="checkbox" data-m="retry"${m.retry ? ' checked' : ''}> Wrong answers can try again</label>`;
  }
  if (m.type === 'item') {
    const it = itemById(m.item);
    h += `<label class="f"><span>Which item</span><select data-m="item">${opts(items, m.item, '– choose –')}${'<option value="__new">+ New item…</option>'}</select></label>
      <label class="f"><span>When students tap it</span><select data-m="take">${opts([['take', 'Pick it up: it goes in their bag'], ['look', 'Look only: inspect it, then put it back'], ['choose', 'Students choose: inspect it, then take it or put it back']], m.take === false ? 'look' : m.take === 'choose' ? 'choose' : 'take')}</select></label>
      ${it ? `<label class="f"><span>Item name (used everywhere)</span><input type="text" data-itemname="${esc(it.id)}" value="${esc(it.name)}"></label>` : ''}
      <label class="f"><span>Card when found (optional)</span><textarea data-m="text" rows="3" placeholder="e.g. A key with a blue tag: 'Store room'">${esc(m.text)}</textarea></label>
      <div class="row" style="margin-bottom:8px"><button type="button" data-act="itemEdit">Edit item: 3D model, description, pages</button></div>`;
    const cm = itemModel(m.item);
    if (cm) {
      h += `<label class="chk"><input type="checkbox" data-m="show3d"${m.show3d !== false ? ' checked' : ''}> Show the 3D model in the room</label>`;
      if (has3d(m)) {
        const sz = cm.size ? cm.size.map((v) => Math.round(v * 100 * (+cm.scale || 1) * (m.size || 1)) + ' cm').join(' × ') : '';
        h += `<div class="small" style="margin-bottom:6px">The marker is the spot it stands on. Drag it along a table top: the height stays, the distance follows.${sz ? ` Size: ${sz}.` : ''}</div>
          <div class="row"><label class="f" style="flex:1"><span>Distance from centre (m)</span><input type="number" step="0.05" min="0.3" data-m="dist" value="${m.dist}"></label>
          <label class="f" style="flex:1"><span>Stands at height (m)</span><input type="number" step="0.05" min="0" data-m="h" value="${m.h}" title="0.75 is a table top, 0.9 a worktop, 0 the floor"></label></div>
          <div class="row"><label class="f" style="flex:1"><span>Turn (°)</span><input type="number" step="15" data-m="turn" value="${m.turn || 0}"></label>
          <label class="f" style="flex:1"><span>Size (×)</span><input type="number" step="0.1" min="0.1" data-m="size" value="${m.size || 1}"></label></div>`;
      }
    } else h += '<div class="small">No 3D model: students find it by tapping its spot. Give the item a model (Edit item) to show it in the room.</div>';
  }
  if (m.type === 'use') {
    h += `<label class="f"><span>What they say when students come to them (optional)</span><textarea data-m="text" rows="3" placeholder="e.g. Dr Shah: Have you got her notes?">${esc(m.text)}</textarea></label>
      <div class="small" style="margin-bottom:8px">Items this person or place takes, and what happens. Tick the right one(s) to score it. Anything else gets the reply at the bottom.</div>`;
    (m.accepts || []).forEach((a, i) => {
      h += `<div class="opt"><div class="row"><select data-a="${i}" data-af="item" style="flex:1">${opts(items, a.item, '– which item –')}</select><button type="button" data-act="delAcc" data-a="${i}" title="Remove">×</button></div>
        <label class="chk"><input type="checkbox" data-a="${i}" data-af="correct"${a.correct ? ' checked' : ''}> Right thing to give</label>
        <label class="chk"><input type="checkbox" data-a="${i}" data-af="consume"${a.consume ? ' checked' : ''}> They keep it (it leaves the bag)</label>
        <label class="f"><span>Reply</span><input type="text" data-a="${i}" data-af="feedback" value="${esc(a.feedback)}" placeholder="${a.correct ? 'That\'s right.' : 'Not quite.'}"></label>
        <div class="row"><select data-a="${i}" data-af="go" title="Afterwards, go to">${opts(allRooms.filter(([id]) => id !== r.id), a.go, 'then stay here')}</select>
        <select data-a="${i}" data-af="give" title="In return they give">${opts(items, a.give, 'gives nothing back')}</select></div></div>`;
    });
    h += `<button type="button" data-act="addAcc">+ Item they take</button>
      <label class="f" style="margin-top:8px"><span>Reply to anything else</span><input type="text" data-m="wrongText" value="${esc(m.wrongText)}" placeholder="That isn't what's needed here."></label>`;
  }
  h += `<h3>Placement</h3>
    <div class="row"><label class="f" style="flex:1"><span>Yaw °</span><input type="number" step="0.5" data-m="yaw" value="${m.yaw}"></label>
    <label class="f" style="flex:1"><span>Pitch °</span><input type="number" step="0.5" data-m="pitch" value="${m.pitch}"></label></div>
    <div class="small" style="margin-bottom:8px">${wallName(m.yaw)} wall${band(r, m) ? ` · <b style="color:#e0605a">${esc(band(r, m))}</b>` : ''}</div>
    <label class="chk"><input type="checkbox" data-m="hidden"${m.hidden ? ' checked' : ''}> Hidden until found (students tap the spot)</label>
    ${m.hidden ? `<label class="f"><span>Find area: ${m.radius || 6}° across each way (bigger = easier)</span><input type="range" min="2" max="15" step="0.5" data-m="radius" value="${m.radius || 6}"></label>` : ''}
    <div class="row"><button type="button" data-act="dup">Duplicate</button></div>`;
  $('right').innerHTML = h;
}
$('right').addEventListener('input', (e) => rightField(e, false));
$('right').addEventListener('change', (e) => rightField(e, true));
function rightField(e, isChange) {
  const el = e.target, m = marker(); if (!m) return;
  if (!isChange && (el.type === 'checkbox' || el.tagName === 'SELECT')) return;
  let rebuild = false;
  if (el.dataset.m) {
    const k = el.dataset.m; let v = el.type === 'checkbox' ? el.checked : el.value;
    if (k === 'yaw') v = r1(wrap180(parseFloat(v) || 0));
    if (k === 'pitch') v = r1(Math.max(-85, Math.min(85, parseFloat(v) || 0)));
    if (['dist', 'h', 'turn', 'size'].includes(k)) v = parseFloat(v) || (k === 'size' ? 1 : 0);
    if (k === 'radius') { v = parseFloat(v) || 6; const s = el.parentNode.querySelector('span'); if (s) s.textContent = `Find area: ${v}° across each way (bigger = easier)`; }
    if (k === 'label') m.auto = false;
    if (k === 'take') v = v === 'choose' ? 'choose' : v !== 'look';   // stored as true / false / 'choose'
    if (k === 'item' && v === '__new') {
      const n = prompt('Name of the new item (e.g. Store room key)'); if (!n) { renderRight(); return; }
      const it = { id: uid('i'), name: n.trim() }; tour.items.push(it); v = it.id; renderLeft();
    }
    if ((k === 'target' || k === 'item') && !v) v = null;
    if (k === 'type' && v !== m.type) {
      const fresh = newMarker(v, m.yaw, m.pitch);
      for (const [fk, fv] of Object.entries(fresh)) if (!(fk in m) || fk === 'label' && m.auto) m[fk] = fv;
      m.type = v; rebuild = true;
    } else m[k] = v;
    if (k === 'dist' || k === 'h') { place3d(room(), m, 'fields'); const fp = $('right').querySelector('[data-m=pitch]'); if (fp) fp.value = m.pitch; }
    if ((k === 'item' || k === 'show3d') && has3d(m) && m.dist == null) place3d(room(), m, 'init');
    if ((k === 'yaw' || k === 'pitch') && has3d(m)) place3d(room(), m, isChange ? 'drag' : 'keep');
    if (k === 'show3d' || k === 'item') rebuild = true;
    if (k === 'target' && m.auto && roomById(v)) m.label = roomById(v).name;
    if (k === 'item' && m.auto && itemById(v)) m.label = itemById(v).name;
    if (['code', 'hidden', 'target', 'item'].includes(k) && isChange) rebuild = true;
  } else if (el.dataset.req) {
    const id = el.dataset.req; m.requires = (m.requires || []).filter((x) => x !== id); if (el.checked) m.requires.push(id); rebuild = true;
  } else if (el.dataset.o != null) {
    const o = (m.options || [])[+el.dataset.o]; if (!o) return; const k = el.dataset.of;
    o[k] = el.type === 'checkbox' ? el.checked : (k === 'go' || k === 'give') ? (el.value || null) : el.value;
    if (k === 'correct') rebuild = true;
  } else if (el.dataset.a != null) {
    const a = (m.accepts || [])[+el.dataset.a]; if (!a) return; const k = el.dataset.af;
    a[k] = el.type === 'checkbox' ? el.checked : (k === 'go' || k === 'give' || k === 'item') ? (el.value || null) : el.value;
    if (k === 'correct') rebuild = true;
  } else if (el.dataset.itemname) {
    const it = itemById(el.dataset.itemname); if (!it) return; it.name = el.value;
    for (const x of tour.rooms) for (const mm of x.markers || []) if (mm.type === 'item' && mm.item === it.id && mm.auto) mm.label = it.name;
    if (isChange) renderLeft();
  } else return;
  setDirty(); draw();
  if (isChange) renderLeft();
  if (rebuild) renderRight();
}
$('right').addEventListener('click', (e) => {
  const pk = e.target.closest('[data-pick]'); if (pk) { sel.marker = pk.dataset.pick; renderRight(); draw(); return; }
  const b = e.target.closest('[data-act]'); if (!b) return;
  const r = room(), m = marker(); if (!r || !m) return;
  const act = b.dataset.act;
  if (act === 'del') delMarker();
  if (act === 'dup') { const c = JSON.parse(JSON.stringify(m)); c.id = uid('m'); c.yaw = r1(wrap180(c.yaw + 8)); r.markers.push(c); sel.marker = c.id; setDirty(); renderAll(); }
  if (act === 'addOpt') { m.options.push({ text: '', correct: false, feedback: '' }); setDirty(); renderRight(); }
  if (act === 'delOpt') { m.options.splice(+b.dataset.o, 1); setDirty(); renderRight(); renderLeft(); }
  if (act === 'addAcc') { m.accepts = m.accepts || []; m.accepts.push({ item: (tour.items[0] || {}).id || null, correct: !m.accepts.length, consume: true, feedback: '' }); setDirty(); renderRight(); renderLeft(); }
  if (act === 'delAcc') { m.accepts.splice(+b.dataset.a, 1); setDirty(); renderRight(); renderLeft(); }
  if (act === 'itemEdit' && m.item) itemDialog(m.item);
});
function delMarker() { const r = room(), m = marker(); if (!r || !m) return; r.markers = r.markers.filter((x) => x !== m); sel.marker = null; setDirty(); renderAll(); }

// ------------------------------------------------------------------ dialogs
function dialog(html, wire) { $('dlgBody').innerHTML = html; wire && wire($('dlgBody')); if (!$('dlg').open) $('dlg').showModal(); }
function pickRoom(title, onPick) {
  const cards = [];
  for (const l of LIB) for (const v of l.views || ['centre']) cards.push({ l, v });
  dialog(`<h2>${esc(title)}</h2><input type="text" id="libQ" placeholder="Search the library (name, room, style)" autocomplete="off">
    <div class="pick" id="libList"></div><div class="foot"><button value="cancel">Cancel</button></div>`, (f) => {
    const list = f.querySelector('#libList'), q = f.querySelector('#libQ');
    const show = () => {
      const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hits = cards.filter(({ l, v }) => words.every((w) => [l.name, l.style, v, physName(dimsOf(l)), l.quality].join(' ').toLowerCase().includes(w)));
      list.innerHTML = hits.map(({ l, v }) => `<button type="button" data-lib="${esc(l.id)}" data-view="${esc(v)}"><img src="${thumb(l.id, v)}" alt="" loading="lazy">
        <b>${esc(l.name)}${v !== 'centre' ? ` (${esc(v)})` : ''}</b><small>${esc(physName(dimsOf(l)))} · ${esc(l.style || '')}${l.quality === 'draft' ? ' · draft' : ''} · ${esc(l.created || '')}</small></button>`).join('') ||
        '<div class="small">Nothing matches. Render rooms in Room Builder first; they appear here.</div>';
    };
    q.addEventListener('input', show); show(); setTimeout(() => q.focus(), 30);
    list.addEventListener('click', (e) => { const b = e.target.closest('[data-lib]'); if (!b) return; $('dlg').close(); onPick(b.dataset.lib, b.dataset.view); });
  });
}
async function openDialog() {
  let list = [];
  try { list = await api('/api/tours'); } catch (e) { return toast('Could not list the tours: ' + e.message, true); }
  dialog(`<h2>Open a tour</h2><div class="tours">${list.map((t) => `<div class="t"><img src="${esc(t.thumb)}" alt=""><div><b>${esc(t.name)}</b><div class="small">${t.rooms} rooms · saved ${esc(t.saved)}${t.description ? ' · ' + esc(t.description) : ''}</div></div>
      <button type="button" class="primary" data-open="${esc(t.id)}">Open</button><button type="button" class="danger" data-rm="${esc(t.id)}" title="Moves it to tours/_removed">Remove</button></div>`).join('') || '<div class="small">No tours saved yet.</div>'}</div>
    <div class="foot"><button value="cancel">Cancel</button></div>`, (f) => {
    f.addEventListener('click', async (e) => {
      const o = e.target.closest('[data-open]'), rm = e.target.closest('[data-rm]');
      if (o) { $('dlg').close(); load(o.dataset.open); }
      if (rm && confirm('Remove this tour? It is kept in the tours/_removed folder.')) {
        try { await api(`/api/tours/${rm.dataset.rm}/remove`, {}); rm.closest('.t').remove(); if (rm.dataset.rm === tourId) { tourId = null; setDirty(); } } catch (err) { toast(err.message, true); }
      }
    });
  });
}

// ------------------------------------------------------------------ items: 3D model, description, pages
function itemDialog(id) {
  const it = itemById(id); if (!it) return;
  const cm = it.model && catById(it.model);
  dialog(`<h2>Item: ${esc(it.name)}</h2>
    <label class="f"><span>Name</span><input type="text" id="itName" value="${esc(it.name)}"></label>
    <div class="f"><span>3D model (from the shared model library: furniture and items)</span>
      <div class="row">${cm ? `<img src="${esc(catThumb(cm))}" alt="" style="width:64px;height:64px;object-fit:contain;background:#2a2f35;border-radius:6px">` : ''}
      <span class="small" style="flex:1">${cm ? esc(cm.name) + (cm.size ? ` · ${cm.size.map((v) => Math.round(v * 100 * (+cm.scale || 1))).join(' × ')} cm` : '') : 'None: students find it by tapping a spot, and see only text.'}</span>
      <button type="button" id="itPick">${cm ? 'Change' : 'Choose or upload…'}</button>${cm ? '<button type="button" id="itNone">No model</button>' : ''}</div>
      ${cm && (cm.warnings || []).length ? cm.warnings.map((w) => `<div class="warnbox">${esc(w)}</div>`).join('') : ''}</div>
    <label class="f"><span>Description (shown while they look at it)</span><textarea id="itDesc" rows="2">${esc(it.description)}</textarea></label>
    <label class="f"><span>Pages to read (notes, a chart, a letter). Put a line with --- between pages.</span><textarea id="itPages" rows="8" placeholder="Page one&#10;---&#10;Page two">${esc((it.pages || []).join('\n---\n'))}</textarea></label>
    <div class="foot"><button value="cancel" class="primary">Done</button></div>`, (f) => {
    const upd = () => {
      it.name = f.querySelector('#itName').value.trim() || it.name; it.description = f.querySelector('#itDesc').value;
      it.pages = f.querySelector('#itPages').value.split(/\n\s*---\s*\n/).map((x) => x.trim()).filter(Boolean);
      for (const x of tour.rooms) for (const m of x.markers || []) if (m.type === 'item' && m.item === it.id && m.auto) m.label = it.name;
      setDirty(); renderLeft(); renderRight(); draw();
    };
    f.addEventListener('input', upd);
    f.querySelector('#itPick').onclick = () => pickModel(it.model, (mid) => { it.model = mid; afterModel(it); itemDialog(id); });
    const none = f.querySelector('#itNone'); if (none) none.onclick = () => { it.model = null; afterModel(it); itemDialog(id); };
  });
}
function afterModel(it) {                       // markers for this item: place the model, or go back to find-by-tapping
  for (const r of tour.rooms) for (const m of r.markers || []) if (m.type === 'item' && m.item === it.id) {
    if (has3d(m)) { m.hidden = false; if (m.dist == null) place3d(r, m, 'init'); } else m.hidden = true;
  }
  setDirty(); renderLeft(); renderRight(); draw();
}
function pickModel(cur, onPick) {
  dialog(`<h2>Choose a 3D model</h2>
    <div class="upl"><b>Your own model</b><input type="file" id="upFile" accept=".fbx,.obj,.glb,.gltf,.stl,.zip">
      <input type="text" id="upName" placeholder="Name (e.g. Patient notes)" style="flex:1;min-width:140px"><button type="button" class="primary" id="upGo">Upload</button>
      <div class="small" style="flex-basis:100%">FBX, OBJ, GLB/glTF or STL. If it has separate texture files, put the model and its textures in a .zip. Blender converts it (up to a minute); it joins the shared library, so Room Builder can use it too.</div>
      <div id="upMsg" class="small" style="flex-basis:100%"></div></div>
    <input type="text" id="catQ" placeholder="Search the library" autocomplete="off">
    <div class="cat" id="catList"></div>
    <div class="foot"><button value="cancel">Cancel</button></div>`, (f) => {
    const list = f.querySelector('#catList'), q = f.querySelector('#catQ');
    const show = () => {
      const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hits = CAT.filter((m) => m.status !== 'rejected' && words.every((w) => [m.name, m.category, ...(m.tags || [])].join(' ').toLowerCase().includes(w)))
        .sort((a, b) => (b.licence && b.licence.source === 'Uploaded') - (a.licence && a.licence.source === 'Uploaded') || a.name.localeCompare(b.name));
      list.innerHTML = hits.map((m) => `<button type="button" data-mid="${esc(m.id)}" class="${m.id === cur ? 'on' : ''}"><img src="${esc(catThumb(m))}" alt="" loading="lazy">
        <b style="font-size:12px">${esc(m.name)}</b><small>${esc(m.category || '')}${m.licence && m.licence.source === 'Uploaded' ? ' · yours' : ''}</small></button>`).join('') || '<div class="small">Nothing matches.</div>';
    };
    q.addEventListener('input', show); show();
    list.addEventListener('click', (e) => { const b = e.target.closest('[data-mid]'); if (b) onPick(b.dataset.mid); });
    f.querySelector('#upGo').onclick = async () => {
      const file = f.querySelector('#upFile').files[0], msg = f.querySelector('#upMsg'), btn = f.querySelector('#upGo');
      if (!file) { msg.textContent = 'Choose a file first.'; return; }
      btn.disabled = true; msg.textContent = `Uploading and converting ${file.name} with Blender…`;
      try {
        const name = f.querySelector('#upName').value.trim() || file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
        const r = await fetch(`/api/catalogue/upload?filename=${encodeURIComponent(file.name)}&name=${encodeURIComponent(name)}`, { method: 'POST', body: file });
        const meta = await r.json().catch(() => ({}));
        if (!r.ok || meta.error) throw new Error(meta.error || r.status);
        CAT = CAT.filter((m) => m.id !== meta.id).concat([meta]);
        toast(`${meta.name} added to the model library`);
        onPick(meta.id);
      } catch (e) { msg.textContent = 'Could not add it: ' + e.message; btn.disabled = false; }
    };
  });
}

// ------------------------------------------------------------------ load / save / play
async function load(id) {
  if (dirty && !confirm('Discard the unsaved changes to this tour?')) return;
  try { tour = await api('/api/tours/' + encodeURIComponent(id)); } catch (e) { return toast('Could not open the tour: ' + e.message, true); }
  tour.items = tour.items || []; tour.rooms = tour.rooms || [];
  tourId = tour.id || id; sel.room = (roomById(tour.start) || tour.rooms[0] || {}).id || null; sel.marker = null;
  history.replaceState(null, '', '?tour=' + encodeURIComponent(tourId));
  setDirty(false); renderAll();
}
async function save() {
  tour.name = $('tourName').value.trim() || 'Untitled tour';
  if (!roomById(tour.start) && tour.rooms[0]) tour.start = tour.rooms[0].id;
  try {
    const d = await api('/api/tours', { id: tourId, tour }); tourId = d.id;
    history.replaceState(null, '', '?tour=' + encodeURIComponent(tourId)); setDirty(false); toast('Saved'); return true;
  } catch (e) { toast('Could not save: ' + e.message, true); return false; }
}
async function play(lookRound, fromRoom) {
  if (!tour.rooms.length) return toast('Add a room first', true);
  if ((dirty || !tourId) && !(await save())) return;
  window.open(`/builder/tour.html?tour=${encodeURIComponent(tourId)}${lookRound ? '&look=1' : ''}${fromRoom ? '&room=' + encodeURIComponent(fromRoom) : ''}`, '_blank');
}
$('bNew').onclick = () => { if (dirty && !confirm('Discard the unsaved changes to this tour?')) return; tour = blank(); tourId = null; sel.room = sel.marker = null; history.replaceState(null, '', location.pathname); setDirty(false); renderAll(); };
$('bOpen').onclick = openDialog;
$('bSave').onclick = save;
$('bPlay').onclick = () => play(true);
$('bPlayRoom').onclick = () => play(false);
$('tourName').addEventListener('input', () => { tour.name = $('tourName').value; setDirty(); });
addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); return; }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '') || $('dlg').open;
  if (typing) return;
  if ((e.key === 'Delete' || e.key === 'Backspace') && marker()) { e.preventDefault(); delMarker(); }
  if (e.key === 'Escape') { setTool('select'); sel.marker = null; renderRight(); draw(); }
});
addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

function renderAll() { $('tourName').value = tour.name || ''; renderLeft(); renderRight(); draw(); }

(async function init() {
  try { LIB = await api('/api/library'); } catch (e) { toast('Could not read the library: ' + e.message, true); }
  try { for (const p of (await api('/api/presets')).rooms || []) PRESETS[p.id] = p; } catch (e) {}
  try { CAT = await api('/api/catalogue'); } catch (e) { CAT = []; }
  const id = new URLSearchParams(location.search).get('tour');
  if (id) await load(id); else renderAll();
})();
