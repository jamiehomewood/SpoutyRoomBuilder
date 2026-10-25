"""Draw Room Builder's starter decals (own work, no licence restrictions) into catalogue/decals/.

Each decal is a PNG with transparency plus an entry in catalogue/decals/decals.json giving its real-world size in metres.
Run with any Python that has Pillow:   python tools/make_decals.py
"""
import json, math, os, random
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "catalogue", "decals")
PPM = 1000                                   # pixels per metre (1 mm per pixel)
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts"]


def font(size, bold=True):
    for d in FONT_DIRS:
        for n in (("DejaVuSans-Bold.ttf", "arialbd.ttf") if bold else ("DejaVuSans.ttf", "arial.ttf")):
            p = os.path.join(d, n)
            if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def canvas(w_m, h_m, bg=(0, 0, 0, 0)):
    return Image.new("RGBA", (int(w_m * PPM), int(h_m * PPM)), bg)


def wobble(pts, amt, rnd):
    return [(x + rnd.uniform(-amt, amt), y + rnd.uniform(-amt, amt)) for x, y in pts]


def crayon_line(d, pts, col, width, rnd, passes=3):
    """A waxy crayon stroke: several slightly offset, semi-transparent passes."""
    for _ in range(passes):
        d.line(wobble(pts, width * 0.35, rnd), fill=(*col, rnd.randint(150, 220)), width=width, joint="curve")


def crayon_fill(img, poly, col, rnd):
    """Scribbly crayon fill inside a polygon."""
    mask = Image.new("L", img.size, 0); ImageDraw.Draw(mask).polygon(poly, fill=255)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    y = min(ys)
    while y < max(ys):
        d.line([(min(xs) - 20, y + rnd.uniform(-6, 6)), (max(xs) + 20, y + 25 + rnd.uniform(-6, 6))], fill=(*col, 170), width=7)
        y += 9
    layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", img.size, 0), mask))
    img.alpha_composite(layer)


def child_drawing():
    """A child's crayon drawing on A4 paper, taped to the wall: house, sun, tree and a family."""
    rnd = random.Random(3)
    img = canvas(0.297, 0.21, (250, 248, 240, 255)); d = ImageDraw.Draw(img)
    W, H = img.size
    crayon_line(d, [(0, H * 0.82), (W * 0.3, H * 0.8), (W * 0.6, H * 0.84), (W, H * 0.81)], (60, 160, 60), 9, rnd)   # grass
    crayon_fill(img, [(40, H * 0.84), (W - 40, H * 0.84), (W - 40, H - 10), (40, H - 10)], (90, 180, 70), rnd)
    house = [(W * 0.12, H * 0.82), (W * 0.12, H * 0.48), (W * 0.42, H * 0.48), (W * 0.42, H * 0.82)]
    crayon_fill(img, house, (230, 120, 60), rnd); crayon_line(d, house + [house[0]], (150, 60, 30), 6, rnd)
    roof = [(W * 0.09, H * 0.5), (W * 0.27, H * 0.24), (W * 0.45, H * 0.5)]
    crayon_fill(img, roof, (200, 40, 40), rnd); crayon_line(d, roof + [roof[0]], (140, 20, 20), 6, rnd)
    door = [(W * 0.24, H * 0.82), (W * 0.24, H * 0.64), (W * 0.31, H * 0.64), (W * 0.31, H * 0.82)]
    crayon_fill(img, door, (110, 70, 40), rnd)
    for wx in (0.15, 0.34):
        win = [(W * wx, H * 0.53), (W * (wx + 0.06), H * 0.53), (W * (wx + 0.06), H * 0.61), (W * wx, H * 0.61)]
        crayon_fill(img, win, (120, 190, 240), rnd); crayon_line(d, win + [win[0]], (40, 80, 160), 4, rnd)
    cx, cy, r = W * 0.85, H * 0.17, H * 0.09                                                                   # sun
    crayon_fill(img, [(cx + r * math.cos(a / 12 * 6.283), cy + r * math.sin(a / 12 * 6.283)) for a in range(12)], (250, 210, 40), rnd)
    for k in range(10):
        a = k / 10 * 6.283
        crayon_line(d, [(cx + r * 1.2 * math.cos(a), cy + r * 1.2 * math.sin(a)), (cx + r * 1.7 * math.cos(a), cy + r * 1.7 * math.sin(a))], (240, 180, 20), 5, rnd)
    for i, (fx, h, col) in enumerate(((0.55, 0.3, (40, 60, 200)), (0.64, 0.33, (200, 40, 160)), (0.72, 0.2, (240, 120, 20)))):   # family
        top = H * (0.82 - h); hx = W * fx
        d.ellipse([hx - 16, top - 16, hx + 16, top + 16], outline=(*col, 220), width=5)
        crayon_line(d, [(hx, top + 16), (hx, H * 0.72)], col, 5, rnd)
        crayon_line(d, [(hx - 22, top + 42), (hx + 22, top + 42)], col, 5, rnd)
        crayon_line(d, [(hx, H * 0.72), (hx - 14, H * 0.82)], col, 5, rnd); crayon_line(d, [(hx, H * 0.72), (hx + 14, H * 0.82)], col, 5, rnd)
    d.text((W * 0.06, H * 0.05), "MY HOUSE", font=font(26), fill=(60, 60, 200, 220))
    for tx, ty in ((0, 0), (W - 60, 0)):                                                                          # sticky tape
        d.rectangle([tx + 5, ty, tx + 55, ty + 22], fill=(235, 230, 200, 150))
    img = img.rotate(rnd.uniform(-3, 3), resample=Image.BICUBIC, expand=True)
    return img, "Child's drawing (taped up)", 0.31, "drawing"


def crayon_scribbles():
    """Crayon scribbles drawn straight on a wall at child height."""
    rnd = random.Random(11)
    img = canvas(0.7, 0.45); d = ImageDraw.Draw(img); W, H = img.size
    for col in ((220, 40, 40), (40, 90, 220), (40, 160, 60), (240, 160, 20)):
        x, y = rnd.uniform(0.1, 0.9) * W, rnd.uniform(0.2, 0.8) * H
        pts = []
        for k in range(40):
            x += rnd.uniform(-60, 60); y += rnd.uniform(-35, 35)
            pts.append((min(W - 10, max(10, x)), min(H - 10, max(10, y))))
        crayon_line(d, pts, col, 6, rnd, passes=2)
    cx, cy = W * 0.7, H * 0.4                                                                                      # a stick figure
    d.ellipse([cx - 30, cy - 90, cx + 30, cy - 30], outline=(40, 40, 40, 200), width=6)
    crayon_line(d, [(cx, cy - 30), (cx, cy + 60)], (40, 40, 40), 6, rnd)
    crayon_line(d, [(cx - 45, cy), (cx + 45, cy - 10)], (40, 40, 40), 6, rnd)
    crayon_line(d, [(cx, cy + 60), (cx - 30, cy + 130)], (40, 40, 40), 6, rnd); crayon_line(d, [(cx, cy + 60), (cx + 30, cy + 130)], (40, 40, 40), 6, rnd)
    return img, "Crayon scribbles on the wall", 0.7, "drawing"


def spray(img, text, size, fill, outline, rnd, drips=True, angle=-6):
    """Spray-paint lettering: soft overspray, bold outline, drips."""
    W, H = img.size
    f = font(size)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    bb = d.textbbox((0, 0), text, font=f, stroke_width=int(size * 0.08))
    x = (W - (bb[2] - bb[0])) / 2; y = (H - (bb[3] - bb[1])) / 2 - bb[1]
    d.text((x, y), text, font=f, fill=(*fill, 235), stroke_width=int(size * 0.08), stroke_fill=(*outline, 245))
    if drips:
        for _ in range(int(len(text) * 2.5)):
            dx = rnd.uniform(x + 10, x + bb[2] - bb[0] - 10); top = y + bb[3] - size * 0.25
            ln = rnd.uniform(size * 0.15, size * 0.7); w = rnd.uniform(3, 7)
            d.line([(dx, top), (dx + rnd.uniform(-2, 2), top + ln)], fill=(*fill, 210), width=int(w))
            d.ellipse([dx - w, top + ln - w, dx + w, top + ln + w], fill=(*fill, 210))
    over = layer.filter(ImageFilter.GaussianBlur(size * 0.05)); over.putalpha(over.getchannel("A").point(lambda a: int(a * 0.45)))
    layer = layer.rotate(angle, resample=Image.BICUBIC, center=(W / 2, H / 2))
    over = over.rotate(angle, resample=Image.BICUBIC, center=(W / 2, H / 2))
    img.alpha_composite(over); img.alpha_composite(layer)


def graffiti_tag():
    rnd = random.Random(5)
    img = canvas(1.2, 0.5)
    spray(img, "ZEKO", 260, (20, 20, 25), (20, 20, 25), rnd, drips=True, angle=-8)
    d = ImageDraw.Draw(img); W, H = img.size
    d.line([(W * 0.12, H * 0.82), (W * 0.9, H * 0.7)], fill=(20, 20, 25, 220), width=10)                          # underline swoosh
    return img, "Graffiti tag (black spray)", 1.2, "graffiti"


def graffiti_piece():
    rnd = random.Random(8)
    img = canvas(2.2, 0.9)
    spray(img, "RB26", 520, (240, 120, 30), (30, 30, 120), rnd, drips=True, angle=-4)
    spray(img, "★", 200, (250, 220, 40), (30, 30, 120), rnd, drips=False, angle=0)
    return img, "Graffiti piece (colour bubble letters)", 2.2, "graffiti"


def graffiti_scrawl():
    rnd = random.Random(21)
    img = canvas(0.9, 0.4)
    spray(img, "OI!", 220, (200, 30, 40), (200, 30, 40), rnd, drips=True, angle=5)
    return img, "Scrawl (red spray)", 0.9, "graffiti"


def poster_handwash():
    """A plain A3 hospital-style poster (generic, no NHS logo). Drawn at 2 px per mm for crisp text."""
    img = Image.new("RGBA", (594, 840), (255, 255, 255, 255)); d = ImageDraw.Draw(img); W, H = img.size
    d.rectangle([0, 0, W, 110], fill=(0, 94, 184, 255))
    d.text((W / 2, 55), "INFECTION CONTROL", font=font(40), fill=(255, 255, 255, 255), anchor="mm")
    d.text((W / 2, 200), "Please wash", font=font(64), fill=(0, 48, 135, 255), anchor="mm")
    d.text((W / 2, 280), "your hands", font=font(64), fill=(0, 48, 135, 255), anchor="mm")
    cx, cy = W / 2 + 30, 400                                                                         # a simple tap and drops
    d.rounded_rectangle([cx - 150, cy - 40, cx + 20, cy], 12, fill=(120, 130, 140, 255))
    d.rectangle([cx - 20, cy, cx + 20, cy + 45], fill=(120, 130, 140, 255))
    for k, dy in enumerate((70, 130, 190)):
        d.ellipse([cx - 14, cy + dy, cx + 14, cy + dy + 38], fill=(65, 182, 230, 255))
    d.text((W / 2, 700), "before and after", font=font(34, False), fill=(40, 40, 40, 255), anchor="mm")
    d.text((W / 2, 750), "every patient contact", font=font(34, False), fill=(40, 40, 40, 255), anchor="mm")
    d.rectangle([0, H - 30, W, H], fill=(0, 94, 184, 255))
    return img, "Poster: please wash your hands", 0.297, "poster"


def sign_no_smoking():
    img = canvas(0.2, 0.2); d = ImageDraw.Draw(img); W, H = img.size
    d.rounded_rectangle([0, 0, W, H], 10, fill=(255, 255, 255, 255))
    d.rectangle([W * 0.18, H * 0.47, W * 0.72, H * 0.56], fill=(30, 30, 30, 255)); d.rectangle([W * 0.72, H * 0.47, W * 0.8, H * 0.56], fill=(230, 120, 30, 255))
    d.ellipse([W * 0.08, H * 0.08, W * 0.92, H * 0.92], outline=(210, 20, 30, 255), width=18)
    d.line([(W * 0.2, H * 0.2), (W * 0.8, H * 0.8)], fill=(210, 20, 30, 255), width=18)
    return img, "No smoking sign", 0.2, "sign"


def mould_patch():
    rnd = random.Random(2)
    img = canvas(0.8, 0.6); d = ImageDraw.Draw(img); W, H = img.size
    for _ in range(2600):
        r = abs(rnd.gauss(0, 0.28)); a = rnd.uniform(0, 6.283)
        x, y = W * (0.5 + r * math.cos(a)), H * (0.4 + r * 0.8 * math.sin(a))
        s = rnd.uniform(1.5, 7) * max(0.3, 1 - r * 2)
        d.ellipse([x - s, y - s, x + s, y + s], fill=(20, 25, 15, int(rnd.uniform(90, 230) * max(0.15, 1 - r * 2.2))))
    return img.filter(ImageFilter.GaussianBlur(1.2)), "Black mould patch", 0.8, "damage"


def damp_stain():
    rnd = random.Random(4)
    img = canvas(1.0, 0.7); W, H = img.size
    base = Image.new("L", img.size, 0); d = ImageDraw.Draw(base)
    for _ in range(14):
        cx, cy, r = W * rnd.uniform(0.3, 0.7), H * rnd.uniform(0.25, 0.6), W * rnd.uniform(0.12, 0.25)
        d.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], fill=255)
    base = base.filter(ImageFilter.GaussianBlur(25)).point(lambda v: 255 if v > 120 else 0).filter(ImageFilter.GaussianBlur(4))
    edge = base.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(3)).point(lambda v: min(255, v * 4))
    stain = Image.new("RGBA", img.size, (120, 90, 50, 0)); stain.putalpha(base.point(lambda v: int(v * 0.35)))
    ring = Image.new("RGBA", img.size, (90, 60, 30, 0)); ring.putalpha(edge.point(lambda v: int(v * 0.6)))
    img.alpha_composite(stain); img.alpha_composite(ring)
    return img, "Damp stain with tide marks", 1.0, "damage"


def wall_crack():
    rnd = random.Random(9)
    img = canvas(0.6, 1.0); d = ImageDraw.Draw(img); W, H = img.size
    def branch(x, y, ang, ln, w):
        if ln < 30 or w < 1: return
        pts = [(x, y)]
        for _ in range(int(ln / 20)):
            ang += rnd.uniform(-0.5, 0.5); x += math.cos(ang) * 20; y += math.sin(ang) * 20; pts.append((x, y))
        d.line(pts, fill=(40, 35, 30, 230), width=int(w))
        if rnd.random() < 0.7: branch(x, y, ang + rnd.uniform(-1, 1), ln * 0.55, w * 0.6)
        branch(x, y, ang + rnd.uniform(-0.3, 0.3), ln * 0.6, w * 0.75)
    branch(W * 0.5, 0, 1.57, 700, 7)
    branch(W * 0.45, H * 0.35, 2.4, 300, 4)
    return img.filter(ImageFilter.GaussianBlur(0.6)), "Plaster crack", 0.6, "damage"


# ------------------------------------------------------------------ Halloween
def bats():
    """A flock of bat silhouettes."""
    rnd = random.Random(31)
    img = canvas(1.2, 0.6); d = ImageDraw.Draw(img); W, H = img.size
    for _ in range(9):
        cx, cy, s = rnd.uniform(0.1, 0.9) * W, rnd.uniform(0.15, 0.85) * H, rnd.uniform(40, 110)
        up = rnd.uniform(-0.3, 0.5)
        wing = []
        for sx in (1, -1):
            pts = [(cx, cy)]
            for k, (fx, fy) in enumerate(((0.35, -0.35 - up), (0.7, -0.5 - up), (1.0, -0.2 - up), (0.82, 0.05), (0.62, -0.05), (0.45, 0.12), (0.25, 0.02))):
                pts.append((cx + sx * fx * s, cy + fy * s))
            d.polygon(pts, fill=(12, 10, 14, 245))
        d.ellipse([cx - s * 0.12, cy - s * 0.18, cx + s * 0.12, cy + s * 0.2], fill=(12, 10, 14, 250))
        d.polygon([(cx - s * 0.1, cy - s * 0.14), (cx - s * 0.05, cy - s * 0.3), (cx - s * 0.01, cy - s * 0.15)], fill=(12, 10, 14, 250))
        d.polygon([(cx + s * 0.1, cy - s * 0.14), (cx + s * 0.05, cy - s * 0.3), (cx + s * 0.01, cy - s * 0.15)], fill=(12, 10, 14, 250))
    return img, "Bats (silhouettes)", 1.2, "halloween"


def cobweb():
    """A cobweb for a top-left corner: radial threads and sagging spiral, with dust."""
    rnd = random.Random(13)
    img = canvas(0.8, 0.8); d = ImageDraw.Draw(img); W, H = img.size
    angles = [i / 9 * (math.pi / 2) for i in range(10)]
    L = W * 1.0
    for a in angles:
        d.line([(0, 0), (math.cos(a) * L, math.sin(a) * L)], fill=(235, 235, 230, 170), width=2)
    for k in range(1, 14):
        r = L * k / 14 * rnd.uniform(0.95, 1.05)
        pts = []
        for i in range(len(angles) - 1):
            a0, a1 = angles[i], angles[i + 1]
            for t in (0, 0.25, 0.5, 0.75):
                a = a0 + (a1 - a0) * t; sag = 1 - 0.07 * math.sin(math.pi * t)
                pts.append((math.cos(a) * r * sag, math.sin(a) * r * sag))
        pts.append((math.cos(angles[-1]) * r, math.sin(angles[-1]) * r))
        d.line(pts, fill=(235, 235, 230, 150), width=2)
    for _ in range(3):                                                                                  # a few broken strands
        a = rnd.uniform(0, 1.5); r = rnd.uniform(0.4, 0.9) * L
        d.line([(math.cos(a) * r, math.sin(a) * r), (math.cos(a) * r + rnd.uniform(-40, 40), math.sin(a) * r + rnd.uniform(60, 140))], fill=(235, 235, 230, 130), width=2)
    return img.filter(ImageFilter.GaussianBlur(0.5)), "Cobweb (top-left corner)", 0.8, "halloween"


def pumpkin_drawing():
    """A child's Halloween drawing: pumpkin, ghost and bats, on orange paper, taped up."""
    rnd = random.Random(17)
    img = canvas(0.297, 0.21, (246, 214, 160, 255)); d = ImageDraw.Draw(img); W, H = img.size
    px, py, r = W * 0.33, H * 0.62, H * 0.27
    crayon_fill(img, [(px + r * 1.15 * math.cos(a / 20 * 6.283), py + r * 0.9 * math.sin(a / 20 * 6.283)) for a in range(20)], (235, 110, 20), rnd)
    crayon_line(d, [(px + r * 1.15 * math.cos(a / 20 * 6.283), py + r * 0.9 * math.sin(a / 20 * 6.283)) for a in range(21)], (170, 60, 10), 5, rnd)
    crayon_line(d, [(px, py - r * 0.9), (px + 6, py - r * 1.25)], (60, 110, 30), 7, rnd)
    for sx in (-1, 1):
        d.polygon([(px + sx * 20, py - 18), (px + sx * 55, py - 18), (px + sx * 38, py - 45)], fill=(30, 20, 10, 230))
    d.polygon([(px - 50, py + 20), (px - 25, py + 35), (px, py + 22), (px + 25, py + 35), (px + 50, py + 20), (px + 30, py + 55), (px - 30, py + 55)], fill=(30, 20, 10, 230))
    gx, gy = W * 0.75, H * 0.45                                                                       # ghost
    ghost = [(gx - 32, gy + 60), (gx - 32, gy - 10), (gx - 20, gy - 38), (gx, gy - 46), (gx + 20, gy - 38), (gx + 32, gy - 10), (gx + 32, gy + 60),
             (gx + 20, gy + 48), (gx + 8, gy + 60), (gx - 6, gy + 48), (gx - 20, gy + 60)]
    crayon_fill(img, ghost, (255, 255, 255), rnd); crayon_line(d, ghost + [ghost[0]], (90, 90, 110), 4, rnd)
    d.ellipse([gx - 15, gy - 20, gx - 5, gy - 6], fill=(20, 20, 20, 240)); d.ellipse([gx + 5, gy - 20, gx + 15, gy - 6], fill=(20, 20, 20, 240))
    d.text((W * 0.06, H * 0.06), "HAPPY HALLOWEEN", font=font(20), fill=(90, 30, 120, 230))
    for tx in (0, W - 60): d.rectangle([tx + 5, 0, tx + 55, 22], fill=(235, 230, 200, 150))
    img = img.rotate(rnd.uniform(-4, 4), resample=Image.BICUBIC, expand=True)
    return img, "Child's Halloween drawing", 0.31, "halloween"


def graffiti_boo():
    rnd = random.Random(23)
    img = canvas(1.3, 0.6)
    spray(img, "BOO!", 300, (245, 120, 15), (25, 10, 35), rnd, drips=True, angle=-7)
    return img, "BOO! (orange spray)", 1.3, "halloween"


def graffiti_trick():
    rnd = random.Random(29)
    img = canvas(2.0, 0.55)
    spray(img, "TRICK OR TREAT", 150, (120, 220, 60), (20, 40, 10), rnd, drips=True, angle=3)
    return img, "TRICK OR TREAT (green spray)", 2.0, "halloween"


def handprints():
    """Orange paint handprints, smeared, as if someone dragged their hands down the wall."""
    rnd = random.Random(37)
    img = canvas(0.6, 0.9); W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    for k, (hx, hy, ang) in enumerate(((0.32, 0.25, -12), (0.68, 0.32, 10), (0.45, 0.62, -4))):
        cx, cy = hx * W, hy * H
        c = (200, 70, 10, 220)
        d.ellipse([cx - 45, cy - 30, cx + 45, cy + 60], fill=c)                               # palm
        for f, (dx, ln) in enumerate(((-38, 70), (-14, 90), (10, 95), (34, 80))):              # fingers
            d.rounded_rectangle([cx + dx - 10, cy - 30 - ln, cx + dx + 10, cy - 20], 10, fill=c)
        d.rounded_rectangle([cx + 40, cy - 5, cx + 85, cy + 15], 10, fill=c)                  # thumb
        for _ in range(4):                                                                     # smears downward
            sx = cx + rnd.uniform(-40, 40); d.line([(sx, cy + 50), (sx + rnd.uniform(-6, 6), cy + 50 + rnd.uniform(60, 160))], fill=(200, 70, 10, 160), width=int(rnd.uniform(8, 18)))
    layer = layer.rotate(0, resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(1.5))
    img.alpha_composite(layer)
    return img, "Paint handprints (orange, smeared)", 0.6, "halloween"


DECALS = [("child_drawing_house", child_drawing), ("crayon_scribbles", crayon_scribbles), ("graffiti_tag", graffiti_tag),
          ("graffiti_piece", graffiti_piece), ("graffiti_scrawl", graffiti_scrawl), ("poster_handwash", poster_handwash),
          ("sign_no_smoking", sign_no_smoking), ("mould_patch", mould_patch), ("damp_stain", damp_stain), ("wall_crack", wall_crack),
          ("hw_bats", bats), ("hw_cobweb", cobweb), ("hw_pumpkin_drawing", pumpkin_drawing), ("hw_boo", graffiti_boo),
          ("hw_trick_or_treat", graffiti_trick), ("hw_handprints", handprints)]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(OUT, "decals.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {"decals": []}
    keep = [x for x in idx["decals"] if x.get("source") != "Room Builder"]   # uploaded decals stay
    made = []
    for did, fn in DECALS:
        img, name, width_m, cat = fn()
        # keep files modest: at most 1600 px across
        if img.width > 1600: img = img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS)
        img.save(os.path.join(OUT, did + ".png"), optimize=True)
        made.append({"id": did, "name": name, "file": did + ".png", "width": width_m, "aspect": round(img.height / img.width, 4),
                     "category": cat, "source": "Room Builder", "licence": "Own work"})
        print("wrote", did)
    json.dump({"decals": made + keep}, open(idx_path, "w"), indent=1)
