"""
Room Builder server - runs on this PC. Serves the builder page, keeps the render queue, runs Blender to render
rooms one at a time, and keeps the library of finished rooms. Only Python's standard library is used.

    python server.py            (http://localhost:8030)
    python server.py 8031       (another port)

Settings live in config.json (made on first run): the path to blender.exe, your Sketchfab API token, and whether
other devices on the network may open the builder.
"""
import json, mimetypes, os, re, shutil, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request, uuid, zipfile, glob, io
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
CAT = os.path.join(ROOT, "catalogue", "models")
LIB = os.path.join(ROOT, "library")
ROOMS = os.path.join(ROOT, "rooms")
JOBS = os.path.join(ROOT, "jobs")
PRESETS = os.path.join(ROOT, "presets")
CONFIG_FILE = os.path.join(ROOT, "config.json")
QUEUE_FILE = os.path.join(JOBS, "queue.json")
STATS_FILE = os.path.join(JOBS, "stats.json")
GENERATOR = os.path.join(ROOT, "generator", "generate.py")
for d in (CAT, LIB, ROOMS, JOBS): os.makedirs(d, exist_ok=True)

for ext, typ in {".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm", ".glb": "model/gltf-binary",
                 ".gltf": "model/gltf+json", ".json": "application/json", ".bin": "application/octet-stream"}.items():
    mimetypes.add_type(typ, ext)

UA = {"User-Agent": "RoomBuilder/1.0 (local scenario room tool)"}
QUALITIES = {"draft": (2048, 1024, 48), "standard": (6144, 3072, 256), "high": (8192, 4096, 512)}
ALLOWED_SKETCHFAB = {"cc0": ("CC0", "https://creativecommons.org/publicdomain/zero/1.0/", False),
                     "by": ("CC-BY 4.0", "https://creativecommons.org/licenses/by/4.0/", True)}

# ------------------------------------------------------------------ config
def find_blender():
    cands = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)
    cands += sorted(glob.glob(os.path.expanduser(r"~\AppData\Local\Programs\Blender Foundation\Blender*\blender.exe")), reverse=True)
    cands += [shutil.which("blender") or ""]
    for c in cands:
        if c and os.path.exists(c): return c
    return ""

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh: return json.load(fh)
    except (OSError, ValueError):
        return default

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(data, fh, indent=2)
    os.replace(tmp, path)

CONFIG = load_json(CONFIG_FILE, {})
CONFIG.setdefault("blender", "")
CONFIG.setdefault("sketchfab_token", "")
CONFIG.setdefault("allow_network", False)
CONFIG.setdefault("port", 8030)
if not CONFIG["blender"] or not os.path.exists(CONFIG["blender"]): CONFIG["blender"] = find_blender()
save_json(CONFIG_FILE, CONFIG)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(CONFIG["port"])

def slug(s, n=40):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", str(s)).strip("-").lower()
    return (s or "room")[:n]

def http_json(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def http_download(url, path, headers=None, timeout=120):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as fh:
        shutil.copyfileobj(r, fh)

# ------------------------------------------------------------------ catalogue
def catalogue_list():
    out = []
    for mid in sorted(os.listdir(CAT)):
        meta = load_json(os.path.join(CAT, mid, "model.json"), None)
        if meta:
            meta["id"] = mid
            out.append(meta)
    return out

def catalogue_update(mid, changes):
    p = os.path.join(CAT, mid, "model.json")
    meta = load_json(p, None)
    if meta is None: raise KeyError(mid)
    for k in ("name", "status", "notes", "category", "styles", "scale", "tags"):
        if k in changes: meta[k] = changes[k]
    if meta.get("status") not in ("untested", "room-tested", "rejected"): meta["status"] = "untested"
    save_json(p, meta)
    return meta

_ph_cache = {"t": 0, "assets": None}
def polyhaven_assets():
    if not _ph_cache["assets"] or time.time() - _ph_cache["t"] > 3600:
        _ph_cache["assets"] = http_json("https://api.polyhaven.com/assets?t=models"); _ph_cache["t"] = time.time()
    return _ph_cache["assets"]

def polyhaven_search(q, category):
    assets = polyhaven_assets(); q = (q or "").lower().strip(); have = set(os.listdir(CAT))
    out = []
    for aid, a in assets.items():
        text = " ".join([aid, a.get("name", "")] + a.get("tags", []) + a.get("categories", [])).lower()
        if q and not all(w in text for w in q.split()): continue
        if category and category not in a.get("categories", []): continue
        out.append({"id": aid, "name": a.get("name", aid), "thumb": f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=256&height=256",
                    "categories": a.get("categories", []), "author": ", ".join(a.get("authors", {}).keys()), "licence": "CC0",
                    "polycount": a.get("polycount"), "url": f"https://polyhaven.com/a/{aid}", "in_library": aid in have,
                    "downloads": a.get("download_count", 0)})
    out.sort(key=lambda r: -r["downloads"])
    return out[:120]

def polyhaven_categories():
    try: return http_json("https://api.polyhaven.com/categories/models")
    except Exception: return {}

def polyhaven_import(aid):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", aid): raise ValueError("bad id")
    info = http_json(f"https://api.polyhaven.com/info/{aid}")
    files = http_json(f"https://api.polyhaven.com/files/{aid}")
    g = files["gltf"].get("2k") or files["gltf"].get("1k") or next(iter(files["gltf"].values()))
    g = g["gltf"]
    dst = os.path.join(CAT, aid); tmp = dst + ".part"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    http_download(g["url"], os.path.join(tmp, f"{aid}.gltf"))
    for rel, inc in g.get("include", {}).items():
        p = os.path.join(tmp, rel); os.makedirs(os.path.dirname(p), exist_ok=True); http_download(inc["url"], p)
    try: http_download(f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=256&height=256", os.path.join(tmp, "thumb.png"))
    except Exception: pass
    meta = {"id": aid, "name": info.get("name", aid), "file": f"{aid}.gltf", "thumb": "thumb.png", "category": guess_category(aid, info.get("categories", []) + info.get("tags", [])),
            "styles": ["modern", "neglected"], "tags": info.get("tags", []), "status": "untested", "notes": "", "scale": 1.0,
            "polycount": info.get("polycount"),
            "licence": {"source": "Poly Haven", "author": ", ".join(info.get("authors", {}).keys()), "licence": "CC0",
                        "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/", "url": f"https://polyhaven.com/a/{aid}", "credit_required": False}}
    save_json(os.path.join(tmp, "model.json"), meta)
    shutil.rmtree(dst, ignore_errors=True); os.replace(tmp, dst)
    return meta

def guess_category(name, words):
    w = set(x.lower() for x in words) | set(re.split(r"[^a-z]+", name.lower()))
    for cat, keys in [("seating", {"seating", "chair", "sofa", "armchair", "ottoman", "stool", "bench", "couch"}),
                      ("tables", {"table", "tables", "desk", "nightstand"}),
                      ("storage", {"cabinet", "shelf", "shelves", "bookshelf", "bookcase", "drawer", "storage", "dresser", "sideboard", "wardrobe"}),
                      ("beds", {"bed", "beds", "mattress"}),
                      ("plants", {"plant", "plants", "shrub", "tree", "planter", "flower"}),
                      ("lighting", {"lamp", "light", "lighting"}),
                      ("electronics", {"television", "tv", "console", "electronics", "radio", "microwave", "kettle", "appliance", "appliances"}),
                      ("kitchen", {"kitchen", "tea", "bowl", "cup", "food", "fruit", "kitchenware", "plate", "mug"}),
                      ("medical", {"medical", "medicine", "pill", "wheelchair", "walker", "commode", "hospital"}),
                      ("decor", {"decorative", "decor", "vase", "frame", "picture", "clock", "pillow", "pillows", "basket", "book", "books", "rug"}),
                      ("clutter", {"box", "trash", "bag", "rubbish", "cardboard", "bottle", "litter"})]:
        if w & keys: return cat
    return "misc"

_sf_cat = {"t": 0, "data": None}
def sketchfab_categories():
    if not _sf_cat["data"] or time.time() - _sf_cat["t"] > 86400:
        d = http_json("https://api.sketchfab.com/v3/categories")
        _sf_cat["data"] = [{"slug": c["slug"], "name": c["name"]} for c in d.get("results", [])]; _sf_cat["t"] = time.time()
    return _sf_cat["data"]

def sketchfab_thumb(m, want=256):
    imgs = (m.get("thumbnails") or {}).get("images") or []
    imgs = sorted(imgs, key=lambda i: abs(i.get("width", 0) - want))
    return imgs[0]["url"] if imgs else ""

def sketchfab_search(q, category, maxfaces, licence, cursor):
    have = set(os.listdir(CAT))
    lic_list = ["cc0", "by"] if licence in ("", "both", None) else [licence]
    lic_list = [l for l in lic_list if l in ALLOWED_SKETCHFAB]
    results, nxt = [], {}
    cursors = json.loads(cursor) if cursor else {}
    for lic in lic_list:
        if cursors and lic not in cursors: continue
        params = {"type": "models", "q": q or "", "downloadable": "true", "license": lic, "count": 24}
        if not q: params["sort_by"] = "-likeCount"
        if category: params["categories"] = category
        if maxfaces: params["max_face_count"] = int(maxfaces)
        if cursors.get(lic): params["cursor"] = cursors[lic]
        d = http_json("https://api.sketchfab.com/v3/search?" + urllib.parse.urlencode(params))
        for m in d.get("results", []):
            uid = m.get("uid"); mid = "sf_" + uid
            results.append({"id": mid, "uid": uid, "name": m.get("name"), "thumb": sketchfab_thumb(m),
                            "author": (m.get("user") or {}).get("displayName") or (m.get("user") or {}).get("username"),
                            "licence": ALLOWED_SKETCHFAB[lic][0], "faces": m.get("faceCount"), "url": m.get("viewerUrl"),
                            "in_library": mid in have, "animated": m.get("isAgeRestricted") is False and m.get("animationCount", 0) > 0})
        c = (d.get("cursors") or {}).get("next")
        if c: nxt[lic] = c
    # interleave the two licence lists so both show near the top
    a = [r for r in results if r["licence"] == "CC0"]; b = [r for r in results if r["licence"] != "CC0"]
    mixed = [x for pair in zip(b, a) for x in pair] + b[len(a):] + a[len(b):]
    return {"results": mixed, "next": json.dumps(nxt) if nxt else ""}

def sketchfab_import(uid):
    token = CONFIG.get("sketchfab_token", "").strip()
    if not token: raise PermissionError("Add your Sketchfab API token in Settings first (Sketchfab > Settings > Password & API).")
    if not re.fullmatch(r"[a-f0-9]{32}", uid): raise ValueError("bad model id")
    info = http_json(f"https://api.sketchfab.com/v3/models/{uid}")
    lic = (info.get("license") or {}).get("slug", "")
    if lic not in ALLOWED_SKETCHFAB:
        raise PermissionError(f"This model's licence ({(info.get('license') or {}).get('label', lic)}) isn't allowed. Only CC0 and CC-BY can be imported.")
    try:
        dl = http_json(f"https://api.sketchfab.com/v3/models/{uid}/download", headers={"Authorization": f"Token {token}"})
    except urllib.error.HTTPError as e:
        if e.code in (401, 403): raise PermissionError("Sketchfab refused the download: check your API token in Settings.")
        raise
    mid = "sf_" + uid; dst = os.path.join(CAT, mid); tmp = dst + ".part"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    if dl.get("glb"):
        http_download(dl["glb"]["url"], os.path.join(tmp, "model.glb")); fname = "model.glb"
    else:
        zp = os.path.join(tmp, "download.zip"); http_download(dl["gltf"]["url"], zp)
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                tgt = os.path.normpath(os.path.join(tmp, n))
                if not tgt.startswith(os.path.normpath(tmp)): continue        # no paths outside the folder
                if n.endswith("/"): os.makedirs(tgt, exist_ok=True); continue
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                with z.open(n) as src, open(tgt, "wb") as out: shutil.copyfileobj(src, out)
        os.remove(zp)
        fname = ""
        for r_, _, fs in os.walk(tmp):
            for f in fs:
                if f.lower().endswith(".gltf"): fname = os.path.relpath(os.path.join(r_, f), tmp).replace("\\", "/"); break
            if fname: break
        if not fname: raise RuntimeError("The download had no glTF file in it.")
    th = sketchfab_thumb(info, 256)
    if th:
        try: http_download(th, os.path.join(tmp, "thumb.jpg"))
        except Exception: pass
    label, lurl, credit = ALLOWED_SKETCHFAB[lic]
    author = (info.get("user") or {}).get("displayName") or (info.get("user") or {}).get("username", "")
    cats = [c.get("name", "") for c in info.get("categories", [])]; tags = [t.get("name", "") for t in info.get("tags", [])]
    meta = {"id": mid, "name": info.get("name", uid), "file": fname, "thumb": "thumb.jpg" if os.path.exists(os.path.join(tmp, "thumb.jpg")) else "",
            "category": guess_category(info.get("name", ""), cats + tags), "styles": ["modern", "neglected"], "tags": tags,
            "status": "untested", "notes": "", "scale": 1.0, "polycount": info.get("faceCount"),
            "licence": {"source": "Sketchfab", "author": author, "author_url": (info.get("user") or {}).get("profileUrl", ""),
                        "licence": label, "licence_url": lurl, "url": info.get("viewerUrl", f"https://sketchfab.com/3d-models/{uid}"),
                        "credit_required": credit,
                        "credit_line": f"\"{info.get('name', uid)}\" by {author} on Sketchfab ({info.get('viewerUrl', '')}), licensed under {label} ({lurl})"}}
    save_json(os.path.join(tmp, "model.json"), meta)
    shutil.rmtree(dst, ignore_errors=True); os.replace(tmp, dst)
    return meta

# ------------------------------------------------------------------ library
# ---- decals (catalogue/decals/decals.json + image files)
DECALS = os.path.join(ROOT, "catalogue", "decals")

def image_size(b):
    """(width, height) of PNG or JPEG bytes, using only the standard library."""
    if b[:8] == b"\x89PNG\r\n\x1a\n": return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    if b[:2] == b"\xff\xd8":
        i = 2
        while i < len(b) - 9:
            if b[i] != 0xFF: i += 1; continue
            m = b[i + 1]; ln = int.from_bytes(b[i + 2:i + 4], "big")
            if m in (0xC0, 0xC1, 0xC2): return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
            i += 2 + ln
    raise ValueError("Only PNG and JPEG images can be used as decals")

def decals_list():
    return load_json(os.path.join(DECALS, "decals.json"), {"decals": []})

def decal_upload(data):
    import base64
    raw = data.get("data", "")
    if "," in raw: raw = raw.split(",", 1)[1]
    b = base64.b64decode(raw)
    if len(b) > 20 * 1024 * 1024: raise ValueError("That image is over 20 MB")
    w, h = image_size(b)
    ext = "png" if b[:4] == b"\x89PNG" else "jpg"
    name = (data.get("name") or "My decal").strip()[:60]
    did = "up_" + slug(name, 30) + "_" + uuid.uuid4().hex[:6]
    os.makedirs(DECALS, exist_ok=True)
    with open(os.path.join(DECALS, f"{did}.{ext}"), "wb") as fh: fh.write(b)
    idx = decals_list()
    entry = {"id": did, "name": name, "file": f"{did}.{ext}", "width": float(data.get("width") or 0.5), "aspect": round(h / w, 4),
             "category": data.get("category") or "uploaded", "source": "Uploaded", "licence": (data.get("licence") or "").strip()[:120]}
    idx["decals"].append(entry); save_json(os.path.join(DECALS, "decals.json"), idx)
    return entry

def decal_remove(did):
    idx = decals_list(); keep, gone = [], None
    for d in idx["decals"]:
        if d["id"] == did and d.get("source") != "Room Builder": gone = d
        else: keep.append(d)
    if not gone: raise ValueError("Only uploaded decals can be removed")
    rm = os.path.join(DECALS, "_removed"); os.makedirs(rm, exist_ok=True)
    try: shutil.move(os.path.join(DECALS, gone["file"]), os.path.join(rm, gone["file"]))
    except Exception: pass
    save_json(os.path.join(DECALS, "decals.json"), {"decals": keep})
    return {"ok": True}

def credits_for(model_ids):
    lines = ["# Credits", "", "Models used in this room and their licences.", ""]
    need, free = [], []
    for mid in model_ids:
        meta = load_json(os.path.join(CAT, mid, "model.json"), {})
        lic = meta.get("licence", {})
        row = {"id": mid, "name": meta.get("name", mid), **lic}
        (need if lic.get("credit_required") else free).append(row)
    if need:
        lines += ["## Credit required (must stay with these images wherever they are used)", ""]
        for r in need:
            lines.append("- " + (r.get("credit_line") or f"\"{r['name']}\" by {r.get('author', '?')} ({r.get('url', '')}), {r.get('licence', '')}"))
        lines.append("")
    cc0 = [r for r in free if r.get("source") != "Room Builder"]
    own = [r for r in free if r.get("source") == "Room Builder"]
    if cc0:
        lines += ["## No credit required (CC0)", ""]
        for r in cc0:
            lines.append(f"- \"{r['name']}\" by {r.get('author') or 'unknown'}, {r.get('source', '')} ({r.get('url', '')}), {r.get('licence', '')}")
        lines.append("")
    if own:
        lines += ["## Own models (made for Room Builder)", ""] + [f"- {r['name']}" for r in own] + [""]
    lines += ["Room shell, kitchen and lighting: generated by Room Builder.", ""]
    return "\n".join(lines), [r["id"] for r in need]

def library_list():
    out = []
    for lid in sorted(os.listdir(LIB), reverse=True):
        if lid.startswith("_"): continue
        meta = load_json(os.path.join(LIB, lid, "meta.json"), None)
        if meta: out.append(meta)
    out.sort(key=lambda m: m.get("created", ""), reverse=True)
    return out

def library_zip(lid):
    d = os.path.join(LIB, lid); zp = os.path.join(d, f"{lid}.zip")
    if not os.path.exists(zp):
        with zipfile.ZipFile(zp + ".part", "w", zipfile.ZIP_STORED) as z:
            for f in sorted(os.listdir(d)):
                if f.startswith("view_") or f in ("spec.json", "credits.md"):
                    z.write(os.path.join(d, f), f)
        os.replace(zp + ".part", zp)
    return zp

# ------------------------------------------------------------------ queue and worker
qlock = threading.Lock()
QUEUE = load_json(QUEUE_FILE, [])
for j in QUEUE:
    if j.get("status") == "rendering": j["status"] = "queued"; j["progress"] = 0
STATS = load_json(STATS_FILE, {"rate": 0.075, "overhead": 12.0, "view_overhead": 3.0, "jobs": 0})
current = {"proc": None, "job": None}

def save_queue():
    with qlock: save_json(QUEUE_FILE, QUEUE[-200:])

def estimate(spec, quality):
    rx, ry, smp = QUALITIES.get(quality, QUALITIES["standard"])
    n = max(1, len(spec.get("views") or [1]))
    items = len(spec.get("items", []))
    units = rx * ry / 1e6 * smp
    per_view = STATS["view_overhead"] + units * STATS["rate"] * (1.25 if spec.get("style") == "neglected" else 1.0)
    return STATS["overhead"] + items * 0.4 + n * per_view

def queue_ahead_seconds(exclude=None):
    total = 0.0
    with qlock:
        for j in QUEUE:
            if j["id"] == exclude: break
            if j["status"] == "queued": total += j.get("estimate", 60)
            elif j["status"] == "rendering": total += max(0, j.get("eta", 0))
    return total

def worker():
    while True:
        job = None
        with qlock:
            for j in QUEUE:
                if j["status"] == "queued": job = j; break
        if not job: time.sleep(1.0); continue
        run_job(job)

def run_job(job):
    jdir = os.path.join(JOBS, job["id"]); out = os.path.join(jdir, "out"); os.makedirs(out, exist_ok=True)
    spec_p = os.path.join(jdir, "spec.json"); save_json(spec_p, job["spec"])
    blender = CONFIG.get("blender") or find_blender()
    with qlock:
        job.update(status="rendering", started=time.time(), progress=0.0, eta=job.get("estimate", 60), message="Building the room")
    save_queue()
    if not blender or not os.path.exists(blender):
        with qlock: job.update(status="failed", message="Blender wasn't found. Set its path in Settings.")
        save_queue(); return
    cmd = [blender, "-b", "--factory-startup", "-P", GENERATOR, "--", spec_p, out, job["quality"]]
    logf = open(os.path.join(jdir, "log.txt"), "w", encoding="utf-8", errors="replace", buffering=1)   # line by line, so it can be read while rendering
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    except OSError as e:
        with qlock: job.update(status="failed", message=f"Couldn't start Blender: {e}")
        save_queue(); return
    current.update(proc=proc, job=job)
    t0 = time.time(); render_t0 = None; n_views = max(1, len(job["spec"].get("views") or [1])); last_save = 0
    view_times = []
    rx_, ry_, smp_ = QUALITIES.get(job["quality"], QUALITIES["standard"])
    expect_view = STATS["view_overhead"] + rx_ * ry_ / 1e6 * smp_ * STATS["rate"]
    vstate = {"i": -1, "start": None, "done": False}

    def ticker():
        # Blender doesn't report samples while it renders in the background, so move the bar on by time
        while not vstate["done"]:
            time.sleep(1.0)
            if vstate["start"] is None: continue
            frac_v = min(0.97, (time.time() - vstate["start"]) / max(1.0, expect_view))
            frac = (vstate["i"] + frac_v) / n_views
            with qlock:
                if job["status"] != "rendering": continue
                job["progress"] = max(job["progress"], round(0.06 + 0.94 * frac, 4))
                over = time.time() - vstate["start"] - expect_view
                if over > 5:                  # slower than this PC's estimate: say so rather than sitting on "1 s left"
                    job["eta"] = None
                    job["message"] = (f"Rendering view {vstate['i'] + 1} of {n_views} \u00b7 still going, "
                                      f"{int((time.time() - vstate['start']) // 60)} min so far (slower than the estimate)")
                else:
                    left_this = max(0.0, expect_view - (time.time() - vstate["start"]))
                    job["eta"] = max(1, left_this + (n_views - vstate["i"] - 1) * expect_view)
    threading.Thread(target=ticker, daemon=True).start()
    for line in proc.stdout:
        logf.write(line)
        m = re.match(r"RB_PROGRESS (\d+) (\d+) (\d+) (\d+)", line)
        if m:
            i, n, s, S = map(int, m.groups())
            if render_t0 is None: render_t0 = time.time()
            if i != vstate["i"]: vstate.update(i=i, start=time.time())
            frac = (i + (s / S if S else 0)) / max(1, n)
            el = time.time() - t0
            with qlock:
                job["progress"] = max(job["progress"], round(0.06 + 0.94 * frac, 4))
                if "still going" not in job.get("message", ""): job["message"] = f"Rendering view {i + 1} of {n}"
        elif line.startswith("RB_VIEW_DONE"):
            view_times.append(time.time())
        elif line.startswith("RB_LOG"):
            with qlock:
                if job["progress"] < 0.06: job["message"] = line[7:].strip().capitalize()[:80]
        if time.time() - last_save > 2: save_queue(); last_save = time.time()
        if job.get("cancel"): proc.kill(); break
    proc.wait(); logf.close(); current.update(proc=None, job=None); vstate["done"] = True
    total = time.time() - t0
    if job.get("cancel"):
        with qlock: job.update(status="cancelled", message="Cancelled", finished=time.time())
        save_queue(); return
    views = sorted(f for f in os.listdir(out) if f.startswith("view_") and f.endswith(".png"))
    if proc.returncode != 0 or not views:
        tail = open(os.path.join(jdir, "log.txt"), encoding="utf-8", errors="replace").read()[-1500:]
        err = next((l for l in reversed(tail.splitlines()) if "Error" in l or "error" in l), "see log")
        with qlock: job.update(status="failed", message=f"Render failed: {err[:200]}", finished=time.time())
        save_queue(); return
    # learn how fast this PC renders
    try:
        rx, ry, smp = QUALITIES.get(job["quality"], QUALITIES["standard"])
        units = rx * ry / 1e6 * smp
        if render_t0 and units:
            per_view = (time.time() - render_t0) / n_views
            rate = max(0.001, (per_view - STATS["view_overhead"]) / units)
            STATS["rate"] = rate if STATS["jobs"] == 0 else 0.6 * STATS["rate"] + 0.4 * rate
            STATS["overhead"] = 0.7 * STATS["overhead"] + 0.3 * (render_t0 - t0)
            STATS["jobs"] += 1; save_json(STATS_FILE, STATS)
    except Exception:
        pass
    # into the library
    lid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug(job.get("name") or job["spec"].get("name", "room"), 30)
    ldir = os.path.join(LIB, lid); os.makedirs(ldir)
    for f in os.listdir(out):
        if f.startswith(("view_", "thumb_")) or f == "room.blend": shutil.move(os.path.join(out, f), os.path.join(ldir, f))
    used = load_json(os.path.join(out, "used_models.json"), [])
    credits, need = credits_for(used)
    outside = load_json(os.path.join(out, "used_outside.json"), {})
    if outside.get("hdri"):
        h = outside["hdri"]
        credits = credits.replace("Room shell, kitchen and lighting", f"Outside view: \"{h}\", Poly Haven (https://polyhaven.com/a/{h}), CC0 (no credit required)\n\nRoom shell, kitchen and lighting")
    decals = load_json(os.path.join(out, "used_decals.json"), {})
    if decals:                                       # decals: own work, or uploaded by whoever made the room
        own = [d["name"] for d in decals.values() if d.get("source") == "Room Builder"]
        up = [f"{d['name']} ({d.get('licence') or 'licence not given'})" for d in decals.values() if d.get("source") != "Room Builder"]
        extra = ["## Decals", ""] + [f"- {n}: own work (Room Builder)" for n in own] + [f"- {n}: uploaded image" for n in up] + [""]
        credits = credits.replace("Room shell, kitchen and lighting", "\n".join(extra) + "\nRoom shell, kitchen and lighting")
    with open(os.path.join(ldir, "credits.md"), "w", encoding="utf-8") as fh: fh.write(credits)
    save_json(os.path.join(ldir, "spec.json"), job["spec"])
    spec = job["spec"]; rx, ry, smp = QUALITIES.get(job["quality"], QUALITIES["standard"])
    meta = {"id": lid, "name": job.get("name") or spec.get("name", "Room"), "created": time.strftime("%Y-%m-%d %H:%M"),
            "style": spec.get("style"), "lighting": spec.get("lighting"), "quality": job["quality"], "resolution": f"{rx}x{ry}",
            "samples": smp, "room": {k: spec.get("room", {}).get(k) for k in ("preset", "width", "depth", "height")},
            "views": [v[5:-4] for v in views], "render_seconds": round(total), "models": used, "credit_required": need,
            "outside": outside.get("hdri"),
            "notes": ""}
    save_json(os.path.join(ldir, "meta.json"), meta)
    with qlock: job.update(status="done", progress=1.0, eta=0, message=f"Done in {round(total)} s", finished=time.time(), library_id=lid)
    save_queue()
    shutil.rmtree(out, ignore_errors=True)

# ------------------------------------------------------------------ live spec (for the Spout / IglooPreview page)
LIVE = {"rev": 0, "spec": None}
live_lock = threading.Condition()

# ------------------------------------------------------------------ HTTP
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, fmt, *args):
        if "/api/queue" in (args[0] if args else "") or "/api/live" in (args[0] if args else ""): return
        sys.stderr.write("%s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store" if self.path.startswith(("/api/", "/builder/")) else "max-age=300")
        super().end_headers()

    def send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 20 * 1024 * 1024: raise ValueError("too big")
        return json.loads(self.rfile.read(n) or b"{}")

    def fail(self, e, code=400):
        self.send_json({"error": str(e)}, code)

    def translate_path(self, path):
        p = super().translate_path(path)
        # only serve the builder, vendor files, the catalogue and the library
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        if rel.split("/")[0] not in ("builder", "vendor", "catalogue", "library", "examples", "presets", "textures"):
            return os.path.join(ROOT, "builder", "__nope__")
        if rel.endswith("config.json"): return os.path.join(ROOT, "builder", "__nope__")
        return p

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query)); path = u.path
        try:
            if path in ("/", "/index.html"):
                self.send_response(302); self.send_header("Location", "/builder/"); self.end_headers(); return
            if not path.startswith("/api/"): return super().do_GET()
            if path == "/api/status":
                return self.send_json({"blender": CONFIG.get("blender"), "blender_found": bool(CONFIG.get("blender") and os.path.exists(CONFIG["blender"])),
                                       "sketchfab_token": bool(CONFIG.get("sketchfab_token")), "allow_network": CONFIG.get("allow_network"),
                                       "port": PORT, "stats": STATS})
            if path == "/api/presets":
                base = load_json(os.path.join(PRESETS, "rooms.json"), {"rooms": []}).get("rooms", [])
                custom = load_json(os.path.join(PRESETS, "custom.json"), {"rooms": []}).get("rooms", [])
                return self.send_json({"rooms": base + [dict(r, custom=True) for r in custom]})
            if path == "/api/catalogue": return self.send_json(catalogue_list())
            if path == "/api/outside": return self.send_json(load_json(os.path.join(PRESETS, "outside.json"), {"views": []}))
            if path == "/api/finishes": return self.send_json(load_json(os.path.join(PRESETS, "finishes.json"), {"presets": {}}))
            if path == "/api/decals": return self.send_json(decals_list())
            m = re.fullmatch(r"/api/hdri/([A-Za-z0-9_\-]+)\.png", path)
            if m:                                   # small equirect preview of an outside view, for the live builder
                d = os.path.join(ROOT, "textures", "hdri"); os.makedirs(d, exist_ok=True)
                fp = os.path.join(d, m.group(1) + "_preview.png")
                if not os.path.exists(fp):
                    http_download(f"https://cdn.polyhaven.com/asset_img/primary/{m.group(1)}.png?width=2048", fp + ".part")
                    os.replace(fp + ".part", fp)
                self.send_response(200); self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(os.path.getsize(fp))); self.end_headers()
                with open(fp, "rb") as fh: shutil.copyfileobj(fh, self.wfile)
                return
            if path == "/api/search/polyhaven": return self.send_json(polyhaven_search(q.get("q"), q.get("category")))
            if path == "/api/polyhaven/categories": return self.send_json(polyhaven_categories())
            if path == "/api/search/sketchfab":
                return self.send_json(sketchfab_search(q.get("q"), q.get("category"), q.get("maxfaces"), q.get("licence"), q.get("cursor")))
            if path == "/api/sketchfab/categories": return self.send_json(sketchfab_categories())
            if path == "/api/rooms":
                out = []
                for f in sorted(os.listdir(ROOMS)):
                    if f.endswith(".json"):
                        s = load_json(os.path.join(ROOMS, f), {})
                        out.append({"id": f[:-5], "name": s.get("name", f[:-5]), "saved": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(ROOMS, f))))})
                for f in sorted(os.listdir(os.path.join(ROOT, "examples"))):
                    if f.endswith(".json"):
                        s = load_json(os.path.join(ROOT, "examples", f), {})
                        out.append({"id": "example:" + f[:-5], "name": s.get("name", f[:-5]), "saved": "example"})
                return self.send_json(out)
            if path.startswith("/api/rooms/"):
                rid = path[len("/api/rooms/"):]
                if rid.startswith("example:"): p = os.path.join(ROOT, "examples", os.path.basename(rid[8:]) + ".json")
                else: p = os.path.join(ROOMS, os.path.basename(rid) + ".json")
                s = load_json(p, None)
                return self.send_json(s) if s else self.fail("not found", 404)
            if path == "/api/queue":
                with qlock: jobs = [{k: v for k, v in j.items() if k != "spec"} for j in QUEUE[-30:]]
                for j in jobs:
                    if j["status"] == "queued": j["ahead"] = queue_ahead_seconds(j["id"])
                return self.send_json(jobs)
            if path == "/api/library": return self.send_json(library_list())
            m = re.fullmatch(r"/api/library/([\w\-]+)/download\.zip", path)
            if m:
                zp = library_zip(m.group(1))
                self.send_response(200); self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{m.group(1)}.zip"')
                self.send_header("Content-Length", str(os.path.getsize(zp))); self.end_headers()
                with open(zp, "rb") as fh: shutil.copyfileobj(fh, self.wfile)
                return
            if path == "/api/live":
                since = int(q.get("rev", -1)); deadline = time.time() + 20
                with live_lock:
                    while LIVE["rev"] == since and time.time() < deadline: live_lock.wait(timeout=deadline - time.time())
                    return self.send_json({"rev": LIVE["rev"], "spec": LIVE["spec"]})
            return self.fail("unknown", 404)
        except (urllib.error.URLError, TimeoutError) as e:
            return self.fail(f"Couldn't reach the online service: {e}", 502)
        except Exception as e:
            return self.fail(e, 500)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self.read_json()
            if path == "/api/live":
                with live_lock:
                    LIVE["spec"] = data.get("spec"); LIVE["rev"] += 1; live_lock.notify_all()
                return self.send_json({"rev": LIVE["rev"]})
            if path == "/api/config":
                for k in ("blender", "sketchfab_token", "allow_network"):
                    if k in data: CONFIG[k] = data[k]
                save_json(CONFIG_FILE, CONFIG)
                return self.send_json({"ok": True, "restart_needed": "allow_network" in data})
            if path == "/api/presets":
                room = data["room"]; p = os.path.join(PRESETS, "custom.json")
                cur = load_json(p, {"rooms": []})
                room["id"] = "custom-" + slug(room.get("name", "room"))
                cur["rooms"] = [r for r in cur["rooms"] if r["id"] != room["id"]] + [room]
                save_json(p, cur); return self.send_json(room)
            m = re.fullmatch(r"/api/catalogue/([\w\-]+)", path)
            if m: return self.send_json(catalogue_update(m.group(1), data))
            if path == "/api/decals": return self.send_json(decal_upload(data))
            if path.startswith("/api/decals/") and path.endswith("/remove"): return self.send_json(decal_remove(path.split("/")[3]))
            if path == "/api/import/polyhaven": return self.send_json(polyhaven_import(data["id"]))
            if path == "/api/import/sketchfab": return self.send_json(sketchfab_import(data["uid"]))
            if path == "/api/rooms":
                spec = data["spec"]; rid = slug(spec.get("name", "room"))
                save_json(os.path.join(ROOMS, rid + ".json"), spec); return self.send_json({"id": rid})
            if path == "/api/estimate":
                spec = data["spec"]; qual = data.get("quality", "standard")
                return self.send_json({"seconds": estimate(spec, qual), "ahead": queue_ahead_seconds()})
            if path == "/api/render":
                spec = data["spec"]; qual = data.get("quality", "standard")
                if qual not in QUALITIES: qual = "standard"
                job = {"id": uuid.uuid4().hex[:10], "name": data.get("name") or spec.get("name", "Room"), "quality": qual, "spec": spec,
                       "status": "queued", "progress": 0.0, "created": time.time(), "estimate": estimate(spec, qual), "message": "Waiting"}
                with qlock: QUEUE.append(job)
                save_queue()
                return self.send_json({"id": job["id"], "estimate": job["estimate"], "ahead": queue_ahead_seconds(job["id"])})
            m = re.fullmatch(r"/api/queue/(\w+)/cancel", path)
            if m:
                with qlock:
                    for j in QUEUE:
                        if j["id"] == m.group(1):
                            if j["status"] == "queued": j["status"] = "cancelled"; j["message"] = "Cancelled"
                            elif j["status"] == "rendering": j["cancel"] = True
                save_queue(); return self.send_json({"ok": True})
            if path == "/api/queue/clear":
                with qlock: QUEUE[:] = [j for j in QUEUE if j["status"] in ("queued", "rendering")]
                save_queue(); return self.send_json({"ok": True})
            m = re.fullmatch(r"/api/library/([\w\-]+)", path)
            if m:
                p = os.path.join(LIB, m.group(1), "meta.json"); meta = load_json(p, None)
                if meta is None: return self.fail("not found", 404)
                for k in ("name", "notes"):
                    if k in data: meta[k] = data[k]
                save_json(p, meta); return self.send_json(meta)
            m = re.fullmatch(r"/api/library/([\w\-]+)/remove", path)
            if m:
                src = os.path.join(LIB, m.group(1))
                if os.path.isdir(src):
                    os.makedirs(os.path.join(LIB, "_removed"), exist_ok=True)
                    shutil.move(src, os.path.join(LIB, "_removed", m.group(1)))
                return self.send_json({"ok": True})
            m = re.fullmatch(r"/api/catalogue/([\w\-]+)/remove", path)
            if m:
                src = os.path.join(CAT, m.group(1))
                if os.path.isdir(src):
                    os.makedirs(os.path.join(ROOT, "catalogue", "_removed"), exist_ok=True)
                    shutil.move(src, os.path.join(ROOT, "catalogue", "_removed", m.group(1)))
                return self.send_json({"ok": True})
            return self.fail("unknown", 404)
        except PermissionError as e:
            return self.fail(e, 403)
        except (urllib.error.URLError, TimeoutError) as e:
            return self.fail(f"Couldn't reach the online service: {e}", 502)
        except Exception as e:
            return self.fail(e, 500)

if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    host = "0.0.0.0" if CONFIG.get("allow_network") else "127.0.0.1"
    srv = ThreadingHTTPServer((host, PORT), Handler)
    print(f"Room Builder running:  http://localhost:{PORT}/")
    print(f"Blender: {CONFIG.get('blender') or 'NOT FOUND - set it in Settings'}")
    print("Leave this window open while you use the builder. Close it to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
