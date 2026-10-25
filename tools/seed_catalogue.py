"""
Seeds the room-tested library with the Poly Haven (CC0) models already used in the Glenda rooms.

    python tools/seed_catalogue.py "<path to Nursing XRP Scenario 001>/blender_room/assets/models"

Copies each model folder into catalogue/models/<id>/ and writes model.json with its licence record.
BlenderKit downloads (folders holding .blend files) are skipped: BlenderKit's terms don't allow them in another tool.
"""
import json, os, shutil, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "catalogue", "models")
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "Nursing XRP Scenario 001", "blender_room", "assets", "models")
UA = {"User-Agent": "RoomBuilder/1.0"}

def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)

def category(cats, tags, name):
    words = set(c.lower() for c in cats) | set(t.lower() for t in tags) | set(name.lower().replace("_", " ").split())
    rules = [("seating", {"seating", "chair", "sofa", "armchair", "ottoman", "stool", "bench"}),
             ("tables", {"table", "tables", "desk", "nightstand"}),
             ("storage", {"cabinet", "shelf", "shelves", "bookshelf", "bookcase", "drawer", "storage", "dresser", "sideboard"}),
             ("plants", {"plant", "plants", "shrub", "tree", "planter", "flower", "nature"}),
             ("lighting", {"lamp", "light", "lighting"}),
             ("electronics", {"television", "tv", "console", "electronics", "radio", "microwave", "kettle", "appliances"}),
             ("kitchen", {"kitchen", "tea", "bowl", "cup", "food", "bananas", "fruit", "kitchenware"}),
             ("decor", {"decorative", "decor", "vase", "frame", "picture", "clock", "pillows", "pillow", "basket", "books", "book"}),
             ("clutter", {"box", "trash", "trashbag", "bag", "rubbish", "cardboard"})]
    for cat, keys in rules:
        if words & keys: return cat
    return "misc"

def styles(name, tags):
    n = name.lower() + " " + " ".join(tags).lower()
    old = any(k in n for k in ("vintage", "old", "worn", "antique", "classic", "trash", "cardboard", "painted"))
    new = any(k in n for k in ("modern", "mid century", "mid_century", "contemporary"))
    if old and not new: return ["neglected"]
    if new and not old: return ["modern"]
    return ["modern", "neglected"]

os.makedirs(CAT, exist_ok=True)
done, skipped = [], []
for mid in sorted(os.listdir(SRC)):
    src = os.path.join(SRC, mid)
    if not os.path.isdir(src): continue
    files = os.listdir(src)
    gltf = next((f for f in files if f.lower().endswith((".gltf", ".glb"))), None)
    if not gltf:
        skipped.append(mid); continue
    dst = os.path.join(CAT, mid)
    if not os.path.exists(dst): shutil.copytree(src, dst)
    try:
        info = get_json(f"https://api.polyhaven.com/info/{mid}")
    except Exception as e:
        print("no Poly Haven info for", mid, e); skipped.append(mid); continue
    cats, tags = info.get("categories", []), info.get("tags", [])
    authors = ", ".join(info.get("authors", {}).keys())
    thumb = os.path.join(dst, "thumb.png")
    if not os.path.exists(thumb):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://cdn.polyhaven.com/asset_img/thumbs/{mid}.png?width=256&height=256", headers=UA), timeout=20) as r, open(thumb, "wb") as fh:
                fh.write(r.read())
        except Exception as e:
            print("no thumbnail for", mid, e)
    meta = {
        "id": mid,
        "name": info.get("name", mid),
        "file": gltf,
        "thumb": "thumb.png" if os.path.exists(thumb) else "",
        "category": category(cats, tags, mid),
        "styles": styles(mid, tags),
        "tags": tags,
        "status": "room-tested",
        "notes": "Used in the Glenda room renders.",
        "scale": 1.0,
        "polycount": info.get("polycount"),
        "licence": {
            "source": "Poly Haven",
            "author": authors,
            "licence": "CC0",
            "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "url": f"https://polyhaven.com/a/{mid}",
            "credit_required": False
        }
    }
    with open(os.path.join(dst, "model.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    done.append(mid)
    print("added", mid, meta["category"], meta["styles"])

print(f"\n{len(done)} models added; skipped (not glTF / not Poly Haven): {len(skipped)}")
for s in skipped: print("  skipped", s)
