"""
Room Builder - Blender generator.

Reads a room spec (JSON) and builds the room in an empty Blender file, then renders one equirectangular
panorama per view with Cycles.

    blender -b --factory-startup -P generate.py -- <spec.json> <out_dir> [quality]

quality: draft | standard | high   (default: the spec's render.quality, else standard)

Writes into <out_dir>:
    view_<name>.png / view_<name>.jpg   one panorama per view (centre of the image = the view's yaw, north by default)
    used_models.json                    catalogue ids used, for the credits file
    room.blend                          the built scene, for checking or hand-tweaking

Progress is printed as lines starting "RB_PROGRESS" so the server can show a percentage.

Coordinates: metres, origin at the centre of the physical room on the floor, x = east, y = north, z = up.
Walls are named north/east/south/west. A feature's "pos" is its centre along the wall: x for north/south walls,
y for east/west walls. Anything at a depth > 0 lies BEYOND the physical wall line, so it never covers the real floor.
"""
import bpy, bmesh, json, math, os, random, sys, time
from mathutils import Vector, Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX = os.path.join(ROOT, "textures")
CAT = os.path.join(ROOT, "catalogue", "models")

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SPEC_PATH = argv[0] if len(argv) > 0 else os.path.join(ROOT, "examples", "glenda_modern.json")
OUT_DIR = argv[1] if len(argv) > 1 else os.path.join(ROOT, "_test_out")
with open(SPEC_PATH, encoding="utf-8") as fh:
    SPEC = json.load(fh)
QUALITY = argv[2] if len(argv) > 2 else SPEC.get("render", {}).get("quality", "standard")
QUALITIES = {"draft": (2048, 1024, 48), "standard": (6144, 3072, 256), "high": (8192, 4096, 512)}
RES_X, RES_Y, SAMPLES = QUALITIES.get(QUALITY, QUALITIES["standard"])
if "samples" in SPEC.get("render", {}): SAMPLES = int(SPEC["render"]["samples"])
os.makedirs(OUT_DIR, exist_ok=True)

def log(*a):
    print("RB_LOG", *a, flush=True)

R = SPEC["room"]
W, D, RH = float(R["width"]), float(R["depth"]), float(R["height"])
EYE = float(R.get("eye", 1.12))
X0, X1, Y0, Y1 = -W / 2, W / 2, -D / 2, D / 2
T = 0.15                                            # wall thickness
STYLE = SPEC.get("style", "modern")
LEGACY_NEGLECT = STYLE == "neglected"                 # old specs: "neglected" was a style; now it is a condition
CONDITION = SPEC.get("condition") or ("neglected" if LEGACY_NEGLECT else "new")
HOME = STYLE in ("modern", "neglected")
NEGLECT = HOME and CONDITION in ("neglected", "derelict")   # run-down home fittings: bare bulb, nets, dated kitchen
HOSPITAL = STYLE == "hospital"
COURT = STYLE == "court"
CUSTODY = STYLE == "custody"
OUTDOOR = SPEC.get("room", {}).get("type") == "outdoor" or STYLE == "outdoor"
PUBLIC = HOSPITAL or COURT or CUSTODY               # public-building corridors, panel lights
LIGHTING = SPEC.get("lighting", "day")
FEATURES = [] if (SPEC.get("room", {}).get("type") == "outdoor" or SPEC.get("style") == "outdoor") else SPEC.get("features", [])

# ---- what is seen through windows and outside doors: a Poly Haven HDRI (CC0), one per room
def _load(p, d):
    try:
        with open(p, encoding="utf-8") as fh: return json.load(fh)
    except Exception: return d
OUT_CFG = _load(os.path.join(ROOT, "presets", "outside.json"), {"views": [], "strength": {}, "style_default": {}})
OUTSIDE = SPEC.get("outside") or {}
OUT_VIEW = OUTSIDE.get("view") or OUT_CFG.get("style_default", {}).get("neglected" if NEGLECT else STYLE, "garden")
_v = next((v for v in OUT_CFG.get("views", []) if v["id"] == OUT_VIEW), None)
HDRI_ID = OUTSIDE.get("hdri") if OUT_VIEW == "custom" else (_v or {}).get(LIGHTING) or (_v or {}).get("day")
HDRI_ROT = float(OUTSIDE.get("rotation", 0))
HDRI_STRENGTH = float(OUTSIDE.get("strength", OUT_CFG.get("strength", {}).get(HDRI_ID or "", 1.0)))
HDRI_DIR = os.path.join(ROOT, "textures", "hdri")

def ensure_hdri(aid, res):
    """Download a Poly Haven HDRI once into textures/hdri/ (falls back to a smaller size, or None if offline)."""
    import urllib.request
    os.makedirs(HDRI_DIR, exist_ok=True)
    order = [res] + [r for r in ("8k", "4k", "2k", "1k") if r != res]
    for r in order:
        p = os.path.join(HDRI_DIR, f"{aid}_{r}.hdr")
        if os.path.exists(p) and os.path.getsize(p) > 1000: return p
    try:
        req = urllib.request.Request(f"https://api.polyhaven.com/files/{aid}", headers={"User-Agent": "RoomBuilder/1.0"})
        files = json.load(urllib.request.urlopen(req, timeout=30))["hdri"]
        for r in order:
            if r in files and "hdr" in files[r]:
                p = os.path.join(HDRI_DIR, f"{aid}_{r}.hdr")
                log("downloading outside view", aid, r)
                req = urllib.request.Request(files[r]["hdr"]["url"], headers={"User-Agent": "RoomBuilder/1.0"})
                with urllib.request.urlopen(req, timeout=600) as resp, open(p + ".part", "wb") as fh:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk: break
                        fh.write(chunk)
                os.replace(p + ".part", p)
                return p
    except Exception as e:
        log("could not get outside view", aid, e)
    return None

# ============================================================== empty scene
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.name = "RoomBuilder"
COLL = {}
def coll(name):
    if name not in COLL:
        c = bpy.data.collections.new(name); sc.collection.children.link(c); COLL[name] = c
    return COLL[name]

def put(o, cname="Room"):
    for c in list(o.users_collection): c.objects.unlink(o)
    coll(cname).objects.link(o)
    return o

# ============================================================== wall frames
# Each wall: how a wall-local point (u along the wall, d outward beyond the wall line, z) maps to the world.
WALLS = {
    "north": dict(axis="x", line=Y1, sign=+1, lo=X0, hi=X1),
    "south": dict(axis="x", line=Y0, sign=-1, lo=X0, hi=X1),
    "east":  dict(axis="y", line=X1, sign=+1, lo=Y0, hi=Y1),
    "west":  dict(axis="y", line=X0, sign=-1, lo=Y0, hi=Y1),
}

# an alcove that stops just short of a room corner leaves a thin stub of wall that shows as an upright: take it to the corner
for _f in FEATURES:
    if _f.get("type") in ("alcove", "kitchenette") and _f.get("wall") in WALLS:
        _w = WALLS[_f["wall"]]; _a = float(_f["pos"]) - float(_f["width"]) / 2; _b = _a + float(_f["width"])
        if 0.001 < _a - _w["lo"] < 0.3: _a = _w["lo"]
        if 0.001 < _w["hi"] - _b < 0.3: _b = _w["hi"]
        _f["pos"], _f["width"] = (_a + _b) / 2, _b - _a

def wbase(wall):
    """The real wall a (possibly virtual) wall frame belongs to: 'north@alcove1' -> 'north'."""
    return WALLS[wall].get("base", wall)

def virtual_wall(wall, d, key):
    """A wall frame parallel to 'wall' but d metres further out (the back of an alcove, the far wall of a side room)."""
    f = WALLS[wall]
    WALLS[key] = dict(f, line=f["line"] + f["sign"] * d, base=wbase(wall))
    return key

def door_side(wall, dd):
    """Which wall of an alcove a door is in: 'back', or the alcove's side wall 'a' (low end) / 'b' (high end).
    People pick left/right as they face the alcove from the room."""
    sd = dd.get("side", "back")
    if sd == "back": return "back"
    left_is_a = wbase(wall) in ("north", "west")
    return "a" if (sd == "left") == left_is_a else "b"

def side_frame(wall, ft, ab, depth, key):
    """A wall frame for an alcove's side wall: u runs along the alcove's depth (as a world coordinate), outward is away
    from the alcove. 'keep' stops anything built through it coming back into the main room."""
    f = WALLS[wall]; u0, u1 = feature_span(ft)
    axis = "y" if f["axis"] == "x" else "x"
    line, sign = (u0, -1) if ab == "a" else (u1, +1)
    base = {("y", -1): "west", ("y", 1): "east", ("x", -1): "south", ("x", 1): "north"}[(axis, sign)]
    lo_, hi_ = sorted((f["line"], f["line"] + f["sign"] * depth))
    WALLS[key] = dict(axis=axis, line=line, sign=sign, lo=lo_, hi=hi_, base=base, keep=(f["line"] + f["sign"] * (2 * T + 0.01), f["sign"]))   # its own wall sits behind the main wall, not in it
    return key

def spans_without(a, b, holes):
    """Pieces of a..b left after cutting out the (u0, u1) holes."""
    out, cur = [], a
    for h0, h1 in sorted(holes):
        if h0 > cur: out.append((cur, min(h0, b)))
        cur = max(cur, h1)
    if cur < b: out.append((cur, b))
    return [(x, y) for x, y in out if y - x > 0.005]

def w2world(wall, u, d, z=0.0):
    f = WALLS[wall]
    if f["axis"] == "x": return Vector((u, f["line"] + f["sign"] * d, z))
    return Vector((f["line"] + f["sign"] * d, u, z))

def wbox_world(wall, u0, u1, d0, d1, z0, z1):
    """World-space min/max corners of a wall-local box."""
    a, b = w2world(wall, u0, d0, z0), w2world(wall, u1, d1, z1)
    return Vector((min(a.x, b.x), min(a.y, b.y), z0)), Vector((max(a.x, b.x), max(a.y, b.y), z1))

def facing(wall):
    """Rotation (radians about z) that turns something whose front faces -Y so it faces into the room from this wall."""
    return {"north": 0.0, "south": math.pi, "east": -math.pi / 2, "west": math.pi / 2}[wbase(wall)]

# ============================================================== materials
def principled(name):
    m = bpy.data.materials.get(name)
    if m: return m, None, None
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs[0], out.inputs[0])
    return m, nt, b

def set_input(b, names, value):
    for n in names:
        if n in b.inputs: b.inputs[n].default_value = value; return

def flat(name, color, rough=0.5, metal=0.0, coat=0.0, emit=None, strength=1.0, alpha=1.0, transmission=0.0):
    m, nt, b = principled(name)
    if nt is None: return m
    b.inputs["Base Color"].default_value = (*color, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if coat: set_input(b, ("Coat Weight", "Clearcoat"), coat)
    if transmission: set_input(b, ("Transmission Weight", "Transmission"), transmission)
    if emit:
        set_input(b, ("Emission Color", "Emission"), (*emit, 1)); b.inputs["Emission Strength"].default_value = strength
    if alpha < 1: b.inputs["Alpha"].default_value = alpha
    return m

def tex_path(base, kind):
    p = os.path.join(TEX, f"{base}_{kind}.jpg")
    return p if os.path.exists(p) else None

def textured(name, base, scale=1.0, tint=None, sat=1.0, lift=0.0, lift_col=(1, 1, 1), rough=None, normal=0.4,
             grime=0.0, grime_col=(0.35, 0.28, 0.18), coord="UV", rough_mul=1.0):
    """Image-textured material (Poly Haven CC0 textures in textures/). Falls back to a flat colour if missing."""
    m, nt, b = principled(name)
    if nt is None: return m
    diff = tex_path(base, "diff")
    if not diff:
        b.inputs["Base Color"].default_value = (*(tint or (0.6, 0.6, 0.6)), 1); return m
    tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(tc.outputs[coord], mp.inputs[0])
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(diff, check_existing=True)
    if coord != "UV": t.projection = "BOX"; t.projection_blend = 0.2
    nt.links.new(mp.outputs[0], t.inputs[0]); col = t.outputs[0]
    if sat != 1.0:
        h = nt.nodes.new("ShaderNodeHueSaturation"); h.inputs["Saturation"].default_value = sat
        nt.links.new(col, h.inputs["Color"]); col = h.outputs[0]
    if tint:
        mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs[0].default_value = 1.0
        nt.links.new(col, mx.inputs[6]); mx.inputs[7].default_value = (*tint, 1); col = mx.outputs[2]
    if lift:
        mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "SCREEN"; mx.inputs[0].default_value = lift
        nt.links.new(col, mx.inputs[6]); mx.inputs[7].default_value = (*lift_col, 1); col = mx.outputs[2]
    if grime:
        col = add_grime(nt, col, grime, grime_col)
    nt.links.new(col, b.inputs["Base Color"])
    rp = tex_path(base, "rough")
    if rough is not None:
        b.inputs["Roughness"].default_value = rough
    elif rp:
        r = nt.nodes.new("ShaderNodeTexImage"); r.image = bpy.data.images.load(rp, check_existing=True)
        r.image.colorspace_settings.name = "Non-Color"
        if coord != "UV": r.projection = "BOX"
        nt.links.new(mp.outputs[0], r.inputs[0])
        if rough_mul != 1.0:
            mm = nt.nodes.new("ShaderNodeMath"); mm.operation = "MULTIPLY"; mm.inputs[1].default_value = rough_mul
            nt.links.new(r.outputs[0], mm.inputs[0]); nt.links.new(mm.outputs[0], b.inputs["Roughness"])
        else:
            nt.links.new(r.outputs[0], b.inputs["Roughness"])
    npth = tex_path(base, "nor")
    if npth and normal:
        n = nt.nodes.new("ShaderNodeTexImage"); n.image = bpy.data.images.load(npth, check_existing=True)
        n.image.colorspace_settings.name = "Non-Color"
        if coord != "UV": n.projection = "BOX"
        nt.links.new(mp.outputs[0], n.inputs[0])
        nm = nt.nodes.new("ShaderNodeNormalMap"); nm.inputs[0].default_value = normal
        nt.links.new(n.outputs[0], nm.inputs[1]); nt.links.new(nm.outputs[0], b.inputs["Normal"])
    return m

def add_grime(nt, col, amount, grime_col, zlo=1.5, zhi=2.4):
    """Darken with blotchy noise, more towards the top (damp / nicotine) and in patches."""
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 1.6; nz.inputs["Detail"].default_value = 8
    nt.links.new(geo.outputs["Position"], nz.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB"); nt.links.new(nz.outputs["Fac"], ramp.inputs[0])
    ramp.color_ramp.elements[0].position = 0.45; ramp.color_ramp.elements[1].position = 0.75
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(geo.outputs["Position"], sep.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange"); nt.links.new(sep.outputs["Z"], mr.inputs[0])
    mr.inputs[1].default_value, mr.inputs[2].default_value, mr.inputs[3].default_value, mr.inputs[4].default_value = zlo, zhi, 0.35, 1.0
    mul = nt.nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"; mul.use_clamp = True
    nt.links.new(ramp.outputs[0], mul.inputs[0]); nt.links.new(mr.outputs[0], mul.inputs[1])
    mul2 = nt.nodes.new("ShaderNodeMath"); mul2.operation = "MULTIPLY"; mul2.inputs[1].default_value = amount
    nt.links.new(mul.outputs[0], mul2.inputs[0])
    mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"
    nt.links.new(mul2.outputs[0], mx.inputs[0]); nt.links.new(col, mx.inputs[6]); mx.inputs[7].default_value = (*grime_col, 1)
    return mx.outputs[2]

def brick_tiles(name, c1, c2, mortar, size, row=1.0, offset=0.0, rough=0.2, coord="Object", wall=False):
    """Tiles/bricks. wall=True lays them out on vertical surfaces (along the wall and up), not across the floor plan."""
    m, nt, b = principled(name)
    if nt is None: return m
    tc = nt.nodes.new("ShaderNodeTexCoord"); br = nt.nodes.new("ShaderNodeTexBrick")
    if wall:
        sep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(tc.outputs[coord], sep.inputs[0])
        add = nt.nodes.new("ShaderNodeMath"); add.operation = "ADD"
        nt.links.new(sep.outputs["X"], add.inputs[0]); nt.links.new(sep.outputs["Y"], add.inputs[1])
        cmb = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(add.outputs[0], cmb.inputs["X"]); nt.links.new(sep.outputs["Z"], cmb.inputs["Y"])
        nt.links.new(cmb.outputs[0], br.inputs["Vector"])
    else:
        nt.links.new(tc.outputs[coord], br.inputs["Vector"])
    br.offset = offset; br.squash = 1.0
    br.inputs["Scale"].default_value = 1 / size; br.inputs["Brick Width"].default_value = 1.0
    br.inputs["Row Height"].default_value = row; br.inputs["Mortar Size"].default_value = min(0.03, 0.0045 / size)
    br.inputs["Color1"].default_value = (*c1, 1); br.inputs["Color2"].default_value = (*c2, 1); br.inputs["Mortar"].default_value = (*mortar, 1)
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    return m

def speckle_vinyl(name, c1, c2, fleck=(0.25, 0.28, 0.3), rough=0.32):
    """Hospital sheet vinyl: a soft mottle with small dark flecks."""
    m, nt, b = principled(name)
    if nt is None: return m
    tc = nt.nodes.new("ShaderNodeTexCoord")
    n1 = nt.nodes.new("ShaderNodeTexNoise"); n1.inputs["Scale"].default_value = 6.0; n1.inputs["Detail"].default_value = 4
    nt.links.new(tc.outputs["Object"], n1.inputs["Vector"])
    r1 = nt.nodes.new("ShaderNodeValToRGB"); nt.links.new(n1.outputs["Fac"], r1.inputs[0])
    r1.color_ramp.elements[0].color = (*c1, 1); r1.color_ramp.elements[1].color = (*c2, 1)
    vo = nt.nodes.new("ShaderNodeTexVoronoi"); vo.inputs["Scale"].default_value = 140.0
    nt.links.new(tc.outputs["Object"], vo.inputs["Vector"])
    r2 = nt.nodes.new("ShaderNodeValToRGB"); nt.links.new(vo.outputs["Distance"], r2.inputs[0])
    r2.color_ramp.elements[0].position = 0.06; r2.color_ramp.elements[1].position = 0.1
    r2.color_ramp.elements[0].color = (0, 0, 0, 1); r2.color_ramp.elements[1].color = (1, 1, 1, 1)
    inv = nt.nodes.new("ShaderNodeInvert"); nt.links.new(r2.outputs[0], inv.inputs["Color"])
    mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"
    nt.links.new(inv.outputs[0], mx.inputs["Factor"]); nt.links.new(r1.outputs[0], mx.inputs[6]); mx.inputs[7].default_value = (*fleck, 1)
    nt.links.new(mx.outputs[2], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    set_input(b, ("Coat Weight", "Clearcoat"), 0.25)
    return m

def carpet(name, c1, c2):
    m = speckle_vinyl(name, c1, c2, fleck=tuple(x * 0.6 for x in c1), rough=0.95)
    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if b: set_input(b, ("Coat Weight", "Clearcoat"), 0.0)
    for n in m.node_tree.nodes:
        if n.type == "TEX_NOISE": n.inputs["Scale"].default_value = 40.0
        if n.type == "TEX_VORONOI": n.inputs["Scale"].default_value = 400.0
    return m

# ============================================================== finishes + condition
# What the walls, lower walls, floor, ceiling and trim are made of (presets/finishes.json, overridden by the spec),
# and how worn the room is. Each finish is built procedurally so any colour works; the condition then adds dirt,
# yellowing, damp, scuffs, peeling and floor wear on top.
FIN_CFG = _load(os.path.join(ROOT, "presets", "finishes.json"), {"presets": {}})
_preset = FIN_CFG.get("presets", {}).get("neglected" if LEGACY_NEGLECT else STYLE) or FIN_CFG.get("presets", {}).get("modern", {})
FIN = {k: dict(v) for k, v in _preset.items() if isinstance(v, dict)}
for _k, _v in (SPEC.get("finishes") or {}).items():
    if isinstance(_v, dict): FIN[_k] = dict(_v)
PATTERNS = os.path.join(TEX, "patterns")
COND = {
    "new":       dict(dirt=0.0, yellow=0.0, damp=0.0, scuff=0.0, peel=0.0, fade=0.0, wear=0.0, stain=0.0),
    "lived_in":  dict(dirt=0.08, yellow=0.0, damp=0.0, scuff=0.3, peel=0.0, fade=0.03, wear=0.15, stain=0.08),
    "worn":      dict(dirt=0.25, yellow=0.12, damp=0.08, scuff=0.55, peel=0.0, fade=0.12, wear=0.35, stain=0.25),
    "neglected": dict(dirt=0.55, yellow=0.35, damp=0.4, scuff=0.75, peel=0.18, fade=0.2, wear=0.55, stain=0.5),
    "derelict":  dict(dirt=0.8, yellow=0.5, damp=0.75, scuff=0.9, peel=0.45, fade=0.3, wear=0.8, stain=0.8),
}.get(CONDITION, {})
SHEEN = {"matt": 0.85, "silk": 0.5, "gloss": 0.22}

def lin(hexs, fallback=(0.7, 0.7, 0.7)):
    """sRGB hex (#rrggbb) to the linear colour Blender wants."""
    try:
        h = hexs.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)
    except Exception:
        return fallback

def shade(c, k): return tuple(max(0.0, min(1.0, x * k)) for x in c)

def _n(nt, kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items():
        if k in n.inputs: n.inputs[k].default_value = v
    return n

def _mix(nt, fac, a, b, blend="MIX"):
    m = nt.nodes.new("ShaderNodeMix"); m.data_type = "RGBA"; m.blend_type = blend
    (nt.links.new(fac, m.inputs[0]) if not isinstance(fac, (int, float)) else setattr(m.inputs[0], "default_value", fac))
    (nt.links.new(a, m.inputs[6]) if not isinstance(a, tuple) else setattr(m.inputs[6], "default_value", (*a, 1)))
    (nt.links.new(b, m.inputs[7]) if not isinstance(b, tuple) else setattr(m.inputs[7], "default_value", (*b, 1)))
    return m.outputs[2]

def _maprange(nt, val, a, b, lo=0.0, hi=1.0):
    m = nt.nodes.new("ShaderNodeMapRange"); nt.links.new(val, m.inputs[0])
    m.inputs[1].default_value, m.inputs[2].default_value, m.inputs[3].default_value, m.inputs[4].default_value = a, b, lo, hi
    return m.outputs[0]

def _math(nt, op, a, b=None, clamp=True):
    m = nt.nodes.new("ShaderNodeMath"); m.operation = op; m.use_clamp = clamp
    (nt.links.new(a, m.inputs[0]) if not isinstance(a, (int, float)) else setattr(m.inputs[0], "default_value", a))
    if b is not None: (nt.links.new(b, m.inputs[1]) if not isinstance(b, (int, float)) else setattr(m.inputs[1], "default_value", b))
    return m.outputs[0]

def _wall_uv(nt, size):
    """Coordinates that run along any wall and up it (x + y, z), in units of 'size' metres."""
    tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(tc.outputs["Object"], sep.inputs[0])
    u = _math(nt, "ADD", sep.outputs["X"], sep.outputs["Y"], clamp=False)
    cmb = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(u, cmb.inputs["X"]); nt.links.new(sep.outputs["Z"], cmb.inputs["Y"])
    sc = nt.nodes.new("ShaderNodeVectorMath"); sc.operation = "SCALE"; nt.links.new(cmb.outputs[0], sc.inputs[0]); sc.inputs["Scale"].default_value = 1 / size
    return sc.outputs[0]

def _floor_uv(nt, size):
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sc = nt.nodes.new("ShaderNodeVectorMath"); sc.operation = "SCALE"; nt.links.new(tc.outputs["Object"], sc.inputs[0]); sc.inputs["Scale"].default_value = 1 / size
    return sc.outputs[0]

def _bump(nt, b, height, strength):
    bp = nt.nodes.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = strength
    nt.links.new(height, bp.inputs["Height"]); nt.links.new(bp.outputs[0], b.inputs["Normal"])

def _bsdf(m): return next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)

def _pattern_mask(nt, name, vec):
    p = os.path.join(PATTERNS, f"{name}.png")
    if not os.path.exists(p): return None
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(p, check_existing=True)
    t.image.colorspace_settings.name = "Non-Color"; t.interpolation = "Cubic"
    nt.links.new(vec, t.inputs[0]); return t.outputs[0]

def paint_mat(name, colour, sheen="matt", texture=0.04):
    m, nt, b = principled(name)
    c = lin(colour)
    nz = _n(nt, "ShaderNodeTexNoise", Scale=3.0, Detail=4.0); nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], nz.inputs["Vector"])
    col = _mix(nt, _maprange(nt, nz.outputs["Fac"], 0.3, 0.7, 0.0, 1.0), shade(c, 0.985), shade(c, 1.012))
    nt.links.new(col, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = SHEEN.get(sheen, 0.85)
    if sheen == "gloss": set_input(b, ("Coat Weight", "Clearcoat"), 0.3)
    fine = _n(nt, "ShaderNodeTexNoise", Scale=180.0, Detail=2.0); nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], fine.inputs["Vector"])
    _bump(nt, b, fine.outputs["Fac"], texture)
    return m

def wallpaper_mat(name, f):
    pat = f.get("pattern", "woodchip"); c1 = lin(f.get("colour", "#e9dfc3")); c2 = lin(f.get("colour2", "#c9a85e"))
    if pat == "vintage" and tex_path("decrepit_wallpaper", "diff"):
        mx = max(c1) or 1
        return textured(name, "decrepit_wallpaper", scale=1.0, tint=tuple(min(1.0, x / mx) for x in c1), sat=0.55, coord="Object", rough=0.8)
    m, nt, b = principled(name)
    vec = _wall_uv(nt, 0.53)
    mask = None if pat == "woodchip" else _pattern_mask(nt, pat, vec)
    col = _mix(nt, mask, c1, c2) if mask else None
    if col is None:
        nz = _n(nt, "ShaderNodeTexNoise", Scale=2.0, Detail=3.0); nt.links.new(vec, nz.inputs["Vector"])
        col = _mix(nt, _maprange(nt, nz.outputs["Fac"], 0.3, 0.7), shade(c1, 0.98), shade(c1, 1.01))
    nt.links.new(col, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.75
    chip = _n(nt, "ShaderNodeTexVoronoi", Scale=260.0 if pat == "woodchip" else 600.0); nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], chip.inputs["Vector"])
    _bump(nt, b, chip.outputs["Distance"], 0.35 if pat == "woodchip" else 0.05)
    return m

TILE_SIZES = {"metro": (0.2, 0.5, 0.5), "sq10": (0.1, 1.0, 0.0), "sq15": (0.15, 1.0, 0.0), "sq30": (0.3, 1.0, 0.0), "sq60": (0.6, 1.0, 0.0)}

def tiles_mat(name, f, wall=True):
    size, row, off = TILE_SIZES.get(f.get("tile_size", "sq15" if wall else "sq30"), (0.15, 1.0, 0.0))
    c1 = lin(f.get("colour", "#efefeb")); grout = lin(f.get("grout", "#bdbdb8" if sum(c1) > 1.2 else "#4a4a48"))
    m = brick_tiles(name, c1, shade(c1, 0.95), grout, size, row=row, offset=off, rough=0.15 if wall else 0.3, wall=wall)
    b = _bsdf(m); nt = m.node_tree
    if not wall:
        checker = bool(f.get("colour2")) and f.get("tile_size") != "metro"          # two colours only on square tiles
        br = next(n for n in nt.nodes if n.type == "TEX_BRICK")
        vec = nt.nodes.new("ShaderNodeTexCoord").outputs["Object"]
        if f.get("layout", "diagonal" if checker else "straight") == "diagonal":     # laid on the diagonal (45 degrees)
            sep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(vec, sep.inputs[0])
            k = 1 / math.sqrt(2)
            u = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", sep.outputs["X"], sep.outputs["Y"], clamp=False), k, clamp=False)
            v = _math(nt, "MULTIPLY", _math(nt, "ADD", sep.outputs["X"], sep.outputs["Y"], clamp=False), k, clamp=False)
            cmb = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(u, cmb.inputs["X"]); nt.links.new(v, cmb.inputs["Y"])
            vec = cmb.outputs[0]
        nt.links.new(vec, br.inputs["Vector"])
        if checker:                                      # a checkerboard lined up with the tile grid
            ck = _n(nt, "ShaderNodeTexChecker", Scale=1.0)
            ck.inputs["Color1"].default_value = (*c1, 1); ck.inputs["Color2"].default_value = (*lin(f["colour2"]), 1)
            sc = nt.nodes.new("ShaderNodeVectorMath"); sc.operation = "SCALE"; sc.inputs["Scale"].default_value = 1 / size        # Cycles' checker: one square per unit at scale 1
            nt.links.new(vec, sc.inputs[0]); nt.links.new(sc.outputs[0], ck.inputs["Vector"])
            nt.links.new(ck.outputs["Color"], br.inputs["Color1"]); nt.links.new(ck.outputs["Color"], br.inputs["Color2"])
    set_input(b, ("Coat Weight", "Clearcoat"), 0.35 if wall else 0.15)
    return m

WOODS = {   # tint, saturation, lift, lift colour for the Poly Haven wood texture
    "light_oak": dict(tint=None, sat=0.45, lift=0.55, lift_col=(0.72, 0.6, 0.45)),
    "oak":       dict(tint=(0.95, 0.72, 0.45), sat=0.9, lift=0.0, lift_col=(1, 1, 1)),
    "dark_oak":  dict(tint=(0.42, 0.28, 0.18), sat=0.9, lift=0.0, lift_col=(1, 1, 1)),
    "pine":      dict(tint=(1.0, 0.82, 0.55), sat=0.8, lift=0.3, lift_col=(0.85, 0.7, 0.45)),
    "grey":      dict(tint=None, sat=0.08, lift=0.4, lift_col=(0.62, 0.62, 0.6)),
}

def wood_mat(name, f, floor=True, laminate=False):
    w = f.get("wood", "oak")
    if w == "painted":
        return paint_mat(name, f.get("colour", "#e6e2d6"), "silk")
    p = WOODS.get(w, WOODS["oak"])
    return textured(name, "wood_floor_worn", scale=0.6 if floor else 0.8, tint=p["tint"], sat=p["sat"], lift=p["lift"], lift_col=p["lift_col"],
                    rough=0.3 if laminate else 0.42, normal=0.12 if laminate else (0.35 if floor else 0.15), coord="UV" if floor else "Object")

def blockwork_mat(name, f):
    c = lin(f.get("colour", "#e4e1d2"))
    m = brick_tiles(name, c, shade(c, 0.975), shade(c, 0.86), 0.44, row=0.49, offset=0.5, rough=0.45, wall=True)
    nt = m.node_tree; nz = _n(nt, "ShaderNodeTexNoise", Scale=90.0, Detail=3.0); nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], nz.inputs["Vector"])
    _bump(nt, _bsdf(m), nz.outputs["Fac"], 0.12)
    return m

BRICKS = {"red": ((0.30, 0.10, 0.06), (0.22, 0.075, 0.045), (0.42, 0.4, 0.37)), "yellow": ((0.5, 0.4, 0.24), (0.4, 0.31, 0.18), (0.45, 0.43, 0.4)),
          "painted": ((0.8, 0.8, 0.77), (0.76, 0.76, 0.73), (0.7, 0.7, 0.67))}

def brick_mat(name, f):
    c1, c2, mortar = BRICKS.get(f.get("brick", "red"), BRICKS["red"])
    m = brick_tiles(name, c1, c2, mortar, 0.225, row=0.075 / 0.225, offset=0.5, rough=0.8, wall=True)
    nt = m.node_tree; br = next(n for n in nt.nodes if n.type == "TEX_BRICK"); br.inputs["Bias"].default_value = 0.0
    nz = _n(nt, "ShaderNodeTexNoise", Scale=40.0, Detail=5.0); nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], nz.inputs["Vector"])
    _bump(nt, _bsdf(m), nz.outputs["Fac"], 0.3)
    return m

def plaster_mat(name):
    m, nt, b = principled(name)
    nz = _n(nt, "ShaderNodeTexNoise", Scale=2.5, Detail=6.0); nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], nz.inputs["Vector"])
    nt.links.new(_mix(nt, nz.outputs["Fac"], (0.62, 0.5, 0.42), (0.74, 0.62, 0.53)), b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.9
    return m

def wall_finish_mat(name, f):
    t = f.get("type", "paint")
    if t == "wallpaper": return wallpaper_mat(name, f)
    if t == "tiles": return tiles_mat(name, f, wall=True)
    if t == "blockwork": return blockwork_mat(name, f)
    if t == "brick": return brick_mat(name, f)
    if t == "panelling": return wood_mat(name, f, floor=False)
    if t == "plaster": return plaster_mat(name)
    return paint_mat(name, f.get("colour", "#ece7dd"), f.get("sheen", "matt"))

def floor_finish_mat(name, f):
    t = f.get("type", "wood")
    c = lin(f.get("colour", "#77787a")); c2 = lin(f.get("colour2", "")) if f.get("colour2") else shade(c, 1.2)
    if t == "carpet":
        pat = f.get("carpet_pattern", "plain")
        m = carpet(name, c, shade(c, 1.12) if pat != "heather" else c2)
        if pat in ("patterned", "cord"):
            nt = m.node_tree; b = _bsdf(m)
            mask = _pattern_mask(nt, "floral" if pat == "patterned" else "cord", _floor_uv(nt, 0.45 if pat == "patterned" else 0.25))
            if mask:
                src = b.inputs["Base Color"].links[0].from_socket
                nt.links.new(_mix(nt, _math(nt, "MULTIPLY", mask, 0.55 if pat == "patterned" else 1.0), src, c2 if pat == "patterned" else shade(c, 0.8)), b.inputs["Base Color"])
        return m
    if t in ("wood", "laminate"): return wood_mat(name, f, floor=True, laminate=(t == "laminate"))
    if t == "vinyl": return speckle_vinyl(name, c, shade(c, 1.12))
    if t == "resin": return speckle_vinyl(name, c, shade(c, 1.08), fleck=shade(c, 1.6), rough=0.45)
    if t == "tiles": return tiles_mat(name, f, wall=False)
    if t == "lino":
        m, nt, b = principled(name); pat = f.get("lino_pattern", "plain")
        if pat == "check":
            ck = _n(nt, "ShaderNodeTexChecker", Scale=1.0); ck.inputs["Color1"].default_value = (*c, 1); ck.inputs["Color2"].default_value = (*c2, 1)
            nt.links.new(_floor_uv(nt, 0.3), ck.inputs["Vector"]); col = ck.outputs["Color"]   # 0.3 m squares
        elif pat == "marble":
            nz = _n(nt, "ShaderNodeTexNoise", Scale=3.0, Detail=10.0, Roughness=0.6, Distortion=2.5); nt.links.new(_floor_uv(nt, 1.0), nz.inputs["Vector"])
            veins = _maprange(nt, nz.outputs["Fac"], 0.47, 0.53)            # thin wandering veins in a mottled ground
            vein = _math(nt, "SUBTRACT", 1.0, _math(nt, "ABSOLUTE", _math(nt, "SUBTRACT", veins, 0.5, clamp=False), clamp=False))
            col = _mix(nt, _math(nt, "MULTIPLY", _math(nt, "POWER", vein, 6.0), 0.55), c, c2)
        else:
            nz = _n(nt, "ShaderNodeTexNoise", Scale=4.0, Detail=3.0); nt.links.new(_floor_uv(nt, 1.0), nz.inputs["Vector"])
            col = _mix(nt, _maprange(nt, nz.outputs["Fac"], 0.3, 0.7), shade(c, 0.96), shade(c, 1.04))
        nt.links.new(col, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.4
        return m
    if t == "concrete":
        m, nt, b = principled(name)
        nz = _n(nt, "ShaderNodeTexNoise", Scale=1.2, Detail=8.0); nt.links.new(_floor_uv(nt, 1.0), nz.inputs["Vector"])
        nt.links.new(_mix(nt, nz.outputs["Fac"], (0.22, 0.22, 0.21), (0.34, 0.33, 0.31)), b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.75
        fine = _n(nt, "ShaderNodeTexNoise", Scale=120.0, Detail=2.0); nt.links.new(_floor_uv(nt, 1.0), fine.inputs["Vector"]); _bump(nt, b, fine.outputs["Fac"], 0.1)
        return m
    return carpet(name, c, shade(c, 1.12))

def ceiling_finish_mat(name, f):
    t = f.get("type", "plaster")
    if t == "tiles":
        return brick_tiles(name, (0.86, 0.86, 0.84), (0.85, 0.85, 0.83), (0.64, 0.64, 0.62), 0.6, row=1.0, rough=0.9)
    m = paint_mat(name, f.get("colour", "#f0eee8"), "matt", texture=0.0)
    if t == "artex":
        nt = m.node_tree; b = _bsdf(m)
        sw = _n(nt, "ShaderNodeTexWave", Scale=6.0, Distortion=12.0, Detail=3.0); sw.wave_type = "RINGS"
        nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], sw.inputs["Vector"]); _bump(nt, b, sw.outputs["Fac"], 0.35)
    return m

def trim_finish_mat(name, f):
    if f.get("wood"):
        return wood_mat(name, {"wood": f["wood"]}, floor=False)
    return paint_mat(name, f.get("colour", "#f2f2f0"), f.get("sheen", "gloss"), texture=0.0)

def apply_condition(m, surface, peelable=False):
    """Age a finish: fade, yellowing, grime, damp tide-marks, low scuffs, peeling (walls); wear, stains, dirt (floors)."""
    C = COND
    if not m or not m.node_tree or not any(C.values()): return m
    nt = m.node_tree; b = _bsdf(m)
    if b is None: return m
    if b.inputs["Base Color"].links: col = b.inputs["Base Color"].links[0].from_socket
    else:
        rgb = nt.nodes.new("ShaderNodeRGB"); rgb.outputs[0].default_value = b.inputs["Base Color"].default_value; col = rgb.outputs[0]
    geo = nt.nodes.new("ShaderNodeNewGeometry"); sep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(geo.outputs["Position"], sep.inputs[0])
    z = sep.outputs["Z"]
    def noise(scale, detail=6.0, rough=0.55):
        n = _n(nt, "ShaderNodeTexNoise", Scale=scale, Detail=detail, Roughness=rough); nt.links.new(geo.outputs["Position"], n.inputs["Vector"]); return n.outputs["Fac"]
    if C["fade"]:
        hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.inputs["Saturation"].default_value = 1 - C["fade"]; hs.inputs["Value"].default_value = 1 - C["fade"] * 0.25
        nt.links.new(col, hs.inputs["Color"]); col = hs.outputs[0]
    if surface in ("wall", "ceiling", "trim") and C["yellow"]:
        hfac = _maprange(nt, z, 0.6, RH, 0.35, 1.0) if surface != "ceiling" else 1.0
        fac = _math(nt, "MULTIPLY", hfac, C["yellow"]) if surface != "ceiling" else C["yellow"] * 0.8
        col = _mix(nt, fac, col, (0.86, 0.72, 0.44), "MULTIPLY")
    if C["dirt"]:
        if surface == "floor":
            fac = _math(nt, "MULTIPLY", _maprange(nt, noise(1.3), 0.4, 0.75), C["dirt"])
            col = _mix(nt, fac, col, (0.45, 0.4, 0.33), "MULTIPLY")
        else:
            col = add_grime(nt, col, C["dirt"] * {"trim": 0.6, "ceiling": 0.45}.get(surface, 1.0), (0.48, 0.4, 0.3), zlo=0.8 if surface == "wall" else -1, zhi=RH if surface == "wall" else 0)
    if surface in ("wall", "ceiling") and C["damp"]:
        n = noise(0.55, 8.0, 0.6)
        blob = _maprange(nt, n, 0.6, 0.63)
        inner = _maprange(nt, n, 0.635, 0.68)
        ring = _math(nt, "SUBTRACT", blob, inner)
        if surface == "wall":                         # rising damp at the bottom, leaks at the top
            zf = _math(nt, "MAXIMUM", _maprange(nt, z, 1.0, 0.15), _maprange(nt, z, RH - 0.8, RH))
        else:
            zf = 1.0
        stain = _math(nt, "ADD", _math(nt, "MULTIPLY", blob, 0.45), _math(nt, "MULTIPLY", ring, 0.9))
        fac = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", stain, zf), min(1.0, C["damp"] * 1.2))
        col = _mix(nt, fac, col, (0.55, 0.42, 0.26), "MULTIPLY")
    if surface == "wall" and C["scuff"]:
        band = _maprange(nt, z, 0.55, 0.12)
        sc = _maprange(nt, noise(9.0, 4.0), 0.52, 0.72)
        fac = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", band, sc), C["scuff"] * 0.7)
        col = _mix(nt, fac, col, (0.5, 0.47, 0.42), "MULTIPLY")
    if surface == "wall" and peelable and C["peel"]:
        n = noise(1.1, 7.0, 0.65)
        t0 = 0.72 - C["peel"] * 0.25
        bare = _maprange(nt, n, t0, t0 + 0.015)
        edge = _math(nt, "SUBTRACT", _maprange(nt, n, t0 - 0.03, t0), bare)
        col = _mix(nt, _math(nt, "MULTIPLY", edge, 0.5), col, (0.3, 0.26, 0.2), "MULTIPLY")
        col = _mix(nt, bare, col, (0.66, 0.55, 0.46))
    if surface == "floor":
        if C["wear"]:
            n = _maprange(nt, noise(0.45, 4.0), 0.45, 0.7)
            hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.inputs["Saturation"].default_value = 0.6; hs.inputs["Value"].default_value = 1.18
            nt.links.new(col, hs.inputs["Color"])
            col = _mix(nt, _math(nt, "MULTIPLY", n, C["wear"] * 0.7), col, hs.outputs[0])
        if C["stain"]:
            vo = _n(nt, "ShaderNodeTexVoronoi", Scale=1.4); nt.links.new(geo.outputs["Position"], vo.inputs["Vector"])
            sp = _maprange(nt, vo.outputs["Distance"], 0.16, 0.04)
            wob = _maprange(nt, noise(6.0, 3.0), 0.35, 0.65)
            fac = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", sp, wob), min(1.0, C["stain"] * 1.3))
            col = _mix(nt, fac, col, (0.3, 0.24, 0.16), "MULTIPLY")
    nt.links.new(col, b.inputs["Base Color"])
    return m

# ============================================================== condition on objects (kitchens, appliances, furniture)
# How beaten-up things are at each condition: surfaces get grime, grease, dust and chips; kitchens also get doors hanging
# open, doors and handles missing. Models get the same ageing at a slightly lower level (they're moved in and out).
CONDITION_LEVEL = {"new": 0.0, "lived_in": 0.12, "worn": 0.35, "neglected": 0.65, "derelict": 1.0}
DMG = CONDITION_LEVEL.get(CONDITION, 0.0)
RNG = random.Random(f"{SPEC.get('name', 'room')}|{CONDITION}")          # the same room always gets the same damage
_aged, _orig = {}, {}

def age_object_mat(m, level, kind="model"):
    """A copy of material m aged to 'level' (0..1). kind: model, kfront (kitchen doors), appliance, steel, worktop."""
    if not m or level <= 0.01 or not m.use_nodes: return m
    key = (m.name, round(level, 2), kind)
    if key in _aged: return _aged[key]
    b0 = _bsdf(m)
    if b0 is None: return m
    def val(name, default=0.0):
        i = b0.inputs.get(name); return i.default_value if i is not None and not i.links else default
    em, ec = b0.inputs.get("Emission Strength"), b0.inputs.get("Emission Color") or b0.inputs.get("Emission")
    if em is not None and ec is not None and (em.links or em.default_value > 0.01) and (ec.links or max(ec.default_value[:3]) > 0.01):
        return m                                             # lights, screens, flames: leave alone
    if val("Transmission Weight", val("Transmission", 0.0)) > 0.3 or val("Alpha", 1.0) < 0.6: return m   # glass
    a = m.copy(); a.name = f"{m.name}~{kind}{int(level * 100)}"; _aged[key] = a; _orig[a.name] = m
    nt = a.node_tree; b = _bsdf(a)
    if b.inputs["Base Color"].links: col = b.inputs["Base Color"].links[0].from_socket
    else:
        rgb = nt.nodes.new("ShaderNodeRGB"); rgb.outputs[0].default_value = b.inputs["Base Color"].default_value; col = rgb.outputs[0]
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    def noise(scale, detail=6.0, rough=0.55):
        n = _n(nt, "ShaderNodeTexNoise", Scale=scale, Detail=detail, Roughness=rough); nt.links.new(geo.outputs["Position"], n.inputs["Vector"]); return n.outputs["Fac"]
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(geo.outputs["Position"], sep.inputs[0]); z = sep.outputs["Z"]
    metal = kind in ("steel",) or val("Metallic") > 0.5
    # faded and grubby all over
    hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.inputs["Saturation"].default_value = 1 - 0.45 * level; hs.inputs["Value"].default_value = 1 - 0.2 * level
    nt.links.new(col, hs.inputs["Color"]); col = hs.outputs[0]
    if kind in ("kfront", "appliance", "worktop"):           # cooking grease and nicotine: yellow-brown film
        col = _mix(nt, 0.45 * level, col, (0.82, 0.68, 0.42), "MULTIPLY")
    grime = _math(nt, "MULTIPLY", _maprange(nt, noise(2.2), 0.3, 0.75), 0.95 * level)
    col = _mix(nt, grime, col, (0.4, 0.33, 0.24), "MULTIPLY")
    # stains: darker blotches (spills, damp, nicotine)
    st = _math(nt, "MULTIPLY", _maprange(nt, noise(3.5, 5.0, 0.6), 0.6, 0.66), 0.7 * level)
    col = _mix(nt, st, col, (0.32, 0.24, 0.14), "MULTIPLY")
    # dirt packed into corners and crevices
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion"); ao.inputs["Distance"].default_value = 0.06; ao.samples = 8
    inv = _math(nt, "SUBTRACT", 1.0, ao.outputs["AO"])
    col = _mix(nt, _math(nt, "MULTIPLY", inv, 1.1 * level), col, (0.25, 0.2, 0.14), "MULTIPLY")
    # dust settled on upward-facing surfaces
    nsep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(geo.outputs["Normal"], nsep.inputs[0])
    up = _maprange(nt, nsep.outputs["Z"], 0.6, 0.95)
    dust = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", up, _maprange(nt, noise(6.0, 4.0), 0.25, 0.65)), 0.65 * level)
    col = _mix(nt, dust, col, (0.5, 0.47, 0.42))
    # chips (doors, appliances) and rust (metal, bottoms of appliances)
    chip = None
    if kind in ("kfront", "appliance", "worktop") and level > 0.3:
        n = noise(5.0, 2.0, 0.5); t0 = 0.8 - 0.08 * level        # a few larger, ragged chips rather than a speckle
        chip = _maprange(nt, n, t0, t0 + 0.008)
        col = _mix(nt, chip, col, (0.5, 0.39, 0.25) if kind != "appliance" else (0.3, 0.13, 0.05))
    rust = None
    if (metal or kind == "appliance") and level > 0.3:
        low = _maprange(nt, z, 0.45, 0.0) if kind == "appliance" else 1.0
        n = _maprange(nt, noise(5.0, 7.0, 0.65), 0.62 - 0.15 * level, 0.72 - 0.1 * level)
        rust = _math(nt, "MULTIPLY", n, low) if not isinstance(low, float) else n
        col = _mix(nt, _math(nt, "MULTIPLY", rust, level), col, (0.28, 0.11, 0.04))
    nt.links.new(col, b.inputs["Base Color"])
    # rougher and duller; rusty patches lose their metal
    r = b.inputs["Roughness"]
    if not r.links: r.default_value = min(1.0, r.default_value + 0.35 * level)
    if metal and rust is not None and not b.inputs["Metallic"].links:
        mm = _math(nt, "SUBTRACT", b.inputs["Metallic"].default_value, _math(nt, "MULTIPLY", rust, level))
        nt.links.new(mm, b.inputs["Metallic"])
    return a

def age_model(root, level):
    """Age every material on an imported model (object-level slots, so other copies can keep their own condition)."""
    if root is None: return
    for o in [root] + list(root.children_recursive):
        if o.type != "MESH": continue
        for slot in o.material_slots:
            m = slot.material
            if not m: continue
            m = _orig.get(m.name, m)                       # copies of an earlier item carry its aged material: start clean
            a = age_object_mat(m, level, "model") if level > 0.01 else m
            if a is not slot.material: slot.link = "OBJECT"; slot.material = a

def finish_set(prefix, walls_f, lower_f):
    """Materials for one wall finish (+ its lower part): returns (wall material, lower material or None, lower finish)."""
    wm = apply_condition(wall_finish_mat(f"{prefix}_wall", walls_f), "wall", peelable=walls_f.get("type") in ("paint", "wallpaper"))
    lf = lower_f if lower_f and lower_f.get("type", "none") != "none" else None
    lm = None
    if lf:
        lm = wood_mat(f"{prefix}_lower_wood", lf, floor=False) if lf["type"] == "panelling" else wall_finish_mat(f"{prefix}_lower", lf)
        lm = apply_condition(lm, "wall", peelable=lf["type"] in ("paint", "wallpaper"))
    return wm, lm, lf

WORKTOPS = {"quartz_white": ((0.78, 0.77, 0.74), 0.18, 0.4, 0.0), "steel": ((0.62, 0.62, 0.6), 0.25, 0.0, 1.0)}

def kitchen_materials(M):
    """Kitchen units, worktop, splashback, kitchen floor and appliances from finishes.kitchen (any room type)."""
    K = FIN.get("kitchen")
    if not K: return
    u = K.get("units", {}); style = u.get("style", "matt")
    if style == "wood":
        front = wood_mat("Kitchen_front", {"wood": u.get("wood", "oak")}, floor=False); carcass = front
    else:
        col = u.get("colour", "#eeeeea")
        front = paint_mat("Kitchen_front", col, {"gloss": "gloss", "satin": "silk"}.get(style, "matt"), texture=0.0)
        carcass = flat("Kitchen_carcass", shade(lin(col), 0.85), 0.6)
    M["k_front"] = apply_condition(front, "trim")
    M["k_carcass"] = carcass if carcass is front else apply_condition(carcass, "trim")
    w = K.get("worktop", {}); wt = w.get("type", "quartz_white")
    if wt == "oak": top = wood_mat("Kitchen_worktop", {"wood": "oak"}, floor=False)
    elif wt == "granite_black": top = speckle_vinyl("Kitchen_worktop", (0.02, 0.02, 0.022), (0.035, 0.035, 0.04), fleck=(0.35, 0.33, 0.3), rough=0.15)
    elif wt == "laminate": top = flat("Kitchen_worktop", lin(w.get("colour", "#cbbd9f")), 0.4)
    else:
        c, r, coat, metal = WORKTOPS.get(wt, WORKTOPS["quartz_white"]); top = flat("Kitchen_worktop", c, r, metal, coat=coat)
    M["k_top"] = apply_condition(top, "floor")
    sp = K.get("splashback", {}); st = sp.get("type", "tiles")
    if st == "same": M["k_splash"] = M["wall"]
    elif st == "glass": M["k_splash"] = flat("Kitchen_splash_glass", lin(sp.get("colour", "#c9cbc8")), 0.06, coat=1.0)
    else: M["k_splash"] = apply_condition(tiles_mat("Kitchen_splash", sp, wall=True), "wall")
    fl = K.get("floor", {})
    M["k_floor"] = M["floor"] if fl.get("type", "same") == "same" else apply_condition(floor_finish_mat("Kitchen_floor", fl), "floor")
    ap = K.get("appliances", "steel")
    M["white_goods"] = M["steel"] if ap == "steel" else (flat("Appliance_black", (0.02, 0.02, 0.022), 0.25, coat=0.6) if ap == "black"
                                                         else flat("White_goods", (0.85, 0.85, 0.84), 0.3, coat=0.3))
    if DMG > 0.01:                                       # the condition beats the kitchen up too
        M["k_front"] = age_object_mat(M["k_front"], DMG, "kfront")
        if M["k_carcass"] is not M["k_front"]: M["k_carcass"] = age_object_mat(M["k_carcass"], DMG * 0.8, "kfront")
        M["k_top"] = age_object_mat(M["k_top"], DMG, "worktop")
        M["white_goods"] = age_object_mat(M["white_goods"], DMG, "appliance")
        M["k_steel"] = age_object_mat(M["steel"], DMG, "steel")

def style_materials():
    M = {}
    if COURT:
        M["wall"] = textured("Wall_paint_court", "white_plaster_rough_01", scale=1.0, tint=(0.86, 0.82, 0.74), sat=0.2,
                             lift=0.5, lift_col=(0.84, 0.8, 0.72), rough=0.8, normal=0.1, coord="Object")
        M["panel"] = textured("Oak_panelling", "wood_floor_worn", scale=0.8, tint=(0.95, 0.72, 0.45), sat=0.9, rough=0.4, normal=0.15, coord="Object")
        M["floor"] = carpet("Carpet_court_blue", (0.025, 0.045, 0.11), (0.032, 0.055, 0.13))
        M["ceiling"] = brick_tiles("Ceiling_tiles_court", (0.86, 0.86, 0.84), (0.85, 0.85, 0.83), (0.66, 0.66, 0.64), 0.6, row=1.0, rough=0.9)
        M["trim"] = M["panel"]
        M["k_floor"] = M["floor"]
        M["k_front"] = M["panel"]; M["k_carcass"] = M["panel"]
        M["k_top"] = flat("Court_top", (0.3, 0.2, 0.12), 0.35); M["k_splash"] = M["wall"]
        M["frame"] = flat("Court_window_frame", (0.8, 0.8, 0.78), 0.4)
        M["door"] = M["panel"]
        M["hall_wall"] = M["wall"]; M["hall_floor"] = carpet("Carpet_corridor", (0.14, 0.15, 0.17), (0.17, 0.18, 0.2))
        M["panel_light"] = flat("Panel_light_emit", (1, 1, 1), 0.5, emit=(1.0, 0.97, 0.92), strength=3)
    elif CUSTODY:
        M["wall"] = brick_tiles("Blockwork_painted", (0.8, 0.79, 0.72), (0.78, 0.77, 0.7), (0.68, 0.67, 0.6), 0.44, row=0.49, offset=0.5, rough=0.3, wall=True)
        M["floor"] = speckle_vinyl("Floor_resin_custody", (0.3, 0.36, 0.4), (0.34, 0.39, 0.43), fleck=(0.55, 0.58, 0.6), rough=0.45)
        M["ceiling"] = flat("Ceiling_custody", (0.83, 0.83, 0.81), 0.6)
        M["trim"] = flat("Coving_resin", (0.28, 0.32, 0.36), 0.4)
        M["k_floor"] = M["floor"]
        M["k_front"] = flat("Custody_front", (0.7, 0.7, 0.68), 0.4); M["k_carcass"] = M["k_front"]
        M["k_top"] = flat("Custody_steel_top", (0.62, 0.62, 0.6), 0.25, 1.0); M["k_splash"] = M["wall"]
        M["frame"] = flat("Custody_frame_steel", (0.55, 0.57, 0.58), 0.35, 0.5)
        M["door"] = flat("Cell_door_steel", (0.24, 0.36, 0.48), 0.35, 0.3)
        M["hall_wall"] = M["wall"]; M["hall_floor"] = M["floor"]
        M["panel_light"] = flat("Panel_light_emit", (1, 1, 1), 0.5, emit=(0.95, 0.98, 1.0), strength=3)
    elif HOSPITAL:
        M["wall"] = textured("Wall_paint_clinical", "white_plaster_rough_01", scale=1.0, tint=(0.8, 0.86, 0.8), sat=0.15,
                             lift=0.5, lift_col=(0.78, 0.85, 0.79), rough=0.6, normal=0.08, coord="Object")
        M["floor"] = speckle_vinyl("Floor_vinyl_clinical", (0.36, 0.43, 0.47), (0.43, 0.49, 0.52))
        M["ceiling"] = brick_tiles("Ceiling_tiles_600", (0.88, 0.88, 0.86), (0.86, 0.86, 0.84), (0.62, 0.62, 0.6), 0.6, row=1.0, rough=0.9)
        M["trim"] = flat("Skirting_coved_vinyl", (0.38, 0.43, 0.46), 0.35)
        M["k_floor"] = M["floor"]
        M["k_front"] = flat("Kitchen_front_clinical", (0.82, 0.83, 0.82), 0.4)
        M["k_carcass"] = flat("Kitchen_carcass_clinical", (0.75, 0.76, 0.75), 0.5)
        M["k_top"] = flat("Kitchen_top_clinical", (0.6, 0.62, 0.62), 0.3)
        M["k_splash"] = flat("Kitchen_splash_clinical", (0.86, 0.87, 0.86), 0.25, coat=0.3)
        M["frame"] = flat("Window_frame_alu", (0.82, 0.83, 0.83), 0.35, 0.3)
        M["door"] = flat("Door_leaf_beech", (0.62, 0.46, 0.3), 0.45)
        M["hall_wall"] = M["wall"]; M["hall_floor"] = M["floor"]
        M["panel_light"] = flat("Panel_light_emit", (1, 1, 1), 0.5, emit=(1.0, 0.98, 0.95), strength=3)
        M["bedhead"] = flat("Bedhead_trunking", (0.9, 0.9, 0.88), 0.35)
        M["outlet_o2"] = flat("Outlet_oxygen", (0.92, 0.92, 0.92), 0.3)
        M["outlet_green"] = flat("Outlet_green", (0.1, 0.45, 0.25), 0.4)
        M["outlet_yellow"] = flat("Outlet_yellow", (0.85, 0.7, 0.1), 0.4)
    elif not NEGLECT:
        M["wall"] = textured("Wall_paint_modern", "white_plaster_rough_01", scale=1.0, tint=(0.93, 0.9, 0.85), sat=0.2,
                             lift=0.55, lift_col=(0.93, 0.9, 0.85), rough=0.85, normal=0.15, coord="Object")
        M["floor"] = textured("Floor_oak_modern", "wood_floor_worn", scale=0.6, sat=0.45, lift=0.55, lift_col=(0.72, 0.6, 0.45),
                              rough=0.42, normal=0.35)
        M["ceiling"] = flat("Ceiling_modern", (0.86, 0.84, 0.8), 0.9)
        M["trim"] = flat("Trim_gloss_white", (0.85, 0.85, 0.83), 0.25, coat=0.3)
        M["k_floor"] = brick_tiles("Kitchen_floor_tiles", (0.42, 0.42, 0.4), (0.4, 0.4, 0.38), (0.3, 0.3, 0.29), 0.6, row=1.0, rough=0.35)
        M["k_front"] = flat("Kitchen_front_modern", (0.085, 0.11, 0.10), 0.55)
        M["k_carcass"] = flat("Kitchen_carcass_modern", (0.05, 0.06, 0.055), 0.6)
        M["k_top"] = flat("Kitchen_quartz", (0.78, 0.77, 0.74), 0.18, coat=0.4)
        M["k_splash"] = brick_tiles("Kitchen_splash_modern", (0.78, 0.8, 0.78), (0.74, 0.77, 0.75), (0.5, 0.5, 0.48), 0.15, row=0.5, offset=0.5, rough=0.12, wall=True)
        M["frame"] = flat("Window_frame_upvc", (0.86, 0.86, 0.85), 0.35)
        M["door"] = flat("Door_leaf_modern", (0.84, 0.84, 0.82), 0.4)
        M["hall_wall"] = M["wall"]; M["hall_floor"] = M["floor"]
    else:
        M["wall"] = textured("Wall_paper_neglect", "decrepit_wallpaper", scale=1.0, grime=0.75, coord="Object", rough=0.8)
        M["floor"] = textured("Floor_wood_neglect", "wood_floor_worn", scale=0.6, tint=(0.55, 0.45, 0.35), sat=0.8, normal=0.5,
                              grime=0.6, grime_col=(0.3, 0.25, 0.18), rough_mul=1.1)
        # the floor grime should not fade with height: reuse a ceiling-style mix at floor level
        M["ceiling"] = flat("Ceiling_neglect_base", (0.62, 0.55, 0.42), 0.95)
        _c = M["ceiling"]; _nt = _c.node_tree; _b = next(n for n in _nt.nodes if n.type == "BSDF_PRINCIPLED")
        _col = add_grime(_nt, _nt.nodes.new("ShaderNodeRGB").outputs[0], 0.9, (0.45, 0.35, 0.2), zlo=-1, zhi=0)
        _rgb = [n for n in _nt.nodes if n.type == "RGB"][0]; _rgb.outputs[0].default_value = (0.66, 0.58, 0.44, 1)
        _nt.links.new(_col, _b.inputs["Base Color"])
        M["trim"] = flat("Trim_cream_neglect", (0.62, 0.56, 0.42), 0.45)
        M["k_floor"] = textured("Kitchen_lino_neglect", "old_linoleum_flooring_01", scale=1.0, grime=0.5, rough=0.6)
        M["k_front"] = flat("Kitchen_front_dated", (0.42, 0.2, 0.08), 0.5)
        M["k_carcass"] = flat("Kitchen_carcass_dated", (0.3, 0.15, 0.06), 0.6)
        M["k_top"] = flat("Kitchen_laminate_dated", (0.55, 0.5, 0.42), 0.4)
        M["k_splash"] = brick_tiles("Kitchen_splash_dated", (0.72, 0.68, 0.55), (0.68, 0.64, 0.52), (0.45, 0.42, 0.34), 0.15, row=1.0, rough=0.25, wall=True)
        M["frame"] = flat("Window_frame_wood_dated", (0.55, 0.5, 0.4), 0.55)
        M["door"] = flat("Door_leaf_dated", (0.6, 0.55, 0.42), 0.5)
        M["hall_wall"] = M["wall"]; M["hall_floor"] = M["floor"]
    # the finishes chosen for this room replace the style's own walls / floor / ceiling / trim
    M["wall"], M["lower"], M["lower_f"] = finish_set("Room", FIN.get("walls", {}), FIN.get("lower"))
    M["floor"] = apply_condition(floor_finish_mat("Room_floor", FIN.get("floor", {})), "floor")
    M["ceiling"] = apply_condition(ceiling_finish_mat("Room_ceiling", FIN.get("ceiling", {})), "ceiling")
    M["trim"] = apply_condition(trim_finish_mat("Room_trim", FIN.get("trim", {})), "trim")
    M["hall_wall"] = M["wall"]
    if not COURT: M["hall_floor"] = M["floor"]
    M["glass"] = flat("Glass", (1, 1, 1), 0.02, transmission=1.0)
    M["dark"] = flat("Dark_gap", (0.01, 0.01, 0.01), 0.8)
    M["steel"] = flat("Steel", (0.62, 0.62, 0.6), 0.25, 1.0)
    M["black_glass"] = flat("Black_glass", (0.01, 0.01, 0.012), 0.05, coat=1.0)
    M["white_goods"] = flat("White_goods", (0.85, 0.85, 0.84), 0.3, coat=0.3) if NEGLECT else M["steel"]
    M["radiator"] = flat("Radiator", (0.82, 0.82, 0.8), 0.35) if not NEGLECT else flat("Radiator_old", (0.7, 0.66, 0.56), 0.5)
    M["shelf"] = flat("Shelf_wood", (0.45, 0.3, 0.18), 0.5) if not NEGLECT else flat("Shelf_wood_old", (0.33, 0.22, 0.12), 0.6)
    M["curtain"] = flat("Curtain_fabric", (0.45, 0.28, 0.12), 0.9) if NEGLECT else (
        flat("Curtain_fabric_modern", (0.55, 0.53, 0.48), 0.9) if not HOSPITAL else flat("Curtain_fabric_ward", (0.36, 0.55, 0.66), 0.85))
    M["nets"] = flat("Net_curtain", (0.86, 0.83, 0.72) if NEGLECT else (0.92, 0.92, 0.9), 1.0, alpha=0.55)
    M["blind"] = flat("Blind_slat", (0.86, 0.87, 0.85) if not NEGLECT else (0.78, 0.74, 0.62), 0.4)
    M["frosted"] = flat("Glass_frosted", (1, 1, 1), 0.45, transmission=1.0)
    kitchen_materials(M)
    M["handrail"] = flat("Handrail_beech", (0.62, 0.45, 0.28), 0.4)
    M["vision"] = flat("Vision_panel_glass", (0.55, 0.6, 0.62), 0.05, coat=1.0)
    M["sign_blue"] = flat("Sign_blue", (0.0, 0.3, 0.6), 0.4)
    M["sign_green"] = flat("Sign_green_exit", (0.0, 0.55, 0.25), 0.4, emit=(0.0, 0.8, 0.3), strength=2.0)
    M["cork"] = flat("Noticeboard_cork", (0.55, 0.38, 0.22), 0.8)
    M["paper"] = flat("Notice_paper", (0.92, 0.92, 0.88), 0.7)
    M["frame_pic"] = flat("Picture_frame", (0.1, 0.08, 0.06), 0.5)
    M["mat"] = flat("Door_mat", (0.25, 0.2, 0.14), 0.95)
    M["daylight_glass"] = flat("Front_door_glazing", (0.9, 0.92, 0.95), 0.4,
                               emit=(0.85, 0.9, 1.0), strength={"day": 2.5, "dusk": 0.8, "night": 0.05}.get(LIGHTING, 2.5))
    M["grass"] = flat("Grass", (0.12, 0.22, 0.06), 0.9)
    M["hedge"] = flat("Hedge", (0.06, 0.13, 0.04), 0.9)
    M["fence"] = flat("Fence", (0.32, 0.22, 0.14), 0.8)
    return M

MAT = style_materials()

def door_and_fitting_materials():
    """Door leaves from the finishes (wood veneer or paint), then age the fittings with the room's condition."""
    d = FIN.get("doors") if isinstance(FIN.get("doors"), dict) else None
    if d is None and HOSPITAL: d = {"type": "wood", "wood": "light_oak"}     # NHS-style light veneer, not a flat peach colour
    if d:
        if d.get("type", "wood") == "wood":
            MAT["door"] = wood_mat("Door_leaf_veneer", {"wood": d.get("wood", "light_oak")}, floor=False, laminate=True)
        else:
            MAT["door"] = paint_mat("Door_leaf_paint", d.get("colour", "#e8e6df"), d.get("sheen", "silk"))
    if DMG > 0.01:                                       # radiators, doors, frames and rails get the same beating as the rest
        MAT["door"] = age_object_mat(MAT["door"], DMG * 0.9, "kfront")
        MAT["radiator"] = age_object_mat(MAT["radiator"], DMG, "appliance")
        for k in ("frame", "handrail", "shelf", "blind", "bedhead"):
            if k in MAT: MAT[k] = age_object_mat(MAT[k], DMG * 0.7, "model")

door_and_fitting_materials()

# per-wall and per-alcove finishes: {"walls": {...}, "lower": {...}} on spec.wall_finishes[<wall>] or an alcove's "finish";
# anything left out is inherited (alcove <- its wall <- the room)
_WF = SPEC.get("wall_finishes") or {}
WALL_FINS, WALL_SET, _ALC = {}, {}, {}
def _has(ov): return bool(ov) and (bool(ov.get("walls")) or "lower" in ov)
for _w in ("north", "south", "east", "west"):
    _ov = _WF.get(_w)
    if _has(_ov):
        WALL_FINS[_w] = (_ov.get("walls") or FIN.get("walls", {}), _ov["lower"] if "lower" in _ov else FIN.get("lower"))
        WALL_SET[_w] = finish_set(f"Wall_{_w}", *WALL_FINS[_w])
    else:
        WALL_FINS[_w] = (FIN.get("walls", {}), FIN.get("lower"))
        WALL_SET[_w] = (MAT["wall"], MAT["lower"], MAT["lower_f"])

def alcove_set(ft):
    """(wall material, lower material, lower finish) for an alcove: its own finish, else its wall's."""
    wall = ft.get("wall"); ov = ft.get("finish")
    if not _has(ov): return WALL_SET.get(wall, (MAT["wall"], MAT["lower"], MAT["lower_f"]))
    key = ft.get("id") or id(ft)
    if key not in _ALC:
        bw, bl = WALL_FINS.get(wall, (FIN.get("walls", {}), FIN.get("lower")))
        _ALC[key] = finish_set(f"Alcove_{key}", ov.get("walls") or bw, ov["lower"] if "lower" in ov else bl)
    return _ALC[key]

def lower_height(lf):
    return min(float(lf.get("height", 1.15 if lf.get("type") == "panelling" else 1.2)), RH - 0.3)

def lower_along(name, wall, a, b, d_face, lm, lf):
    """Lower-wall finish (panelling with rail and stiles, or a band of tiles / paint / paper with a dado rail) on a run
    parallel to the wall whose room-side face is at depth d_face (the room is towards smaller d)."""
    if b - a < 0.05: return
    H = lower_height(lf)
    if lf.get("type") == "panelling":
        wbox(name, wall, a, b, d_face - 0.02, d_face, 0.12, H, lm)
        wbox(f"{name}_rail", wall, a, b, d_face - 0.04, d_face, H, H + 0.06, lm)
        n = max(1, round((b - a) / 0.6))
        for k in range(n + 1):
            u = a + (b - a) * k / n
            wbox(f"{name}_stile{k}", wall, max(a, u - 0.025), min(b, u + 0.025), d_face - 0.03, d_face, 0.12, H, lm)
    else:
        wbox(name, wall, a, b, d_face - 0.006, d_face, 0.0, H, lm)
        wbox(f"{name}_rail", wall, a, b, d_face - 0.022, d_face, H, H + 0.045, MAT["trim"])

def lower_side(name, wall, u_face, sgn, d0, d1, lm, lf):
    """The same on an alcove side wall: face at u_face, the room is towards +sgn along the wall."""
    H = lower_height(lf)
    span = lambda t: (u_face, u_face + t) if sgn > 0 else (u_face - t, u_face)
    if lf.get("type") == "panelling":
        wbox(name, wall, *span(0.02), d0, d1, 0.12, H, lm)
        wbox(f"{name}_rail", wall, *span(0.04), d0, d1, H, H + 0.06, lm)
        n = max(1, round((d1 - d0) / 0.6))
        for k in range(n + 1):
            d = d0 + (d1 - d0) * k / n
            wbox(f"{name}_stile{k}", wall, *span(0.03), max(d0, d - 0.025), min(d1, d + 0.025), 0.12, H, lm)
    else:
        wbox(name, wall, *span(0.006), d0, d1, 0.0, H, lm)
        wbox(f"{name}_rail", wall, *span(0.022), d0, d1, H, H + 0.045, MAT["trim"])

# ============================================================== geometry helpers
def box_obj(name, mn, mx, m, cname="Room"):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((mn.x if v.co.x < 0 else mx.x, mn.y if v.co.y < 0 else mx.y, mn.z if v.co.z < 0 else mx.z))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # box-projected UVs in metres so image textures keep their real size
    uv = bm.loops.layers.uv.new()
    for f in bm.faces:
        n = f.normal
        for l in f.loops:
            p = l.vert.co
            if abs(n.z) > 0.5: l[uv].uv = (p.x, p.y)
            elif abs(n.x) > 0.5: l[uv].uv = (p.y, p.z)
            else: l[uv].uv = (p.x, p.z)
    bm.to_mesh(me); bm.free()
    if m: me.materials.append(m)
    o = bpy.data.objects.new(name, me); coll(cname).objects.link(o)
    return o

def wbox(name, wall, u0, u1, d0, d1, z0, z1, m, cname="Room"):
    mn, mx = wbox_world(wall, u0, u1, d0, d1, z0, z1)
    return box_obj(name, mn, mx, m, cname)

def plane(name, x0, y0, x1, y1, z, m, flip=False, cname="Room"):
    me = bpy.data.meshes.new(name)
    vs = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    f = (0, 1, 2, 3) if not flip else (3, 2, 1, 0)
    me.from_pydata(vs, [], [f])
    uv = me.uv_layers.new()
    for li, vi in enumerate(f): uv.data[li].uv = (vs[vi][0], vs[vi][1])
    if m: me.materials.append(m)
    o = bpy.data.objects.new(name, me); coll(cname).objects.link(o)
    return o

def cylinder_obj(name, r, h, loc, m, rot=(0, 0, 0), verts=48, cname="Room"):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=verts, radius1=r, radius2=r, depth=h)
    bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    if m: me.materials.append(m)
    o = bpy.data.objects.new(name, me); coll(cname).objects.link(o)
    o.location = loc; o.rotation_euler = rot
    return o

def apply_cutters(obj, cutters):
    """Boolean-difference each cutter out of obj, bake the result into its mesh and delete the cutters."""
    if not cutters: return obj
    for i, c in enumerate(cutters):
        md = obj.modifiers.new(f"cut{i}", "BOOLEAN"); md.operation = "DIFFERENCE"; md.object = c
        md.solver = "EXACT" if "EXACT" in [e.identifier for e in md.bl_rna.properties["solver"].enum_items] else md.solver
        c.hide_render = True; c.display_type = "WIRE"
    dg = bpy.context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    old = obj.data; obj.modifiers.clear(); obj.data = new; bpy.data.meshes.remove(old)
    for c in cutters: bpy.data.objects.remove(c, do_unlink=True)
    return obj

def opening_cutter(wall, f, z0, z1, round_top=None):
    """A cutter through the whole wall thickness. round_top = (spring, top) for an arch."""
    w = float(f["width"]); u = float(f["pos"])
    if not round_top:
        return wbox(f"cut_{f.get('id', f['type'])}", wall, u - w / 2, u + w / 2, -0.3, T + 0.3, z0, z1, None, "_cutters")
    spring, top = round_top
    body = wbox(f"cut_{f.get('id', 'arch')}_body", wall, u - w / 2, u + w / 2, -0.3, T + 0.3, z0, spring + 0.001, None, "_cutters")
    c = w2world(wall, u, T / 2, spring)
    axis_rot = (math.pi / 2, 0, 0) if WALLS[wall]["axis"] == "x" else (math.pi / 2, 0, math.pi / 2)
    cyl = cylinder_obj(f"cut_{f.get('id', 'arch')}_top", w / 2, T + 0.6, c, None, rot=axis_rot, verts=96, cname="_cutters")
    cyl.scale = (1, max(0.05, (top - spring) / (w / 2)), 1) if WALLS[wall]["axis"] == "x" else (1, max(0.05, (top - spring) / (w / 2)), 1)
    # scale along the cylinder's local Y (which points up after the 90 deg X rotation) squashes the circle into the arch
    return [body, cyl]

# ============================================================== shell
log("building shell", W, D, RH, STYLE)
by_wall = {k: [f for f in FEATURES if f.get("wall") == k] for k in WALLS}
zones = []                                           # floor/ceiling rectangles: (name, mn, mx, floor_m, ceiling_z)
if not OUTDOOR:
    zones.append(("main", Vector((X0 - T / 2, Y0 - T / 2, 0)), Vector((X1 + T / 2, Y1 + T / 2, 0)), MAT["floor"], RH))
skirt_runs = []                                      # (wall-or-local frame, u0, u1, d, facing sign) handled per wall below
lights_extra = []

def feature_span(f):
    w = float(f["width"]); return float(f["pos"]) - w / 2, float(f["pos"]) + w / 2

# Where two full-height recesses meet in a corner, the old room corner would be left standing as a pillar.
# corner_mate() finds the recess on the next wall; the shell cut and the recess walls then open the corner right up.
CORNERS = {("north", "lo"): ("west", "hi"), ("north", "hi"): ("east", "hi"), ("south", "lo"): ("west", "lo"), ("south", "hi"): ("east", "lo")}
CORNERS.update({v: k for k, v in list(CORNERS.items())})
def full_recess(f): return f.get("type") in ("alcove", "kitchenette") and min(float(f.get("height", RH)), RH) >= RH - 0.01
def at_end(f, end):
    w = WALLS[f["wall"]]; u0, u1 = feature_span(f)
    return u0 <= w["lo"] + 0.01 if end == "lo" else u1 >= w["hi"] - 0.01
def fdepth(f): return float(f.get("depth", 0.65 if f.get("type") == "kitchenette" else 0.6))
def corner_mate(f, end):
    if f.get("wall") not in WALLS or not full_recess(f) or not at_end(f, end): return None
    k = CORNERS[(f["wall"], end)]
    for g in FEATURES:
        if g is not f and g.get("wall") == k[0] and full_recess(g) and at_end(g, k[1]): return g
    return None

for wall, f in ({} if OUTDOOR else WALLS).items():
    lo, hi = f["lo"], f["hi"]
    wmat, lmat, lfin = WALL_SET[wall]
    solid = wbox(f"Wall_{wall}", wall, lo - T, hi + T, 0, T, 0, RH, wmat)
    cutters = []
    floor_gaps = []                                  # spans along the wall where the skirting stops
    top_gaps = []                                    # spans where the cornice stops (full-height openings)
    for ft in by_wall[wall]:
        typ = ft["type"]; u0, u1 = feature_span(ft)
        if typ in ("alcove", "kitchenette"):
            h = min(float(ft.get("height", RH)), RH)
            e0 = u0 - (T + 0.01 if corner_mate(ft, "lo") else 0); e1 = u1 + (T + 0.01 if corner_mate(ft, "hi") else 0)
            cutters.append(opening_cutter(wall, dict(ft, pos=(e0 + e1) / 2, width=e1 - e0), -0.1, h if h < RH - 0.01 else RH + 0.1))
            floor_gaps.append((u0, u1))
            if h >= RH - 0.01: top_gaps.append((u0, u1))
        elif typ == "door":
            cutters.append(opening_cutter(wall, ft, -0.1, float(ft.get("height", 2.0))))
            floor_gaps.append((u0, u1))
        elif typ == "window":
            sill = float(ft.get("sill", 0.8)); h = float(ft.get("height", 1.2))
            cutters.append(opening_cutter(wall, ft, sill, sill + h))
        elif typ == "arch":
            top = min(float(ft.get("height", 2.0)), RH - 0.05)
            if ft.get("shape", "round") == "round":
                spring = max(0.3, top - float(ft["width"]) / 2 * float(ft.get("rise", 0.2)))
                cutters.extend(opening_cutter(wall, ft, -0.1, top, round_top=(spring, top)))
            else:
                cutters.append(opening_cutter(wall, ft, -0.1, top))
            floor_gaps.append((u0, u1))
    flat_cutters = []
    for c in cutters: flat_cutters.extend(c if isinstance(c, list) else [c])
    apply_cutters(solid, flat_cutters)
    # skirting along the room side of the wall line, broken at floor-level openings
    runs, cur = [], lo
    for g0, g1 in sorted(floor_gaps):
        if g0 > cur: runs.append((cur, g0))
        cur = max(cur, g1)
    if cur < hi: runs.append((cur, hi))
    for i, (a, b) in enumerate(runs):
        if b - a > 0.02: wbox(f"Skirting_{wall}_{i}", wall, a, b, -0.018, 0, 0, 0.12, MAT["trim"])
    if lfin:                                          # lower walls: panelling, tiles, two-tone paint or paper, with a rail
        H = lower_height(lfin)
        gaps = sorted(floor_gaps + [feature_span(x) for x in by_wall[wall] if x["type"] == "window" and float(x.get("sill", 0.8)) < H + 0.06])
        wr, cur = [], lo
        for g0, g1 in gaps:
            if g0 > cur: wr.append((cur, g0))
            cur = max(cur, g1)
        if cur < hi: wr.append((cur, hi))
        for i, (a, b) in enumerate(wr):
            lower_along(f"Lower_{wall}_{i}", wall, a, b, 0.0, lmat, lfin)
    # cornice / coving along the top
    runs, cur = [], lo
    for g0, g1 in sorted(top_gaps):
        if g0 > cur: runs.append((cur, g0))
        cur = max(cur, g1)
    if cur < hi: runs.append((cur, hi))
    for i, (a, b) in enumerate(runs):
        if b - a > 0.02: wbox(f"Cornice_{wall}_{i}", wall, a, b, -0.05, 0, RH - 0.05, RH, MAT["trim"])

# ============================================================== features
def panel_light(name, at, along_x=True, energy=150, size=(1.2, 0.6)):
    """A recessed 1200 x 600 ceiling panel: an emitting face and an area light just under it."""
    sx, sy = size if along_x else (size[1], size[0])
    box_obj(name + "_face", Vector((at.x - sx / 2, at.y - sy / 2, RH - 0.012)), Vector((at.x + sx / 2, at.y + sy / 2, RH - 0.002)),
            MAT.get("panel_light") or flat("Panel_light_emit", (1, 1, 1), 0.5, emit=(1.0, 0.98, 0.95), strength=6), "Lights")
    bpy.ops.object.light_add(type="AREA", location=(at.x, at.y, RH - 0.02))
    l = bpy.context.active_object; l.name = name; l.data.shape = "RECTANGLE"; l.data.size, l.data.size_y = sx * 0.95, sy * 0.95
    l.data.energy = energy; l.data.color = (1.0, 0.97, 0.93); put(l, "Lights")

def recess(ft, wall, depth, h, name, floor_m=None, lower=True):
    """A recess beyond the wall line: back wall, two side walls, floor and ceiling zone."""
    u0, u1 = feature_span(ft)
    mlo, mhi = corner_mate(ft, "lo"), corner_mate(ft, "hi")     # recesses meeting this one in a corner
    dlo, dhi = (fdepth(mlo) if mlo else 0.0), (fdepth(mhi) if mhi else 0.0)
    amat, almat, alfin = alcove_set(ft)
    doors_ = ft.get("doors") or []
    holes = [(*feature_span(dd), min(float(dd.get("height", 2.0)), h - 0.05)) for dd in doors_ if door_side(wall, dd) == "back"]
    sholes = {ab: [(float(dd["pos"]) - float(dd["width"]) / 2, float(dd["pos"]) + float(dd["width"]) / 2, min(float(dd.get("height", 2.0)), h - 0.05))
                   for dd in doors_ if door_side(wall, dd) == ab] for ab in ("a", "b")}      # side doors: along the depth
    for a, b in spans_without(u0 - T - dlo, u1 + T + dhi, [(h0, h1) for h0, h1, _ in holes]):
        wbox(f"{name}_back", wall, a, b, depth, depth + T, 0, RH, amat)
    for k, (h0, h1, dh) in enumerate(holes):                  # wall over each door
        wbox(f"{name}_back_over{k}", wall, h0, h1, depth, depth + T, dh, RH, amat)
    for ab, mate, (sa, sb) in (("a", mlo, (u0 - T, u0)), ("b", mhi, (u1, u1 + T))):
        if mate: continue
        flush = WALLS[wall]["lo"] >= u0 - 0.001 if ab == "a" else WALLS[wall]["hi"] <= u1 + 0.001   # in line with the room's side wall
        for d0, d1 in spans_without(T if flush else 0.0, depth + T, [(x0, x1) for x0, x1, _ in sholes[ab]]):
            wbox(f"{name}_side_{ab}", wall, sa, sb, d0, d1, 0, RH, amat)
        for k, (x0, x1, dh) in enumerate(sholes[ab]): wbox(f"{name}_side_{ab}_over{k}", wall, sa, sb, x0, x1, dh, RH, amat)
    mn, mx = wbox_world(wall, u0, u1, T / 2, depth, 0, 0)
    zones.append((name, mn, mx, floor_m or MAT["floor"], h))
    for m_, a, b, tag in ((mlo, u0 - dlo, u0, "lo"), (mhi, u1, u1 + dhi, "hi")):   # the opened-up corner square
        if m_ and wall < m_["wall"]:
            cmn, cmx = wbox_world(wall, a, b, 0, depth, 0, 0); zones.append((f"{name}_corner_{tag}", cmn, cmx, floor_m or MAT["floor"], h))
    # the alcove is part of the room: skirting, coving (and court panelling) carry on round the inside.
    # wrap=True starts the side pieces in front of the wall line so they wrap the outside corner of the opening.
    full = h >= RH - 0.01; top = RH if full else h
    def trim_round(tag, t, z0, z1, m, wrap=True):
        for a, b in (spans_without(u0 - dlo, u1 + dhi, [(h0, h1) for h0, h1, dh in holes if z0 < dh]) if holes else [(u0 - dlo, u1 + dhi)]):
            wbox(f"{name}_{tag}_back", wall, a, b, depth - t, depth, z0, z1, m)
        d0 = -t if wrap else 0.0
        for ab, mate, (sa, sb) in (("a", mlo, (u0, u0 + t)), ("b", mhi, (u1 - t, u1))):
            if mate: continue
            for x0, x1 in spans_without(d0, depth, [(p0, p1) for p0, p1, dh in sholes[ab] if z0 < dh]):
                wbox(f"{name}_{tag}_{ab}", wall, sa, sb, x0, x1, z0, z1, m)
    trim_round("skirt", 0.018, 0, 0.12, MAT["trim"])
    trim_round("cornice", 0.05, top - 0.05, top, MAT["trim"], wrap=full)
    if lower and alfin:                              # the lower-wall finish carries on round the inside too
        for a, b in spans_without(u0 - dlo, u1 + dhi, [(h0, h1) for h0, h1, _ in holes]):
            lower_along(f"{name}_lower_back", wall, a, b, depth, almat, alfin)
        for ab, mate, uf, sg in (("a", mlo, u0, +1), ("b", mhi, u1, -1)):
            if mate: continue
            for x0, x1 in spans_without(-0.02, depth, [(p0, p1) for p0, p1, _ in sholes[ab]]):
                lower_side(f"{name}_lower_{ab}", wall, uf, sg, x0, x1, almat, alfin)
    if depth > 1.2:                                 # deep bays need their own light
        cu = (u0 + u1) / 2
        if HOSPITAL or COURT:
            big = max(1.0, (u1 - u0) * depth / 6.5)          # bigger bays get more light
            panel_light(f"{name}_panel", w2world(wall, cu, depth * 0.55, 0), along_x=WALLS[wall]["axis"] == "x", energy=45 * big * (1.3 if COURT else 1.0))
            if COURT and depth > 2.5:                        # a second panel over the back of very deep bays (the judge's bench)
                panel_light(f"{name}_panel_back", w2world(wall, cu, depth * 0.85, 0), along_x=WALLS[wall]["axis"] == "x", energy=60 * big)
        else:
            lc = w2world(wall, cu, depth / 2, RH - 0.04)
            bpy.ops.object.light_add(type="AREA", location=lc)
            l = bpy.context.active_object; l.name = f"{name}_light"; l.data.shape = "DISK"; l.data.size = 0.4
            l.data.energy = 45; l.data.color = (1.0, 0.92, 0.8); put(l)
    if HOSPITAL and depth > 1.5 and (u1 - u0) > 1.4:   # bed-head services unit on the back wall
        a, b = u0 + 0.25, u1 - 0.25
        wbox(f"{name}_bedhead", wall, a, b, depth - 0.07, depth, 1.3, 1.62, MAT["bedhead"])
        cu = (u0 + u1) / 2
        for k, (du, m_) in enumerate(((-0.45, MAT["outlet_o2"]), (-0.3, MAT["outlet_yellow"]), (0.32, MAT["outlet_green"]))):
            o = cylinder_obj(f"{name}_outlet{k}", 0.035, 0.03, w2world(wall, cu + du, depth - 0.085, 1.46), m_, verts=20)
            o.rotation_euler = (math.pi / 2, 0, 0) if WALLS[wall]["axis"] == "x" else (0, math.pi / 2, 0)
        wbox(f"{name}_reading_light", wall, cu - 0.2, cu + 0.2, depth - 0.11, depth - 0.07, 1.56, 1.6, MAT["panel_light"])
        wbox(f"{name}_call_panel", wall, cu + 0.55, cu + 0.7, depth - 0.085, depth - 0.07, 1.4, 1.52, MAT["outlet_o2"])
    return u0, u1

def shelves(ft, wall, depth, n):
    u0, u1 = feature_span(ft)
    zs = [0.35 + i * (min(RH, 2.1) - 0.5) / max(1, n - 1) for i in range(n)] if n > 1 else [1.0]
    for i, z in enumerate(zs):
        wbox(f"{ft.get('id', 'alcove')}_shelf{i}", wall, u0 + 0.005, u1 - 0.005, max(0.0, depth - 0.32), depth, z, z + 0.025, MAT["shelf"])

def swing_open(objs, wall, u_hinge, u_free, d, ang):
    """Turn door objects (built in place) about a vertical hinge at (u_hinge, d) so the free edge comes out into the room."""
    h = w2world(wall, u_hinge, d, 0); f = w2world(wall, u_free, d, 0)
    best = None
    for sgn in (1, -1):
        R = Matrix.Rotation(sgn * ang, 4, "Z"); p = h + R.to_3x3() @ (f - h)
        if best is None or p.xy.length < best[0]: best = (p.xy.length, R)
    M_ = Matrix.Translation(h) @ best[1] @ Matrix.Translation(-h)
    for o in objs:
        if o is not None: o.data.transform(M_)

def kitchen_door(name, wall, a, b, d0, z0, z1, mat, handle_z, hinge_left, chance=1.0):
    """One unit door with a bar handle. In a run-down room some hang open, some lose their handle, some are gone."""
    KS = MAT.get("k_steel", MAT["steel"]); r = RNG.random(); r2 = RNG.random()
    if DMG >= 0.6 and r < 0.16 * DMG * chance:           # door gone: the dark inside of the cupboard shows
        wbox(f"{name}_void", wall, a + 0.015, b - 0.015, d0 + 0.019, d0 + 0.0205, z0 + 0.015, z1 - 0.015, MAT["dark"])
        return
    door_o = wbox(name, wall, a, b, d0, d0 + 0.02, z0, z1, mat)
    handle_o = None
    if not (DMG >= 0.35 and r2 < 0.35 * DMG):             # handle missing (screw holes not modelled)
        hu = b - 0.06 if hinge_left else a + 0.06
        handle_o = wbox(f"{name}_handle", wall, hu - 0.008, hu + 0.008, d0 - 0.028, d0, handle_z - 0.07, handle_z + 0.07, KS)
    if DMG >= 0.3 and r < 0.5 * DMG * chance:              # hanging open
        ang = math.radians(RNG.uniform(10, 25 + 55 * DMG))
        swing_open([door_o, handle_o], wall, a if hinge_left else b, b if hinge_left else a, d0, ang)

def kitchen_run(wall, u0, u1, back_d, name, tall_end="hi"):
    """A fitted kitchen along a back wall at depth back_d, facing the room. Fridge-freezer at one end."""
    BD, BH, PL = 0.6, 0.9, 0.12            # base depth, height, plinth
    WD, WZ0, WZ1 = 0.35, 1.45, 2.15         # wall units
    L = u1 - u0
    fridge_w = 0.62 if L > 2.0 else 0.0
    fu0, fu1 = (u1 - fridge_w, u1) if tall_end == "hi" else (u0, u0 + fridge_w)
    ru0, ru1 = (u0, u1 - fridge_w) if tall_end == "hi" else (u0 + fridge_w, u1)
    d_front = back_d - BD
    # plinth, carcass, worktop
    wbox(f"{name}_plinth", wall, ru0, ru1, d_front + 0.06, back_d, 0, PL, MAT["dark"])
    wbox(f"{name}_carcass", wall, ru0, ru1, d_front + 0.02, back_d, PL, BH - 0.04, MAT["k_carcass"])
    wbox(f"{name}_worktop", wall, ru0, ru1, d_front - 0.02, back_d, BH - 0.04, BH, MAT["k_top"])
    # doors / drawers with gaps
    n = max(1, round((ru1 - ru0) / 0.6)); dw = (ru1 - ru0) / n
    for i in range(n):
        a, b = ru0 + i * dw + 0.002, ru0 + (i + 1) * dw - 0.002
        kitchen_door(f"{name}_door{i}", wall, a, b, d_front, PL + 0.003, BH - 0.045, MAT["k_front"], BH - 0.12, hinge_left=i % 2 == 0)
    # sink and hob
    sink_u = ru0 + (ru1 - ru0) * 0.3; hob_u = ru0 + (ru1 - ru0) * 0.72
    wbox(f"{name}_sink", wall, sink_u - 0.3, sink_u + 0.3, d_front + 0.08, back_d - 0.12, BH - 0.005, BH + 0.001, MAT.get("k_steel", MAT["steel"]))
    wbox(f"{name}_sink_bowl", wall, sink_u - 0.22, sink_u + 0.22, d_front + 0.12, back_d - 0.16, BH - 0.004, BH + 0.002, MAT["dark"])
    tap = w2world(wall, sink_u, back_d - 0.07, BH + 0.15)
    cylinder_obj(f"{name}_tap", 0.012, 0.3, tap, MAT.get("k_steel", MAT["steel"]), verts=16)
    wbox(f"{name}_hob", wall, hob_u - 0.3, hob_u + 0.3, d_front + 0.04, back_d - 0.04, BH, BH + 0.006, MAT["black_glass"] if not NEGLECT else MAT["white_goods"])
    # splashback between worktop and wall units
    wbox(f"{name}_splash", wall, ru0, ru1, back_d - 0.01, back_d, BH, WZ0, MAT["k_splash"])
    # wall units (gap above the hob for the hood)
    for i, (a, b) in enumerate(((ru0, hob_u - 0.35), (hob_u + 0.35, ru1))):
        if b - a < 0.25: continue
        wbox(f"{name}_wallunit{i}", wall, a, b, back_d - WD, back_d, WZ0, WZ1, MAT["k_carcass"])
        m_ = max(1, round((b - a) / 0.5)); w_ = (b - a) / m_
        for j in range(m_):
            kitchen_door(f"{name}_wdoor{i}_{j}", wall, a + j * w_ + 0.002, a + (j + 1) * w_ - 0.002, back_d - WD - 0.02, WZ0 + 0.003, WZ1 - 0.003,
                         MAT["k_front"], WZ0 + 0.1, hinge_left=j % 2 == 0, chance=0.7)
    # cooker hood
    wbox(f"{name}_hood", wall, hob_u - 0.3, hob_u + 0.3, back_d - 0.48, back_d, WZ0 + 0.15, WZ0 + 0.22, MAT.get("k_steel", MAT["steel"]))
    wbox(f"{name}_hood_chimney", wall, hob_u - 0.13, hob_u + 0.13, back_d - 0.26, back_d, WZ0 + 0.22, RH, MAT.get("k_steel", MAT["steel"]))
    # under-cabinet LED strip (modern) as a soft area light
    if not NEGLECT:
        c = w2world(wall, (ru0 + ru1) / 2, back_d - WD + 0.06, WZ0 - 0.02)
        bpy.ops.object.light_add(type="AREA", location=c)
        l = bpy.context.active_object; l.name = f"{name}_led"; l.data.shape = "RECTANGLE"
        l.data.size, l.data.size_y = (ru1 - ru0) * 0.9, 0.05
        if WALLS[wall]["axis"] == "y": l.rotation_euler.z = math.pi / 2
        l.data.energy = 25 * (ru1 - ru0); l.data.color = (1.0, 0.9, 0.75); put(l)
    # fridge-freezer
    if fridge_w:
        wbox(f"{name}_fridge", wall, fu0 + 0.01, fu1 - 0.01, back_d - 0.66, back_d, 0, 1.85, MAT["white_goods"])
        wbox(f"{name}_fridge_split", wall, fu0 + 0.01, fu1 - 0.01, back_d - 0.665, back_d - 0.66, 1.08, 1.09, MAT["dark"])

def window(ft, wall):
    u0, u1 = feature_span(ft); sill = float(ft.get("sill", 0.8)); h = float(ft.get("height", 1.2)); top = sill + h
    fw = 0.06
    # frame on the outer half of the wall, glass in the middle
    for nm, (a, b, z0, z1) in {"l": (u0, u0 + fw, sill + fw, top - fw), "r": (u1 - fw, u1, sill + fw, top - fw), "b": (u0, u1, sill, sill + fw),
                                "t": (u0, u1, top - fw, top), "mid": ((u0 + u1) / 2 - 0.03, (u0 + u1) / 2 + 0.03, sill + fw, top - fw)}.items():
        wbox(f"{ft.get('id', 'window')}_frame_{nm}", wall, a, b, T * 0.55, T * 0.9, z0, z1, MAT["frame"])
    wbox(f"{ft.get('id', 'window')}_glass", wall, u0, u1, T * 0.7, T * 0.71, sill, top, MAT["glass"])
    # inside sill board and radiator below
    wbox(f"{ft.get('id', 'window')}_sillboard", wall, u0 - 0.06, u1 + 0.06, -0.05, T * 0.55, sill - 0.025, sill, MAT["trim"])
    rw = min(1.1, (u1 - u0) * 0.9); rc = (u0 + u1) / 2
    if sill > 0.45 and sill < 1.5 and not CUSTODY:
        wbox(f"{ft.get('id', 'window')}_radiator", wall, rc - rw / 2, rc + rw / 2, -0.11, -0.04, 0.14, min(sill - 0.1, 0.65), MAT["radiator"])
    dressing = ft.get("dressing") or {"neglected": "nets_curtains", "hospital": "blinds", "court": "blinds", "custody": "frosted"}.get("neglected" if NEGLECT else STYLE, "none")
    fid = ft.get('id', 'window')
    if dressing == "frosted":
        glass = bpy.data.objects.get(f"{fid}_glass")
        if glass: glass.data.materials[0] = MAT["frosted"]
    if dressing == "blinds":
        venetian(fid, wall, u0, u1, sill, top)
    if dressing in ("curtains", "nets_curtains"):
        rail_z = min(RH - 0.03, top + 0.15)
        wbox(f"{fid}_curtain_rail", wall, u0 - 0.4, u1 + 0.4, -0.12, -0.1, rail_z, rail_z + 0.025, MAT["steel"] if not NEGLECT else MAT["shelf"])
        for side, (a_, b_) in (("l", (u0 - 0.38, u0 + 0.06)), ("r", (u1 - 0.06, u1 + 0.38))):
            curtain(f"{fid}_curtain_{side}", wall, a_, b_, -0.09, 0.0 if NEGLECT else 0.02, rail_z)
    if dressing == "nets_curtains":
        curtain(f"{fid}_nets", wall, u0 - 0.02, u1 + 0.02, -0.03, sill + 0.01, top + 0.02, folds=max(4, int((u1 - u0) * 9)), m=MAT["nets"], amp=0.012)
    # a window portal so Cycles samples the daylight efficiently
    if LIGHTING in ("day", "dusk"):
        pc = w2world(wall, (u0 + u1) / 2, T + 0.02, (sill + top) / 2)
        bpy.ops.object.light_add(type="AREA", location=pc)
        p = bpy.context.active_object; p.name = f"{ft.get('id', 'window')}_portal"; p.data.shape = "RECTANGLE"
        p.data.size, p.data.size_y = (u1 - u0), h
        # area lights face -Z: turn it to face into the room
        p.rotation_euler = {"north": (-math.pi / 2, 0, 0), "south": (math.pi / 2, 0, 0),
                            "east": (0, math.pi / 2, 0), "west": (0, -math.pi / 2, 0)}[wbase(wall)]
        try: p.data.cycles.is_portal = True
        except Exception: pass
        put(p)

def venetian(fid, wall, u0, u1, sill, top):
    """Venetian blind in the reveal: drawn up a third, the rest of the slats tilted open."""
    me = bpy.data.meshes.new(f"{fid}_blind"); bm = bmesh.new()
    d_c, half, ang = T * 0.35, 0.0125, math.radians(40)
    stack_z = top - (top - sill) * 0.33
    z = stack_z - 0.05
    slats = []
    while z > sill + 0.03:
        slats.append((z, ang)); z -= 0.045
    zz = top - 0.06
    while zz > stack_z:                               # the drawn-up stack: slats flat and close together
        slats.append((zz, 0.0)); zz -= 0.008
    for z_, a_ in slats:
        dd, dz = half * math.cos(a_), half * math.sin(a_)
        q = [w2world(wall, u0 + 0.01, d_c - dd, z_ - dz), w2world(wall, u1 - 0.01, d_c - dd, z_ - dz),
             w2world(wall, u1 - 0.01, d_c + dd, z_ + dz), w2world(wall, u0 + 0.01, d_c + dd, z_ + dz)]
        bm.faces.new([bm.verts.new(v) for v in q])
    bm.to_mesh(me); bm.free(); me.materials.append(MAT["blind"])
    o = bpy.data.objects.new(f"{fid}_blind", me); coll("Room").objects.link(o)
    wbox(f"{fid}_blind_head", wall, u0, u1, d_c - 0.025, d_c + 0.025, top - 0.05, top - 0.005, MAT["blind"])
    wbox(f"{fid}_blind_bar", wall, u0 + 0.01, u1 - 0.01, d_c - 0.012, d_c + 0.012, sill + 0.02, sill + 0.035, MAT["blind"])

def curtain(name, wall, u0, u1, d0, z0, z1, folds=7, m=None, amp=0.035):
    """A wavy curtain panel hanging from z1 down to the floor."""
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    nu, nz = folds * 6, 2
    grid = []
    for j in range(nz + 1):
        z = z0 + (z1 - z0) * j / nz; row = []
        for i in range(nu + 1):
            u = u0 + (u1 - u0) * i / nu
            d = d0 - amp * (0.5 + 0.5 * math.sin(i / nu * folds * 2 * math.pi))
            row.append(bm.verts.new(w2world(wall, u, d, z)))
        grid.append(row)
    for j in range(nz):
        for i in range(nu):
            bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
    bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    me.materials.append(m or MAT["curtain"])
    o = bpy.data.objects.new(name, me); coll("Room").objects.link(o)
    sol = o.modifiers.new("thick", "SOLIDIFY"); sol.thickness = 0.01 if m is None else 0.002

def corridor(ft, wall, u0, u1, h, fid, lit=True):
    """A corridor running along the wall outside the door, dressed for the room's style."""
    lo, hi = WALLS[wall]["lo"], WALLS[wall]["hi"]
    cw = {"hospital": 1.9, "court": 2.2, "custody": 1.6}.get(STYLE, 1.15)
    a, b = lo, hi
    for g in FEATURES:                              # stop short of anything else built beyond this wall
        if g is ft or g.get("wall") != wall or g.get("type") not in ("alcove", "kitchenette", "arch", "window", "door"): continue
        g0, g1 = feature_span(g)
        if g.get("type") == "arch":
            rm = g.get("room", {}); rp = float(rm.get("pos", g["pos"])); rw = float(rm.get("width", float(g["width"]) + 1.0))
            g0, g1 = min(g0, rp - rw / 2), max(g1, rp + rw / 2)
        if g1 <= u0: a = max(a, g1 + T + 0.05)
        elif g0 >= u1: b = min(b, g0 - T - 0.05)
    a, b = min(a, u0 - 0.2), max(b, u1 + 0.2)
    back = T + cw
    W_ = MAT["hall_wall"]
    wbox(f"{fid}_cor_back", wall, a - T, b + T, back, back + T, 0, RH, W_)
    wbox(f"{fid}_cor_end_a", wall, a - T, a, 0, back + T, 0, RH, W_)
    wbox(f"{fid}_cor_end_b", wall, b, b + T, 0, back + T, 0, RH, W_)
    mn, mx = wbox_world(wall, a, b, T / 2, back, 0, 0)
    zones.append((f"{fid}_corridor", mn, mx, MAT["hall_floor"], RH))
    wbox(f"{fid}_cor_skirt_back", wall, a, b, back - 0.018, back, 0, 0.12, MAT["trim"])
    for k, (p0, p1) in enumerate(((a, u0), (u1, b))):
        if p1 - p0 > 0.05: wbox(f"{fid}_cor_skirt_front{k}", wall, p0, p1, T, T + 0.018, 0, 0.12, MAT["trim"])
    uc = (u0 + u1) / 2
    # the door opposite, offset so it doesn't line up with this one
    opp = uc + 1.7 if b - (uc + 1.7) > 0.8 else uc - 1.7
    opp = max(a + 0.7, min(b - 0.7, opp))
    if not lit:
        return
    if PUBLIC:
        for k, (d0, d1, p0, p1) in enumerate(() if not HOSPITAL else((back - 0.07, back - 0.02, a, b), (T + 0.02, T + 0.07, a, u0 - 0.12), (T + 0.02, T + 0.07, u1 + 0.12, b))):
            if p1 - p0 > 0.1:
                wbox(f"{fid}_handrail{k}", wall, p0, p1, d0, d1, 0.88, 0.94, MAT["handrail"])
                wbox(f"{fid}_wallguard{k}", wall, p0, p1, (d0 + d1) / 2 - 0.01, d1 if d0 > T + 0.1 else d0 + 0.02, 0.2, 0.35, MAT["trim"]) if d0 > T + 0.1 else None
        dw = 1.3                                       # double doors with vision panels on the far wall
        wbox(f"{fid}_opp_frame", wall, opp - dw / 2 - 0.06, opp + dw / 2 + 0.06, back - 0.03, back, 0, 2.11, MAT["trim"])
        for k, (p0, p1) in enumerate(((opp - dw / 2, opp - 0.005), (opp + 0.005, opp + dw / 2))):
            wbox(f"{fid}_opp_leaf{k}", wall, p0, p1, back - 0.06, back - 0.02, 0.01, 2.05, MAT["door"])
            wbox(f"{fid}_opp_vision{k}", wall, p0 + 0.15, p1 - 0.15, back - 0.065, back - 0.055, 1.15, 1.75, MAT["vision"])
            wbox(f"{fid}_opp_kick{k}", wall, p0 + 0.02, p1 - 0.02, back - 0.065, back - 0.055, 0.02, 0.28, MAT["steel"])
        wbox(f"{fid}_opp_sign", wall, opp - 0.35, opp + 0.35, back - 0.02, back, 2.14, min(RH - 0.02, 2.24), MAT["sign_blue"])
        nb = opp - 1.5 if opp - 1.5 > a + 0.6 else opp + 1.5
        if a + 0.5 < nb < b - 0.5:                  # noticeboard
            wbox(f"{fid}_notice", wall, nb - 0.45, nb + 0.45, back - 0.02, back, 1.2, 1.8, MAT["cork"])
            for j, (du, dz) in enumerate(((-0.25, 0.12), (0.05, 0.18), (0.25, -0.05), (-0.1, -0.12))):
                wbox(f"{fid}_notice_paper{j}", wall, nb + du - 0.1, nb + du + 0.1, back - 0.025, back - 0.02, 1.5 + dz - 0.14, 1.5 + dz + 0.14, MAT["paper"])
        gx = uc + (0.9 if b - uc > 1.2 else -0.9)       # hand gel by the door, on the corridor side
        if HOSPITAL: wbox(f"{fid}_gel", wall, gx - 0.06, gx + 0.06, T, T + 0.1, 1.15, 1.37, MAT["paper"])
        # exit sign hanging near one end, panel lights along the middle
        ex = b - 0.6
        wbox(f"{fid}_exit_sign", wall, ex - 0.2, ex + 0.2, T + cw / 2 - 0.01, T + cw / 2 + 0.01, RH - 0.32, RH - 0.17, MAT["sign_green"])
        n = max(1, int((b - a) / 2.4)); step = (b - a) / n
        for k in range(n):
            panel_light(f"{fid}_cor_panel{k}", w2world(wall, a + (k + 0.5) * step, T + cw / 2, 0), along_x=WALLS[wall]["axis"] == "x", energy=40)
    else:
        # home hallway: front door on one end wall, a door to another room opposite, radiator and picture
        wbox(f"{fid}_opp_arch", wall, opp - 0.47, opp + 0.47, back - 0.02, back, 0, 2.07, MAT["trim"])
        wbox(f"{fid}_opp_leaf", wall, opp - 0.41, opp + 0.41, back - 0.045, back - 0.02, 0.01, 2.0, MAT["door"])
        k_ = w2world(wall, opp + 0.32, back - 0.07, 1.0)
        cylinder_obj(f"{fid}_opp_handle", 0.02, 0.06, k_, MAT["steel"], rot=(math.pi / 2, 0, 0) if WALLS[wall]["axis"] == "x" else (0, math.pi / 2, 0))
        rc = uc if abs(uc - opp) > 1.2 else (uc - 1.1 if uc - 1.1 > a + 0.6 else uc + 1.1)
        wbox(f"{fid}_hall_radiator", wall, rc - 0.45, rc + 0.45, back - 0.1, back - 0.04, 0.15, 0.65, MAT["radiator"])
        wbox(f"{fid}_hall_picture", wall, rc - 0.3, rc + 0.3, back - 0.03, back, 1.3, 1.72, MAT["frame_pic"])
        wbox(f"{fid}_hall_picture_in", wall, rc - 0.25, rc + 0.25, back - 0.035, back - 0.03, 1.35, 1.67,
             flat("Hall_picture", (0.45, 0.52, 0.42) if not NEGLECT else (0.4, 0.36, 0.28), 0.6))
        # front door on the end wall further from the room door, with frosted glazing showing daylight
        end_u, inward = (b, -1) if (b - uc) > (uc - a) else (a, 1)
        fd0, fd1 = T + cw / 2 - 0.44, T + cw / 2 + 0.44
        e0, e1 = (end_u - 0.045, end_u) if inward < 0 else (end_u, end_u + 0.045)
        wbox(f"{fid}_front_door", wall, e0, e1, fd0, fd1, 0.01, 2.0, MAT["door"])
        g0_, g1_ = (end_u - 0.05, end_u - 0.045) if inward < 0 else (end_u + 0.045, end_u + 0.05)
        wbox(f"{fid}_front_glass_a", wall, g0_, g1_, fd0 + 0.18, fd1 - 0.18, 1.1, 1.85, MAT["daylight_glass"])
        m0, m1 = (end_u - 0.75, end_u - 0.05) if inward < 0 else (end_u + 0.05, end_u + 0.75)
        wbox(f"{fid}_doormat", wall, m0, m1, fd0, fd1, 0.0, 0.012, MAT["mat"])
        if NEGLECT:
            for j in range(5):                          # unopened post on the mat
                pu = (m0 + m1) / 2 + (j - 2) * 0.09; pd = T + cw / 2 + (j % 2) * 0.1 - 0.05
                wbox(f"{fid}_post{j}", wall, pu - 0.08, pu + 0.08, pd - 0.11, pd + 0.11, 0.012 + j * 0.004, 0.016 + j * 0.004, MAT["paper"])
            bag = place_model("trashbag", w2world(wall, opp + (0.9 if opp + 0.9 < b - 0.3 else -0.9), back - 0.35, 0), 0.4, 1.0)
        n = max(1, int((b - a) / 2.2)); step = (b - a) / n
        for k in range(n):
            lc = w2world(wall, a + (k + 0.5) * step, T + cw / 2, RH - 0.2)
            bpy.ops.object.light_add(type="POINT", location=lc)
            hl = bpy.context.active_object; hl.name = f"{fid}_hall_light{k}"; hl.data.energy = 18 if NEGLECT else 28
            hl.data.color = (1.0, 0.82, 0.6) if NEGLECT else (1.0, 0.88, 0.72); hl.data.shadow_soft_size = 0.08; put(hl)
            bulb = cylinder_obj(f"{fid}_hall_shade{k}", 0.12, 0.1, w2world(wall, a + (k + 0.5) * step, T + cw / 2, RH - 0.28),
                                flat("Hall_shade", (0.85, 0.8, 0.7), 0.6, emit=(1.0, 0.85, 0.65), strength=1.5), verts=24)
            cylinder_obj(f"{fid}_hall_flex{k}", 0.004, 0.23, w2world(wall, a + (k + 0.5) * step, T + cw / 2, RH - 0.115), MAT["steel"], verts=8)

def _quad(name, P, m):
    """A box from its 8 corners P (bottom 4 then top 4, same order), with outward normals."""
    me = bpy.data.meshes.new(name); me.from_pydata([tuple(v) for v in P], [], [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)])
    bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(me); bm.free()
    me.materials.append(m); o = bpy.data.objects.new(name, me); coll("Room").objects.link(o); return o

def open_leaf(fid, wall, u0, u1, h, new_since=None):
    """The door leaf standing open beyond the wall. It opens as far as it can (78 degrees) without passing through
    anything built behind the door (basin, rail, stairs...): if something is in the way it opens less, or hangs on the
    other side instead."""
    O = w2world(wall, 0, 0, 0); eu = (w2world(wall, 1, 0, 0) - O); ed = (w2world(wall, 0, 1, 0) - O)
    eu.z = ed.z = 0; eu.normalize(); ed.normalize()
    w = u1 - u0
    obst = []
    if new_since is not None:
        bpy.context.view_layer.update()
        for o in bpy.data.objects:
            if o.name in new_since or o.type != "MESH": continue
            if any(t in o.name for t in ("room_front", "_skirt_", "tiles_", "_ceiling", "_slab", "_up_")): continue
            cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
            if max(c.z for c in cs) < 0.03 or min(c.z for c in cs) > h: continue
            obst.append((min(c.x for c in cs), min(c.y for c in cs), max(c.x for c in cs), max(c.y for c in cs)))
    def frame(hs, a):
        H = w2world(wall, u1 if hs > 0 else u0, T, 0); r = math.radians(a)
        dirv = (-hs * eu) * math.cos(r) + ed * math.sin(r)              # from the hinge to the free edge
        perp = ed * math.cos(r) + (hs * eu) * math.sin(r)               # across the leaf, towards the wall behind it
        return H, dirv, perp
    def hits(hs, a):
        H, dv, pp = frame(hs, a)
        poly = [H + dv * x + pp * y for x in (0.0, w + 0.03) for y in (-0.07, 0.03)]
        axes = [Vector((1, 0, 0)), Vector((0, 1, 0)), dv, pp]
        n = 0
        for b in obst:
            box = [Vector((b[0], b[1], 0)), Vector((b[2], b[1], 0)), Vector((b[2], b[3], 0)), Vector((b[0], b[3], 0))]
            if all(not (max(p.dot(ax) for p in poly) <= min(q.dot(ax) for q in box) + 1e-4 or
                        max(q.dot(ax) for q in box) <= min(p.dot(ax) for p in poly) + 1e-4) for ax in axes): n += 1
        return n
    choice = None
    for a in (78, 70, 62, 54, 46, 38):
        for hs in (1, -1):
            if hits(hs, a) == 0: choice = (hs, a); break
        if choice: break
    if choice is None:
        choice = min(((hs, a) for a in (38, 30) for hs in (1, -1)), key=lambda c: hits(*c))
        log("door leaf", fid, "still touches something behind it")
    H, dv, pp = frame(*choice); up = Vector((0, 0, 1))
    P = lambda x0, x1, y0, y1, z0, z1: [H + dv * x + pp * y + up * z for z in (z0, z1) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    _quad(f"{fid}_leaf", P(0, w, -0.04, 0, 0, h - 0.01), MAT["door"])
    if HOSPITAL:                                   # vision panel in the leaf
        _quad(f"{fid}_leaf_vision", P(w * 0.38, w * 0.62, -0.045, 0.005, 1.2, 1.75), MAT["vision"])

def door(ft, wall):
    u0, u1 = feature_span(ft); h = float(ft.get("height", 2.0)); fid = ft.get("id", "door")
    beyond = ft.get("beyond", "hall")
    aw = 0.07
    # architrave on the room side
    for nm, (a, b, z0, z1) in {"l": (u0 - aw, u0, 0, h + aw), "r": (u1, u1 + aw, 0, h + aw), "t": (u0, u1, h, h + aw)}.items():
        wbox(f"{fid}_arch_{nm}", wall, a, b, -0.02, 0, z0, z1, MAT["trim"])
    # lining in the reveal
    wbox(f"{fid}_lining_t", wall, u0, u1, 0, T, h - 0.02, h, MAT["trim"])
    if beyond in ("hall", "corridor", "dark", "outside", "room"):
        before = set(bpy.data.objects.keys())
        if beyond == "room":
            side_room(ft, wall, u0, u1, fid)
        elif beyond != "outside":
            corridor(ft, wall, u0, u1, h, fid, lit=beyond != "dark")
        else:
            OPEN_SIDES.add(wbase(wall))
            wbox(f"{fid}_step", wall, u0 - 0.05, u1 + 0.05, T, T + 0.35, -0.12, -0.005, flat("Doorstep_stone", (0.5, 0.5, 0.48), 0.8))
        open_leaf(fid, wall, u0, u1, h, before if beyond == "room" else None)
    elif CUSTODY:                                  # cell door: flush steel, wicket hatch, viewing slot, heavy frame
        fr = flat("Cell_frame", (0.42, 0.45, 0.48), 0.35, 0.5)
        for nm, (a_, b_, z0, z1) in {"l": (u0 - 0.08, u0, 0, h + 0.08), "r": (u1, u1 + 0.08, 0, h + 0.08), "t": (u0, u1, h, h + 0.08)}.items():
            wbox(f"{fid}_frame_{nm}", wall, a_, b_, -0.03, T * 0.5, z0, z1, fr)
        wbox(f"{fid}_leaf", wall, u0, u1, T * 0.2, T * 0.2 + 0.06, 0.0, h, MAT["door"])
        cu = (u0 + u1) / 2
        wbox(f"{fid}_wicket", wall, cu - 0.2, cu + 0.2, T * 0.2 - 0.012, T * 0.2, 0.98, 1.24, fr)
        for k, du in enumerate((-0.14, 0.14)):
            cylinder_obj(f"{fid}_wicket_hinge{k}", 0.014, 0.06, w2world(wall, cu + du, T * 0.2 - 0.014, 0.98), MAT["steel"],
                         rot=(0, math.pi / 2, 0) if WALLS[wall]["axis"] == "x" else (math.pi / 2, 0, 0), verts=12)
        wbox(f"{fid}_slot_frame", wall, cu - 0.08, cu + 0.08, T * 0.2 - 0.012, T * 0.2, 1.42, 1.72, fr)
        wbox(f"{fid}_slot_glass", wall, cu - 0.05, cu + 0.05, T * 0.2 - 0.014, T * 0.2 - 0.012, 1.45, 1.69, flat("Cell_slot_glass", (0.05, 0.06, 0.07), 0.05, coat=1.0))
        wbox(f"{fid}_lock_plate", wall, u1 - 0.2, u1 - 0.06, T * 0.2 - 0.008, T * 0.2, 0.9, 1.2, MAT["steel"])
        wbox(f"{fid}_kick", wall, u0 + 0.02, u1 - 0.02, T * 0.2 - 0.006, T * 0.2, 0.02, 0.3, MAT["steel"])
    else:                                          # closed door in the opening
        c0 = w2world(wall, u0, T * 0.4, 0)
        wbox(f"{fid}_leaf", wall, u0 + 0.003, u1 - 0.003, T * 0.35, T * 0.35 + 0.04, 0.01, h - 0.005, MAT["door"])
        k = w2world(wall, u0 + 0.08, T * 0.35 - 0.03, 1.0)
        cylinder_obj(f"{fid}_handle", 0.02, 0.06, k, MAT["steel"], rot=(math.pi / 2, 0, 0) if WALLS[wall]["axis"] == "x" else (0, math.pi / 2, 0))

ROOM_TYPES = {"room": (3.0, 3.0), "toilet": (1.3, 1.8), "bathroom": (2.4, 2.1), "cupboard": (1.0, 0.8), "conservatory": (3.4, 3.0), "hallway": (2.0, 4.0), "porch": (1.8, 1.4)}
STYLE_SIZES = {("toilet", "accessible"): (1.7, 2.2), ("bathroom", "wetroom"): (2.4, 2.4), ("hallway", "turning"): (2.8, 4.0)}
_side_mats = {}
OPEN_SIDES = set()                                    # real walls whose outside the renders need to see through
def side_mat(key):
    """Materials for the rooms through doors (made once, aged with the room's condition)."""
    if key in _side_mats: return _side_mats[key]
    m = {"ceramic": lambda: flat("WC_ceramic", (0.88, 0.88, 0.86), 0.12, coat=0.6),
         "wc_tiles": lambda: apply_condition(tiles_mat("WC_wall_tiles", {"tile_size": "metro", "colour": "#f0f0ec", "grout": "#c4c4c0"}, wall=True), "wall"),
         "wc_floor": lambda: apply_condition(tiles_mat("WC_floor_tiles", {"tile_size": "sq30", "colour": "#cfccc4", "grout": "#8f8d88"}, wall=False), "floor"),
         "quarry": lambda: apply_condition(tiles_mat("Quarry_tiles", {"tile_size": "sq15", "colour": "#9a5a3c", "grout": "#5e4a3e"}, wall=False), "floor"),
         "mirror": lambda: flat("Mirror", (0.85, 0.86, 0.86), 0.02, 1.0),
         "mat": lambda: flat("Doormat_coir", (0.28, 0.18, 0.09), 0.95),
         "stair": lambda: wood_mat("Stair_wood", {"wood": "oak"}, floor=False),
         "white": lambda: flat("Gloss_white", (0.86, 0.86, 0.84), 0.25, coat=0.3),
         "grey_tiles": lambda: apply_condition(tiles_mat("Wetroom_wall_tiles", {"tile_size": "sq30", "colour": "#d9dbd8", "grout": "#a9aca8"}, wall=True), "wall"),
         "nonslip": lambda: apply_condition(tiles_mat("Nonslip_floor", {"tile_size": "sq15", "colour": "#8d9294", "grout": "#5e6264"}, wall=False), "floor"),
         "red": lambda: flat("Pull_cord_red", (0.75, 0.04, 0.03), 0.5),
         "shower_curtain": lambda: flat("Shower_curtain", (0.82, 0.86, 0.88), 0.7),
         }[key]()
    if DMG > 0.01 and key in ("ceramic", "white", "stair"): m = age_object_mat(m, DMG * 0.8, "model")
    _side_mats[key] = m; return m

def sloped_bar(name, wall, ua, ub, d0, z0, d1, z1, th, m):
    """A bar from (d0, z0) up to (d1, z1) between ua and ub along the wall, th thick (a handrail)."""
    P = lambda u, d, z: w2world(wall, u, d, z)
    vs = [P(ua, d0, z0), P(ub, d0, z0), P(ub, d1, z1), P(ua, d1, z1), P(ua, d0, z0 + th), P(ub, d0, z0 + th), P(ub, d1, z1 + th), P(ua, d1, z1 + th)]
    me = bpy.data.meshes.new(name); me.from_pydata([tuple(v) for v in vs], [], [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)])
    bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(me); bm.free()
    me.materials.append(m); o = bpy.data.objects.new(name, me); coll("Room").objects.link(o); return o

def side_room(ft, wall, u0, u1, fid):
    """What is through a door: a plain room, a toilet, a cupboard, a conservatory, a hallway with stairs, or a porch."""
    rm = ft.get("room") or {}
    kind = rm.get("type", "room"); style = rm.get("style", "")
    dw, dd = STYLE_SIZES.get((kind, style), ROOM_TYPES.get(kind, ROOM_TYPES["room"]))
    rw, rd = max(u1 - u0 + 0.3, float(rm.get("width", dw))), max(0.6, float(rm.get("depth", dd)))
    rp = float(rm.get("pos", (u0 + u1) / 2))
    ru0, ru1 = min(u0 - 0.15, rp - rw / 2), max(u1 + 0.15, rp + rw / 2)
    keep = WALLS[wall].get("keep")                     # a door in an alcove's side wall: never back into the main room
    if keep:
        lim, sg = keep
        if sg > 0: sh = max(0.0, lim - ru0); ru0 += sh; ru1 += sh
        else: sh = max(0.0, ru1 - lim); ru0 -= sh; ru1 -= sh
    back = T + rd
    wm = MAT["wall"]
    bw = lambda nm, a, b, d0, d1, z0, z1, m: wbox(f"{fid}_{nm}", wall, a, b, d0, d1, z0, z1, m)
    glazed = kind in ("conservatory", "porch")
    zd = 0.6 if kind == "conservatory" else 0.95              # dwarf wall height under the glazing
    gtop = RH if kind == "conservatory" else min(RH, 2.1)
    def side_wall(tag, a, b):                                  # a side wall running away from the door (u = a..b thick)
        if not glazed: bw(f"room_{tag}", a, b, T, back + T, 0, RH, wm); return
        bw(f"room_{tag}_dwarf", a, b, T, back + T, 0, zd, wm)
        if gtop < RH: bw(f"room_{tag}_top", a, b, T, back + T, gtop, RH, wm)
        bw(f"room_{tag}_glass", a + (b - a) * 0.45, a + (b - a) * 0.55, T, back, zd, gtop, MAT["glass"])
        n = max(1, round((back - T) / 0.8))
        for k in range(n + 1):
            d = T + (back - T) * k / n
            bw(f"room_{tag}_post{k}", a, b, max(T, d - 0.03), min(back + T, d + 0.03), zd, gtop, MAT["frame"])
        bw(f"room_{tag}_rail", a, b, T, back + T, gtop - 0.05, gtop, MAT["frame"])
    side_wall("a", ru0 - T, ru0); side_wall("b", ru1, ru1 + T)
    for a, b in spans_without(ru0, ru1, [(u0, u1)]):          # the door's wall, seen from inside this room
        bw("room_front", a, b, T, T + 0.02, 0, RH, wm)
    far = virtual_wall(wall, back, f"{wall}@{fid}_far")
    if glazed or kind == "porch" or (rm.get("window") and kind != "cupboard"): OPEN_SIDES.add(wbase(wall))
    if glazed: OPEN_SIDES.update(("east", "west") if wbase(wall) in ("north", "south") else ("north", "south"))   # glass on its sides too
    fw = lambda nm, a, b, z0, z1, m: wbox(f"{fid}_{nm}", far, a, b, 0, T, z0, z1, m)
    cu = (ru0 + ru1) / 2
    # ---- the far wall: window, glazing, or the outside door
    ocu = cu
    s_left_a = wbase(wall) in ("north", "west")              # which side is 'left' as you come in through the door
    if rm.get("stairs", "left") == "right": s_left_a = not s_left_a
    if kind == "hallway":                                     # front door beside the stairs (and past any turn), not behind them
        clear = 0.9 + (3 * 0.25 if style == "turning" and (ru1 - ru0) >= 0.9 + 0.75 + 1.0 else 0.0) + 0.5
        x = min((ru1 - ru0) - 0.5, max((ru1 - ru0) / 2, clear))
        ocu = (ru0 + x) if s_left_a else (ru1 - x)
    if kind == "porch" or kind == "hallway":
        ow, oh = 0.9, 2.05
        c_ = ocu
        for a, b in spans_without(ru0 - T, ru1 + T, [(c_ - ow / 2, c_ + ow / 2)]): fw("room_back", a, b, 0, RH, wm)
        f0, f1 = oh + 0.08, min(RH - 0.05, oh + 0.4)
        if kind == "hallway" and f1 - f0 > 0.12:              # a glass fanlight over the front door, if there is height for it
            fw("room_back_over", c_ - ow / 2, c_ + ow / 2, oh, f0, wm); fw("room_fanlight_over", c_ - ow / 2, c_ + ow / 2, f1, RH, wm)
            wbox(f"{fid}_room_fanlight", far, c_ - ow / 2, c_ + ow / 2, T * 0.45, T * 0.55, f0, f1, MAT["glass"])
        else:
            fw("room_back_over", c_ - ow / 2, c_ + ow / 2, oh, RH, wm)
        door({"id": f"{fid}_outer", "pos": c_, "width": ow, "height": oh, "beyond": "outside" if kind == "porch" else "closed"}, far)
    elif kind == "conservatory":
        fw("room_back_dwarf", ru0 - T, ru1 + T, 0, zd, wm)
        wbox(f"{fid}_room_back_glass", far, ru0, ru1, T * 0.45, T * 0.55, zd, RH, MAT["glass"])
        n = max(1, round((ru1 - ru0) / 0.8))
        for k in range(n + 1):
            u = ru0 + (ru1 - ru0) * k / n; fw(f"room_back_post{k}", u - 0.03, u + 0.03, zd, RH, MAT["frame"])
    elif rm.get("window") and kind != "cupboard":
        small = kind in ("toilet", "bathroom")
        ww = 0.6 if small else min(1.6, rw - 0.8); sill = 1.35 if small else 0.85; wh = 0.6 if small else 1.25
        for a, b in spans_without(ru0 - T, ru1 + T, [(cu - ww / 2, cu + ww / 2)]): fw("room_back", a, b, 0, RH, wm)
        fw("room_back_under", cu - ww / 2, cu + ww / 2, 0, sill, wm); fw("room_back_over", cu - ww / 2, cu + ww / 2, sill + wh, RH, wm)
        window({"id": f"{fid}_room_window", "pos": cu, "width": ww, "sill": sill, "height": wh,
                "dressing": "frosted" if small else rm.get("dressing", "curtains")}, far)
    else:
        fw("room_back", ru0 - T, ru1 + T, 0, RH, wm)
    # ---- floor, ceiling (a conservatory has a glass roof instead), skirting
    floor_m = {"toilet": side_mat("nonslip" if style == "accessible" else "wc_floor"), "bathroom": side_mat("nonslip" if style == "wetroom" else "wc_floor"),
               "conservatory": side_mat("quarry"), "porch": side_mat("quarry")}.get(kind, MAT["floor"])
    mn, mx = wbox_world(wall, ru0, ru1, T / 2, back, 0, 0)
    zones.append((f"{fid}_room", mn, mx, floor_m, None if kind in ("conservatory", "hallway") else RH))   # the hall builds its own (with the stairwell)
    if kind == "conservatory":
        bw("room_roof_glass", ru0 - T, ru1 + T, T, back + T, RH - 0.01, RH, MAT["glass"])
        n = max(1, round((ru1 - ru0) / 0.8))
        for k in range(n + 1):
            u = ru0 + (ru1 - ru0) * k / n; bw(f"room_roof_bar{k}", u - 0.03, u + 0.03, T, back + T, RH - 0.06, RH, MAT["frame"])
    if not glazed:
        for nm, (a, b, d0, d1) in {"back": (ru0, ru1, back - 0.018, back), "a": (ru0, ru0 + 0.018, T, back), "b": (ru1 - 0.018, ru1, T, back)}.items():
            bw(f"room_skirt_{nm}", a, b, d0, d1, 0, 0.12, MAT["trim"])
    # ---- what is in it
    rot_in = facing(wall)                                        # a model against the far wall, facing back towards the door
    def model(mid, u, d, z=0.0, scale=1.0, turn=0.0):
        try: age_model(place_model(mid, w2world(wall, u, d, z), rot_in + turn, scale), DMG * 0.8)
        except Exception as e: log("side room model failed", mid, e)
    S_ = MAT["steel"]
    def tiles(m, H, back_h=None):                                # tiled walls (higher round a bath or shower)
        bw("tiles_back", ru0, ru1, back - 0.008, back, 0, back_h or H, m)
        bw("tiles_a", ru0, ru0 + 0.008, T, back, 0, H, m); bw("tiles_b", ru1 - 0.008, ru1, T, back, 0, H, m)
    def wc_back(nm, u, seat_z=0.42):                            # a toilet against the far wall, centred at u
        c, w_ = side_mat("ceramic"), side_mat("white")
        bw(f"{nm}_cistern", u - 0.19, u + 0.19, back - 0.19, back - 0.008, seat_z, seat_z + 0.38, c)
        bw(f"{nm}_pan", u - 0.17, u + 0.17, back - 0.68, back - 0.19, 0.0, seat_z - 0.03, c)
        bw(f"{nm}_seat", u - 0.19, u + 0.19, back - 0.72, back - 0.17, seat_z - 0.03, seat_z, w_)
        bw(f"{nm}_flush", u - 0.03, u + 0.03, back - 0.2, back - 0.185, seat_z + 0.3, seat_z + 0.34, S_)
    def wc_side(nm, d, at_b=True, seat_z=0.42):                 # a toilet against a side wall, centred at depth d
        c, w_ = side_mat("ceramic"), side_mat("white")
        e = ru1 - 0.008 if at_b else ru0 + 0.008; sg = -1 if at_b else 1
        U = lambda x0, x1: (min(e + sg * x0, e + sg * x1), max(e + sg * x0, e + sg * x1))
        bw(f"{nm}_cistern", *U(0, 0.18), d - 0.19, d + 0.19, seat_z, seat_z + 0.38, c)
        bw(f"{nm}_pan", *U(0.18, 0.68), d - 0.17, d + 0.17, 0.0, seat_z - 0.03, c)
        bw(f"{nm}_seat", *U(0.16, 0.72), d - 0.19, d + 0.19, seat_z - 0.03, seat_z, w_)
    def basin_side(nm, d, at_b=True, z=0.82, mirror=True):      # a wall-hung basin on a side wall
        c = side_mat("ceramic"); e = ru1 - 0.008 if at_b else ru0 + 0.008; sg = -1 if at_b else 1
        U = lambda x0, x1: (min(e + sg * x0, e + sg * x1), max(e + sg * x0, e + sg * x1))
        bw(f"{nm}_basin", *U(0, 0.42), d - 0.25, d + 0.25, z, z + 0.08, c)
        bw(f"{nm}_tap", *U(0.02, 0.07), d - 0.02, d + 0.02, z + 0.08, z + 0.22, S_)
        if mirror: bw(f"{nm}_mirror", *U(0, 0.01), d - 0.25, d + 0.25, z + 0.4, z + 1.0, side_mat("mirror"))
    def rail_x(nm, at_b, d0, d1, z, off=0.04):                  # a grab rail along a side wall
        e = ru1 - off if at_b else ru0 + off
        bw(nm, min(e, e + (-0.035 if at_b else 0.035)), max(e, e + (-0.035 if at_b else 0.035)), d0, d1, z, z + 0.035, S_)
    def rail_v(nm, at_b, d, z0, z1, off=0.04):                  # a vertical grab rail on a side wall
        e = ru1 - off if at_b else ru0 + off
        bw(nm, min(e, e + (-0.035 if at_b else 0.035)), max(e, e + (-0.035 if at_b else 0.035)), d - 0.018, d + 0.018, z0, z1, S_)
    def pull_cord(nm, u, d):                                    # red emergency pull cord from the ceiling to near the floor
        r = side_mat("red")
        bw(f"{nm}_cord", u - 0.003, u + 0.003, d - 0.003, d + 0.003, 0.1, RH, r)
        for k, z in enumerate((0.1, 0.85)): bw(f"{nm}_bangle{k}", u - 0.035, u + 0.035, d - 0.008, d + 0.008, z, z + 0.06, r)
        bw(f"{nm}_box", u - 0.05, u + 0.05, d - 0.05, d + 0.05, RH - 0.03, RH, side_mat("white"))
    if kind == "toilet" and style == "accessible":
        # an accessible WC: toilet near one side wall, grab rails, drop-down rail, raised seat, basin in reach, pull cord
        tiles(side_mat("wc_tiles"), 1.2)
        tu = ru0 + 0.5
        wc_back("awc", tu, seat_z=0.48)
        rail_x("awc_rail_h", False, back - 0.8, back - 0.15, 0.68)
        rail_v("awc_rail_v", False, back - 0.85, 0.8, 1.4)
        bw("awc_dropdown", tu + 0.3, tu + 0.335, back - 0.78, back - 0.008, 0.68, 0.715, S_)            # hinged rail on the open side
        bw("awc_dropdown_plate", tu + 0.28, tu + 0.355, back - 0.05, back - 0.008, 0.62, 0.78, S_)
        basin_side("awc", back - 1.0, at_b=False, z=0.72)
        pull_cord("awc", tu + 0.55, back - 0.9)
        bw("awc_roll", ru0 + 0.008, ru0 + 0.12, back - 0.55, back - 0.45, 0.7, 0.82, side_mat("white"))
    elif kind == "bathroom" and style == "wetroom":
        # an accessible wet room: level shower with a fold-down seat and rails, curtain, toilet with rails, basin
        tiles(side_mat("grey_tiles"), RH - 0.02)
        bw("wr_drain", ru0 + 0.55, ru0 + 0.75, back - 0.75, back - 0.55, 0.0, 0.004, MAT["dark"])
        bw("wr_riser", ru0 + 0.58, ru0 + 0.6, back - 0.04, back - 0.008, 1.0, 2.0, S_)
        bw("wr_head", ru0 + 0.53, ru0 + 0.65, back - 0.16, back - 0.04, 1.95, 2.0, S_)
        bw("wr_controls", ru0 + 0.75, ru0 + 0.95, back - 0.06, back - 0.008, 1.0, 1.12, S_)
        bw("wr_seat", ru0 + 0.008, ru0 + 0.42, back - 0.95, back - 0.5, 0.47, 0.5, side_mat("white"))      # fold-down seat, down
        bw("wr_seat_bracket", ru0 + 0.008, ru0 + 0.05, back - 0.95, back - 0.5, 0.3, 0.47, S_)
        rail_x("wr_rail_h", False, back - 1.3, back - 1.0, 0.85); rail_v("wr_rail_v", False, back - 0.4, 0.8, 1.5)
        bw("wr_rail_back", ru0 + 0.9, ru0 + 1.5, back - 0.045, back - 0.008, 0.85, 0.885, S_)
        cd = back - 1.35                                      # curtain on a rail across the shower area, pulled back
        bw("wr_curtain_rail", ru0, ru0 + 1.25, cd - 0.012, cd + 0.012, 2.0, 2.02, S_)
        curtain(f"{fid}_wr_curtain", wall, ru0 + 0.02, ru0 + 0.45, cd, 0.12, 2.0, folds=5, m=side_mat("shower_curtain"), amp=0.04)
        if rw >= 2.0:
            wc_side("wr_wc", T + 0.55, at_b=True, seat_z=0.48)
            rail_x("wr_wc_rail", True, T + 0.75, T + 1.35, 0.68)
            bw("wr_wc_drop", ru1 - 0.75, ru1 - 0.008, T + 0.22, T + 0.255, 0.68, 0.715, S_)
            basin_side("wr", T + 1.55, at_b=True, z=0.75)
        pull_cord("wr", ru1 - 0.9, back - 0.6)
    elif kind == "bathroom":
        # a family bathroom: bath with a shower over it and a glass screen, basin, toilet, towel radiator
        tiles(side_mat("wc_tiles"), 1.2, back_h=2.0)
        bl = min(1.7, rw - 0.05); w_ = side_mat("white"); c = side_mat("ceramic")
        b0, b1, bd = ru0, ru0 + bl, back - 0.72
        bw("bath_panel", b0, b1, bd, bd + 0.03, 0, 0.55, w_)
        for nm, (a, b, d0, d1) in {"f": (b0, b1, bd, bd + 0.06), "k": (b0, b1, back - 0.06, back), "l": (b0, b0 + 0.08, bd, back), "r": (b1 - 0.08, b1, bd, back)}.items():
            bw(f"bath_side_{nm}", a, b, d0, d1, 0.0, 0.56, c)
        bw("bath_bottom", b0 + 0.08, b1 - 0.08, bd + 0.06, back - 0.06, 0.0, 0.14, c)
        bw("bath_taps", b0 + 0.1, b0 + 0.3, back - 0.06, back - 0.008, 0.62, 0.68, S_)
        bw("bath_riser", b0 + 0.18, b0 + 0.2, back - 0.04, back - 0.008, 0.9, 1.95, S_)
        bw("bath_head", b0 + 0.13, b0 + 0.25, back - 0.16, back - 0.04, 1.9, 1.95, S_)
        bw("bath_screen", b0, b0 + 0.8, bd + 0.02, bd + 0.03, 0.56, 2.0, MAT["glass"])
        bw("bath_screen_edge", b0 + 0.78, b0 + 0.8, bd + 0.015, bd + 0.035, 0.56, 2.0, S_)
        wc_side("bath_wc", back - 1.15, at_b=True)
        basin_side("bath", T + 0.45, at_b=False)
        # chrome towel radiator on the door wall, beside the doorway (never across it), on whichever side has room
        sides = [(u1 + 0.15, ru1 - 0.1), (ru0 + 0.1, u0 - 0.15)]
        ta, tb = max(sides, key=lambda p: p[1] - p[0])
        if tb - ta >= 0.35:
            tw = min(0.5, tb - ta); ta = (ta + tb) / 2 - tw / 2; tb = ta + tw
            for k in range(6):
                bw(f"bath_towel_bar{k}", ta, tb, T + 0.02, T + 0.045, 0.4 + k * 0.2, 0.425 + k * 0.2, S_)
            for k, x in enumerate((ta, tb - 0.025)):
                bw(f"bath_towel_post{k}", x, x + 0.025, T + 0.02, T + 0.05, 0.3, 1.5, S_)
    elif kind == "toilet":
        tm = side_mat("wc_tiles"); H = 1.2
        bw("wc_tiles_back", ru0, ru1, back - 0.008, back, 0, H, tm)
        bw("wc_tiles_a", ru0, ru0 + 0.008, T, back, 0, H, tm); bw("wc_tiles_b", ru1 - 0.008, ru1, T, back, 0, H, tm)
        c, w_ = side_mat("ceramic"), side_mat("white")
        bw("wc_cistern", cu - 0.19, cu + 0.19, back - 0.19, back - 0.008, 0.42, 0.8, c)
        bw("wc_pan", cu - 0.17, cu + 0.17, back - 0.66, back - 0.19, 0.0, 0.39, c)
        bw("wc_seat", cu - 0.19, cu + 0.19, back - 0.7, back - 0.17, 0.39, 0.42, w_)
        bw("wc_flush", cu - 0.03, cu + 0.03, back - 0.2, back - 0.185, 0.72, 0.76, MAT["steel"])
        if rw >= 1.1:                                            # basin on the side wall
            bu = ru1 - 0.008
            bw("wc_basin", bu - 0.4, bu, T + 0.25, T + 0.72, 0.8, 0.88, c)
            bw("wc_pedestal", bu - 0.26, bu - 0.12, T + 0.41, T + 0.56, 0.0, 0.8, c)
            bw("wc_tap", bu - 0.06, bu - 0.02, T + 0.47, T + 0.5, 0.88, 1.02, MAT["steel"])
            bw("wc_mirror", bu - 0.01, bu, T + 0.27, T + 0.7, 1.25, 1.75, side_mat("mirror"))
        bw("wc_roll", ru0 + 0.008, ru0 + 0.12, back - 0.55, back - 0.45, 0.62, 0.74, w_)
    elif kind == "cupboard":
        for k, z in enumerate((0.9, 1.3, 1.7)):
            bw(f"cup_shelf{k}", ru0, ru1, back - 0.38, back, z, z + 0.022, MAT["shelf"])
        model("cardboard_box_01", ru0 + 0.25, back - 0.25, 0.0, 0.8)
        model("cardboard_box_01", cu + 0.1, back - 0.2, 1.3 + 0.022, 0.55, 0.4)
        model("wicker_basket_01", cu - 0.15, back - 0.2, 0.9 + 0.022, 0.8)
        model("wooden_broom", ru1 - 0.12, back - 0.12, 0.0, 1.0)
        bw("cup_hooks", ru0 + 0.004, ru0 + 0.03, T + 0.15, back - 0.45, 1.6, 1.64, MAT["shelf"])
    elif kind == "conservatory":
        model("outdoor_table_chair_set_01", cu, T + rd * 0.55, 0.0, 1.0)
        model("potted_plant_02", ru0 + 0.35, back - 0.35, 0.0, 1.0)
        model("potted_plant_04", ru1 - 0.35, back - 0.35, 0.0, 1.0)
        model("potted_plant_01", ru1 - 0.35, T + 0.4, 0.0, 1.0)
    elif kind == "hallway":
        # stairs up one side (left or right as you come in), straight or turning at the top, through an opening in the
        # ceiling to a landing, so you can see there is an upstairs. Worked out across the hall in x (0 = the stairs' wall).
        st = side_mat("stair"); Wd = ru1 - ru0
        Ux = lambda x: (ru0 + x) if s_left_a else (ru1 - x)
        def bx(nm, x0, x1, d0, d1, z0, z1, m):
            a_, b_ = sorted((Ux(x0), Ux(x1))); bw(nm, a_, b_, d0, d1, z0, z1, m)
        SW = 0.9; FL2, H2 = RH + 0.25, 2.4
        n = max(1, round(FL2 / 0.19)); rise, going = FL2 / n, 0.25
        d_start = T + 0.5
        turn = style == "turning" and Wd >= SW + 3 * going + 1.0
        n2 = 3 if turn else 0
        room_d = back - d_start - (SW if turn else 0.0)            # depth available for the first flight
        n1 = max(1, min(n - n2, int(room_d // going)))
        for k in range(n1):
            bx(f"hall_step{k}", 0, SW, d_start + k * going, back, k * rise, (k + 1) * rise, st)
        d_end1 = d_start + n1 * going
        top = n1 * rise
        if turn:                                                    # quarter landing in the far corner, then 3 steps along the far wall
            bx("hall_quarter_landing", 0, SW, back - SW, back, 0, top, st)
            for k in range(n2):
                bx(f"hall_turn_step{k}", SW + k * going, SW + (k + 1) * going, back - SW, back, 0, top + (k + 1) * rise, st)
            top += n2 * rise
        full = top >= FL2 - 0.01
        dh0 = d_start + going
        holes = [(0, SW, dh0, back)] + ([(SW, SW + n2 * going, back - SW, back)] if turn else [])
        # ceiling and floor slab round the stairwell (a grid of pieces, skipping the opening)
        xs = sorted({0.0, Wd, *[h[0] for h in holes], *[h[1] for h in holes]}) if full else [0.0, Wd]
        ds = sorted({T, back, *[h[2] for h in holes], *[h[3] for h in holes]}) if full else [T, back]
        k = 0
        for xi in range(len(xs) - 1):
            for di in range(len(ds) - 1):
                x0, x1, d0, d1 = xs[xi], xs[xi + 1], ds[di], ds[di + 1]
                if x1 - x0 < 0.01 or d1 - d0 < 0.01: continue
                if full and any(h[0] <= x0 + 1e-6 and x1 <= h[1] + 1e-6 and h[2] <= d0 + 1e-6 and d1 <= h[3] + 1e-6 for h in holes): continue
                bx(f"hall_ceiling{k}", x0, x1, d0, d1, RH - 0.005, RH + 0.005, MAT["ceiling"])
                bx(f"hall_slab{k}", x0, x1, d0, d1, RH + 0.005, FL2, MAT["floor"]); k += 1
        if full:
            UP = FL2 + H2
            bw("hall_up_a", ru0 - T, ru0, T, back + T, RH, UP, wm); bw("hall_up_b", ru1, ru1 + T, T, back + T, RH, UP, wm)
            bw("hall_up_front", ru0 - T, ru1 + T, 0, T, RH, UP, wm)
            wbox(f"{fid}_hall_up_back", far, ru0 - T, ru1 + T, 0, T, RH, UP, wm)
            bw("hall_up_ceiling", ru0, ru1, T, back, UP, UP + 0.02, MAT["ceiling"])
            for nm, (u0_, u1_) in {"a": (ru0, ru0 + 0.018), "b": (ru1 - 0.018, ru1)}.items():
                bw(f"hall_up_skirt_{nm}", u0_, u1_, T, back, FL2, FL2 + 0.12, MAT["trim"])
            # banisters round the opening on the landing (the arrival at the top is left open)
            edges = [("x", SW, dh0, back - SW if turn else back), ("d", dh0, 0, SW)] + ([("d", back - SW, SW, SW + n2 * going)] if turn else [])
            for e, (ax, c_, p0, p1) in enumerate(edges):
                if p1 - p0 < 0.05: continue
                if ax == "x":
                    bx(f"land_rail{e}", c_, c_ + 0.05, p0, p1, FL2 + 0.88, FL2 + 0.93, st)
                    q = p0 + 0.06
                    while q < p1 - 0.03: bx(f"land_sp{e}_{int(q * 100)}", c_ + 0.01, c_ + 0.04, q, q + 0.03, FL2, FL2 + 0.88, MAT["trim"]); q += 0.13
                else:
                    bx(f"land_rail{e}", p0, p1, c_ - 0.05, c_, FL2 + 0.88, FL2 + 0.93, st)
                    q = p0 + 0.06
                    while q < p1 - 0.03: bx(f"land_sp{e}_{int(q * 100)}", q, q + 0.03, c_ - 0.04, c_ - 0.01, FL2, FL2 + 0.88, MAT["trim"]); q += 0.13
            bx("land_post", SW - 0.02, SW + 0.07, dh0 - 0.07, dh0 + 0.02, FL2 - 0.3, FL2 + 1.05, st)
            if Wd - SW > 0.9:                                         # a bedroom door upstairs, on the other side wall
                dm = (dh0 + (back - SW if turn else back)) / 2
                bx("land_door", Wd - 0.045, Wd - 0.005, dm - 0.41, dm + 0.41, FL2, FL2 + 1.98, MAT["door"])
                for nm, (d0_, d1_, z0_, z1_) in {"l": (dm - 0.48, dm - 0.41, FL2, FL2 + 2.05), "r": (dm + 0.41, dm + 0.48, FL2, FL2 + 2.05), "t": (dm - 0.41, dm + 0.41, FL2 + 1.98, FL2 + 2.05)}.items():
                    bx(f"land_door_arch_{nm}", Wd - 0.02, Wd, d0_, d1_, z0_, z1_, MAT["trim"])
            lc2 = w2world(wall, Ux((SW + Wd) / 2), (dh0 + back) / 2, UP - 0.04)
            bpy.ops.object.light_add(type="AREA", location=lc2)
            l2 = bpy.context.active_object; l2.name = f"{fid}_landing_light"; l2.data.shape = "DISK"; l2.data.size = 0.4
            l2.data.energy = 55; l2.data.color = (1.0, 0.9, 0.75); put(l2)
        # handrails following the pitch of each flight, on a newel post at the bottom
        def rail(nm, P0, P1):
            Pw = [w2world(wall, Ux(x), d, z) for x, d, z in (P0, P1)]
            v = (Pw[1] - Pw[0]); hz = Vector((v.x, v.y, 0)).normalized(); side = Vector((-hz.y, hz.x, 0)) * 0.0225; up = Vector((0, 0, 0.05))
            vs = [Pw[0] - side, Pw[0] + side, Pw[1] + side, Pw[1] - side]; vs += [p + up for p in vs]
            me = bpy.data.meshes.new(nm); me.from_pydata([tuple(p) for p in vs], [], [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)])
            bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(me); bm.free()
            me.materials.append(st); o = bpy.data.objects.new(nm, me); coll("Room").objects.link(o)
        if n1 > 1: rail(f"{fid}_hall_rail1", (SW - 0.02, d_start, rise + 0.85), (SW - 0.02, d_start + (n1 - 1) * going, n1 * rise + 0.85))
        if turn: rail(f"{fid}_hall_rail2", (SW, back - SW + 0.02, n1 * rise + 0.85), (SW + (n2 - 1) * going, back - SW + 0.02, (n1 + n2) * rise + 0.85))
        bx("hall_newel", SW - 0.07, SW + 0.02, d_start - 0.05, d_start + 0.05, 0, rise + 0.95, st)
        bx("hall_radiator", Wd - 0.1, Wd - 0.03, T + 0.4, T + 1.4, 0.15, 0.7, MAT["radiator"])
        bx("hall_hooks", Wd - 0.03, Wd - 0.008, T + 1.6, T + 2.4, 1.62, 1.68, side_mat("stair"))
        bw("hall_mat", ocu - 0.35, ocu + 0.35, back - 0.55, back - 0.05, 0.0, 0.012, side_mat("mat"))
    elif kind == "porch":
        bw("porch_mat", cu - 0.35, cu + 0.35, back - 0.6, back - 0.1, 0.0, 0.012, side_mat("mat"))
        bw("porch_hooks", ru0 + 0.008, ru0 + 0.035, T + 0.2, back - 0.2, 1.7, 1.75, side_mat("stair")) if not glazed else None
        model("potted_plant_01", ru1 - 0.25, back - 0.25, 0.0, 0.8)
    # ---- light (a conservatory is lit by the sky through its roof)
    lit = rm.get("lit", kind != "cupboard")
    if kind != "conservatory" or LIGHTING == "night":
        lc = w2world(wall, cu, T + rd / 2, RH - 0.04)
        bpy.ops.object.light_add(type="AREA", location=lc)
        l = bpy.context.active_object; l.name = f"{fid}_room_light"; l.data.shape = "DISK"; l.data.size = 0.4
        l.data.energy = (70 * max(0.5, rw * rd / 9) if lit else (8 if kind == "cupboard" else 0)); l.data.color = (1.0, 0.92, 0.8); put(l)

def arch(ft, wall):
    u0, u1 = feature_span(ft)
    room = ft.get("room", {"type": "recess", "depth": 1.0})
    depth = float(room.get("depth", 2.0))
    rpos = float(room.get("pos", ft["pos"])); rw = float(room.get("width", float(ft["width"]) + 1.0))
    lo, hi = WALLS[wall]["lo"], WALLS[wall]["hi"]
    ru0, ru1 = max(lo - T, min(u0, rpos - rw / 2)), min(hi + T, max(u1, rpos + rw / 2))
    back = T + depth
    name = ft.get("id", "arch")
    wbox(f"{name}_room_back", wall, ru0 - T, ru1 + T, back, back + T, 0, RH, MAT["wall"])
    wbox(f"{name}_room_a", wall, ru0 - T, ru0, T, back + T, 0, RH, MAT["wall"])
    wbox(f"{name}_room_b", wall, ru1, ru1 + T, T, back + T, 0, RH, MAT["wall"])
    kitchen = room.get("type") == "kitchen"
    mn, mx = wbox_world(wall, ru0, ru1, T / 2, back, 0, 0)
    zones.append((f"{name}_room", mn, mx, MAT["k_floor"] if kitchen else MAT["floor"], RH))
    if kitchen:
        kitchen_run(wall, ru0, ru1, back, f"{name}_kitchen", tall_end=room.get("fridge", "hi"))
    else:
        wbox(f"{name}_room_skirt", wall, ru0, ru1, back - 0.018, back, 0, 0.12, MAT["trim"])
    lc = w2world(wall, (ru0 + ru1) / 2, T + depth / 2, RH - 0.04)
    bpy.ops.object.light_add(type="AREA", location=lc)
    l = bpy.context.active_object; l.name = f"{name}_room_light"; l.data.shape = "DISK"; l.data.size = 0.4
    l.data.energy = 60 if not NEGLECT else 70; l.data.color = (1.0, 0.95, 0.85) if not NEGLECT else (1.0, 0.85, 0.6); put(l)
    # the arch's reveal gets a trim edge on the room side
    wbox(f"{name}_skirt_l", wall, ru0, u0, T - 0.018, T, 0, 0.12, MAT["trim"]) if u0 - ru0 > 0.05 else None
    wbox(f"{name}_skirt_r", wall, u1, ru1, T - 0.018, T, 0, 0.12, MAT["trim"]) if ru1 - u1 > 0.05 else None

# models first: windows use the catalogue's shrubs
USED = set()
def find_model_file(mid):
    d = os.path.join(CAT, mid)
    meta_p = os.path.join(d, "model.json")
    if os.path.exists(meta_p):
        with open(meta_p, encoding="utf-8") as fh: meta = json.load(fh)
        p = os.path.join(d, meta.get("file", ""))
        if os.path.exists(p): return p, meta
    for ext in (".gltf", ".glb"):
        for root_, _, files in os.walk(d):
            for fn in files:
                if fn.lower().endswith(ext): return os.path.join(root_, fn), {}
    return None, {}

_model_cache = {}
def place_model(mid, loc, rot_z, scale, cname="Items", record=True, z=None):
    """Import a catalogue glTF, scale it, centre its footprint on loc and stand it on z."""
    path, meta = find_model_file(mid)
    if not path:
        log("missing model", mid); return None
    if record: USED.add(mid)
    if mid in _model_cache:                         # linked duplicate of an earlier import (fast, light)
        src_root, src_objs = _model_cache[mid]
        root = bpy.data.objects.new(f"M_{mid}", None); coll(cname).objects.link(root)
        mapping = {}
        for o in src_objs:
            c = o.copy(); coll(cname).objects.link(c); mapping[o] = c
        for o, c in mapping.items():
            c.parent = mapping.get(o.parent, root)
            if o.parent not in mapping: c.matrix_parent_inverse = Matrix.Identity(4); c.matrix_basis = o.matrix_basis.copy()
        new = list(mapping.values())
    else:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        new = [o for o in bpy.data.objects if o not in before]
        root = bpy.data.objects.new(f"M_{mid}", None); coll(cname).objects.link(root)
        for o in new:
            for c in list(o.users_collection): c.objects.unlink(o)
            coll(cname).objects.link(o)
            if o.parent is None: o.parent = root
        _model_cache[mid] = (root, new)
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in new if o.type == "MESH" for c in o.bound_box]
    if not pts: return root
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (mn + mx) / 2
    s = float(scale) * float(meta.get("scale", 1.0))
    zz = loc.z if z is None else z
    root.matrix_world = (Matrix.Translation((loc.x, loc.y, zz)) @ Matrix.Rotation(rot_z, 4, "Z") @ Matrix.Scale(s, 4)
                         @ Matrix.Translation((-ctr.x, -ctr.y, -mn.z)) @ root.matrix_world)
    return root

for ft in FEATURES:
    wall = ft.get("wall"); typ = ft.get("type")
    if wall not in WALLS: continue
    try:
        if typ == "alcove":
            depth = float(ft.get("depth", 0.6)); h = min(float(ft.get("height", RH)), RH)
            recess(ft, wall, depth, h, ft.get("id", "alcove"))
            if ft.get("shelves"): shelves(ft, wall, depth, int(ft["shelves"]))
            for k, dd in enumerate(ft.get("doors") or []):       # doors in the alcove's back or side walls, to a corridor or another room
                aid = ft.get("id", "alcove"); sd = door_side(wall, dd)
                if sd == "back":
                    vw = virtual_wall(wall, depth, f"{wall}@{aid}")
                    a0, a1 = feature_span(ft); WALLS[vw].update(lo=max(WALLS[wall]["lo"], a0 - 1.2), hi=min(WALLS[wall]["hi"], a1 + 1.2))
                    dd2 = dict(dd)
                else:
                    vw = side_frame(wall, ft, sd, depth, f"{wall}@{aid}_{sd}")
                    f_ = WALLS[wall]; dd2 = dict(dd, pos=f_["line"] + f_["sign"] * float(dd["pos"]))   # distance in -> a world coordinate
                door(dict(dd2, id=f"{aid}_door{k}", type="door", wall=vw), vw)
                d0_, d1_ = feature_span(dd2); mn, mx = wbox_world(vw, d0_, d1_, -0.01, T / 2 + 0.01, 0, 0)   # floor through the doorway
                zones.append((f"{aid}_door{k}_sill", mn, mx, MAT["floor"], min(float(dd.get("height", 2.0)), RH)))
        elif typ == "kitchenette":
            depth = float(ft.get("depth", 0.65))
            u0, u1 = recess(ft, wall, depth, RH, ft.get("id", "kitchenette"), floor_m=MAT["k_floor"], lower=False)
            kitchen_run(wall, u0, u1, depth, ft.get("id", "kitchenette"))
        elif typ == "window": window(ft, wall)
        elif typ == "door": door(ft, wall)
        elif typ == "arch": arch(ft, wall)
    except Exception as e:
        import traceback; traceback.print_exc(); log("feature failed", ft.get("id"), typ, e)

# floors and ceilings per zone
for name, mn, mx, fm, ch in zones:
    plane(f"Floor_{name}", mn.x, mn.y, mx.x, mx.y, 0.0, fm)
    if ch: plane(f"Ceiling_{name}", mn.x, mn.y, mx.x, mx.y, ch, MAT["ceiling"], flip=True)      # none under a glass roof
# a lowered alcove gets the underside of its header
for ft in FEATURES:
    if ft.get("type") == "alcove" and float(ft.get("height", RH)) < RH - 0.01 and ft.get("wall") in WALLS:
        u0, u1 = feature_span(ft); h = float(ft["height"])
        wbox(f"{ft.get('id', 'alcove')}_header_soffit", ft["wall"], u0, u1, 0, float(ft.get("depth", 0.6)), h - 0.01, h, MAT["ceiling"])

# a black shell round everything so no daylight leaks through gaps (open where windows look out)
G = 3.0
win_walls = {ft["wall"] for ft in FEATURES if ft.get("wall") in WALLS and (ft.get("type") == "window" or (ft.get("type") == "door" and ft.get("beyond") == "outside")
                                                                 or (ft.get("type") == "door" and ft.get("beyond") == "room" and (ft.get("room") or {}).get("window")))}
win_walls |= OPEN_SIDES                              # rooms through doors that look outside (windows, glazing, porches)
shell_m = flat("Shell_black", (0, 0, 0), 1.0)
ext = 9.0
sides = {"west": (X0 - ext - 0.3, Y0 - ext, X0 - ext, Y1 + ext), "east": (X1 + ext, Y0 - ext, X1 + ext + 0.3, Y1 + ext),
         "south": (X0 - ext, Y0 - ext - 0.3, X1 + ext, Y0 - ext), "north": (X0 - ext, Y1 + ext, X1 + ext, Y1 + ext + 0.3)}
for k, (a, b, c, d) in ({} if OUTDOOR else sides).items():
    if k in win_walls: continue
    box_obj(f"Shell_{k}", Vector((a, b, -1.0)), Vector((c, d, RH + 4)), shell_m, "_shell")

if OUTDOOR:                                         # an invisible ground that only picks up the models' shadows
    gnd = plane("Ground_shadow_catcher", -30, -30, 30, 30, 0.0, flat("Ground_catcher", (0.3, 0.3, 0.3), 0.9))
    try: gnd.is_shadow_catcher = True
    except Exception: log("no shadow catcher in this Blender")

# ============================================================== decals
# Drawings, graffiti, posters, stains: an image card just in front of a wall, an alcove's back wall or the floor.
# spec.decals: [{decal, surface: north|east|south|west|floor|alcove:<id>, u, z (walls) or x, y (floor), width, rot, opacity}]
DECAL_DIR = os.path.join(ROOT, "catalogue", "decals")
DECAL_CAT = {d["id"]: d for d in _load(os.path.join(DECAL_DIR, "decals.json"), {"decals": []}).get("decals", [])}
USED_DECALS = []

def decal_material(meta, opacity):
    key = f"Decal_{meta['id']}_{round(opacity, 2)}"
    if key in bpy.data.materials: return bpy.data.materials[key]
    m, nt, b = principled(key)
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(os.path.join(DECAL_DIR, meta["file"]), check_existing=True)
    t.extension = "CLIP"
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    a = _math(nt, "MULTIPLY", t.outputs["Alpha"], float(opacity)); nt.links.new(a, b.inputs["Alpha"])
    b.inputs["Roughness"].default_value = 0.45 if meta.get("category") in ("poster", "sign") else 0.8
    for attr, val in (("blend_method", "HASHED"), ("surface_render_method", "DITHERED")):
        try: setattr(m, attr, val)
        except Exception: pass
    return m

def decal_quad(name, centre, right, up, w, h, rot, mat):
    """A w x h card centred on 'centre', its image right along 'right' and up along 'up', turned by rot degrees."""
    c, sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    r = right * c + up * sn; u = up * c - right * sn
    corners = [centre - r * (w / 2) - u * (h / 2), centre + r * (w / 2) - u * (h / 2), centre + r * (w / 2) + u * (h / 2), centre - r * (w / 2) + u * (h / 2)]
    me = bpy.data.meshes.new(name); me.from_pydata([tuple(v) for v in corners], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for li, (x, y) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))): uv.data[li].uv = (x, y)
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me); coll("Decals").objects.link(o)
    o.visible_shadow = False
    return o

for i, dc in enumerate(SPEC.get("decals", []) or []):
    try:
        meta = DECAL_CAT.get(dc.get("decal"))
        if not meta or not os.path.exists(os.path.join(DECAL_DIR, meta["file"])): log("decal missing", dc.get("decal")); continue
        w = float(dc.get("width", meta.get("width", 0.5))); h = w * float(meta.get("aspect", 1.0))
        mat = decal_material(meta, float(dc.get("opacity", 1.0))); surf = dc.get("surface", "north"); name = f"Decal_{i}_{meta['id']}"
        if surf == "floor":
            decal_quad(name, Vector((float(dc.get("x", 0)), float(dc.get("y", 0)), 0.003)), Vector((1, 0, 0)), Vector((0, 1, 0)), w, h, float(dc.get("rot", 0)), mat)
        else:
            wall, depth = surf, 0.0
            if surf.startswith("alcove:"):
                ft = next((f for f in FEATURES if f.get("id") == surf[7:]), None)
                if not ft: log("decal: no alcove", surf); continue
                wall, depth = ft["wall"], fdepth(ft)
            if wall not in WALLS: continue
            z = float(dc.get("z", 1.4)); lf = (WALL_SET.get(wall) or (None, None, None))[2]
            panel = lf and lf.get("type") == "panelling" and z - h / 2 < lower_height(lf) + 0.07
            off = 0.045 if panel else 0.009                                 # in front of panelling, rails and tiles
            centre = w2world(wall, float(dc.get("u", 0)), depth - off, z)
            n = (w2world(wall, 0, 1, 0) - w2world(wall, 0, 0, 0)).normalized()  # into the wall
            right = n.cross(Vector((0, 0, 1)))                                  # what the viewer sees as "right"
            decal_quad(name, centre, right, Vector((0, 0, 1)), w, h, float(dc.get("rot", 0)), mat)
        USED_DECALS.append({"id": meta["id"], "name": meta.get("name", meta["id"]), "source": meta.get("source", ""), "licence": meta.get("licence", "")})
    except Exception as e:
        import traceback; traceback.print_exc(); log("decal failed", dc.get("decal"), e)

# ============================================================== items
for it in SPEC.get("items", []):
    if it.get("live"):                 # drawn live by a scene page (e.g. a rocking chair in the Halloween room): not in the render
        USED.add(it["model"]); continue
    try:
        lvl = CONDITION_LEVEL.get(it["condition"], 0.0) if it.get("condition") in CONDITION_LEVEL else DMG * 0.8   # own condition, or the room's
        root = place_model(it["model"], Vector((float(it.get("x", 0)), float(it.get("y", 0)), float(it.get("z", 0)))),
                           math.radians(float(it.get("rot", 0))), float(it.get("scale", 1.0)))
        age_model(root, lvl)
    except Exception as e:
        import traceback; traceback.print_exc(); log("item failed", it.get("model"), e)

# ============================================================== lighting
LIGHT_LEVEL = float(SPEC.get("light_level", 1.0))

def downlights(n_target_spacing=1.6, energy=70):
    nx = max(1, round(W / n_target_spacing)); ny = max(1, round(D / n_target_spacing))
    disc = flat("Downlight_emit", (1, 1, 1), 0.5, emit=(1.0, 0.95, 0.85), strength=25)
    ring = flat("Downlight_ring", (0.8, 0.8, 0.8), 0.3)
    for i in range(nx):
        for j in range(ny):
            x = X0 + (i + 0.5) * W / nx; y = Y0 + (j + 0.5) * D / ny
            bpy.ops.object.light_add(type="SPOT", location=(x, y, RH - 0.01))
            s = bpy.context.active_object; s.name = f"Downlight_{i}_{j}"
            s.data.energy = energy; s.data.spot_size = math.radians(110); s.data.spot_blend = 0.6
            s.data.shadow_soft_size = 0.04; s.data.color = (1.0, 0.92, 0.82); put(s, "Lights")
            cylinder_obj(f"Downlight_ring_{i}_{j}", 0.05, 0.006, (x, y, RH - 0.003), ring, verts=24, cname="Lights")
            cylinder_obj(f"Downlight_disc_{i}_{j}", 0.035, 0.004, (x, y, RH - 0.006), disc, verts=24, cname="Lights")

def pendant(energy=60, on=True):
    """A dated flush 'dome' ceiling light: a frosted glass dome with a warm bulb behind it. It sits off the zenith
    (straight above the camera an equirect smears it into a band across the top of the image)."""
    cx, cy = 0.0, min(0.9, D / 4)
    glow = flat("Dome_glass", (1, 1, 1), 0.4, emit=(1.0, 0.82, 0.6), strength=2.0 * LIGHT_LEVEL) if on else flat("Dome_glass_off", (0.85, 0.83, 0.78), 0.35)
    rim = flat("Dome_rim", (0.6, 0.55, 0.42), 0.5)
    cylinder_obj("Dome_rim", 0.21, 0.012, (cx, cy, RH - 0.006), rim, verts=48, cname="Lights")
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(cx, cy, RH - 0.012), segments=48, ring_count=24)
    d = bpy.context.active_object; d.name = "Dome_glass"; d.scale = (1, 1, 0.35); d.data.materials.append(glow); put(d, "Lights")
    d.visible_shadow = False
    for p_ in d.data.polygons: p_.use_smooth = True
    if not on: return                                 # switched off: the fitting is there, unlit
    bpy.ops.object.light_add(type="POINT", location=(cx, cy, RH - 0.15))
    l = bpy.context.active_object; l.name = "Dome_light"; l.data.energy = energy; l.data.color = (1.0, 0.78, 0.5)
    l.data.shadow_soft_size = 0.15; put(l, "Lights")

world = bpy.data.worlds.new("World"); sc.world = world; world.use_nodes = True; wn = world.node_tree; wn.nodes.clear()
wo = wn.nodes.new("ShaderNodeOutputWorld"); bg = wn.nodes.new("ShaderNodeBackground"); wn.links.new(bg.outputs[0], wo.inputs[0])
hdri_path = None
if HDRI_ID:
    hdri_path = ensure_hdri(HDRI_ID, "8k" if QUALITY in ("standard", "high") else "4k")
if hdri_path:
    tc = wn.nodes.new("ShaderNodeTexCoord"); mp = wn.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(HDRI_ROT))
    env = wn.nodes.new("ShaderNodeTexEnvironment"); env.image = bpy.data.images.load(hdri_path, check_existing=True)
    wn.links.new(tc.outputs["Generated"], mp.inputs[0]); wn.links.new(mp.outputs[0], env.inputs[0])
    wn.links.new(env.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = HDRI_STRENGTH
    log("outside view", HDRI_ID, os.path.basename(hdri_path), "rotation", HDRI_ROT)
    with open(os.path.join(OUT_DIR, "used_outside.json"), "w", encoding="utf-8") as fh: json.dump({"hdri": HDRI_ID, "view": OUT_VIEW}, fh)
elif LIGHTING == "night":
    bg.inputs[0].default_value = (0.004, 0.006, 0.012, 1); bg.inputs[1].default_value = 1.0
else:                                              # offline fallback: a plain sky
    sky = wn.nodes.new("ShaderNodeTexSky")
    for t in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
        try: sky.sky_type = t; break
        except Exception: continue
    for attr, val in (("sun_elevation", math.radians(24 if LIGHTING == "day" else 4)), ("sun_disc", False)):
        try: setattr(sky, attr, val)
        except Exception: pass
    wn.links.new(sky.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = 0.35

# room lights: on unless the spec says "lights_on": false (e.g. a lights-off version of a scene to cross-fade with);
# "light_level" dims or brightens them (1 = normal). The camera exposure stays the same either way.
lights_on = bool(SPEC.get("lights_on", True))
if OUTDOOR:
    pass
elif CUSTODY:                                       # one recessed anti-ligature light, off the zenith
    if W * D <= 12:
        panel_light("Cell_light", Vector((0, min(0.8, D / 4), 0)), along_x=True, energy=55, size=(0.9, 0.3))
    else:                                           # bigger rooms (e.g. a cell at Igloo-room size): two fittings
        for i, fx in enumerate((-1, 1)):
            panel_light(f"Cell_light_{i}", Vector((fx * W / 4, D / 6, 0)), along_x=True, energy=55 * min(2.0, W * D / 16), size=(0.9, 0.3))
elif COURT:
    for i, (fx, fy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        panel_light(f"Panel_{i}", Vector((fx * W / 4, fy * D / 4, 0)), along_x=True, energy=70)
elif HOSPITAL:
    # four panels in the main room, kept away from the zenith so none smears across the top of the panorama
    for i, (fx, fy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        panel_light(f"Panel_{i}", Vector((fx * W / 4, fy * D / 4, 0)), along_x=True, energy=65 if LIGHTING == "day" else 90)
elif not NEGLECT:
    if lights_on: downlights(energy=(70 if LIGHTING == "day" else 90) * LIGHT_LEVEL)
else:
    pendant(energy=(55 if LIGHTING == "day" else 80) * LIGHT_LEVEL, on=lights_on)

# ============================================================== render settings
sc.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dt in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = dt; prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == dt]
            if gpus:
                for d in prefs.devices: d.use = d.type == dt
                sc.cycles.device = "GPU"; log("render device", dt, [d.name for d in gpus]); break
        except Exception: continue
except Exception as e:
    log("no GPU, using CPU", e)
if sc.cycles.device != "GPU":
    log("render device CPU (no supported GPU found: renders will be much slower)")
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = True
sc.cycles.use_adaptive_sampling = True
sc.cycles.max_bounces = 8
sc.cycles.transmission_bounces = 8
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = RES_X, RES_Y, 100
try:
    sc.view_settings.view_transform = "AgX"
except Exception: pass
sc.view_settings.exposure = {"day": 0.6, "dusk": 0.9, "night": 0.9}.get(LIGHTING, 0.6) + (0.35 if NEGLECT else {"worn": 0.1, "neglected": 0.25, "derelict": 0.35}.get(CONDITION, 0.0)) - (0.5 if HOSPITAL else 0.0) \
    - (0.55 if COURT else 0.0) - (0.4 if CUSTODY else 0.0) + float(SPEC.get("render", {}).get("exposure", 0))
if OUTDOOR: sc.view_settings.exposure = {"day": 0.0, "dusk": 0.5, "night": 1.0}.get(LIGHTING, 0.0) + float(SPEC.get("render", {}).get("exposure", 0))
sc.render.film_transparent = False

cam_data = bpy.data.cameras.new("PanoCam")
try:
    cam_data.type = "PANO"
    try: cam_data.panorama_type = "EQUIRECTANGULAR"
    except Exception: cam_data.cycles.panorama_type = "EQUIRECTANGULAR"
except Exception as e:
    log("panorama camera setup failed", e)
cam = bpy.data.objects.new("PanoCam", cam_data); sc.collection.objects.link(cam); sc.camera = cam
cam_data.clip_start = 0.02

# save the scene for checking
try:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "room.blend"), compress=True)
except Exception as e:
    log("could not save room.blend", e)

with open(os.path.join(OUT_DIR, "used_decals.json"), "w", encoding="utf-8") as fh:
    json.dump({d["id"]: d for d in USED_DECALS}, fh)
with open(os.path.join(OUT_DIR, "used_models.json"), "w", encoding="utf-8") as fh:
    json.dump(sorted(USED), fh)

# ============================================================== render each view
views = SPEC.get("views") or [{"name": "centre", "x": 0, "y": 0, "yaw": 0}]
N = len(views)
state = {"i": 0}
def on_stats(*args):
    s = next((a for a in args if isinstance(a, str)), "")
    import re
    m = re.search(r"Sample (\d+)/(\d+)", s)
    if m: print(f"RB_PROGRESS {state['i']} {N} {m.group(1)} {m.group(2)}", flush=True)
try:
    bpy.app.handlers.render_stats.append(on_stats)
except Exception:
    pass

t0 = time.time()
for i, v in enumerate(views):
    state["i"] = i
    name = "".join(ch for ch in str(v.get("name", f"view{i}")) if ch.isalnum() or ch in "-_") or f"view{i}"
    cam.location = (float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", EYE)))
    cam.rotation_euler = (math.radians(90), 0, -math.radians(float(v.get("yaw", 0))))   # yaw: compass degrees, 0 = north
    print(f"RB_PROGRESS {i} {N} 0 {SAMPLES}", flush=True)
    png = os.path.join(OUT_DIR, f"view_{name}.png")
    sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_depth = "8"
    sc.render.filepath = png
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.get("Render Result")
    sc.render.image_settings.file_format = "JPEG"; sc.render.image_settings.quality = 92
    try:
        img.save_render(os.path.join(OUT_DIR, f"view_{name}.jpg"), scene=sc)
    except Exception as e:
        log("jpg save failed", e)
    try:                                            # small preview for the library
        th = bpy.data.images.load(os.path.join(OUT_DIR, f"view_{name}.jpg")); th.scale(768, 384)
        th.filepath_raw = os.path.join(OUT_DIR, f"thumb_{name}.jpg"); th.file_format = "JPEG"; th.save()
        bpy.data.images.remove(th)
    except Exception as e:
        log("thumbnail failed", e)
    print(f"RB_PROGRESS {i} {N} {SAMPLES} {SAMPLES}", flush=True)
    print(f"RB_VIEW_DONE {name} {time.time() - t0:.1f}", flush=True)

print(f"RB_DONE {time.time() - t0:.1f} {RES_X}x{RES_Y} {SAMPLES} {N}", flush=True)
