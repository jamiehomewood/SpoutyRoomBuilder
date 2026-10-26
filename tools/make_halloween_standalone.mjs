// Build one self-contained Halloween file that needs no server and no Python: open it straight from disk
// (or point an ICE web layer at it). Everything goes inside: three.js, the page code, the room and both renders.
//
//   npm i esbuild            (once, anywhere)
//   node tools/make_halloween_standalone.mjs <lit library id> <dark library id> [out.html]
import { build } from 'esbuild';
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const [lit, dark, out = path.join(ROOT, 'halloween_standalone.html')] = process.argv.slice(2);
if (!lit || !dark) { console.error('usage: node tools/make_halloween_standalone.mjs <lit id> <dark id> [out.html]'); process.exit(1); }
const page = fs.readFileSync(path.join(ROOT, 'builder/halloween.html'), 'utf8');
const m = page.match(/<script type="module">([\s\S]*?)<\/script>/);
const entry = path.join(ROOT, 'builder', '_hw_entry.js'); fs.writeFileSync(entry, m[1]);
const three = path.join(ROOT, 'vendor/three/build/three.module.js'), addons = path.join(ROOT, 'vendor/three/jsm');
const res = await build({ entryPoints: [entry], bundle: true, format: 'esm', write: false, minify: true, target: 'es2022',
  plugins: [{ name: 'three', setup(b) {
    b.onResolve({ filter: /^three$/ }, () => ({ path: three }));
    b.onResolve({ filter: /^three\/addons\// }, a => ({ path: path.join(addons, a.path.slice('three/addons/'.length)) }));
  } }] });
fs.unlinkSync(entry);
const lib = id => path.join(ROOT, 'library', id);
const uri = f => 'data:image/jpeg;base64,' + fs.readFileSync(f).toString('base64');
const data = { litName: lit, darkName: dark, spec: JSON.parse(fs.readFileSync(path.join(lib(lit), 'spec.json'), 'utf8')),
  lit: uri(path.join(lib(lit), 'view_centre.jpg')), dark: uri(path.join(lib(dark), 'view_centre.jpg')) };
const js = res.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
let html = page.replace(/<script type="importmap">[\s\S]*?<\/script>\s*/, '')
  .replace(/<script type="module">[\s\S]*?<\/script>/, () => `<script>window.__HW_DATA = ${JSON.stringify(data)};</script>\n<script type="module">${js}</script>`);
fs.writeFileSync(out, html);
console.log('wrote', out, (fs.statSync(out).size / 1e6).toFixed(1), 'MB');
