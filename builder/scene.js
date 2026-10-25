// Room Builder - shared room geometry for the builder and the live 360 page.
// Builds a quick, plain version of a room spec in three.js. The Blender generator builds the real one from the
// same spec with the same rules, so positions here match the final render.
//
// Spec coordinates (metres): x = east, y = north, z = up, origin at the centre of the physical room on the floor.
// three.js is y-up, so a spec point (x, y, z) sits at three (x, z, -y).

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export const T = 0.15;                      // wall thickness, same as the generator
export const b2t = (x, y, z = 0) => new THREE.Vector3(x, z, -y);

export function roomFrame(spec) {
  const r = spec.room;
  const W = +r.width, D = +r.depth, RH = +r.height;
  const X0 = -W / 2, X1 = W / 2, Y0 = -D / 2, Y1 = D / 2;
  const walls = {
    north: { axis: 'x', line: Y1, sign: +1, lo: X0, hi: X1 },
    south: { axis: 'x', line: Y0, sign: -1, lo: X0, hi: X1 },
    east:  { axis: 'y', line: X1, sign: +1, lo: Y0, hi: Y1 },
    west:  { axis: 'y', line: X0, sign: -1, lo: Y0, hi: Y1 },
  };
  const w2 = (wall, u, d, z = 0) => {
    const f = walls[wall];
    return f.axis === 'x' ? [u, f.line + f.sign * d, z] : [f.line + f.sign * d, u, z];
  };
  return { W, D, RH, X0, X1, Y0, Y1, walls, w2, eye: +(r.eye ?? 1.12) };
}

// rotation (degrees) that turns a model whose front faces south (-y) to face into the room from a wall
export const FACING = { north: 0, south: 180, east: -90, west: 90 };

// ------------------------------------------------------------------ materials
export function styleColours(style) {
  if (style === 'court') return { wall: 0xd8d0bc, floor: 0x1c2a44, ceiling: 0xdcdcd8, trim: 0x7a5530, kfloor: 0x1c2a44, kfront: 0x7a5530,
    ktop: 0x4d3420, splash: 0xd8d0bc, frame: 0xcdcdc8, door: 0x7a5530, glass: 0xbfd8e8, shelf: 0x7a5530, fridge: 0xcfcfcd };
  if (style === 'custody') return { wall: 0xccc9b8, floor: 0x55626b, ceiling: 0xd4d4d0, trim: 0x47525c, kfloor: 0x55626b, kfront: 0xb4b4b0,
    ktop: 0x9e9e9c, splash: 0xccc9b8, frame: 0x8c9194, door: 0x3d5c7a, glass: 0xbfd8e8, shelf: 0x9e9e9c, fridge: 0xcfcfcd };
  if (style === 'hospital') return { wall: 0xdde6dc, floor: 0x93a0a6, ceiling: 0xe0e0dc, trim: 0x63707a, kfloor: 0x93a0a6, kfront: 0xd2d4d2,
    ktop: 0x9ea2a2, splash: 0xdcdedc, frame: 0xd2d4d4, door: 0xa07a52, glass: 0xbfd8e8, shelf: 0xb8a07a, fridge: 0xd0d0ce };
  return style === 'neglected'
    ? { wall: 0x6f6553, floor: 0x5b3b22, ceiling: 0x857660, trim: 0x9e9068, kfloor: 0x77705e, kfront: 0x6b3415,
        ktop: 0x8c8068, splash: 0xb8ae8c, frame: 0x8c806a, door: 0x9a8c6c, glass: 0xbfd8e8, shelf: 0x54371e, fridge: 0xd9d9d6 }
    : { wall: 0xebe6de, floor: 0xd8c6ab, ceiling: 0xdcd8d0, trim: 0xf2f2f0, kfloor: 0xb9b8b3, kfront: 0x3d4a45,
        ktop: 0xd2d0ca, splash: 0xd8ddd9, frame: 0xf0f0ee, door: 0xe8e8e4, glass: 0xbfd8e8, shelf: 0x7a5534, fridge: 0xa8a8a6 };
}

// ------------------------------------------------------------------ finishes (a flat colour per finish for the live preview)
const WOOD_HEX = { light_oak: 0xd9c4a3, oak: 0xa87a4a, dark_oak: 0x5a3d26, pine: 0xd8b07a, grey: 0xa8a49c };
const BRICK_HEX = { red: 0x8a4a36, yellow: 0xb39a6a, painted: 0xe6e4dc };
const COND_SHADE = { new: 1, lived_in: 0.97, worn: 0.9, neglected: 0.78, derelict: 0.66 };
const hexNum = h => parseInt(String(h || '#888888').replace('#', ''), 16);
function mixHex(a, b, t) {
  const ca = new THREE.Color(a), cb = new THREE.Color(b); return ca.lerp(cb, t).getHex();
}
export function finishColour(f) {
  if (!f) return null;
  switch (f.type) {
    case 'paint': case 'blockwork': case 'vinyl': case 'resin': case 'lino': case 'carpet':
      return f.type === 'carpet' && f.carpet_pattern === 'patterned' && f.colour2 ? mixHex(hexNum(f.colour), hexNum(f.colour2), 0.25) : hexNum(f.colour);
    case 'wallpaper': return f.pattern === 'woodchip' ? hexNum(f.colour) : mixHex(hexNum(f.colour), hexNum(f.colour2 || f.colour), f.pattern === 'vintage' ? 0.15 : 0.3);
    case 'tiles': return f.colour2 ? mixHex(hexNum(f.colour), hexNum(f.colour2), 0.5) : hexNum(f.colour);
    case 'wood': case 'laminate': case 'panelling': return f.wood === 'painted' ? hexNum(f.colour) : (WOOD_HEX[f.wood] ?? WOOD_HEX.oak);
    case 'brick': return BRICK_HEX[f.brick] ?? BRICK_HEX.red;
    case 'plaster': return 0xb89a86;
    case 'concrete': return 0x5a5955;
    case 'artex': return hexNum(f.colour);
    default: return f.colour ? hexNum(f.colour) : null;
  }
}
// ---- preview textures: a small canvas per finish (tiles with grout, checks, boards, blocks, wallpaper patterns),
// laid on the room in metres by worldUVs(). The Blender render is still the real thing; this is so the choice is visible.
const TILE_M = { metro: [0.2, 0.1], sq10: [0.1, 0.1], sq15: [0.15, 0.15], sq30: [0.3, 0.3], sq60: [0.6, 0.6] };
const texCache = new Map();
let texChanged = null;                                     // called when an async pattern finishes loading
export function onPreviewTexture(fn) { texChanged = fn; }
function canvasTex(w, h, draw, mx, my, rot = 0) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(1 / mx, 1 / my); t.rotation = rot; t.anisotropy = 4;
  t.userData.canvas = c;
  return t;
}
const css = h => (typeof h === 'number' ? '#' + h.toString(16).padStart(6, '0') : h);
function shadeHex(h, k) { const c = new THREE.Color(css(h)); c.multiplyScalar(k); return '#' + c.getHexString(); }
function defaultGrout(c) { return new THREE.Color(css(c)).getHSL({}).l > 0.45 ? '#bdbdb8' : '#4a4a48'; }
function tilesTex(f, floor) {
  const metro = f.tile_size === 'metro';
  const [tw, th] = TILE_M[f.tile_size] || (floor ? TILE_M.sq30 : TILE_M.sq15);
  const c1 = f.colour || '#efefeb', c2 = (floor && f.colour2 && !metro) ? f.colour2 : null, g = f.grout || defaultGrout(c1);
  const diag = floor && (f.layout || (c2 ? 'diagonal' : 'straight')) === 'diagonal';
  return canvasTex(256, metro ? 128 : 256, (x, W, H) => {
    x.fillStyle = g; x.fillRect(0, 0, W, H);
    const gp = Math.max(1.5, W * 0.006 / (tw * 2));
    if (metro) {
      for (let r = 0; r < 2; r++) for (let k = -1; k < 3; k++) {
        const ox = (k + (r % 2 ? 0.5 : 0)) * W / 2; x.fillStyle = k % 2 ? shadeHex(c1, 0.97) : c1;
        x.fillRect(ox + gp / 2, r * H / 2 + gp / 2, W / 2 - gp, H / 2 - gp);
      }
    } else {
      for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) {
        x.fillStyle = c2 ? ((i + j) % 2 ? c2 : c1) : ((i + j) % 2 ? shadeHex(c1, 0.97) : c1);
        x.fillRect(i * W / 2 + gp / 2, j * H / 2 + gp / 2, W / 2 - gp, H / 2 - gp);
      }
    }
  }, tw * 2, th * 2, diag ? Math.PI / 4 : 0);
}
function bondTex(c1, c2, mortar, bw, bh, rows = 2) {           // blockwork / brick in stretcher bond
  return canvasTex(256, 256, (x, W, H) => {
    x.fillStyle = mortar; x.fillRect(0, 0, W, H);
    const rh = H / rows, g = Math.max(1.5, W * 0.01 / bw);
    for (let r = 0; r < rows; r++) for (let k = -1; k < 2; k++) {
      x.fillStyle = (r + k) % 2 ? c2 : c1;
      x.fillRect((k + (r % 2 ? 0.5 : 0)) * W + g / 2, r * rh + g / 2, W - g, rh - g);
    }
  }, bw, bh * rows);
}
function boardsTex(base) {                                       // wood boards, staggered
  return canvasTex(256, 512, (x, W, H) => {
    const n = 4, bw = W / n;
    for (let i = 0; i < n; i++) {
      const off = ((i * 37) % 10) / 10 * H;
      for (let k = -1; k < 2; k++) {
        x.fillStyle = shadeHex(base, 0.9 + ((i * 7 + k * 3) % 5) * 0.045);
        x.fillRect(i * bw + 1, off + k * H + 1, bw - 2, H - 2);
      }
    }
  }, 0.6, 1.2);
}
function maskTex(name, ground, ink, metres, mix = 1) {          // a pattern mask from textures/patterns, coloured
  const t = canvasTex(256, 256, (x, W, H) => { x.fillStyle = ground; x.fillRect(0, 0, W, H); }, metres, metres);
  const img = new Image();
  img.onload = () => {
    const c = t.userData.canvas, x = c.getContext('2d');
    x.drawImage(img, 0, 0, c.width, c.height);
    // mix in sRGB (canvas pixels are sRGB; THREE.Color stores linear)
    const a = new THREE.Color(ground).getRGB({}, THREE.SRGBColorSpace), b = new THREE.Color(ink).getRGB({}, THREE.SRGBColorSpace);
    const d = x.getImageData(0, 0, c.width, c.height);
    for (let i = 0; i < d.data.length; i += 4) {
      const m = d.data[i] / 255 * mix;
      d.data[i] = 255 * (a.r + (b.r - a.r) * m); d.data[i + 1] = 255 * (a.g + (b.g - a.g) * m); d.data[i + 2] = 255 * (a.b + (b.b - a.b) * m); d.data[i + 3] = 255;
    }
    x.putImageData(d, 0, 0); t.needsUpdate = true; texChanged?.();
  };
  img.src = `/textures/patterns/${name}.png`;
  return t;
}
function finishTexture(f) {
  if (!f || typeof document === 'undefined') return null;
  const key = JSON.stringify(f); if (texCache.has(key)) return texCache.get(key);
  let t = null;
  switch (f.type) {
    case 'tiles': t = tilesTex(f, !!f.__floor); break;
    case 'blockwork': { const c = f.colour || '#e4e1d2'; t = bondTex(c, shadeHex(c, 0.975), shadeHex(c, 0.86), 0.44, 0.215); break; }
    case 'brick': { const B = { red: ['#94503a', '#7e4330', '#b1aba3'], yellow: ['#b9a170', '#a48c5c', '#b1aca3'], painted: ['#e6e4dc', '#dedcd4', '#cfcdc6'] }[f.brick || 'red'];
      t = bondTex(B[0], B[1], B[2], 0.225, 0.075); break; }
    case 'wood': case 'laminate': if (f.wood !== 'painted') t = boardsTex(css(WOOD_HEX[f.wood] ?? WOOD_HEX.oak)); break;
    case 'wallpaper': if (!['woodchip', 'vintage'].includes(f.pattern)) t = maskTex(f.pattern, f.colour || '#e9dfc3', f.colour2 || '#c9a85e', 0.53); break;
    case 'carpet':
      if (f.carpet_pattern === 'patterned') t = maskTex('floral', f.colour || '#5d2329', f.colour2 || '#a9853f', 0.45, 0.55);
      else if (f.carpet_pattern === 'cord') t = maskTex('cord', f.colour || '#777777', shadeHex(f.colour || '#777777', 0.8), 0.25);
      break;
    case 'lino': if (f.lino_pattern === 'check') t = canvasTex(64, 64, (x, W, H) => {
      x.fillStyle = f.colour || '#b9ab8e'; x.fillRect(0, 0, W, H); x.fillStyle = f.colour2 || '#7a604a'; x.fillRect(0, 0, W / 2, H / 2); x.fillRect(W / 2, H / 2, W / 2, H / 2); }, 0.6, 0.6);
      break;
    case 'ceiling_tiles': t = canvasTex(128, 128, (x, W, H) => { x.fillStyle = '#a9a9a6'; x.fillRect(0, 0, W, H); x.fillStyle = '#dcdcd8'; x.fillRect(2, 2, W - 4, H - 4); }, 0.6, 0.6); break;
  }
  texCache.set(key, t); return t;
}
function finishMat(f, cond, fallback, floor = false) {
  if (f?.type === 'tiles' && floor) f = { ...f, __floor: true };
  const tex = finishTexture(f);
  const c = tex ? 0xffffff : finishColour(f); if (c == null) return fallback;
  const col = new THREE.Color(c).multiplyScalar(COND_SHADE[cond] ?? 1);
  return new THREE.MeshStandardMaterial({ color: col, map: tex, roughness: 0.85, side: THREE.DoubleSide });
}
// ---- decals: drawings, graffiti, posters, stains on a wall, an alcove's back wall or the floor
let DECALS = [];
export function setDecalCatalogue(list) { DECALS = list || []; }
const decalTex = new Map();
function decalTexture(meta) {
  let t = decalTex.get(meta.file);
  if (!t) { t = texLoader.load(`/catalogue/decals/${encodeURIComponent(meta.file)}`, () => texChanged?.()); t.colorSpace = THREE.SRGBColorSpace; decalTex.set(meta.file, t); }
  return t;
}
// where a decal sits: centre, the image's right and up directions (spec space), size
export function decalPlacement(spec, dc) {
  const meta = DECALS.find(d => d.id === dc.decal); if (!meta) return null;
  const F = roomFrame(spec), w = +(dc.width ?? meta.width ?? 0.5), h = w * (+meta.aspect || 1);
  if (dc.surface === 'floor') return { meta, w, h, c: [+dc.x || 0, +dc.y || 0, 0.004], right: [1, 0, 0], up: [0, 1, 0] };
  let wall = dc.surface, depth = 0;
  if (String(dc.surface).startsWith('alcove:')) {
    const ft = (spec.features || []).find(f => f.id === dc.surface.slice(7)); if (!ft) return null;
    wall = ft.wall; depth = +(ft.depth ?? 0.6);
  }
  if (!F.walls[wall]) return null;
  const z = +(dc.z ?? 1.4);
  const lf = spec.wall_finishes?.[wall] && 'lower' in spec.wall_finishes[wall] ? spec.wall_finishes[wall].lower : spec.finishes?.lower;
  const panel = lf?.type === 'panelling' && z - h / 2 < Math.min(+(lf.height ?? 1.15), F.RH - 0.3) + 0.07;
  const off = panel ? 0.045 : 0.009;
  const c = F.w2(wall, +dc.u || 0, depth - off, z), o = F.w2(wall, 0, 0, 0), n1 = F.w2(wall, 0, 1, 0);
  const n = [n1[0] - o[0], n1[1] - o[1]];
  return { meta, w, h, c, right: [n[1], -n[0], 0], up: [0, 0, 1], wall, depth };
}
function decalMesh(spec, dc, i) {
  const P = decalPlacement(spec, dc); if (!P) return null;
  const a = (+dc.rot || 0) * Math.PI / 180, cs = Math.cos(a), sn = Math.sin(a);
  const r = P.right.map((v, k) => v * cs + P.up[k] * sn), u = P.up.map((v, k) => v * cs - P.right[k] * sn);
  const pt = (sx, sy) => b2t(...P.c.map((v, k) => v + r[k] * sx * P.w / 2 + u[k] * sy * P.h / 2));
  const vs = [pt(-1, -1), pt(1, -1), pt(1, 1), pt(-1, 1)];
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(vs.flatMap(v => [v.x, v.y, v.z]), 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
  g.setIndex([0, 1, 2, 0, 2, 3]); g.computeVertexNormals();
  const m = new THREE.MeshStandardMaterial({ map: decalTexture(P.meta), transparent: true, opacity: +(dc.opacity ?? 1), depthWrite: false,
    side: THREE.DoubleSide, roughness: 0.8, polygonOffset: true, polygonOffsetFactor: -2 });
  const mesh = new THREE.Mesh(g, m); mesh.name = 'decal_' + i; mesh.userData.decalIndex = i; mesh.userData.uvDone = true; mesh.renderOrder = 2;
  return mesh;
}

// give room meshes texture coordinates in metres: floors/ceilings use the plan, walls run along the wall and up
const _v = new THREE.Vector3(), _n = new THREE.Vector3();
function worldUVs(root) {
  root.updateMatrixWorld(true);
  root.traverse(o => {
    if (!o.isMesh || !o.material?.map || o.userData.uvDone) return;
    let g = o.geometry; if (g.index) { g = g.toNonIndexed(); o.geometry = g; }
    g.computeVertexNormals();
    const pos = g.attributes.position, nor = g.attributes.normal, uv = new Float32Array(pos.count * 2);
    const nm = new THREE.Matrix3().getNormalMatrix(o.matrixWorld);
    for (let i = 0; i < pos.count; i++) {
      _v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld); _n.fromBufferAttribute(nor, i).applyMatrix3(nm).normalize();
      if (Math.abs(_n.y) > 0.7) { uv[i * 2] = _v.x; uv[i * 2 + 1] = -_v.z; }
      else { uv[i * 2] = Math.abs(_n.x) > Math.abs(_n.z) ? -_v.z : _v.x; uv[i * 2 + 1] = _v.y; }
    }
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); o.userData.uvDone = true;
  });
}

// a run-down home (neglected / derelict condition): bare bulb, nets, dated kitchen, like the old "neglected" style
export const runDown = spec => spec?.style === 'neglected' || ((spec?.style || 'modern') === 'modern' && ['neglected', 'derelict'].includes(spec?.condition));

function mats(style, spec) {
  const rd = runDown(spec);
  const c = styleColours(style);
  const m = {};
  for (const [k, v] of Object.entries(c)) {
    m[k] = new THREE.MeshStandardMaterial({ color: v, roughness: k === 'glass' ? 0.1 : 0.85, side: THREE.DoubleSide,
      transparent: k === 'glass', opacity: k === 'glass' ? 0.35 : 1 });
  }
  m.dark = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.8 });
  m.frosted = new THREE.MeshStandardMaterial({ color: 0xe8eef0, roughness: 0.6, transparent: true, opacity: 0.85 });
  m.blind = new THREE.MeshStandardMaterial({ color: rd ? 0xc4bc9e : 0xdcdedb, roughness: 0.5 });
  m.curtain = new THREE.MeshStandardMaterial({ color: rd ? 0x734720 : style === 'hospital' ? 0x5c8ca8 : 0x8c877a, roughness: 0.9 });
  m.nets = new THREE.MeshStandardMaterial({ color: 0xf0eee4, roughness: 1, transparent: true, opacity: 0.5, side: THREE.DoubleSide });
  m.outside = new THREE.MeshBasicMaterial({ color: 0x8fb36b, side: THREE.DoubleSide });
  m.sky = new THREE.MeshBasicMaterial({ color: 0xbcd6ee, side: THREE.DoubleSide });
  m.night = new THREE.MeshBasicMaterial({ color: 0x0b1020, side: THREE.DoubleSide });
  const fin = spec?.finishes, cond = spec?.condition || 'new';
  if (fin) {
    m.wall = finishMat(fin.walls, cond, m.wall);
    m.floor = finishMat(fin.floor, cond, m.floor, true);
    // ceiling plaster/artex are painted (not the bare pink plaster wall finish)
    m.ceiling = finishMat(fin.ceiling?.type === 'tiles' ? { type: 'ceiling_tiles' } : { type: 'paint', colour: fin.ceiling?.colour || '#f0eee8' }, cond, m.ceiling);
    m.trim = fin.trim ? finishMat(fin.trim.wood ? { type: 'wood', wood: fin.trim.wood } : { type: 'paint', colour: fin.trim.colour }, cond, m.trim) : m.trim;
    const K = fin.kitchen;
    if (K) {                                           // kitchen units, worktop, splashback, floor, appliances
      const u = K.units || {};
      m.kfront = finishMat(u.style === 'wood' ? { type: 'wood', wood: u.wood } : { type: 'paint', colour: u.colour }, cond, m.kfront);
      const WT = { quartz_white: '#cfcdc6', granite_black: '#1c1c1e', oak: null, steel: '#a9a9a6' };
      const wt = K.worktop?.type || 'quartz_white';
      m.ktop = finishMat(wt === 'oak' ? { type: 'wood', wood: 'oak' } : { type: 'paint', colour: wt === 'laminate' ? K.worktop.colour : WT[wt] }, cond, m.ktop);
      const sp = K.splashback || {};
      m.splash = sp.type === 'same' ? null : finishMat(sp.type === 'glass' ? { type: 'paint', colour: sp.colour } : { type: 'tiles', tile_size: sp.tile_size || 'metro', colour: sp.colour, grout: sp.grout }, cond, m.splash);
      if (K.floor && K.floor.type !== 'same') m.kfloor = finishMat(K.floor, cond, m.kfloor, true); else m.kfloor = null;
      m.fridge = finishMat({ type: 'paint', colour: { steel: '#a9a9a6', white: '#e6e6e3', black: '#1e1f21' }[K.appliances || 'steel'] }, cond, m.fridge);
    }
    m.lowerFin = fin.lower && fin.lower.type !== 'none' ? fin.lower : null;
    m.lower = m.lowerFin ? finishMat(m.lowerFin.type === 'panelling' ? { type: 'wood', wood: m.lowerFin.wood, colour: m.lowerFin.colour } : m.lowerFin, cond, m.wall) : null;
    // per-wall and per-alcove overrides: {walls, lower}; missing parts are inherited
    const set = (ov, base) => {
      if (!ov || (!ov.walls && !('lower' in ov))) return base;
      const lf = 'lower' in ov ? (ov.lower && ov.lower.type !== 'none' ? ov.lower : null) : base.lowerFin;
      return { wall: ov.walls ? finishMat(ov.walls, cond, base.wall) : base.wall, lowerFin: lf,
               lower: lf ? finishMat(lf.type === 'panelling' ? { type: 'wood', wood: lf.wood, colour: lf.colour } : lf, cond, base.wall) : null };
    };
    const room = { wall: m.wall, lower: m.lower, lowerFin: m.lowerFin };
    m.wallSet = Object.fromEntries(['north', 'south', 'east', 'west'].map(w => [w, set(spec.wall_finishes?.[w], room)]));
    m.alcoveSet = ft => set(ft.finish, m.wallSet[ft.wall] || room);
  }
  m.splash ||= m.wall; m.kfloor ||= m.floor;
  m.wallSet ||= Object.fromEntries(['north', 'south', 'east', 'west'].map(w => [w, { wall: m.wall, lower: null, lowerFin: null }]));
  m.alcoveSet ||= ft => m.wallSet[ft.wall];
  return m;
}

// ------------------------------------------------------------------ helpers
function boxBetween(a, b, mat, name) {
  // a, b: spec-space corners [x, y, z]
  const mn = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.min(a[2], b[2])];
  const mx = [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.max(a[2], b[2])];
  const g = new THREE.BoxGeometry(Math.max(1e-3, mx[0] - mn[0]), Math.max(1e-3, mx[2] - mn[2]), Math.max(1e-3, mx[1] - mn[1]));
  const o = new THREE.Mesh(g, mat);
  o.position.copy(b2t((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2));
  o.name = name || '';
  return o;
}

function rectPlane(x0, y0, x1, y1, z, mat, name) {
  const g = new THREE.PlaneGeometry(Math.abs(x1 - x0), Math.abs(y1 - y0));
  g.rotateX(-Math.PI / 2);
  const o = new THREE.Mesh(g, mat);
  o.position.copy(b2t((x0 + x1) / 2, (y0 + y1) / 2, z));
  o.name = name || '';
  return o;
}

export function span(f) { const w = +f.width; return [+f.pos - w / 2, +f.pos + w / 2]; }

export function archSpring(f, RH) {
  const top = Math.min(+(f.height ?? 2.0), RH - 0.05);
  const spring = Math.max(0.3, top - (+f.width) / 2 * (+(f.rise ?? 0.2)));
  return { top, spring };
}

// ------------------------------------------------------------------ the room
export function buildRoom(spec, opts = {}) {
  const F = roomFrame(spec);
  if (spec.style === 'outdoor' || spec.room?.type === 'outdoor') {
    // outdoors there is no room: just a faint ground disc to stand models on (the photo sphere shows the place)
    const root = new THREE.Group(); root.name = 'room';
    const g = new THREE.Mesh(new THREE.CircleGeometry(12, 64).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: 0x6d7a5a, transparent: true, opacity: 0.35, depthWrite: false }));
    g.userData.isFloor = true; root.add(g);
    const ceilings = new THREE.Group(); root.add(ceilings);
    return { root, ceilings, pick: [], frame: F, zones: [] };
  }
  const { W, D, RH, X0, X1, Y0, Y1, walls, w2 } = F;
  const style = spec.style || 'modern';
  const M = mats(style === 'neglected' ? 'modern' : style, spec);
  const root = new THREE.Group(); root.name = 'room';
  const ceilings = new THREE.Group(); ceilings.name = 'ceilings';
  const pick = [];                              // meshes that select a feature when clicked
  const zones = [{ name: 'main', x0: X0 - T / 2, y0: Y0 - T / 2, x1: X1 + T / 2, y1: Y1 + T / 2, floor: M.floor, h: RH }];
  const feats = spec.features || [];
  const add = (o, featId) => { if (featId) { o.userData.featureId = featId; pick.push(o); } root.add(o); return o; };
  const wb = (wall, u0, u1, d0, d1, z0, z1, mat, fid) => add(boxBetween(w2(wall, u0, d0, z0), w2(wall, u1, d1, z1), mat), fid);

  // where two full-height recesses meet in a corner, open the corner up (no pillar left standing)
  const CORN = { 'north:lo': 'west:hi', 'north:hi': 'east:hi', 'south:lo': 'west:lo', 'south:hi': 'east:lo' };
  for (const [k, v] of Object.entries({ ...CORN })) CORN[v] = k;
  const fullRecess = f => (f.type === 'alcove' || f.type === 'kitchenette') && Math.min(+(f.height ?? RH), RH) >= RH - 0.01;
  const atEnd = (f, end) => { const w = walls[f.wall], [a, b] = span(f); return end === 'lo' ? a <= w.lo + 0.01 : b >= w.hi - 0.01; };
  const fdepth = f => +(f.depth ?? (f.type === 'kitchenette' ? 0.65 : 0.6));
  const cornerMate = (f, end) => {
    if (!walls[f.wall] || !fullRecess(f) || !atEnd(f, end)) return null;
    const [w2n, e2] = CORN[`${f.wall}:${end}`].split(':');
    return feats.find(g => g !== f && g.wall === w2n && fullRecess(g) && atEnd(g, e2)) || null;
  };

  // walls with their openings cut out
  for (const [wall, f] of Object.entries(walls)) {
    const shape = new THREE.Shape();
    shape.moveTo(f.lo - T, -0.05); shape.lineTo(f.hi + T, -0.05); shape.lineTo(f.hi + T, RH + 0.05); shape.lineTo(f.lo - T, RH + 0.05); shape.closePath();
    for (const ft of feats.filter(x => x.wall === wall)) {
      const [u0, u1] = span(ft);
      if (!(u1 > u0)) continue;
      const p = new THREE.Path();
      if (ft.type === 'alcove' || ft.type === 'kitchenette') {
        const h = Math.min(+(ft.height ?? RH), RH);
        const top = h >= RH - 0.01 ? RH + 0.01 : h;
        const e0 = u0 - (cornerMate(ft, 'lo') ? T + 0.01 : 0), e1 = u1 + (cornerMate(ft, 'hi') ? T + 0.01 : 0);
        p.moveTo(e0, -0.01); p.lineTo(e1, -0.01); p.lineTo(e1, top); p.lineTo(e0, top); p.closePath();
      } else if (ft.type === 'door') {
        const h = +(ft.height ?? 2.0);
        p.moveTo(u0, -0.01); p.lineTo(u1, -0.01); p.lineTo(u1, h); p.lineTo(u0, h); p.closePath();
      } else if (ft.type === 'window') {
        const s = +(ft.sill ?? 0.8), h = +(ft.height ?? 1.2);
        p.moveTo(u0, s); p.lineTo(u1, s); p.lineTo(u1, s + h); p.lineTo(u0, s + h); p.closePath();
      } else if (ft.type === 'arch') {
        const { top, spring } = archSpring(ft, RH);
        p.moveTo(u0, -0.01); p.lineTo(u1, -0.01);
        if ((ft.shape || 'round') === 'round') {
          p.lineTo(u1, spring);
          p.absellipse(+ft.pos, spring, (u1 - u0) / 2, Math.max(0.01, top - spring), 0, Math.PI, false);
        } else { p.lineTo(u1, top); p.lineTo(u0, top); }
        p.closePath();
      } else continue;
      shape.holes.push(p);
    }
    let geo;
    try { geo = new THREE.ExtrudeGeometry(shape, { depth: T, bevelEnabled: false, curveSegments: 24 }); }
    catch (e) { geo = new THREE.BoxGeometry(0.01, 0.01, 0.01); }
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const [x, y, z] = w2(wall, pos.getX(i), pos.getZ(i), pos.getY(i));
      const v = b2t(x, y, z); pos.setXYZ(i, v.x, v.y, v.z);
    }
    geo.computeVertexNormals();
    const WS = M.wallSet[wall];
    const mesh = new THREE.Mesh(geo, WS.wall); mesh.name = 'wall_' + wall; mesh.userData.wall = wall;
    root.add(mesh);
    // skirting runs (not across floor-level openings)
    const gaps = feats.filter(x => x.wall === wall && ['alcove', 'kitchenette', 'door', 'arch'].includes(x.type)).map(span).sort((a, b) => a[0] - b[0]);
    let cur = f.lo;
    const runs = [];
    for (const [a, b] of gaps) { if (a > cur) runs.push([cur, a]); cur = Math.max(cur, b); }
    if (cur < f.hi) runs.push([cur, f.hi]);
    for (const [a, b] of runs) if (b - a > 0.02) wb(wall, a, b, -0.018, 0, 0, 0.12, M.trim);
    if (WS.lowerFin) {                                  // lower walls (panelling / tiles / two-tone) and their rail
      const H = Math.min(+(WS.lowerFin.height ?? (WS.lowerFin.type === 'panelling' ? 1.15 : 1.2)), RH - 0.3);
      for (const [a, b] of runs) if (b - a > 0.05) { wb(wall, a, b, -0.008, 0, 0, H, WS.lower); wb(wall, a, b, -0.03, 0, H, H + 0.05, M.trim); }
    }
    // coving along the top, broken only where a full-height alcove or kitchenette opens the wall
    const tops = feats.filter(x => x.wall === wall && fullRecess(x)).map(span).sort((a, b) => a[0] - b[0]);
    let ct = f.lo; const cruns = [];
    for (const [a, b] of tops) { if (a > ct) cruns.push([ct, a]); ct = Math.max(ct, b); }
    if (ct < f.hi) cruns.push([ct, f.hi]);
    for (const [a, b] of cruns) if (b - a > 0.02) wb(wall, a, b, -0.05, 0, RH - 0.05, RH, M.trim);
  }

  const recess = (ft, wall, depth, h, floorMat) => {
    const [u0, u1] = span(ft);
    const mlo = cornerMate(ft, 'lo'), mhi = cornerMate(ft, 'hi');
    const dlo = mlo ? fdepth(mlo) : 0, dhi = mhi ? fdepth(mhi) : 0;
    const AS = M.alcoveSet(ft);
    wb(wall, u0 - T - dlo, u1 + T + dhi, depth, depth + T, 0, RH, AS.wall, ft.id);
    if (!mlo) wb(wall, u0 - T, u0, 0, depth + T, 0, RH, AS.wall, ft.id);
    if (!mhi) wb(wall, u1, u1 + T, 0, depth + T, 0, RH, AS.wall, ft.id);
    if (AS.lowerFin && ft.type === 'alcove') {
      const H = Math.min(+(AS.lowerFin.height ?? (AS.lowerFin.type === 'panelling' ? 1.15 : 1.2)), RH - 0.3);
      wb(wall, u0 - dlo, u1 + dhi, depth - 0.008, depth, 0, H, AS.lower, ft.id);
      if (!mlo) wb(wall, u0, u0 + 0.008, -0.008, depth, 0, H, AS.lower, ft.id);
      if (!mhi) wb(wall, u1 - 0.008, u1, -0.008, depth, 0, H, AS.lower, ft.id);
    }
    const zone = (p0, p1, name) => { const a = w2(wall, p0[0], p0[1]), b = w2(wall, p1[0], p1[1]);
      zones.push({ name, x0: Math.min(a[0], b[0]), y0: Math.min(a[1], b[1]), x1: Math.max(a[0], b[0]), y1: Math.max(a[1], b[1]), floor: floorMat || M.floor, h, fid: ft.id }); };
    zone([u0, T / 2], [u1, depth], ft.id);
    // skirting and coving carry on round the inside (wrapping the outside corners of the opening)
    const full = h >= RH - 0.01, top = full ? RH : h;
    const trimRound = (t, z0, z1, wrap) => {
      wb(wall, u0 - dlo, u1 + dhi, depth - t, depth, z0, z1, M.trim);
      const d0 = wrap ? -t : 0;
      if (!mlo) wb(wall, u0, u0 + t, d0, depth, z0, z1, M.trim);
      if (!mhi) wb(wall, u1 - t, u1, d0, depth, z0, z1, M.trim);
    };
    trimRound(0.018, 0, 0.12, true);
    trimRound(0.05, top - 0.05, top, full);
    if (mlo && wall < mlo.wall) zone([u0 - dlo, 0], [u0, depth], ft.id + '_corner_lo');
    if (mhi && wall < mhi.wall) zone([u1, 0], [u1 + dhi, depth], ft.id + '_corner_hi');
    return [u0, u1];
  };

  const kitchenRun = (wall, u0, u1, back, fid) => {
    const L = u1 - u0, fw = L > 2.0 ? 0.62 : 0;
    const ru0 = u0, ru1 = u1 - fw, df = back - 0.6;
    wb(wall, ru0, ru1, df, back, 0, 0.9, M.kfront, fid);
    wb(wall, ru0, ru1, df - 0.02, back, 0.86, 0.9, M.ktop, fid);
    wb(wall, ru0, ru1, back - 0.01, back, 0.9, 1.45, M.splash, fid);
    const hob = ru0 + (ru1 - ru0) * 0.72;
    if (hob - 0.35 - ru0 > 0.25) wb(wall, ru0, hob - 0.35, back - 0.35, back, 1.45, 2.15, M.kfront, fid);
    if (ru1 - hob - 0.35 > 0.25) wb(wall, hob + 0.35, ru1, back - 0.35, back, 1.45, 2.15, M.kfront, fid);
    wb(wall, hob - 0.3, hob + 0.3, back - 0.48, back, 1.6, 1.67, M.fridge, fid);
    if (fw) wb(wall, u1 - fw + 0.01, u1 - 0.01, back - 0.66, back, 0, 1.85, M.fridge, fid);
  };

  for (const ft of feats) {
    const wall = ft.wall; if (!walls[wall]) continue;
    const [u0, u1] = span(ft);
    if (ft.type === 'alcove') {
      const depth = +(ft.depth ?? 0.6), h = Math.min(+(ft.height ?? RH), RH);
      recess(ft, wall, depth, h);
      if (h < RH - 0.01) wb(wall, u0, u1, 0, depth, h - 0.01, h, M.ceiling, ft.id);
      const n = +(ft.shelves || 0);
      for (let i = 0; i < n; i++) {
        const z = n > 1 ? 0.35 + i * (Math.min(RH, 2.1) - 0.5) / (n - 1) : 1.0;
        wb(wall, u0 + 0.005, u1 - 0.005, Math.max(0, depth - 0.32), depth, z, z + 0.025, M.shelf, ft.id);
      }
    } else if (ft.type === 'kitchenette') {
      const depth = +(ft.depth ?? 0.65);
      recess(ft, wall, depth, RH, M.kfloor);
      kitchenRun(wall, u0, u1, depth, ft.id);
    } else if (ft.type === 'window') {
      const s = +(ft.sill ?? 0.8), h = +(ft.height ?? 1.2);
      wb(wall, u0, u1, T * 0.7, T * 0.72, s, s + h, M.glass, ft.id);
      wb(wall, u0, u1, T * 0.55, T * 0.9, s, s + 0.06, M.frame, ft.id);
      wb(wall, u0, u1, T * 0.55, T * 0.9, s + h - 0.06, s + h, M.frame, ft.id);
      wb(wall, u0, u0 + 0.06, T * 0.55, T * 0.9, s, s + h, M.frame, ft.id);
      wb(wall, u1 - 0.06, u1, T * 0.55, T * 0.9, s, s + h, M.frame, ft.id);
      wb(wall, (u0 + u1) / 2 - 0.03, (u0 + u1) / 2 + 0.03, T * 0.55, T * 0.9, s, s + h, M.frame, ft.id);
      wb(wall, u0 - 0.06, u1 + 0.06, -0.05, T * 0.55, s - 0.025, s, M.trim, ft.id);
      // the outside view itself is the photo sphere (outsideSphere); here only the dressing
      const dressing = ft.dressing || { neglected: 'nets_curtains', hospital: 'blinds', court: 'blinds', custody: 'frosted' }[runDown(spec) ? 'neglected' : spec.style] || 'none';
      if (dressing === 'frosted') wb(wall, u0, u1, T * 0.69, T * 0.73, s, s + h, M.frosted, ft.id);
      if (dressing === 'blinds') {
        const stack = s + h - h * 0.33;
        wb(wall, u0, u1, T * 0.3, T * 0.4, stack, s + h, M.blind, ft.id);
        for (let z = stack - 0.05; z > s + 0.03; z -= 0.09) wb(wall, u0 + 0.01, u1 - 0.01, T * 0.3, T * 0.4, z, z + 0.012, M.blind, ft.id);
      }
      if (dressing === 'curtains' || dressing === 'nets_curtains') {
        wb(wall, u0 - 0.38, u0 + 0.06, -0.12, -0.08, 0.02, Math.min(RH - 0.03, s + h + 0.15), M.curtain, ft.id);
        wb(wall, u1 - 0.06, u1 + 0.38, -0.12, -0.08, 0.02, Math.min(RH - 0.03, s + h + 0.15), M.curtain, ft.id);
      }
      if (dressing === 'nets_curtains') wb(wall, u0, u1, -0.04, -0.03, s, s + h, M.nets, ft.id);
    } else if (ft.type === 'door') {
      const h = +(ft.height ?? 2.0);
      wb(wall, u0 - 0.07, u0, -0.02, 0, 0, h + 0.07, M.trim, ft.id);
      wb(wall, u1, u1 + 0.07, -0.02, 0, 0, h + 0.07, M.trim, ft.id);
      wb(wall, u0 - 0.07, u1 + 0.07, -0.02, 0, h, h + 0.07, M.trim, ft.id);
      const beyond = ft.beyond === 'hall' ? 'corridor' : (ft.beyond || 'corridor');
      if (beyond === 'closed') {
        wb(wall, u0, u1, T * 0.35, T * 0.35 + 0.04, 0, h, M.door, ft.id);
      } else {
        if (beyond !== 'outside') {
          // a corridor along the wall, stopping short of anything else built beyond it (same rule as the generator)
          const [ca, cb, cw] = corridorExtent(spec, ft);
          const hm = beyond === 'dark' ? M.dark : M.wall, back = T + cw;
          wb(wall, ca - T, cb + T, back, back + T, 0, RH, hm, ft.id);
          wb(wall, ca - T, ca, 0, back + T, 0, RH, hm, ft.id);
          wb(wall, cb, cb + T, 0, back + T, 0, RH, hm, ft.id);
          const a = w2(wall, ca, T / 2), b = w2(wall, cb, back);
          zones.push({ name: ft.id + '_hall', x0: Math.min(a[0], b[0]), y0: Math.min(a[1], b[1]), x1: Math.max(a[0], b[0]), y1: Math.max(a[1], b[1]), floor: beyond === 'dark' ? M.dark : M.floor, h: RH, fid: ft.id });
        }
        // open leaf, swung out into the hall from the u1 side
        const lw = u1 - u0, ang = 78 * Math.PI / 180;
        const hinge = w2(wall, u1, T, 0);
        const leaf = new THREE.Mesh(new THREE.BoxGeometry(lw, h - 0.01, 0.04), M.door);
        leaf.geometry.translate(-lw / 2, (h - 0.01) / 2, 0.02);
        const closed = { north: 0, south: 0, east: Math.PI / 2, west: Math.PI / 2 }[wall];
        const swing = { north: -ang, south: ang, east: ang, west: -ang }[wall];
        leaf.position.copy(b2t(hinge[0], hinge[1], 0)); leaf.rotation.y = closed + swing;
        add(leaf, ft.id);
      }
    } else if (ft.type === 'arch') {
      const room = ft.room || { type: 'recess', depth: 1.0 };
      const depth = +(room.depth ?? 2.0), rpos = +(room.pos ?? ft.pos), rw = +(room.width ?? (+ft.width + 1.0));
      const lo = walls[wall].lo, hi = walls[wall].hi;
      const ru0 = Math.max(lo - T, Math.min(u0, rpos - rw / 2)), ru1 = Math.min(hi + T, Math.max(u1, rpos + rw / 2));
      const back = T + depth;
      wb(wall, ru0 - T, ru1 + T, back, back + T, 0, RH, M.wall, ft.id);
      wb(wall, ru0 - T, ru0, T, back + T, 0, RH, M.wall, ft.id);
      wb(wall, ru1, ru1 + T, T, back + T, 0, RH, M.wall, ft.id);
      const kit = room.type === 'kitchen';
      const a = w2(wall, ru0, T / 2), b = w2(wall, ru1, back);
      zones.push({ name: ft.id + '_room', x0: Math.min(a[0], b[0]), y0: Math.min(a[1], b[1]), x1: Math.max(a[0], b[0]), y1: Math.max(a[1], b[1]), floor: kit ? M.kfloor : M.floor, h: RH, fid: ft.id });
      if (kit) kitchenRun(wall, ru0, ru1, back, ft.id);
    }
  }

  for (const z of zones) {
    const fl = rectPlane(z.x0, z.y0, z.x1, z.y1, 0, z.floor, 'floor_' + z.name);
    fl.userData.isFloor = true; root.add(fl);
    const ce = rectPlane(z.x0, z.y0, z.x1, z.y1, z.h, M.ceiling, 'ceiling_' + z.name);
    ceilings.add(ce);
  }
  root.add(ceilings);
  worldUVs(root);
  const decals = new THREE.Group(); decals.name = 'decals';
  (spec.decals || []).forEach((dc, i) => { const m = decalMesh(spec, dc, i); if (m) decals.add(m); });
  root.add(decals);
  return { root, ceilings, pick, frame: F, zones, decals };
}

export function corridorExtent(spec, ft) {
  const F = roomFrame(spec), w = F.walls[ft.wall]; const [u0, u1] = span(ft);
  const cw = { hospital: 1.9, court: 2.2, custody: 1.6 }[spec.style] || 1.15;
  let a = w.lo, b = w.hi;
  for (const g of spec.features || []) {
    if (g === ft || g.wall !== ft.wall || !['alcove', 'kitchenette', 'arch', 'window', 'door'].includes(g.type)) continue;
    let [g0, g1] = span(g);
    if (g.type === 'arch') { const rm = g.room || {}; const rp = +(rm.pos ?? g.pos), rw = +(rm.width ?? (+g.width + 1)); g0 = Math.min(g0, rp - rw / 2); g1 = Math.max(g1, rp + rw / 2); }
    if (g1 <= u0) a = Math.max(a, g1 + T + 0.05); else if (g0 >= u1) b = Math.min(b, g0 - T - 0.05);
  }
  return [Math.min(a, u0 - 0.2), Math.max(b, u1 + 0.2), cw];
}

// The view outside windows and outside doors: the same Poly Haven photo the render uses, on a big sphere.
// Blender shows the photo's centre to the west at rotation 0 and turns it anticlockwise (seen from above) as
// rotation goes up; three.js rotation.y = -rotation does the same here.
const texLoader = new THREE.TextureLoader();
const outsideTex = new Map();
export function outsideHdriId(spec, cfg) {
  const out = spec.outside || {};
  const view = out.view || cfg?.style_default?.[runDown(spec) ? 'neglected' : spec.style] || 'garden';
  if (view === 'custom') return out.hdri || null;
  const v = (cfg?.views || []).find(x => x.id === view);
  return v ? (v[spec.lighting || 'day'] || v.day) : null;
}
export function outsideSphere(spec, cfg, onLoad) {
  const id = outsideHdriId(spec, cfg);
  const geo = new THREE.SphereGeometry(60, 64, 32); geo.scale(-1, 1, 1);
  const mat = new THREE.MeshBasicMaterial({ color: 0x8aa0b4, depthWrite: false });
  const mesh = new THREE.Mesh(geo, mat); mesh.name = 'outside'; mesh.renderOrder = -1;
  mesh.rotation.y = -(+(spec.outside?.rotation || 0)) * Math.PI / 180;
  if (id) {
    let t = outsideTex.get(id);
    if (!t) { t = texLoader.load(`/api/hdri/${encodeURIComponent(id)}.png`, () => onLoad?.()); t.colorSpace = THREE.SRGBColorSpace; outsideTex.set(id, t); }
    mat.map = t; mat.color.set(0xffffff);
    if (spec.lighting === 'night') mat.color.set(0x9a9a9a);
  }
  return mesh;
}

// ------------------------------------------------------------------ catalogue models
const loader = new GLTFLoader();
const cache = new Map();

export function loadModel(meta) {
  if (!meta || !meta.file) return Promise.reject(new Error('no file'));
  const key = meta.id;
  if (!cache.has(key)) {
    const url = `/catalogue/models/${encodeURIComponent(meta.id)}/${meta.file.split('/').map(encodeURIComponent).join('/')}`;
    cache.set(key, new Promise((res, rej) => loader.load(url, g => {
      const scene = g.scene;
      scene.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(scene);
      scene.traverse(o => { if (o.isMesh) { o.castShadow = false; o.receiveShadow = false; } });
      res({ scene, box });
    }, undefined, rej)));
  }
  return cache.get(key);
}

// An item group: the model centred on its footprint and standing on its base, then moved/turned/scaled like the
// generator does it.
export async function makeItem(item, meta) {
  const g = new THREE.Group(); g.name = 'item_' + item.id; g.userData.itemId = item.id;
  try {
    const { scene, box } = await loadModel(meta);
    const inner = scene.clone(true);
    const c = box.getCenter(new THREE.Vector3());
    inner.position.set(-c.x, -box.min.y, -c.z);
    const holder = new THREE.Group(); holder.add(inner);
    g.add(holder);
    g.userData.size = box.getSize(new THREE.Vector3());       // three-space size before scaling (x, height, z)
  } catch (e) {
    const fallback = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.5), new THREE.MeshStandardMaterial({ color: 0xff00ff }));
    fallback.position.y = 0.25; g.add(fallback); g.userData.size = new THREE.Vector3(0.5, 0.5, 0.5); g.userData.missing = true;
  }
  applyItem(g, item, meta);
  return g;
}

export function applyItem(g, item, meta) {
  const s = (+(item.scale ?? 1)) * (+(meta?.scale ?? 1));
  g.scale.setScalar(s);
  g.rotation.set(0, (+(item.rot ?? 0)) * Math.PI / 180, 0);
  g.position.copy(b2t(+item.x || 0, +item.y || 0, +(item.z ?? 0)));
}

// footprint corners of an item in spec space (x, y), for the floor check and wall snapping
export function footprint(g, item, meta) {
  const size = g.userData.size || new THREE.Vector3(0.5, 0.5, 0.5);
  const s = (+(item.scale ?? 1)) * (+(meta?.scale ?? 1));
  const hx = size.x * s / 2, hy = size.z * s / 2;       // three z is spec -y
  const a = (+(item.rot ?? 0)) * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
  return [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]].map(([x, y]) => [+item.x + x * ca - y * sa, +item.y + x * sa + y * ca]);
}

export function lightRoom(scene, spec) {
  const neg = runDown(spec), night = spec.lighting === 'night', dusk = spec.lighting === 'dusk';
  // the ground colour also lights the ceiling: keep it pale so ceilings don't preview brown
  const hemi = new THREE.HemisphereLight(neg ? 0xffe2b8 : 0xffffff, neg ? 0x8a7a64 : 0xc4beb4, neg ? 1.1 : (night ? 1.2 : 1.6));
  const dir = new THREE.DirectionalLight(neg ? 0xffd9a0 : 0xffffff, night ? 0.4 : (dusk ? 0.7 : 1.2));
  dir.position.set(-3, 6, 2);
  const amb = new THREE.AmbientLight(0xffffff, neg ? 0.25 : 0.45);
  const g = new THREE.Group(); g.name = 'lights'; g.add(hemi, dir, amb);
  scene.add(g);
  return g;
}

// ------------------------------------------------------------------ cube -> equirectangular (the live 360 page)
export class EquirectRenderer {
  constructor(renderer, size = 1024) {
    this.renderer = renderer;
    this.target = new THREE.WebGLCubeRenderTarget(size, { generateMipmaps: false });
    this.cubeCam = new THREE.CubeCamera(0.02, 100, this.target);
    this.scene = new THREE.Scene();
    this.cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.mat = new THREE.ShaderMaterial({
      uniforms: { env: { value: this.target.texture }, yaw: { value: 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: `
        uniform samplerCube env; uniform float yaw; varying vec2 vUv;
        void main(){
          // centre of the image looks north (spec +y = three -z), right edge wraps round through east
          float lon = (vUv.x - 0.5) * 6.28318530718 + yaw;
          float lat = (vUv.y - 0.5) * 3.14159265359;
          vec3 d = vec3(sin(lon) * cos(lat), sin(lat), -cos(lon) * cos(lat));
          gl_FragColor = textureCube(env, d);
          #include <colorspace_fragment>
        }`,
    });
    this.scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.mat));
  }
  render(scene, pos, yawDeg = 0) {
    this.cubeCam.position.copy(pos);
    this.cubeCam.update(this.renderer, scene);
    this.mat.uniforms.yaw.value = yawDeg * Math.PI / 180;
    this.renderer.setRenderTarget(null);
    this.renderer.render(this.scene, this.cam);
  }
}
