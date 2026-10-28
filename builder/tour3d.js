// tour3d.js: live 3D objects drawn into a 360 (equirectangular) picture, for tours.
// The objects sit in a three.js scene round the projection centre (metres; origin = eye at the room centre,
// -Z = Front wall = middle of the 360 image, +X = Right). A cube camera at the origin films them and a shader turns that
// into an equirect with a transparent background, laid over the room render (the same way as the scare layer).
// Lighting comes from the room's own render (as an environment map), so objects pick up its colours and light.
//   const t = createTour3D({ canvas, base: '/' });          base = where catalogue/ lives on this server
//   t.setSize(w, h); await t.setRoom(panoUrl);
//   t.sync([{ key, model, yaw, dist, h, eye, turn, size, visible }]);   models standing in the room (h = height of the surface)
//   t.setInspect({ model, yaw, dist, y, fit, rx, ry, zoom }) or null;   one object held up big in front of a wall
//   t.frame() each animation frame: renders only when something changed; returns true when it drew
//   t.hit(key) -> { yaw, pitch, rad } where the object is in the picture (degrees), once loaded
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { clone as skClone } from 'three/addons/utils/SkeletonUtils.js';

const D2R = Math.PI / 180;

export function createTour3D({ canvas, base = '/', cube = 1024, onLoad = null }) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, premultipliedAlpha: true, preserveDrawingBuffer: true });
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3a3a, 0.35));
  const sun = new THREE.DirectionalLight(0xffffff, 0.55); sun.position.set(0.6, 3, 1.2); scene.add(sun);
  const cubeRT = new THREE.WebGLCubeRenderTarget(cube, { type: THREE.HalfFloatType, generateMipmaps: false });
  const cubeCam = new THREE.CubeCamera(0.02, 60, cubeRT);
  const comp = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
    uniforms: { env: { value: cubeRT.texture } }, depthTest: false, depthWrite: false, transparent: true,
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: `uniform samplerCube env; varying vec2 vUv;
      void main(){
        float lon = (vUv.x - 0.5) * 6.28318530718, lat = (vUv.y - 0.5) * 3.14159265359;
        vec3 d = vec3(sin(lon) * cos(lat), sin(lat), -cos(lon) * cos(lat));
        vec4 o = textureCube(env, d);
        gl_FragColor = vec4(o.rgb, 1.0);
        #include <colorspace_fragment>
        gl_FragColor = vec4(gl_FragColor.rgb * o.a, o.a);
      }`,
  }));
  comp.material.blending = THREE.NoBlending;
  const compScene = new THREE.Scene(); compScene.add(comp);
  const compCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const pmrem = new THREE.PMREMGenerator(renderer);
  let dirty = true, envTex = null;

  // ---------------------------------------------------------------- models from the catalogue
  const loader = new GLTFLoader(), cache = {};
  function load(id) {
    if (!cache[id]) cache[id] = (async () => {
      const root = `${base}catalogue/models/${encodeURIComponent(id)}/`;
      const meta = await (await fetch(root + 'model.json')).json();
      const gltf = await loader.loadAsync(root + meta.file);
      const g = gltf.scene;
      g.traverse((o) => { if (o.isMesh) { o.frustumCulled = false; const ms = Array.isArray(o.material) ? o.material : [o.material]; for (const m of ms) if (m && 'envMapIntensity' in m) m.envMapIntensity = 1; } });
      const box = new THREE.Box3().setFromObject(g), c = box.getCenter(new THREE.Vector3());
      g.position.sub(new THREE.Vector3(c.x, box.min.y, c.z));         // footprint centred, lowest point on the floor
      const proto = new THREE.Group(); proto.add(g); proto.scale.setScalar(+meta.scale || 1);
      const size = box.getSize(new THREE.Vector3()).multiplyScalar(+meta.scale || 1);
      return { proto, size, meta };
    })();
    return cache[id];
  }
  let blobTex = null;
  function blob(size) {                                               // a soft contact shadow under a standing object
    if (!blobTex) {
      const cv = document.createElement('canvas'); cv.width = cv.height = 64; const x = cv.getContext('2d');
      const g = x.createRadialGradient(32, 32, 2, 32, 32, 32); g.addColorStop(0, 'rgba(0,0,0,.55)'); g.addColorStop(1, 'rgba(0,0,0,0)');
      x.fillStyle = g; x.fillRect(0, 0, 64, 64); blobTex = new THREE.CanvasTexture(cv);
    }
    const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; m.position.y = 0.002; m.scale.set(size.x * 1.35 + 0.02, size.z * 1.35 + 0.02, 1); m.renderOrder = -1;
    return m;
  }

  // ---------------------------------------------------------------- objects standing in the room
  const placed = new Map();
  function sync(list) {
    const keep = new Set(list.map((o) => o.key));
    for (const [k, p] of placed) if (!keep.has(k)) { scene.remove(p.group); placed.delete(k); dirty = true; }
    for (const o of list) {
      let p = placed.get(o.key);
      if (!p || p.model !== o.model) {
        if (p) scene.remove(p.group);
        p = { model: o.model, group: new THREE.Group(), size: null, error: '' }; placed.set(o.key, p); scene.add(p.group);
        const mine = p;
        load(o.model).then((m) => {
          if (placed.get(o.key) !== mine) return;
          mine.group.add(skClone(m.proto)); mine.group.add(blob(m.size)); mine.size = m.size.clone(); dirty = true; onLoad && onLoad(o.key);
        }).catch((e) => { mine.error = e.message || String(e); onLoad && onLoad(o.key, mine.error); });
      }
      const y = (+o.yaw || 0) * D2R, d = Math.max(0.2, +o.dist || 1);
      p.group.position.set(d * Math.sin(y), (+o.h || 0) - (+o.eye || 1.12), -d * Math.cos(y));
      p.group.rotation.set(0, -(+o.turn || 0) * D2R, 0);
      p.group.scale.setScalar(+o.size || 1);
      p.group.visible = o.visible !== false;
      p.spec = o;
    }
    dirty = true;
  }
  function hit(key) {
    const p = placed.get(key); if (!p || !p.size || !p.group.visible) return null;
    const s = p.group.scale.x, c = p.group.position.clone().add(new THREE.Vector3(0, p.size.y * s / 2, 0));
    const r = p.size.length() * s / 2, dist = c.length();
    return { yaw: Math.atan2(c.x, -c.z) / D2R, pitch: Math.atan2(c.y, Math.hypot(c.x, c.z)) / D2R, rad: Math.atan(r / Math.max(dist, 0.1)) / D2R + 0.6 };
  }
  const error = (key) => (placed.get(key) || {}).error || '';

  // ---------------------------------------------------------------- one object held up to look at
  let insp = null;
  function setInspect(o) {
    if (!o) { if (insp) { scene.remove(insp.group); insp = null; dirty = true; } return; }
    if (!insp || insp.model !== o.model) {
      if (insp) scene.remove(insp.group);
      const group = new THREE.Group(), tilt = new THREE.Group(), spin = new THREE.Group();
      group.add(tilt); tilt.add(spin); scene.add(group);
      insp = { model: o.model, group, tilt, spin, size: null, cur: { rx: 0, ry: 0, zoom: 1 } };
      const mine = insp;
      load(o.model).then((m) => {
        if (insp !== mine) return;
        const inst = skClone(m.proto); inst.position.y = -m.size.y / 2; mine.size = m.size.clone();
        // something that lies flat (notes, a clipboard, a tray) is held up with its top facing you, or you'd only see its edge.
        // Stood up inside the turning frame, so left/right still turns it round and up/down still tilts it.
        if (m.size.y < 0.35 * Math.max(m.size.x, m.size.z)) {
          const up = new THREE.Group(); up.rotation.x = Math.PI / 2; up.add(inst); mine.spin.add(up);
          mine.size = new THREE.Vector3(m.size.x, m.size.z, m.size.y);  // its size as held
        } else mine.spin.add(inst);
        dirty = true;
      }).catch(() => {});
    }
    insp.spec = o; dirty = true;
  }
  function stepInspect() {
    if (!insp || !insp.size) return false;
    // glide toward the angle asked for: time-based (about 0.2 s), so tablet updates a few times a second blend into one smooth turn
    const t = performance.now(), dt = Math.min(0.1, (t - (insp.t || t)) / 1000); insp.t = t;
    const o = insp.spec, c = insp.cur, k = 1 - Math.exp(-dt / 0.2);
    const tgt = { rx: (+o.rx || 0) * D2R, ry: (+o.ry || 0) * D2R, zoom: +o.zoom || 1 };
    let moving = false;
    for (const key of ['rx', 'ry', 'zoom']) { const dv = tgt[key] - c[key]; if (Math.abs(dv) > 2e-3) { c[key] += dv * k; moving = true; } else c[key] = tgt[key]; }
    const y = (+o.yaw || 0) * D2R, d = +o.dist || 2.4;
    insp.group.position.set(d * Math.sin(y), +o.y || 0, -d * Math.cos(y));
    insp.group.rotation.set(0, -y, 0);                                 // the model's front (+Z) faces the middle of the room
    insp.group.scale.setScalar((+o.fit || 0.8) / Math.max(insp.size.x, insp.size.y, insp.size.z, 0.01) * c.zoom);
    insp.tilt.rotation.set(c.rx, 0, 0); insp.spin.rotation.set(0, c.ry, 0);
    return moving;
  }

  // ---------------------------------------------------------------- room lighting and drawing
  async function setRoom(url) {
    const tex = await new THREE.TextureLoader().loadAsync(url).catch(() => null);
    if (!tex) return;
    tex.mapping = THREE.EquirectangularReflectionMapping; tex.colorSpace = THREE.SRGBColorSpace;
    const env = pmrem.fromEquirectangular(tex).texture; tex.dispose();
    if (envTex) envTex.dispose();
    envTex = env; scene.environment = env;
    scene.environmentRotation.set(0, Math.PI / 2, 0);                  // three puts the middle of an equirect at +X; ours is the Front (-Z)
    dirty = true;
  }
  // a message lying flat on the floor in front of a wall, parallel to it, reading from the room centre ("Carrying: ...")
  //   setFloorText({ text, yaw (the wall's middle), dist (metres from the centre), eye, maxW, color }) or null
  let floor = null;
  function setFloorText(o) {
    const key = o ? JSON.stringify(o) : '';
    if (floor && floor.key === key) return;
    if (floor) { scene.remove(floor.mesh); floor.mesh.geometry.dispose(); floor.mesh.material.map.dispose(); floor.mesh.material.dispose(); floor = null; dirty = true; }
    if (!o || !o.text) return;
    const cv = document.createElement('canvas'), x = cv.getContext('2d'), fpx = 96, font = `600 ${fpx}px "Segoe UI", system-ui, sans-serif`;
    x.font = font; const tw = x.measureText(o.text).width;
    cv.width = Math.ceil(tw + fpx * 1.6); cv.height = Math.round(fpx * 1.8);
    x.font = font; x.textAlign = 'center'; x.textBaseline = 'middle';
    const r = cv.height / 2 - 4;
    x.beginPath(); x.roundRect(4, 4, cv.width - 8, cv.height - 8, r); x.fillStyle = 'rgba(16,20,26,0.85)'; x.fill();
    x.lineWidth = 6; x.strokeStyle = o.color || '#f3d36b'; x.stroke();
    x.fillStyle = '#fff'; x.fillText(o.text, cv.width / 2, cv.height / 2 + 4);
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
    let h = 0.24, w = h * cv.width / cv.height;                       // letters about 13 cm tall on the floor
    if (o.maxW && w > o.maxW) { h *= o.maxW / w; w = o.maxW; }
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false }));
    const y = (+o.yaw || 0) * D2R, d = +o.dist || 2;
    mesh.rotation.order = 'YXZ'; mesh.rotation.set(-Math.PI / 2, -y, 0);   // flat, the top of the letters towards the wall
    mesh.position.set(d * Math.sin(y), 0.004 - (+o.eye || 1.12), -d * Math.cos(y));
    scene.add(mesh); floor = { key, mesh }; dirty = true;
  }
  function setSize(w, h) { renderer.setSize(Math.max(2, Math.round(w)), Math.max(2, Math.round(h)), false); dirty = true; }
  function frame() {
    if (stepInspect()) dirty = true;
    if (!dirty) return false;
    dirty = false;
    cubeCam.position.set(0, 0, 0); cubeCam.update(renderer, scene);
    renderer.setRenderTarget(null); renderer.clear(); renderer.render(compScene, compCam);
    return true;
  }
  return { setSize, setRoom, sync, setInspect, setFloorText, frame, hit, error, load, invalidate: () => { dirty = true; }, renderer, scene, THREE };
}
