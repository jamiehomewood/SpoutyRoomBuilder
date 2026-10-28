"""Turn a finished 360 render sideways by a multiple of 90 degrees, without rendering again.

    blender -b --factory-startup -P tools/turn_view.py -- <library room folder> <view name> <degrees>

degrees (90, -90 or 180) is added to where everything sits in the picture: +90 moves what was on the Left wall to the
Front wall (and the Front to the Right). A 360 picture turns exactly by sliding it sideways, so nothing is re-rendered:
view_<view>.png is turned losslessly; view_<view>.jpg and thumb_<view>.jpg are made again from it (or turned from the
JPG if there is no PNG). Writes turn_info.json in the folder ({"ok": true} or {"error": ...}). Used by server.py
(/api/library/<id>/turn), which keeps the untouched originals in <folder>/_unturned first."""
import bpy, sys, os, json, traceback
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
d, view, by = os.path.abspath(argv[0]), argv[1], int(argv[2])
info = {"view": view, "by": by}

def load(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h, ch = img.size[0], img.size[1], img.channels
    px = np.empty(w * h * ch, dtype=np.float32); img.pixels.foreach_get(px)
    return img, px.reshape(h, w, ch)

def save(px, like, path, fmt, quality=92):
    h, w, ch = px.shape
    out = bpy.data.images.new("turned", w, h, alpha=(ch == 4), float_buffer=False)
    out.colorspace_settings.name = like.colorspace_settings.name
    out.pixels.foreach_set(px.ravel())
    out.file_format = fmt
    tmp = path + ".tmp"
    try: out.save(filepath=tmp, quality=quality)
    except TypeError: out.filepath_raw = tmp; out.save()
    os.replace(tmp, path)
    return out

def turn(px):
    w = px.shape[1]
    shift = by / 360 * w
    if abs(shift - round(shift)) > 1e-6: raise ValueError(f"{w} px wide can't turn by exactly {by} degrees")
    return np.roll(px, int(round(shift)), axis=1)                 # right in the picture = turning to the right

try:
    if by % 90: raise ValueError("Turn by 90, -90 or 180 degrees")
    png, jpg, thumb = (os.path.join(d, f"{p}_{view}.{e}") for p, e in (("view", "png"), ("view", "jpg"), ("thumb", "jpg")))
    src = png if os.path.exists(png) else jpg
    if not os.path.exists(src): raise ValueError(f"No picture for the view '{view}'")
    img, px = load(src)
    rolled = turn(px)
    if src == png:
        out = save(rolled, img, png, "PNG")
        chk = np.empty(rolled.size, dtype=np.float32); out.pixels.foreach_get(chk)      # lossless check
        info["png_max_error"] = float(np.abs(chk - rolled.ravel()).max())
    save(rolled, img, jpg, "JPEG", 92)
    tw, th = (768, 384)
    if os.path.exists(thumb):
        t_img = bpy.data.images.load(thumb, check_existing=False); tw, th = t_img.size[0], t_img.size[1]
    h, w, ch = rolled.shape                                        # thumbnail: the turned picture, scaled down in memory
    mem = bpy.data.images.new("thumbsrc", w, h, alpha=(ch == 4), float_buffer=False)
    mem.colorspace_settings.name = img.colorspace_settings.name
    mem.pixels.foreach_set(rolled.ravel()); mem.scale(tw, th)
    sp = np.empty(tw * th * mem.channels, dtype=np.float32); mem.pixels.foreach_get(sp)
    save(sp.reshape(th, tw, mem.channels), img, thumb, "JPEG", 90)
    info["size"] = [int(px.shape[1]), int(px.shape[0])]
    info["ok"] = True
except Exception as e:
    info["error"] = str(e); info["trace"] = traceback.format_exc()[-1500:]
with open(os.path.join(d, "turn_info.json"), "w", encoding="utf-8") as f: json.dump(info, f, indent=1)
