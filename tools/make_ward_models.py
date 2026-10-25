"""
Builds Room Builder's own ward models in Blender and adds them to the library (catalogue/models/<id>/).

    blender -b --factory-startup -P tools/make_ward_models.py

Each model is built at the origin standing on the floor, with its front facing -Y (so rot 0 in a spec faces into the
room from the north wall). Beds have their head at +Y. Each gets a .glb, a thumbnail and model.json (own work, no credit).
"""
import bpy, bmesh, json, math, os, sys
from mathutils import Vector, Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "catalogue", "models")
ONLY = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

# ------------------------------------------------------------------ helpers
def mat(name, color, rough=0.5, metal=0.0, coat=0.0):
    m = bpy.data.materials.get(name)
    if m: return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k in ("Coat Weight", "Clearcoat"):
        if k in b.inputs and coat: b.inputs[k].default_value = coat; break
    m.diffuse_color = (*color, 1)
    return m

def emat(name, color, strength=6.0):
    """A glowing material (candle flames, a lit pumpkin face). Exported as glTF emissive with strength."""
    m = bpy.data.materials.get(name)
    if m: return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    for k in ("Emission Color", "Emission"):
        if k in b.inputs: b.inputs[k].default_value = (*color, 1); break
    b.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*color, 1)
    return m

def link(o):
    bpy.context.scene.collection.objects.link(o); return o

def box(name, size, loc, m, bevel=0.006, rot=None, pivot=None):
    """size (x, y, z), centred at loc. rot = (axis, degrees) about pivot (default its centre)."""
    me = bpy.data.meshes.new(name); bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts: v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    bm.to_mesh(me); bm.free(); me.materials.append(m)
    o = link(bpy.data.objects.new(name, me)); o.location = loc
    if bevel:
        md = o.modifiers.new("bevel", "BEVEL"); md.width = min(bevel, min(size) * 0.45); md.segments = 2; md.limit_method = "ANGLE"
    if rot:
        bpy.context.view_layer.update()            # matrix_world is stale until the view layer updates
        axis, deg = rot; p = Vector(pivot) if pivot else Vector(loc)
        o.matrix_world = Matrix.Translation(p) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-p) @ o.matrix_world
    return o

def cyl(name, r, h, loc, m, axis="Z", verts=24, r2=None):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=verts, radius1=r, radius2=r if r2 is None else r2, depth=h)
    bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    me.materials.append(m)
    o = link(bpy.data.objects.new(name, me)); o.location = loc
    o.rotation_euler = {"Z": (0, 0, 0), "X": (0, math.pi / 2, 0), "Y": (math.pi / 2, 0, 0)}[axis]
    return o

def tube(name, pts, r, m, verts=12):
    """A tube through a list of points (a bent rail)."""
    cu = bpy.data.curves.new(name, "CURVE"); cu.dimensions = "3D"; cu.bevel_depth = r; cu.bevel_resolution = 3
    sp = cu.splines.new("POLY"); sp.points.add(len(pts) - 1)
    for p, c in zip(sp.points, pts): p.co = (*c, 1)
    cu.materials.append(m)
    o = link(bpy.data.objects.new(name, cu))
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    return o

def castor(name, x, y, m_dark, m_metal, r=0.05):
    cyl(name + "_stem", 0.012, 0.06, (x, y, 2 * r + 0.03), m_metal, verts=10)
    box(name + "_fork", (0.03, 0.06, 0.05), (x, y, 2 * r - 0.005), m_metal, bevel=0.004)
    cyl(name + "_wheel", r, 0.035, (x, y, r), m_dark, axis="X", verts=20)

def wavy(name, x0, x1, z0, z1, depth, folds, m, y=0.0):
    me = bpy.data.meshes.new(name); bm = bmesh.new(); nu = max(8, folds * 6); grid = []
    for j in range(3):
        z = z0 + (z1 - z0) * j / 2; row = []
        for i in range(nu + 1):
            x = x0 + (x1 - x0) * i / nu
            yy = y + depth * math.sin(i / nu * folds * 2 * math.pi)
            row.append(bm.verts.new((x, yy, z)))
        grid.append(row)
    for j in range(2):
        for i in range(nu): bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
    bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    me.materials.append(m)
    o = link(bpy.data.objects.new(name, me))
    s = o.modifiers.new("thick", "SOLIDIFY"); s.thickness = 0.006
    return o

# ------------------------------------------------------------------ shared materials
def M():
    return {
        "frame": mat("Bed_frame_grey", (0.62, 0.64, 0.66), 0.35, 0.6),
        "metal": mat("Chrome", (0.8, 0.8, 0.8), 0.2, 1.0),
        "dark": mat("Castor_black", (0.03, 0.03, 0.03), 0.6),
        "panel": mat("Panel_white_plastic", (0.86, 0.87, 0.86), 0.35, coat=0.2),
        "panel_wood": mat("Panel_beech", (0.66, 0.48, 0.3), 0.45),
        "mattress": mat("Mattress_blue_vinyl", (0.06, 0.24, 0.42), 0.35, coat=0.3),
        "sheet": mat("Sheet_white", (0.88, 0.89, 0.9), 0.8),
        "blanket": mat("Blanket_cellular_blue", (0.48, 0.62, 0.78), 0.9),
        "pillow": mat("Pillow_white", (0.9, 0.9, 0.9), 0.8),
        "laminate": mat("Laminate_light_oak", (0.72, 0.6, 0.44), 0.4),
        "laminate_white": mat("Laminate_white", (0.85, 0.85, 0.83), 0.35),
        "handle": mat("Handle_steel", (0.7, 0.7, 0.7), 0.25, 1.0),
        "curtain": mat("Curtain_ward_blue", (0.36, 0.55, 0.66), 0.85),
        "curtain_print": mat("Curtain_ward_print", (0.5, 0.66, 0.74), 0.85),
        "track": mat("Track_aluminium", (0.78, 0.78, 0.78), 0.3, 0.8),
        "vinyl_teal": mat("Vinyl_teal", (0.05, 0.32, 0.36), 0.4, coat=0.2),
        "ceramic": mat("Ceramic_white", (0.92, 0.92, 0.9), 0.15, coat=0.5),
        "ips": mat("IPS_panel_white", (0.88, 0.88, 0.86), 0.3),
        "dispenser": mat("Dispenser_grey", (0.75, 0.76, 0.77), 0.35),
        "blue_sign": mat("Sign_blue", (0.0, 0.33, 0.62), 0.4),
        "screen": mat("Screen_black", (0.02, 0.03, 0.04), 0.1, coat=0.8),
    }

# ------------------------------------------------------------------ models
def hospital_bed(m, rails_up=False):
    L, Wd = 2.15, 1.0
    for i, (x, y) in enumerate(((-0.4, -0.92), (0.4, -0.92), (-0.4, 0.92), (0.4, 0.92))): castor(f"castor{i}", x, y, m["dark"], m["metal"])
    box("base_frame", (0.86, 1.95, 0.07), (0, 0, 0.2), m["frame"])
    box("lift_a", (0.16, 0.12, 0.22), (0, -0.55, 0.34), m["frame"]); box("lift_b", (0.16, 0.12, 0.22), (0, 0.55, 0.34), m["frame"])
    box("platform", (0.92, 2.02, 0.05), (0, 0, 0.47), m["frame"])
    # mattress: foot section flat, back section raised 30 deg about a hinge at y = 0.2
    hy, hz = 0.2, 0.495
    box("mattress_foot", (0.9, 1.2, 0.15), (0, hy - 0.6, hz + 0.075), m["mattress"], bevel=0.03)
    box("sheet_foot", (0.92, 1.21, 0.012), (0, hy - 0.605, hz + 0.155), m["sheet"], bevel=0.004)
    back = [box("mattress_back", (0.9, 0.78, 0.15), (0, hy + 0.39, hz + 0.075), m["mattress"], bevel=0.03),
            box("sheet_back", (0.92, 0.79, 0.012), (0, hy + 0.395, hz + 0.155), m["sheet"], bevel=0.004),
            box("pillow", (0.62, 0.36, 0.13), (0, hy + 0.55, hz + 0.22), m["pillow"], bevel=0.05)]
    bpy.context.view_layer.update()
    rot = Matrix.Translation((0, hy, hz)) @ Matrix.Rotation(math.radians(30), 4, "X") @ Matrix.Translation((0, -hy, -hz))
    for o in back: o.matrix_world = rot @ o.matrix_world
    # folded blanket across the foot, hanging a little over the sides
    box("blanket_top", (0.95, 0.55, 0.04), (0, -0.62, hz + 0.18), m["blanket"], bevel=0.015)
    box("blanket_side_l", (0.03, 0.55, 0.16), (-0.475, -0.62, hz + 0.1), m["blanket"], bevel=0.01)
    box("blanket_side_r", (0.03, 0.55, 0.16), (0.475, -0.62, hz + 0.1), m["blanket"], bevel=0.01)
    # head and foot boards with posts
    box("headboard", (0.98, 0.045, 0.5), (0, L / 2 - 0.05, 0.78), m["panel"], bevel=0.02)
    box("footboard", (0.98, 0.045, 0.36), (0, -L / 2 + 0.05, 0.7), m["panel"], bevel=0.02)
    for sx in (-0.47, 0.47):
        cyl(f"post_h{sx}", 0.02, 0.62, (sx, L / 2 - 0.05, 0.72), m["frame"], verts=12)
        cyl(f"post_f{sx}", 0.02, 0.46, (sx, -L / 2 + 0.05, 0.66), m["frame"], verts=12)
    # split side rails at the head end (down at the foot)
    z_r = 0.86 if rails_up else 0.6
    for sx in (-0.5, 0.5):
        tube(f"rail_top{sx}", [(sx, 0.05, z_r), (sx, 0.85, z_r)], 0.014, m["frame"])
        tube(f"rail_mid{sx}", [(sx, 0.05, z_r - 0.13), (sx, 0.85, z_r - 0.13)], 0.012, m["frame"])
        for y in (0.08, 0.82): cyl(f"rail_post{sx}{y}", 0.012, 0.2, (sx, y, z_r - 0.1), m["frame"], verts=10)
    # handset hanging on the rail
    box("handset", (0.05, 0.03, 0.16), (0.53, 0.5, z_r - 0.1), m["dispenser"], bevel=0.01)

def bedside_locker(m):
    W, Dp, H = 0.48, 0.47, 0.82
    for i, (x, y) in enumerate(((-0.19, -0.18), (0.19, -0.18), (-0.19, 0.18), (0.19, 0.18))): castor(f"castor{i}", x, y, m["dark"], m["metal"], r=0.03)
    box("body", (W, Dp, H - 0.1), (0, 0, 0.1 + (H - 0.1) / 2), m["laminate_white"], bevel=0.01)
    box("top", (W + 0.02, Dp + 0.02, 0.025), (0, 0, H + 0.0125), m["laminate"], bevel=0.008)
    box("drawer", (W - 0.04, 0.02, 0.15), (0, -Dp / 2 - 0.006, H - 0.11), m["laminate"], bevel=0.005)
    box("door", (W - 0.04, 0.02, 0.45), (0, -Dp / 2 - 0.006, 0.38), m["laminate"], bevel=0.005)
    box("drawer_handle", (0.18, 0.025, 0.02), (0, -Dp / 2 - 0.025, H - 0.11), m["handle"], bevel=0.004)
    box("door_handle", (0.025, 0.025, 0.18), (W / 2 - 0.07, -Dp / 2 - 0.025, 0.48), m["handle"], bevel=0.004)
    # jug and cup on top
    cyl("jug", 0.055, 0.2, (-0.1, 0.05, H + 0.125), mat("Jug_clear", (0.8, 0.88, 0.9), 0.1), verts=24, r2=0.045)
    cyl("cup", 0.035, 0.09, (0.09, -0.05, H + 0.07), mat("Cup_white", (0.92, 0.92, 0.92), 0.3), verts=20)

def overbed_table(m):
    for i, (x, y) in enumerate(((-0.33, -0.25), (-0.33, 0.25))): castor(f"castor{i}", x, y, m["dark"], m["metal"], r=0.03)
    box("base", (0.08, 0.6, 0.04), (-0.33, 0, 0.09), m["frame"])
    box("foot_a", (0.55, 0.06, 0.03), (-0.06, -0.25, 0.04), m["frame"]); box("foot_b", (0.55, 0.06, 0.03), (-0.06, 0.25, 0.04), m["frame"])
    cyl("column", 0.025, 0.72, (-0.33, 0, 0.47), m["frame"], verts=14)
    box("arm", (0.08, 0.06, 0.05), (-0.33, 0, 0.83), m["frame"])
    box("top", (0.8, 0.4, 0.025), (0.0, 0, 0.865), m["laminate"], bevel=0.008)
    box("lip", (0.8, 0.012, 0.02), (0, -0.2, 0.885), m["laminate"], bevel=0.003)

def drip_stand(m):
    for k in range(5):
        a = k * 2 * math.pi / 5; x, y = 0.28 * math.cos(a), 0.28 * math.sin(a)
        tube(f"leg{k}", [(0, 0, 0.09), (x, y, 0.07)], 0.012, m["metal"])
        castor(f"castor{k}", x, y, m["dark"], m["metal"], r=0.025)
    cyl("pole", 0.013, 1.85, (0, 0, 1.0), m["metal"], verts=14)
    cyl("hub", 0.035, 0.06, (0, 0, 0.09), m["metal"], verts=16)
    for k in range(4):
        a = k * math.pi / 2
        tube(f"hook{k}", [(0, 0, 1.9), (0.12 * math.cos(a), 0.12 * math.sin(a), 1.92), (0.13 * math.cos(a), 0.13 * math.sin(a), 1.86)], 0.006, m["metal"])
    box("bag", (0.12, 0.03, 0.2), (0.12, 0, 1.7), mat("IV_bag", (0.85, 0.9, 0.92), 0.1), bevel=0.02)
    box("pump", (0.15, 0.1, 0.2), (0, -0.07, 1.15), m["dispenser"], bevel=0.015)
    box("pump_screen", (0.1, 0.005, 0.06), (0, -0.122, 1.19), m["screen"], bevel=0)

def bay_curtain(m):
    """Ceiling track across a bay opening, curtain pulled back to one end. The hem is at z 0: place it at z 0.3."""
    L, H = 2.6, 1.85
    box("track", (L, 0.035, 0.03), (0, 0, H + 0.02), m["track"], bevel=0.005)
    for x in (-L / 2 + 0.05, L / 2 - 0.05): box(f"end{x}", (0.04, 0.04, 0.05), (x, 0, H + 0.01), m["track"], bevel=0.005)
    wavy("curtain_bunch", L / 2 - 0.42, L / 2 - 0.03, 0.0, H, 0.045, 9, m["curtain"])
    box("mesh_top", (0.39, 0.012, 0.25), (L / 2 - 0.225, 0, H - 0.12), mat("Curtain_mesh", (0.85, 0.87, 0.88), 0.9), bevel=0)

def handwash_station(m):
    """Wall-mounted clinical hand-wash basin with splashback and dispensers. Back at +Y (against the wall)."""
    box("splashback", (0.7, 0.012, 1.0), (0, 0.0, 0.95), m["ips"], bevel=0.004)
    box("basin", (0.5, 0.38, 0.16), (0, -0.19, 0.78), m["ceramic"], bevel=0.04)
    box("basin_bowl", (0.4, 0.28, 0.02), (0, -0.2, 0.86), mat("Basin_inner", (0.8, 0.8, 0.78), 0.1), bevel=0.01)
    cyl("mixer", 0.02, 0.16, (0, -0.04, 0.95), m["handle"], verts=14)
    tube("spout", [(0, -0.04, 1.02), (0, -0.14, 1.02), (0, -0.16, 0.98)], 0.01, m["handle"])
    tube("lever", [(0.02, -0.04, 1.0), (0.17, -0.06, 1.0)], 0.008, m["handle"])
    box("soap", (0.11, 0.1, 0.22), (-0.28, -0.05, 1.18), m["dispenser"], bevel=0.015)
    box("gel", (0.11, 0.1, 0.22), (0.28, -0.05, 1.18), mat("Gel_dispenser", (0.85, 0.86, 0.87), 0.35), bevel=0.015)
    box("gel_label", (0.07, 0.005, 0.05), (0.28, -0.103, 1.2), m["blue_sign"], bevel=0)
    box("towels", (0.3, 0.12, 0.4), (0, -0.06, 1.6), m["dispenser"], bevel=0.02)
    box("sign", (0.2, 0.005, 0.28), (-0.42, -0.003, 1.55), m["blue_sign"], bevel=0)
    box("bin", (0.32, 0.28, 0.42), (0.55, -0.16, 0.21), mat("Pedal_bin_white", (0.86, 0.86, 0.85), 0.3), bevel=0.03)
    box("bin_lid", (0.33, 0.29, 0.03), (0.55, -0.16, 0.435), mat("Pedal_bin_lid", (0.84, 0.82, 0.25), 0.4), bevel=0.01)

def ward_chair(m):
    """High-back wipe-clean ward chair. Front faces -Y."""
    for i, (x, y) in enumerate(((-0.27, -0.27), (0.27, -0.27), (-0.27, 0.27), (0.27, 0.27))):
        cyl(f"leg{i}", 0.018, 0.4, (x, y, 0.2), m["frame"], verts=12)
    box("seat", (0.58, 0.56, 0.12), (0, -0.02, 0.46), m["vinyl_teal"], bevel=0.035)
    box("back", (0.58, 0.12, 0.72), (0, 0.29, 0.86), m["vinyl_teal"], bevel=0.04, rot=("X", -10), pivot=(0, 0.25, 0.5))
    box("wings_l", (0.1, 0.25, 0.25), (-0.28, 0.22, 1.05), m["vinyl_teal"], bevel=0.03)
    box("wings_r", (0.1, 0.25, 0.25), (0.28, 0.22, 1.05), m["vinyl_teal"], bevel=0.03)
    for sx in (-0.33, 0.33):
        box(f"arm{sx}", (0.08, 0.52, 0.06), (sx, 0.0, 0.68), m["panel_wood"], bevel=0.02)
        box(f"arm_post{sx}", (0.05, 0.05, 0.24), (sx, -0.22, 0.55), m["frame"], bevel=0.01)

def obs_monitor(m):
    """Mobile observations monitor on a stand. Screen faces -Y."""
    for k in range(5):
        a = k * 2 * math.pi / 5; x, y = 0.25 * math.cos(a), 0.25 * math.sin(a)
        tube(f"leg{k}", [(0, 0, 0.08), (x, y, 0.06)], 0.012, m["frame"])
        castor(f"castor{k}", x, y, m["dark"], m["metal"], r=0.025)
    cyl("pole", 0.02, 1.0, (0, 0, 0.58), m["frame"], verts=14)
    box("basket", (0.3, 0.2, 0.12), (0, -0.05, 0.95), m["dispenser"], bevel=0.01)
    box("monitor", (0.32, 0.12, 0.26), (0, 0, 1.22), m["panel"], bevel=0.025)
    box("screen", (0.25, 0.005, 0.17), (0, -0.062, 1.24), m["screen"], bevel=0)
    box("cuff", (0.1, 0.06, 0.08), (0.14, -0.05, 0.95), m["blue_sign"], bevel=0.02)

def linen_trolley(m):
    for i, (x, y) in enumerate(((-0.28, -0.22), (0.28, -0.22), (-0.28, 0.22), (0.28, 0.22))):
        castor(f"castor{i}", x, y, m["dark"], m["metal"], r=0.04)
        cyl(f"upright{i}", 0.015, 0.95, (x, y, 0.58), m["metal"], verts=10)
    box("shelf_low", (0.62, 0.5, 0.02), (0, 0, 0.18), m["metal"], bevel=0.004)
    box("bag", (0.6, 0.46, 0.75), (0, 0, 0.6), mat("Linen_bag_white", (0.86, 0.87, 0.88), 0.85), bevel=0.06)
    tube("ring", [(-0.3, -0.24, 1.0), (0.3, -0.24, 1.0), (0.3, 0.24, 1.0), (-0.3, 0.24, 1.0), (-0.3, -0.24, 1.0)], 0.012, m["metal"])


# ================================================================== UK court room
def C():
    return {
        "oak": mat("Court_oak", (0.2, 0.105, 0.045), 0.4), "oak_dark": mat("Court_oak_dark", (0.09, 0.048, 0.02), 0.4),
        "leather": mat("Judge_leather_green", (0.06, 0.18, 0.12), 0.45, coat=0.2), "seat_blue": mat("Court_seat_blue", (0.1, 0.16, 0.32), 0.85),
        "carpet": mat("Dais_carpet", (0.025, 0.045, 0.11), 0.95), "glass": mat("Dock_glass", (0.9, 0.95, 0.95), 0.03),
        "steel": mat("Court_steel", (0.7, 0.7, 0.7), 0.25, 1.0), "black": mat("Office_black", (0.03, 0.03, 0.03), 0.5),
        "paper": mat("Paper_white", (0.9, 0.9, 0.86), 0.8), "file": mat("Lever_arch_blue", (0.1, 0.2, 0.45), 0.5),
        "file_red": mat("Lever_arch_red", (0.5, 0.08, 0.06), 0.5), "screen": mat("Screen_dark", (0.02, 0.03, 0.04), 0.1, coat=0.8),
        "jug": mat("Jug_glass", (0.85, 0.9, 0.92), 0.05), "brass": mat("Brass", (0.75, 0.55, 0.25), 0.3, 1.0),
    }

def raised_panels(prefix, x0, x1, y, z0, z1, n, m, inset=0.06):
    w = (x1 - x0) / n
    for k in range(n):
        box(f"{prefix}{k}", (w - 2 * inset, 0.012, (z1 - z0) - 2 * inset), (x0 + (k + 0.5) * w, y, (z0 + z1) / 2), m, bevel=0.004)

def office_chair(prefix, x, y, z, c, back_h=0.55, m_seat=None, high=False):
    ms = m_seat or c["black"]
    cyl(prefix + "_column", 0.025, 0.3, (x, y, z + 0.18), c["steel"], verts=12)
    for k in range(5):
        a = k * 2 * math.pi / 5
        tube(prefix + f"_leg{k}", [(x, y, z + 0.05), (x + 0.28 * math.cos(a), y + 0.28 * math.sin(a), z + 0.04)], 0.014, c["black"])
    box(prefix + "_seat", (0.52, 0.5, 0.1), (x, y, z + 0.45), ms, bevel=0.03)
    box(prefix + "_back", (0.5, 0.09, back_h), (x, y + 0.24, z + 0.5 + back_h / 2), ms, bevel=0.035)
    if high:
        for sx in (-0.29, 0.29): box(prefix + f"_arm{sx}", (0.06, 0.4, 0.05), (x + sx, y + 0.02, z + 0.66), ms, bevel=0.015)

def files_stack(prefix, x, y, z, c, n=3, rot=0):
    for k in range(n):
        box(prefix + f"{k}", (0.08, 0.29, 0.32), (x + k * 0.085, y, z + 0.16), c["file"] if k % 2 == 0 else c["file_red"], bevel=0.006)

def judge_bench(m):
    """UK court judge's bench: carpeted dais, panelled oak bench with leather-inlaid top, three high-back chairs and a tall
    oak back panel with a plain roundel (no royal arms). Front faces -Y; the judge sits on the +Y side."""
    c = C(); W, Dp, dz = 3.6, 2.0, 0.6
    box("dais", (W, Dp, dz), (0, 0, dz / 2), c["oak_dark"], bevel=0.01)
    box("dais_carpet", (W - 0.04, Dp - 0.04, 0.012), (0, 0, dz + 0.006), c["carpet"], bevel=0)
    box("step", (0.7, 0.35, 0.2), (W / 2 - 0.4, -Dp / 2 - 0.17, 0.1), c["oak_dark"], bevel=0.008)
    box("step2", (0.7, 0.3, 0.4), (W / 2 - 0.4, -Dp / 2 + 0.15, 0.2), c["oak_dark"], bevel=0.008)
    fy = -Dp / 2 + 0.07
    box("bench_front", (W, 0.06, 0.82), (0, fy, dz + 0.41), c["oak"], bevel=0.01)
    raised_panels("bench_panel", -W / 2 + 0.05, W / 2 - 0.05, fy - 0.035, dz + 0.08, dz + 0.74, 5, c["oak"])
    box("bench_top", (W + 0.1, 0.72, 0.05), (0, fy + 0.31, dz + 0.845), c["oak"], bevel=0.012)
    box("bench_inlay", (W - 0.3, 0.55, 0.004), (0, fy + 0.33, dz + 0.872), c["leather"], bevel=0)
    for sx in (-W / 2 + 0.03, W / 2 - 0.03): box(f"bench_end{sx}", (0.06, 0.75, 0.82), (sx, fy + 0.33, dz + 0.41), c["oak"], bevel=0.008)
    by = Dp / 2 - 0.05
    box("back_panel", (W, 0.08, 1.56), (0, by, dz + 0.78), c["oak"], bevel=0.012)
    raised_panels("back_inset", -W / 2 + 0.05, W / 2 - 0.05, by - 0.045, dz + 0.1, dz + 1.46, 3, c["oak_dark"], inset=0.08)
    cyl("roundel", 0.3, 0.05, (0, by - 0.07, dz + 1.12), c["oak_dark"], axis="Y", verts=48)
    cyl("roundel_inner", 0.22, 0.06, (0, by - 0.075, dz + 1.12), c["oak"], axis="Y", verts=48)
    box("cornice", (W + 0.08, 0.16, 0.05), (0, by - 0.02, dz + 1.585), c["oak_dark"], bevel=0.01)
    for k, x in enumerate((-1.1, 0.0, 1.1)):
        hb = 0.95 if x == 0 else 0.78
        box(f"jchair_seat{k}", (0.62, 0.58, 0.14), (x, 0.15, dz + 0.5), c["leather"], bevel=0.04)
        box(f"jchair_back{k}", (0.64, 0.14, hb), (x, 0.46, dz + 0.55 + hb / 2), c["leather"], bevel=0.05)
        box(f"jchair_base{k}", (0.12, 0.12, 0.38), (x, 0.15, dz + 0.24), c["black"], bevel=0.01)
        for sx in (-0.34, 0.34): box(f"jchair_arm{k}{sx}", (0.08, 0.45, 0.07), (x + sx, 0.2, dz + 0.72), c["oak_dark"], bevel=0.02)
    top = dz + 0.87
    box("monitor", (0.5, 0.04, 0.32), (-0.55, fy + 0.45, top + 0.24), c["black"], bevel=0.008)
    box("monitor_screen", (0.46, 0.005, 0.28), (-0.55, fy + 0.428, top + 0.24), c["screen"], bevel=0)
    box("monitor_stand", (0.18, 0.15, 0.08), (-0.55, fy + 0.47, top + 0.04), c["black"], bevel=0.01)
    box("notebook", (0.3, 0.22, 0.02), (0.05, fy + 0.3, top + 0.01), c["paper"], bevel=0.003)
    files_stack("bundle", 0.7, fy + 0.4, top, c, n=3)
    cyl("jug", 0.06, 0.22, (1.35, fy + 0.35, top + 0.11), c["jug"], verts=24, r2=0.05)
    cyl("glass", 0.035, 0.11, (1.22, fy + 0.25, top + 0.055), c["jug"], verts=20)
    tube("mic", [(-0.15, fy + 0.4, top), (-0.15, fy + 0.35, top + 0.25), (-0.15, fy + 0.25, top + 0.32)], 0.006, c["black"])

def clerk_desk(m):
    """Court clerk's desk below the bench: raised panelled front, two monitors, papers, chair behind (+Y side)."""
    c = C(); W = 2.4
    box("front", (W, 0.06, 0.88), (0, -0.4, 0.44), c["oak"], bevel=0.01)
    raised_panels("front_panel", -W / 2 + 0.05, W / 2 - 0.05, -0.435, 0.1, 0.8, 4, c["oak"])
    box("top", (W + 0.06, 0.75, 0.04), (0, -0.05, 0.75), c["oak"], bevel=0.01)
    box("ledge", (W, 0.2, 0.03), (0, -0.4, 0.895), c["oak"], bevel=0.006)
    for sx in (-W / 2 + 0.03, W / 2 - 0.03): box(f"end{sx}", (0.06, 0.75, 0.75), (sx, -0.05, 0.375), c["oak"], bevel=0.008)
    for k, x in enumerate((-0.45, 0.25)):
        box(f"mon{k}", (0.5, 0.04, 0.32), (x, -0.2, 1.02), c["black"], bevel=0.008)
        box(f"mon_screen{k}", (0.46, 0.005, 0.28), (x, -0.222, 1.02), c["screen"], bevel=0)
        box(f"mon_stand{k}", (0.15, 0.12, 0.08), (x, -0.18, 0.81), c["black"], bevel=0.01)
    files_stack("files", 0.75, -0.1, 0.77, c, n=2)
    box("keyboard", (0.42, 0.14, 0.02), (-0.1, 0.05, 0.78), c["black"], bevel=0.004)
    box("papers", (0.3, 0.22, 0.015), (0.55, 0.12, 0.775), c["paper"], bevel=0.002)
    office_chair("chair", -0.1, 0.45, 0.0, c, back_h=0.5)

def witness_box(m):
    """Raised witness box with panelled sides, ledge, microphone and water. Front faces -Y; open at the back (+Y)."""
    c = C(); W, Dp, dz, H = 1.3, 1.1, 0.25, 1.05
    box("floor", (W, Dp, dz), (0, 0, dz / 2), c["oak_dark"], bevel=0.008)
    box("floor_carpet", (W - 0.1, Dp - 0.1, 0.01), (0, 0, dz + 0.005), c["carpet"], bevel=0)
    box("front", (W, 0.05, H), (0, -Dp / 2 + 0.025, dz + H / 2), c["oak"], bevel=0.008)
    raised_panels("front_panel", -W / 2 + 0.04, W / 2 - 0.04, -Dp / 2 - 0.005, dz + 0.08, dz + H - 0.08, 2, c["oak"])
    for sx in (-W / 2 + 0.025, W / 2 - 0.025):
        box(f"side{sx}", (0.05, Dp - 0.25, H), (sx, -0.12, dz + H / 2), c["oak"], bevel=0.008)
    box("ledge", (W + 0.06, 0.28, 0.04), (0, -Dp / 2 + 0.12, dz + H + 0.02), c["oak_dark"], bevel=0.008)
    tube("mic", [(0.2, -Dp / 2 + 0.15, dz + H + 0.04), (0.2, -Dp / 2 + 0.2, dz + H + 0.3), (0.15, -Dp / 2 + 0.28, dz + H + 0.36)], 0.006, c["black"])
    cyl("glass", 0.035, 0.11, (-0.35, -Dp / 2 + 0.12, dz + H + 0.095), c["jug"], verts=20)
    box("seat", (0.5, 0.45, 0.06), (0, 0.2, dz + 0.47), c["seat_blue"], bevel=0.02)
    box("seat_legs", (0.45, 0.4, 0.44), (0, 0.2, dz + 0.22), c["oak_dark"], bevel=0.01)
    box("step", (0.6, 0.3, 0.12), (0, Dp / 2 + 0.15, 0.06), c["oak_dark"], bevel=0.006)

def jury_box(m):
    """Two-tier jury box for 12: panelled front with a ledge, fixed upholstered seats. Front faces -Y."""
    c = C(); W, Dp = 3.6, 1.9
    box("front", (W, 0.05, 1.0), (0, -Dp / 2 + 0.025, 0.5), c["oak"], bevel=0.008)
    raised_panels("front_panel", -W / 2 + 0.05, W / 2 - 0.05, -Dp / 2 - 0.005, 0.1, 0.9, 6, c["oak"])
    box("ledge", (W + 0.06, 0.25, 0.04), (0, -Dp / 2 + 0.11, 1.02), c["oak_dark"], bevel=0.008)
    box("tier2", (W, 0.95, 0.3), (0, Dp / 2 - 0.475, 0.15), c["oak_dark"], bevel=0.008)
    box("tier2_carpet", (W - 0.04, 0.93, 0.01), (0, Dp / 2 - 0.475, 0.305), c["carpet"], bevel=0)
    box("tier2_front", (W, 0.04, 0.85), (0, -0.01, 0.3 + 0.425), c["oak"], bevel=0.006)
    for sx in (-W / 2 + 0.025, W / 2 - 0.025): box(f"side{sx}", (0.05, Dp, 1.0), (sx, 0, 0.5), c["oak"], bevel=0.008)
    for row, (y, z) in enumerate(((-0.45, 0.0), (0.5, 0.3))):
        for k in range(6):
            x = -W / 2 + 0.3 + k * (W - 0.6) / 5
            box(f"seat{row}{k}", (0.48, 0.46, 0.09), (x, y, z + 0.46), c["seat_blue"], bevel=0.03)
            box(f"back{row}{k}", (0.48, 0.08, 0.5), (x, y + 0.24, z + 0.75), c["seat_blue"], bevel=0.03)
            box(f"base{row}{k}", (0.06, 0.3, 0.42), (x, y + 0.05, z + 0.21), c["black"], bevel=0.006)
    for k in range(4):
        box(f"pad{k}", (0.21, 0.29, 0.01), (-1.2 + k * 0.75, -Dp / 2 + 0.12, 1.045), c["paper"], bevel=0.002)
    files_stack("bundle", 1.2, -Dp / 2 + 0.12, 1.04, c, n=2)

def secure_dock(m):
    """Glass-screened dock: panelled base, toughened glass to 2.1 m on steel posts, bench inside for four.
    Front (the glass facing the court) faces -Y."""
    c = C(); W, Dp, dz, top = 3.0, 1.7, 0.15, 2.12
    box("floor", (W, Dp, dz), (0, 0, dz / 2), c["oak_dark"], bevel=0.008)
    box("base_front", (W, 0.06, 0.9), (0, -Dp / 2 + 0.03, dz + 0.45), c["oak"], bevel=0.008)
    raised_panels("base_panel", -W / 2 + 0.05, W / 2 - 0.05, -Dp / 2 - 0.005, dz + 0.08, dz + 0.82, 4, c["oak"])
    for sx in (-W / 2 + 0.03, W / 2 - 0.03):
        box(f"base_side{sx}", (0.06, Dp, 0.9), (sx, 0, dz + 0.45), c["oak"], bevel=0.008)
    box("rail_front", (W, 0.1, 0.05), (0, -Dp / 2 + 0.05, dz + 0.92), c["oak_dark"], bevel=0.01)
    # glass panels and posts
    xs = [-W / 2 + k * W / 4 for k in range(5)]
    for k, x in enumerate(xs):
        box(f"post_f{k}", (0.05, 0.05, top - dz - 0.9), (x, -Dp / 2 + 0.03, (dz + 0.9 + top) / 2), c["steel"], bevel=0.004)
    box("glass_front", (W, 0.015, top - dz - 0.95), (0, -Dp / 2 + 0.03, (dz + 0.95 + top) / 2), c["glass"], bevel=0)
    for sx in (-W / 2 + 0.03, W / 2 - 0.03):
        box(f"glass_side{sx}", (0.015, Dp, top - dz - 0.95), (sx, 0, (dz + 0.95 + top) / 2), c["glass"], bevel=0)
        for y in (-Dp / 2 + 0.03, Dp / 2 - 0.03): box(f"post_s{sx}{y}", (0.05, 0.05, top - dz - 0.9), (sx, y, (dz + 0.9 + top) / 2), c["steel"], bevel=0.004)
    box("top_rail_f", (W, 0.06, 0.06), (0, -Dp / 2 + 0.03, top), c["steel"], bevel=0.005)
    for sx in (-W / 2 + 0.03, W / 2 - 0.03): box(f"top_rail_s{sx}", (0.06, Dp, 0.06), (sx, 0, top), c["steel"], bevel=0.005)
    for k, x in enumerate((-0.75, 0.0, 0.75)):
        box(f"slot{k}", (0.25, 0.02, 0.06), (x, -Dp / 2 + 0.03, dz + 1.25), c["steel"], bevel=0.004)
    box("bench", (W - 0.3, 0.45, 0.06), (0, Dp / 2 - 0.35, dz + 0.45), c["oak"], bevel=0.015)
    box("bench_base", (W - 0.4, 0.35, 0.42), (0, Dp / 2 - 0.35, dz + 0.21), c["oak_dark"], bevel=0.01)
    tube("mic", [(0.9, -Dp / 2 + 0.12, dz + 0.95), (0.9, -Dp / 2 + 0.18, dz + 1.2), (0.85, -Dp / 2 + 0.26, dz + 1.25)], 0.006, c["black"])

# ================================================================== UK police custody cell
def K():
    return {
        "concrete": mat("Plinth_concrete_paint", (0.62, 0.63, 0.62), 0.6), "mattress": mat("Cell_mattress_blue", (0.05, 0.2, 0.42), 0.35, coat=0.3),
        "blanket": mat("Cell_blanket_grey", (0.36, 0.37, 0.38), 0.95), "steel": mat("Stainless_brushed", (0.75, 0.75, 0.74), 0.3, 1.0),
        "block": mat("Modesty_wall_paint", (0.8, 0.79, 0.72), 0.35), "black": mat("Dome_black", (0.02, 0.02, 0.02), 0.1, coat=1.0),
        "white": mat("Fitting_white", (0.88, 0.88, 0.86), 0.35), "red": mat("Call_red", (0.6, 0.06, 0.05), 0.4),
    }

def cell_bench(m):
    """Fixed cell plinth with a wipe-clean blue mattress and a folded grey blanket. Front faces -Y (back against the wall)."""
    k = K(); L, Dp, H = 2.0, 0.7, 0.42
    box("plinth", (L, Dp, H), (0, 0, H / 2), k["concrete"], bevel=0.02)
    box("mattress", (L - 0.1, Dp - 0.08, 0.08), (0, 0.01, H + 0.04), k["mattress"], bevel=0.03)
    box("blanket", (0.55, 0.45, 0.1), (L / 2 - 0.4, 0.04, H + 0.13), k["blanket"], bevel=0.03)
    box("blanket_fold", (0.55, 0.45, 0.04), (L / 2 - 0.4, 0.03, H + 0.2), k["blanket"], bevel=0.015)

def cell_toilet(m):
    """Stainless steel cell toilet (no seat) on a plinth with a flush plate, behind a low modesty wall on its -X side.
    Back at +Y against the wall."""
    k = K()
    box("modesty_wall", (0.12, 1.0, 1.05), (-0.42, -0.05, 0.525), k["block"], bevel=0.015)
    box("modesty_cap", (0.14, 1.02, 0.03), (-0.42, -0.05, 1.065), k["concrete"], bevel=0.008)
    cyl("pan_base", 0.17, 0.32, (0.1, 0.0, 0.16), k["steel"], verts=40, r2=0.2)
    cyl("pan_bowl", 0.22, 0.1, (0.1, -0.03, 0.37), k["steel"], verts=40, r2=0.24)
    cyl("pan_rim", 0.24, 0.025, (0.1, -0.03, 0.43), k["steel"], verts=40)
    cyl("pan_hole", 0.17, 0.03, (0.1, -0.03, 0.435), mat("Pan_inner_dark", (0.15, 0.15, 0.15), 0.2), verts=40)
    box("cistern_cover", (0.42, 0.12, 0.35), (0.1, 0.33, 0.6), k["steel"], bevel=0.02)
    box("flush_plate", (0.12, 0.012, 0.12), (0.1, 0.264, 0.85), k["steel"], bevel=0.008)
    cyl("flush_button", 0.03, 0.015, (0.1, 0.257, 0.85), k["steel"], axis="Y", verts=20)

def cctv_dome(m):
    """Ceiling CCTV dome. Its base is at z 0.12 below the top: place it at z = ceiling height - 0.12."""
    k = K()
    cyl("base", 0.1, 0.03, (0, 0, 0.105), k["white"], verts=40)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.075, location=(0, 0, 0.09), segments=32, ring_count=16)
    d = bpy.context.active_object; d.name = "dome"; d.data.materials.append(k["black"])
    for p in d.data.polygons: p.use_smooth = True

def cell_call_point(m):
    """Anti-ligature cell call point: steel plate with a call button and speaker grille. Back at +Y; place at z 1.1."""
    k = K()
    box("plate", (0.16, 0.012, 0.24), (0, 0, 0.12), k["steel"], bevel=0.008)
    cyl("button", 0.025, 0.012, (0, -0.012, 0.07), k["red"], axis="Y", verts=24)
    for i in range(5): box(f"grille{i}", (0.08, 0.004, 0.006), (0, -0.007, 0.15 + i * 0.015), k["black"], bevel=0)

# ================================================================== UK park
def P():
    return {"iron": mat("Cast_iron_black", (0.02, 0.02, 0.02), 0.45, 0.6), "teak": mat("Bench_teak_weathered", (0.42, 0.33, 0.24), 0.75),
            "brass": mat("Plaque_brass", (0.72, 0.55, 0.28), 0.3, 1.0), "bin_black": mat("Bin_black", (0.03, 0.03, 0.03), 0.4, 0.3),
            "gold": mat("Bin_gold", (0.7, 0.55, 0.2), 0.35, 0.8), "red": mat("Dog_bin_red", (0.6, 0.04, 0.04), 0.4),
            "post_grey": mat("Post_grey", (0.35, 0.36, 0.37), 0.5, 0.4), "green": mat("Sign_green", (0.05, 0.22, 0.12), 0.5),
            "white": mat("Sign_white", (0.9, 0.9, 0.88), 0.6), "concrete": mat("Bin_base_concrete", (0.55, 0.55, 0.53), 0.85)}

def park_bench(m):
    """Traditional UK park bench: black cast-iron ends, weathered wooden slats, memorial plaque on the back.
    Front faces -Y (people sit facing -Y)."""
    p = P(); L = 1.8
    for sx in (-L / 2 + 0.06, L / 2 - 0.06):
        tube(f"end_frame{sx}", [(sx, -0.28, 0.0), (sx, -0.22, 0.42), (sx, 0.2, 0.42), (sx, 0.26, 0.0)], 0.022, p["iron"])
        tube(f"end_back{sx}", [(sx, 0.18, 0.42), (sx, 0.3, 0.88)], 0.022, p["iron"])
        tube(f"end_arm{sx}", [(sx, -0.3, 0.62), (sx, -0.25, 0.65), (sx, 0.2, 0.66)], 0.02, p["iron"])
        tube(f"end_armpost{sx}", [(sx, -0.25, 0.42), (sx, -0.28, 0.63)], 0.018, p["iron"])
        box(f"armrest{sx}", (0.07, 0.4, 0.03), (sx, -0.04, 0.675), p["teak"], bevel=0.01)
    for k in range(4): box(f"seat_slat{k}", (L, 0.085, 0.035), (0, -0.2 + k * 0.11, 0.44), p["teak"], bevel=0.008)
    for k in range(3):
        y = 0.22 + k * 0.03; z = 0.55 + k * 0.12
        box(f"back_slat{k}", (L - 0.02, 0.035, 0.09), (0, y, z), p["teak"], bevel=0.008, rot=("X", -18))
    box("plaque", (0.16, 0.008, 0.05), (0.0, 0.265, 0.79), p["brass"], bevel=0.002, rot=("X", -18))

def litter_bin(m):
    """Black UK street litter bin with a gold band and a domed hood."""
    p = P()
    cyl("base", 0.25, 0.06, (0, 0, 0.03), p["concrete"], verts=40)
    cyl("body", 0.24, 0.7, (0, 0, 0.41), p["bin_black"], verts=40, r2=0.23)
    cyl("band", 0.242, 0.05, (0, 0, 0.62), p["gold"], verts=40)
    cyl("band2", 0.242, 0.02, (0, 0, 0.18), p["gold"], verts=40)
    cyl("hood", 0.25, 0.12, (0, 0, 0.82), p["bin_black"], verts=40, r2=0.16)
    cyl("top", 0.16, 0.04, (0, 0, 0.9), p["bin_black"], verts=40, r2=0.05)
    box("aperture", (0.2, 0.03, 0.07), (0, -0.2, 0.82), mat("Bin_inside", (0.005, 0.005, 0.005), 0.9), bevel=0)

def dog_bin(m):
    """Red dog-waste bin on a grey post. Front (opening) faces -Y."""
    p = P()
    cyl("post", 0.04, 1.1, (0, 0.05, 0.55), p["post_grey"], verts=20)
    box("bin", (0.34, 0.26, 0.42), (0, -0.09, 0.95), p["red"], bevel=0.03)
    box("lid", (0.36, 0.28, 0.04), (0, -0.09, 1.18), p["red"], bevel=0.015)
    box("flap", (0.24, 0.01, 0.1), (0, -0.225, 1.06), mat("Dog_bin_flap", (0.45, 0.03, 0.03), 0.4), bevel=0)
    box("label", (0.2, 0.005, 0.12), (0, -0.223, 0.88), p["white"], bevel=0)

def park_sign(m):
    """Green park noticeboard on two posts. Front faces -Y."""
    p = P()
    for sx in (-0.55, 0.55): box(f"post{sx}", (0.08, 0.08, 1.9), (sx, 0, 0.95), p["green"], bevel=0.01)
    box("board", (1.2, 0.05, 0.75), (0, -0.04, 1.45), p["green"], bevel=0.015)
    box("face", (1.08, 0.006, 0.62), (0, -0.068, 1.45), p["white"], bevel=0)
    box("title_band", (1.08, 0.008, 0.12), (0, -0.07, 1.68), p["green"], bevel=0)
    for k in range(5): box(f"line{k}", (0.8 - (k % 2) * 0.2, 0.004, 0.025), (-0.05, -0.073, 1.55 - k * 0.08), mat("Sign_text_grey", (0.3, 0.3, 0.3), 0.6), bevel=0)
    box("cap", (1.3, 0.12, 0.05), (0, -0.03, 1.85), p["green"], bevel=0.01)

# ------------------------------------------------------------------ Halloween
def prism(name, pts2d, y0, y1, m):
    """A flat shape (list of (x, z)) extruded along Y from y0 to y1."""
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    front = [bm.verts.new((x, y0, z)) for x, z in pts2d]; back = [bm.verts.new((x, y1, z)) for x, z in pts2d]
    bm.faces.new(front); bm.faces.new(list(reversed(back)))
    n = len(pts2d)
    for i in range(n): bm.faces.new((front[i], front[(i + 1) % n], back[(i + 1) % n], back[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free(); me.materials.append(m)
    return link(bpy.data.objects.new(name, me))

def jack_o_lantern(m):
    """A carved pumpkin, lit from inside: ribbed orange body, stem, and a glowing face (triangle eyes and nose, toothy grin)
    on the -Y side that follows the curve of the skin."""
    orange = mat("Pumpkin_skin", (0.62, 0.17, 0.01), 0.55); stem = mat("Pumpkin_stem", (0.12, 0.09, 0.03), 0.8)
    glow = emat("Pumpkin_glow", (1.0, 0.45, 0.06), 12.0)
    R, H = 0.17, 0.26
    def rad(z):                                         # radius of the body at height z (without ribs)
        zs = max(-1.0, min(1.0, z / H * 2 - 1)); return R * math.sqrt(max(0.0, 1 - zs * zs)) * (1 - 0.18 * abs(zs) ** 3)
    me = bpy.data.meshes.new("pumpkin"); bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=1.0)
    for v in bm.verts:
        a = math.atan2(v.co.y, v.co.x); rib = 1 + 0.05 * math.cos(10 * a)
        zs = v.co.z; flat = 1 - 0.18 * abs(zs) ** 3
        v.co.x *= R * rib * flat; v.co.y *= R * rib * flat; v.co.z = (zs * 0.5 + 0.5) * H
    bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    me.materials.append(orange); link(bpy.data.objects.new("pumpkin", me))
    cyl("stem", 0.018, 0.07, (0.005, 0, H + 0.02), stem, r2=0.012)
    def face_piece(name, pts):
        """A glowing shape on the front: its front face sits on the skin, its back sinks into the pumpkin."""
        me = bpy.data.meshes.new(name); bm = bmesh.new()
        fr = [bm.verts.new((x, -math.sqrt(max(1e-6, (rad(z) * 1.065) ** 2 - x * x)), z)) for x, z in pts]   # just outside the ribs
        bk = [bm.verts.new((x, -rad(z) * 0.55, z)) for x, z in pts]
        bm.faces.new(fr); bm.faces.new(list(reversed(bk)))
        n = len(pts)
        for i in range(n): bm.faces.new((fr[i], fr[(i + 1) % n], bk[(i + 1) % n], bk[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(me); bm.free(); me.materials.append(glow)
        link(bpy.data.objects.new(name, me))
    for sx in (-1, 1):
        face_piece(f"eye{sx}", [(sx * 0.025, 0.155), (sx * 0.085, 0.155), (sx * 0.055, 0.2)])
    face_piece("nose", [(-0.016, 0.125), (0.016, 0.125), (0, 0.148)])
    face_piece("mouth", [(-0.095, 0.105), (-0.06, 0.088), (-0.042, 0.1), (-0.025, 0.082), (0.0, 0.094), (0.025, 0.082), (0.042, 0.1), (0.06, 0.088), (0.095, 0.105),
                         (0.07, 0.065), (0.035, 0.056), (0.0, 0.052), (-0.035, 0.056), (-0.07, 0.065)])

def candles(m):
    """Three church candles of different heights, lit, with wax drips, on a small dish."""
    wax = mat("Candle_wax", (0.82, 0.76, 0.6), 0.6); flame = emat("Candle_flame", (1.0, 0.62, 0.2), 20.0)
    dish = mat("Candle_dish_pewter", (0.35, 0.35, 0.34), 0.35, 0.8)
    cyl("dish", 0.15, 0.015, (0, 0, 0.0075), dish, verts=40)
    for i, (x, y, r, h) in enumerate(((-0.05, 0.02, 0.035, 0.22), (0.045, 0.03, 0.03, 0.15), (0.0, -0.05, 0.028, 0.1))):
        cyl(f"candle{i}", r, h, (x, y, 0.015 + h / 2), wax, verts=28)
        for k in range(3):
            a = k * 2.1 + i
            cyl(f"drip{i}_{k}", 0.006, 0.04 + 0.02 * k, (x + math.cos(a) * r * 0.98, y + math.sin(a) * r * 0.98, 0.015 + h - 0.02 - 0.01 * k), wax, verts=8)
        cyl(f"wick{i}", 0.0015, 0.012, (x, y, 0.015 + h + 0.006), mat("Wick", (0.02, 0.02, 0.02), 0.9), verts=6)
        cyl(f"flame{i}", 0.007, 0.03, (x, y, 0.015 + h + 0.025), flame, verts=12, r2=0.0005)

MODELS = {
    "rb_hospital_bed": ("Hospital bed", hospital_bed, "beds", "Profiling hospital bed, back raised, made up with sheet, pillow and folded cellular blanket. Head end at +Y (against the wall). 2.15 x 1.0 m."),
    "rb_bedside_locker": ("Bedside locker", bedside_locker, "storage", "Ward bedside cabinet on castors with water jug and cup."),
    "rb_overbed_table": ("Over-bed table", overbed_table, "tables", "Height-adjustable over-bed table."),
    "rb_drip_stand": ("Drip stand with pump", drip_stand, "medical", "Five-leg IV stand with bag and infusion pump."),
    "rb_bay_curtain": ("Bay curtain (pulled back)", bay_curtain, "medical", "2.6 m ceiling track with the curtain gathered at one end. Place at z 0.3 so the track sits near a 2.2 m ceiling."),
    "rb_handwash_station": ("Clinical hand-wash station", handwash_station, "medical", "Wall basin with splashback, soap, gel, towel dispenser and pedal bin. Back against the wall."),
    "rb_ward_chair": ("Ward high-back chair", ward_chair, "seating", "Wipe-clean high-back patient chair."),
    "rb_obs_monitor": ("Observations monitor", obs_monitor, "medical", "Mobile vital-signs monitor on a five-leg stand."),
    "rb_linen_trolley": ("Linen trolley", linen_trolley, "medical", "Ward linen skip on castors."),
    "rb_judge_bench": ("Judge's bench (UK court)", judge_bench, "court", "Carpeted dais, panelled oak bench, three high-back chairs, tall back panel with a plain roundel. 3.6 x 2.0 m, 2.2 m tall. Front faces -Y.", {"styles": ["court"], "tags": ["court", "judge", "uk"]}),
    "rb_clerk_desk": ("Court clerk's desk", clerk_desk, "court", "Raised panelled front, monitors, files; chair on the +Y side. 2.4 m wide.", {"styles": ["court"], "tags": ["court", "clerk", "uk"]}),
    "rb_witness_box": ("Witness box", witness_box, "court", "Raised panelled witness box with ledge, microphone and water; open at the back.", {"styles": ["court"], "tags": ["court", "witness", "uk"]}),
    "rb_jury_box": ("Jury box (12 seats)", jury_box, "court", "Two tiers of six upholstered seats behind a panelled front. 3.6 x 1.9 m. Faces -Y.", {"styles": ["court"], "tags": ["court", "jury", "uk"]}),
    "rb_secure_dock": ("Secure dock", secure_dock, "court", "Glass-screened dock on a panelled base with a bench for four. 3.0 x 1.7 m, 2.12 m tall. Glass front faces -Y.", {"styles": ["court"], "tags": ["court", "dock", "uk"]}),
    "rb_cell_bench": ("Cell bench with mattress", cell_bench, "custody", "Fixed plinth with blue wipe-clean mattress and grey blanket. 2.0 x 0.7 m. Back against the wall.", {"styles": ["custody"], "tags": ["custody", "cell", "police", "uk"]}),
    "rb_cell_toilet": ("Cell toilet and modesty wall", cell_toilet, "custody", "Stainless steel toilet, no seat, flush plate, low modesty wall on one side. Back against the wall.", {"styles": ["custody"], "tags": ["custody", "cell", "police", "uk"]}),
    "rb_cctv_dome": ("CCTV dome", cctv_dome, "custody", "Ceiling camera dome. Place at z = ceiling height - 0.12.", {"styles": ["custody", "hospital", "court"], "tags": ["cctv", "camera"]}),
    "rb_cell_call_point": ("Cell call point", cell_call_point, "custody", "Steel call button and speaker plate. Place at z 1.1 against a wall.", {"styles": ["custody"], "tags": ["custody", "cell", "uk"]}),
    "rb_park_bench": ("Park bench (UK)", park_bench, "outdoor", "Cast-iron ends, wooden slats, memorial plaque. 1.8 m. Front faces -Y.", {"styles": ["outdoor", "modern"], "tags": ["park", "bench", "uk"]}),
    "rb_litter_bin": ("Litter bin (UK)", litter_bin, "outdoor", "Black street bin with gold band.", {"styles": ["outdoor"], "tags": ["park", "bin", "uk"]}),
    "rb_dog_bin": ("Dog-waste bin", dog_bin, "outdoor", "Red dog-waste bin on a post. Opening faces -Y.", {"styles": ["outdoor"], "tags": ["park", "bin", "uk"]}),
    "rb_park_sign": ("Park noticeboard", park_sign, "outdoor", "Green noticeboard on two posts. Faces -Y.", {"styles": ["outdoor"], "tags": ["park", "sign", "uk"]}),
    "rb_jack_o_lantern": ("Jack-o'-lantern (lit)", jack_o_lantern, "decor", "Carved pumpkin with a glowing face on the -Y side. About 0.35 m across.", {"styles": ["modern", "neglected"], "tags": ["halloween", "pumpkin", "seasonal"]}),
    "rb_candles": ("Candles (lit)", candles, "decor", "Three lit church candles on a pewter dish.", {"styles": ["modern", "neglected"], "tags": ["halloween", "candle", "light"]}),
}

def clear():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        for d in list(coll):
            if d.users == 0: coll.remove(d)

def thumbnail(path):
    sc = bpy.context.scene
    bpy.context.view_layer.update()
    objs = [o for o in sc.objects if o.type in ("MESH", "CURVE")]
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        oe = o.evaluated_get(dg)
        pts += [oe.matrix_world @ Vector(c) for c in oe.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (mn + mx) / 2; rad = (mx - mn).length / 2
    cam_d = bpy.data.cameras.new("thumbcam"); cam_d.lens = 50
    cam = bpy.data.objects.new("thumbcam", cam_d); sc.collection.objects.link(cam)
    d = Vector((0.75, -1.0, 0.55)).normalized()
    cam.location = ctr + d * rad * 2.05
    cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    ld = bpy.data.lights.new("key", "AREA"); ld.energy = 300 * max(1, rad) ** 2; ld.size = 2
    key = bpy.data.objects.new("key", ld); sc.collection.objects.link(key)
    key.location = ctr + Vector((-1.5, -2, 3)) * max(1, rad)
    key.rotation_euler = (ctr - key.location).to_track_quat("-Z", "Y").to_euler()
    w = sc.world or bpy.data.worlds.new("W"); sc.world = w; w.use_nodes = True
    bg = w.node_tree.nodes.get("Background"); bg.inputs[0].default_value = (0.32, 0.34, 0.36, 1); bg.inputs[1].default_value = 1.0
    sc.render.engine = "CYCLES"; sc.cycles.samples = 48; sc.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dt in ("OPTIX", "CUDA"):
            prefs.compute_device_type = dt; prefs.get_devices()
            if any(dv.type == dt for dv in prefs.devices):
                for dv in prefs.devices: dv.use = dv.type == dt
                sc.cycles.device = "GPU"; break
    except Exception: pass
    sc.render.resolution_x = sc.render.resolution_y = 256; sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"; sc.render.filepath = path
    sc.view_settings.view_transform = "AgX"
    bpy.ops.render.render(write_still=True)
    for o in (cam, key): bpy.data.objects.remove(o, do_unlink=True)

for mid, entry in MODELS.items():
    name, fn, category, notes = entry[:4]
    extra = entry[4] if len(entry) > 4 else {}
    if ONLY and mid not in ONLY: continue
    clear()
    m = M()
    fn(m)
    d = os.path.join(CAT, mid); os.makedirs(d, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in bpy.context.scene.objects:
        if o.type in ("MESH", "CURVE"): o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(d, mid + ".glb"), export_format="GLB", use_selection=True, export_apply=True)
    thumbnail(os.path.join(d, "thumb.png"))
    meta = {"id": mid, "name": name, "file": mid + ".glb", "thumb": "thumb.png", "category": category,
            "styles": extra.get("styles", ["hospital", "modern"]), "tags": extra.get("tags", ["hospital", "ward", "clinical"]), "status": "untested", "notes": notes,
            "scale": 1.0, "polycount": None,
            "licence": {"source": "Room Builder", "author": "Own model (made for Room Builder)", "licence": "Own work",
                        "licence_url": "", "url": "", "credit_required": False}}
    old = os.path.join(d, "model.json")
    if os.path.exists(old):                          # keep Jamie's status and notes if the model is rebuilt
        try:
            prev = json.load(open(old, encoding="utf-8"))
            for k in ("status", "notes", "styles", "scale", "category"): meta[k] = prev.get(k, meta[k])
        except Exception: pass
    json.dump(meta, open(old, "w", encoding="utf-8"), indent=2)
    print("RB_MODEL", mid, flush=True)
print("RB_DONE", flush=True)
