"""Turn an uploaded model (FBX, OBJ, glTF/GLB, STL) into a catalogue model: one GLB, a thumbnail and its size.

    blender -b --factory-startup -P tools/import_model.py -- <input file> <output folder>

Writes model.glb (textures inside it), thumb.png (256 x 256, transparent) and info.json
({"size": [width, depth, height] in metres, "polycount", "warnings": [...]}) to the output folder.
The model is moved so the middle of its footprint is at the origin and its lowest point is on the floor
(that is how Room Builder and the tours stand models on things). Animation is left out; a rigged model keeps its rest pose.
Used by server.py (/api/catalogue/upload). Errors go in info.json as "error"."""
import bpy, sys, os, json, math, traceback
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = os.path.abspath(argv[0]), os.path.abspath(argv[1])
os.makedirs(out, exist_ok=True)
info = {"warnings": []}

def save():
    with open(os.path.join(out, "info.json"), "w", encoding="utf-8") as f: json.dump(info, f, indent=1)

try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext = os.path.splitext(src)[1].lower()
    if ext == ".fbx": bpy.ops.import_scene.fbx(filepath=src, use_anim=False)
    elif ext == ".obj": bpy.ops.wm.obj_import(filepath=src)
    elif ext in (".gltf", ".glb"): bpy.ops.import_scene.gltf(filepath=src)
    elif ext == ".stl": bpy.ops.wm.stl_import(filepath=src)
    else: raise ValueError(f"Can't read {ext} files (use FBX, OBJ, GLB/glTF or STL)")

    for o in list(bpy.data.objects):                       # cameras and lights from the file aren't wanted
        if o.type in ("CAMERA", "LIGHT"): bpy.data.objects.remove(o, do_unlink=True)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes: raise ValueError("There is no mesh in this file")
    bpy.context.view_layer.update()

    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    size = mx - mn
    root = bpy.data.objects.new("model", None); bpy.context.scene.collection.objects.link(root)
    for o in list(bpy.data.objects):
        if o is not root and o.parent is None:
            mw = o.matrix_world.copy(); o.parent = root; o.matrix_world = mw
    root.location = (-(mn.x + mx.x) / 2, -(mn.y + mx.y) / 2, -mn.z)
    bpy.context.view_layer.update()

    info["size"] = [round(size.x, 4), round(size.y, 4), round(size.z, 4)]
    info["polycount"] = sum(len(o.data.polygons) for o in meshes)
    big = max(size)
    if big > 20: info["warnings"].append(f"It is {big:.1f} m across: if it should be smaller it was probably made in centimetres (set its Scale to 0.01).")
    if big < 0.01: info["warnings"].append(f"It is only {big * 1000:.1f} mm across: if it should be bigger set its Scale (e.g. 100 if it was made in metres as centimetres).")
    if info["polycount"] > 300000: info["warnings"].append(f"{info['polycount']:,} polygons is heavy for the room PC; keep items under about 50,000.")
    missing = []
    for im in bpy.data.images:
        if im.source == "FILE" and not im.packed_file:
            try: im.reload()
            except Exception: pass
            if im.size[0] == 0: missing.append(os.path.basename(im.filepath) or im.name)
    if missing: info["warnings"].append("Textures not found (upload a .zip with the model and its texture files): " + ", ".join(sorted(set(missing))[:8]))

    bpy.ops.export_scene.gltf(filepath=os.path.join(out, "model.glb"), export_format="GLB", export_animations=False, export_yup=True)

    # thumbnail: workbench, textures, transparent background, three-quarter view from the front
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
    sc.render.resolution_x = sc.render.resolution_y = 256; sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_mode = "RGBA"
    cam_data = bpy.data.cameras.new("thumb"); cam_data.lens = 50
    cam = bpy.data.objects.new("thumb", cam_data); sc.collection.objects.link(cam); sc.camera = cam
    c = Vector((0, 0, size.z / 2)); r = max(size.length / 2, 0.01)
    fov = 2 * math.atan(18 / cam_data.lens)
    d = r / math.sin(fov / 2) * 1.05
    direction = Vector((0.55, -1.0, 0.55)).normalized()            # front is -Y in Blender (glTF +Z), a little from the right and above
    cam.location = c + direction * d
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_start = d / 100; cam_data.clip_end = d * 10
    sc.render.filepath = os.path.join(out, "thumb.png")
    bpy.ops.render.render(write_still=True)
    info["ok"] = True
except Exception as e:
    info["error"] = str(e); info["trace"] = traceback.format_exc()[-1500:]
save()
