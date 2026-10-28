"""A graffiti pack for Room Builder's decals (own work, drawn here: no licence restrictions on the pictures).

Adds its PNGs to catalogue/decals/ and its entries to decals.json next to the starter decals. Its entries have their own
source ("Room Builder graffiti pack"), so make_decals.py keeps them and running this again replaces only its own.
Run with a Python that has Pillow:   python tools/make_graffiti.py
Tags are invented names; nothing rude, no real crews, slogans or artists' work.
Kinds: spray-can handstyle tags, chrome and colour throw-ups, big pieces with 3D shadows and double outlines, stencils,
drippy words, a heart, felt-tip marker writing, scratched marks (custody cells), buffed-over patches, stickers,
a thrown paint splat and spray symbols."""
import json, math, os, random
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "catalogue", "decals")
SOURCE = "Room Builder graffiti pack"
DIRS = ["C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu"]
FONTS = {"block": ["impact.ttf", "ariblk.ttf", "DejaVuSans-Bold.ttf"], "bubble": ["ariblk.ttf", "comicbd.ttf", "DejaVuSans-Bold.ttf"],
         "hand": ["segoescb.ttf", "segoesc.ttf", "inkfree.ttf", "DejaVuSans-Bold.ttf"], "marker": ["inkfree.ttf", "segoepr.ttf", "DejaVuSans.ttf"],
         "print": ["segoeprb.ttf", "comicbd.ttf", "DejaVuSans-Bold.ttf"]}

def font(kind, size):
    for n in FONTS[kind]:
        for d in DIRS:
            p = os.path.join(d, n)
            if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def shift(m, dx, dy):
    out = Image.new("L", m.size, 0); out.paste(m, (int(dx), int(dy))); return out

def union(a, b): return ImageChops.lighter(a, b)

def place(m, size, x, y):
    """m pasted at (x, y) on an empty mask of the given size."""
    out = Image.new("L", size, 0); out.paste(m, (int(x), int(y))); return out

def letters(text, f, stroke, rnd, rot=7.0, bounce=0.07, overlap=0.12):
    """Each letter drawn on its own, tilted and bounced a little. Returns (fill mask, outline mask) on one canvas."""
    size = f.size; gl = []
    for ch in text:
        if ch == " ": gl.append(None); continue
        bb = f.getbbox(ch, stroke_width=stroke)
        w, h = bb[2] - bb[0] + 40, bb[3] - bb[1] + 40
        fm, om = Image.new("L", (w, h), 0), Image.new("L", (w, h), 0)
        ImageDraw.Draw(om).text((20 - bb[0], 20 - bb[1]), ch, font=f, fill=255, stroke_width=stroke, stroke_fill=255)
        ImageDraw.Draw(fm).text((20 - bb[0], 20 - bb[1]), ch, font=f, fill=255)
        a = rnd.uniform(-rot, rot)
        gl.append((fm.rotate(a, Image.BICUBIC, expand=True), om.rotate(a, Image.BICUBIC, expand=True)))
    W = int(sum(g[1].width * (1 - overlap) if g else size * 0.35 for g in gl) + size * 0.9)
    H = int(max(g[1].height for g in gl if g) + size * bounce * 2 + size * 0.9)
    FM, OM = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
    x = size * 0.45
    for g in gl:
        if not g: x += size * 0.35; continue
        fm, om = g; y = int(size * 0.3 + size * bounce * (1 + rnd.uniform(-1, 1)))
        FM = union(FM, place(fm, (W, H), x, y)); OM = union(OM, place(om, (W, H), x, y))
        x += om.width * (1 - overlap)
    return FM, OM

def solid(size, col, mask, alpha=1.0):
    im = Image.new("RGBA", size, (*col, 255)); im.putalpha(mask.point(lambda v: int(v * alpha))); return im

def gradient(size, top, bottom):
    W, H = size; g = Image.new("RGBA", size)
    d = ImageDraw.Draw(g)
    for y in range(H):
        t = y / max(1, H - 1); d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    return g

def drips(img, mask, col, n, rnd, length=(0.1, 0.5), width=(5, 12)):
    """Paint runs from the bottom edge of the mask."""
    d = ImageDraw.Draw(img); W, H = mask.size; px = mask.load(); bbox = mask.getbbox()
    if not bbox: return
    for _ in range(n):
        x = rnd.randint(bbox[0] + 5, bbox[2] - 5)
        ys = [y for y in range(bbox[1], bbox[3]) if px[x, y] > 128]
        if not ys: continue
        y0 = max(ys); ln = rnd.uniform(*length) * (bbox[3] - bbox[1]); w = rnd.uniform(*width)
        d.line([(x, y0 - 3), (x + rnd.uniform(-2, 2), y0 + ln)], fill=(*col, 235), width=int(w))
        d.ellipse([x - w * 0.7, y0 + ln - w * 0.7, x + w * 0.7, y0 + ln + w * 0.7], fill=(*col, 235))

def compose(FM, OM, fill_top, fill_bot, outline, rnd, outer=None, outer_w=0, shadow=None, depth=0, sdir=(1, 1),
            highlight=True, overspray=0.35, n_drips=0, drip_col=None):
    """Bubble / block letters: overspray, 3D shadow, outer and inner outline, gradient fill, highlights, drips."""
    size = FM.size; img = Image.new("RGBA", size, (0, 0, 0, 0))
    OUTER = OM.filter(ImageFilter.MaxFilter(outer_w * 2 + 1)) if outer and outer_w else None
    edge = OUTER or OM
    if overspray:
        img.alpha_composite(solid(size, outer or outline, edge.filter(ImageFilter.GaussianBlur(max(4, size[1] * 0.015))), overspray))
    if shadow and depth:
        sh = Image.new("L", size, 0)
        for k in range(1, depth + 1): sh = union(sh, shift(edge, sdir[0] * k, sdir[1] * k))
        img.alpha_composite(solid(size, shadow, sh))
    if OUTER: img.alpha_composite(solid(size, outer, OUTER))
    img.alpha_composite(solid(size, outline, OM))
    g = gradient(size, fill_top, fill_bot); g.putalpha(FM); img.alpha_composite(g)
    if highlight:                                   # a white edge along the top of each letter
        band = ImageChops.subtract(FM, shift(FM, 0, max(3, FM.size[1] * 0.012))).filter(ImageFilter.GaussianBlur(1.2))
        img.alpha_composite(solid(size, (255, 255, 255), band, 0.75))
        for _ in range(6):                          # little shine marks
            bb = FM.getbbox()
            if not bb: break
            x = rnd.randint(bb[0], bb[2] - 1); y = rnd.randint(bb[1], bb[1] + (bb[3] - bb[1]) // 3)
            if FM.getpixel((x, y)) > 200:
                ImageDraw.Draw(img).ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 255, 255, 200))
    if n_drips: drips(img, FM, drip_col or fill_bot, n_drips, rnd)
    return img

def spray_text(text, kind, size, col, rnd, rot=4.0, bounce=0.04, overlap=0.04, weight=0.035, n_drips=6, overspray=0.4):
    """One-colour spray lettering (tags, drippy words)."""
    f = font(kind, size); FM, OM = letters(text, f, max(1, int(size * weight)), rnd, rot, bounce, overlap)
    img = Image.new("RGBA", OM.size, (0, 0, 0, 0))
    img.alpha_composite(solid(OM.size, col, OM.filter(ImageFilter.GaussianBlur(size * 0.03)), overspray))
    img.alpha_composite(solid(OM.size, col, OM))
    if n_drips: drips(img, OM, col, n_drips, rnd, (0.08, 0.45), (3, 8))
    return img

def swoosh(img, col, rnd, y=0.82, width=10, arrow=True):
    d = ImageDraw.Draw(img); W, H = img.size
    pts = [(W * (0.1 + 0.8 * t), H * y - math.sin(t * math.pi) * H * 0.08 + rnd.uniform(-3, 3)) for t in [k / 24 for k in range(25)]]
    d.line(pts, fill=(*col, 235), width=width, joint="curve")
    if arrow:
        x, yy = pts[-1]; d.polygon([(x + width * 3, yy - width * 0.5), (x - width, yy - width * 2.6), (x - width * 0.4, yy + width * 1.8)], fill=(*col, 235))

def crown(d, cx, cy, s, col, w=8):
    pts = [(cx - s, cy + s * 0.5), (cx - s, cy - s * 0.4), (cx - s * 0.5, cy), (cx, cy - s * 0.6), (cx + s * 0.5, cy), (cx + s, cy - s * 0.4), (cx + s, cy + s * 0.5), (cx - s, cy + s * 0.5)]
    d.line(pts, fill=(*col, 235), width=w, joint="curve")
    for x_, y_ in ((cx - s, cy - s * 0.4), (cx, cy - s * 0.6), (cx + s, cy - s * 0.4)): d.ellipse([x_ - w, y_ - w * 2.2, x_ + w, y_ - w * 0.2], fill=(*col, 235))

def pad(img, m=40):
    out = Image.new("RGBA", (img.width + 2 * m, img.height + 2 * m), (0, 0, 0, 0)); out.alpha_composite(img, (m, m)); return out

def tilt(img, a): return img.rotate(a, Image.BICUBIC, expand=True)

# ---------------------------------------------------------------- the decals: each returns (image, name, width in metres)
def tag(word, col, seed, extra=None, w=1.0, label=""):
    rnd = random.Random(seed)
    img = pad(spray_text(word, "hand", 300, col, rnd, n_drips=5), 30)
    if extra == "swoosh": swoosh(img, col, rnd)
    if extra == "crown": crown(ImageDraw.Draw(img), img.width * 0.78, img.height * 0.2, 60, col)
    if extra == "star":
        d = ImageDraw.Draw(img); cx, cy, r = img.width * 0.88, img.height * 0.25, 45
        d.polygon([(cx + r * (1 if k % 2 == 0 else 0.45) * math.cos(-math.pi / 2 + k * math.pi / 5), cy + r * (1 if k % 2 == 0 else 0.45) * math.sin(-math.pi / 2 + k * math.pi / 5)) for k in range(10)], fill=(*col, 235))
    return tilt(img, rnd.uniform(-7, 4)), label or f"Tag \"{word}\"", w

def throwup(word, top, bot, outline, seed, w, label):
    rnd = random.Random(seed); f = font("bubble", 420)
    FM, OM = letters(word, f, 34, rnd, rot=9, bounce=0.06, overlap=0.22)
    return tilt(compose(FM, OM, top, bot, outline, rnd, overspray=0.3, n_drips=4), rnd.uniform(-5, 3)), label, w

def piece(word, top, bot, outline, outer, shadow, seed, w, label, arrows=False):
    rnd = random.Random(seed); f = font("bubble", 460)
    FM, OM = letters(word, f, 22, rnd, rot=10, bounce=0.09, overlap=0.16)
    img = compose(FM, OM, top, bot, outline, rnd, outer=outer, outer_w=16, shadow=shadow, depth=28, sdir=(1, 1), n_drips=3)
    if arrows:                                    # arrows flicking off the letters (wildstyle-ish)
        d = ImageDraw.Draw(img); bb = OM.getbbox()
        for k in range(5):
            x = rnd.uniform(bb[0] + 60, bb[2] - 60); y = bb[1] + rnd.uniform(-10, 40); ang = rnd.uniform(-2.4, -0.7); L = rnd.uniform(90, 160)
            x2, y2 = x + math.cos(ang) * L, y + math.sin(ang) * L
            d.line([(x, y), (x2, y2)], fill=(*outer, 255), width=34); d.line([(x, y), (x2, y2)], fill=(*outline, 255), width=18)
            p = [(x2 + math.cos(ang) * 50, y2 + math.sin(ang) * 50), (x2 + math.cos(ang + 2.2) * 40, y2 + math.sin(ang + 2.2) * 40), (x2 + math.cos(ang - 2.2) * 40, y2 + math.sin(ang - 2.2) * 40)]
            d.polygon(p, fill=(*top, 255), outline=(*outer, 255), width=10)
    return tilt(img, rnd.uniform(-3, 2)), label, w

def stencil(text, col, seed, w, label, eye=False):
    rnd = random.Random(seed); f = font("block", 260)
    bb = f.getbbox(text); W, H = bb[2] - bb[0] + 160, bb[3] - bb[1] + 160 + (260 if eye else 0)
    m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
    oy = 260 if eye else 0
    d.text((80 - bb[0], 80 - bb[1] + oy), text, font=f, fill=255)
    for x in range(80 + 70, W - 80, 150):           # stencil bridges through the letters
        d.rectangle([x, 80 + oy, x + 12, H - 80], fill=0)
    if eye:                                         # an eye above the words
        cx, cy = W / 2, 150
        d.ellipse([cx - 230, cy - 95, cx + 230, cy + 95], fill=255); d.ellipse([cx - 210, cy - 78, cx + 210, cy + 78], fill=0)
        d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=255); d.ellipse([cx - 25, cy - 25, cx + 25, cy + 25], fill=0)
        d.rectangle([cx - 6, cy - 95, cx + 6, cy + 95], fill=0)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    haze = Image.new("L", (W, H), 0); ImageDraw.Draw(haze).rectangle([30, 30, W - 30, H - 30], fill=14)
    img.alpha_composite(solid((W, H), col, haze.filter(ImageFilter.GaussianBlur(30)), 0.6))   # the card's faint edge
    img.alpha_composite(solid((W, H), col, m.filter(ImageFilter.GaussianBlur(5)), 0.35))
    img.alpha_composite(solid((W, H), col, m))
    return tilt(img, rnd.uniform(-2, 2)), label, w

def drippy(word, col, seed, w, label):
    rnd = random.Random(seed)
    img = pad(spray_text(word, "block", 320, col, rnd, rot=6, bounce=0.06, overlap=0.02, weight=0.01, n_drips=22, overspray=0.45), 30)
    return tilt(img, rnd.uniform(-6, 6)), label, w

def heart(seed):
    rnd = random.Random(seed); W, H = 900, 820; img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
    pts = [(W / 2 + 16 * math.sin(t) ** 3 * 24, H * 0.46 - (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) * 24) for t in [k / 80 * 2 * math.pi for k in range(81)]]
    d.line(pts, fill=255, width=26, joint="curve")
    red = (205, 25, 40)
    img.alpha_composite(solid((W, H), red, m.filter(ImageFilter.GaussianBlur(10)), 0.4)); img.alpha_composite(solid((W, H), red, m))
    drips(img, m, red, 5, rnd, (0.05, 0.2), (4, 8))
    t = spray_text("J + K", "hand", 150, red, rnd, n_drips=2); img.alpha_composite(t, (int(W / 2 - t.width / 2), int(H * 0.3)))
    t2 = spray_text("4EVA", "hand", 110, red, rnd, n_drips=2); img.alpha_composite(t2, (int(W / 2 - t2.width / 2), int(H * 0.56)))
    return tilt(img, rnd.uniform(-8, 8)), "Heart \"J + K 4EVA\" (red spray)", 0.6

def marker(lines, col, seed, w, label, kind="marker", size=90):
    rnd = random.Random(seed); f = font(kind, size)
    W = int(max(f.getlength(l) for l in lines) + 320); H = int(len(lines) * size * 1.5 + 260)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); y = 60
    for l in lines:
        lay = Image.new("RGBA", (W, int(size * 2.4)), (0, 0, 0, 0))
        ImageDraw.Draw(lay).text((rnd.uniform(70, 120), size * 0.5), l, font=f, fill=(*col, 230), stroke_width=1, stroke_fill=(*col, 160))
        img.alpha_composite(lay.rotate(rnd.uniform(-4, 4), Image.BICUBIC), (0, int(y - size * 0.5))); y += size * 1.5
    return img, label, w

def scratched(seed, tally=True):
    """Scratched into paint: a pale gouge with a thin dark edge (shows on any wall colour)."""
    rnd = random.Random(seed); W, H = 900, 700; img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    def gouge(p, q):
        jit = lambda a: (a[0] + rnd.uniform(-2, 2), a[1] + rnd.uniform(-2, 2))
        d.line([jit(p), jit(q)], fill=(40, 34, 30, 110), width=4)
        d.line([(p[0] - 2, p[1] - 2), (q[0] - 2, q[1] - 2)], fill=(238, 234, 226, 210), width=3)
    if tally:
        for row in range(3):
            for g in range(5 if row < 2 else 3):
                x0, y0 = 60 + g * 160, 60 + row * 210
                n = 5 if not (row == 2 and g == 2) else 3
                for k in range(min(n, 4)): gouge((x0 + k * 28, y0), (x0 + k * 28 + rnd.uniform(-6, 6), y0 + 150))
                if n == 5: gouge((x0 - 12, y0 + 120), (x0 + 108, y0 + 30))
        return img, "Scratched tally marks (cell wall)", 0.35
    f = font("marker", 120)
    for (txt, x, y) in (("D.M.", 60, 40), ("WAS ERE", 60, 220), ("13 DAYS", 300, 420)):
        lay = Image.new("L", (W, 200), 0); ImageDraw.Draw(lay).text((x, 0), txt, font=f, fill=255)
        lay = lay.rotate(rnd.uniform(-6, 6), Image.BICUBIC)
        for dx, dy, colour, a in ((2, 2, (40, 34, 30), 0.45), (0, 0, (238, 234, 226), 0.85)):
            img.alpha_composite(solid((W, 200), colour, shift(lay, dx, dy), a), (0, y))
    return img, "Scratched initials and words (cell wall)", 0.4

def buffed(seed):
    rnd = random.Random(seed)
    t = pad(spray_text("KRAYZ", "hand", 300, (25, 25, 30), rnd, n_drips=6), 60)
    d = ImageDraw.Draw(t); W, H = t.size
    for k, col in enumerate(((205, 202, 194), (188, 186, 180), (214, 210, 200))):     # council grey / magnolia roller patches
        x0 = W * (0.04 + k * 0.33 + rnd.uniform(-0.02, 0.02)); x1 = x0 + W * rnd.uniform(0.17, 0.24)   # gaps between: the tag shows through
        y0 = H * rnd.uniform(0.05, 0.3); y1 = H * rnd.uniform(0.7, 0.95)
        for x in range(int(x0), int(x1), 6):                                             # roller texture: streaky edges
            d.line([(x, y0 + rnd.uniform(-14, 14)), (x, y1 + rnd.uniform(-14, 14))], fill=(*[max(0, c + rnd.randint(-6, 6)) for c in col], 250), width=7)
    return t, "Buffed-over graffiti (grey paint patches)", 1.4

def stickers(seed):
    rnd = random.Random(seed); W, H = 900, 700; img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    names = ["VEXA", "MOSH", "OZ", "DREK", "SKOE"]
    for k in range(7):
        sw, sh = rnd.randint(230, 330), rnd.randint(150, 200)
        s = Image.new("RGBA", (sw, sh), (0, 0, 0, 0)); d = ImageDraw.Draw(s)
        style = k % 3
        if style == 0:                              # white "HELLO" sticker with a tag written on it
            d.rounded_rectangle([0, 0, sw - 1, sh - 1], 14, fill=(244, 244, 240, 255)); d.rounded_rectangle([0, 0, sw - 1, sh * 0.32], 14, fill=(200, 30, 35, 255))
            d.text((sw * 0.27, sh * 0.04), "HELLO", font=font("block", int(sh * 0.22)), fill=(255, 255, 255, 255))
            d.text((sw * 0.12, sh * 0.42), rnd.choice(names), font=font("hand", int(sh * 0.36)), fill=(20, 20, 25, 255))
        elif style == 1:                            # printed sticker: bold name on a colour
            c = rnd.choice(((30, 30, 32), (250, 200, 30), (40, 120, 200)))
            d.rectangle([0, 0, sw - 1, sh - 1], fill=(*c, 255)); d.text((sw * 0.1, sh * 0.18), rnd.choice(names), font=font("block", int(sh * 0.55)), fill=(255, 255, 255, 255) if c != (250, 200, 30) else (20, 20, 20, 255))
        else:                                       # round sticker with a star
            d.ellipse([0, 0, sh - 1, sh - 1], fill=(240, 60, 120, 255)); cx = cy = sh / 2; r = sh * 0.36
            d.polygon([(cx + r * (1 if q % 2 == 0 else 0.45) * math.cos(-math.pi / 2 + q * math.pi / 5), cy + r * (1 if q % 2 == 0 else 0.45) * math.sin(-math.pi / 2 + q * math.pi / 5)) for q in range(10)], fill=(255, 255, 255, 255))
        d.polygon([(sw - 40, 0), (sw, 0), (sw, 40)], fill=(0, 0, 0, 0))                     # a peeled corner
        d.polygon([(sw - 40, 0), (sw, 40), (sw - 34, 34)], fill=(225, 222, 215, 255))
        s = s.rotate(rnd.uniform(-20, 20), Image.BICUBIC, expand=True)
        img.alpha_composite(s, (rnd.randint(0, W - s.width), rnd.randint(0, H - s.height)))
    return img, "Sticker slaps (cluster)", 0.45

def splat(seed):
    rnd = random.Random(seed); W, H = 1100, 1000; m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
    cx, cy = W * 0.5, H * 0.38
    d.ellipse([cx - 170, cy - 140, cx + 170, cy + 150], fill=255)
    for _ in range(26):                             # spikes and blobs flung out
        a = rnd.uniform(0, 2 * math.pi); L = rnd.uniform(160, 460); r = rnd.uniform(8, 40)
        x, y = cx + math.cos(a) * L, cy + math.sin(a) * L * 0.8
        d.line([(cx, cy), (x, y)], fill=255, width=int(r * 0.9)); d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    for _ in range(60):
        a = rnd.uniform(0, 2 * math.pi); L = rnd.uniform(300, 520); r = rnd.uniform(3, 10)
        x, y = cx + math.cos(a) * L, cy + math.sin(a) * L * 0.8; d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    col = (60, 170, 70); img = solid((W, H), col, m.filter(ImageFilter.GaussianBlur(1.5)))
    drips(img, m, col, 14, rnd, (0.1, 0.45), (6, 14))
    return img, "Thrown paint splat (green)", 0.9

def symbols(seed):
    rnd = random.Random(seed); W, H = 1300, 600; img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    col = (240, 200, 30); crown(d, 250, 300, 170, col, w=20)
    a = [(560, 360), (980, 260)]; d.line(a, fill=(*col, 240), width=26)                         # arrow
    d.polygon([(1080, 235), (950, 180), (985, 330)], fill=(*col, 240))
    m = img.getchannel("A"); glow = solid((W, H), col, m.filter(ImageFilter.GaussianBlur(12)), 0.35)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0)); out.alpha_composite(glow); out.alpha_composite(img)
    drips(out, m, col, 6, rnd, (0.05, 0.25), (4, 9))
    return out, "Spray crown and arrow (yellow)", 0.8

def smiley(seed):
    rnd = random.Random(seed); W = H = 700; m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
    d.ellipse([60, 60, W - 60, H - 60], fill=255)
    f = Image.new("L", (W, H), 0); e = ImageDraw.Draw(f)
    e.ellipse([230, 220, 290, 330], fill=255); e.ellipse([410, 220, 470, 330], fill=255)
    e.arc([190, 260, 510, 520], 20, 160, fill=255, width=30)
    yel, blk = (250, 210, 30), (20, 20, 22)
    img = solid((W, H), yel, m); img.alpha_composite(solid((W, H), blk, f))
    ring = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(17)), m); img.alpha_composite(solid((W, H), blk, ring))
    drips(img, m, yel, 7, rnd, (0.06, 0.3), (6, 12))
    return tilt(img, rnd.uniform(-10, 10)), "Dripping smiley (yellow spray)", 0.5

PACK = [
    ("gr_tag_krayz", lambda: tag("Krayz", (22, 22, 26), 101, "swoosh", 1.1, "Tag \"Krayz\" (black, with swoosh)")),
    ("gr_tag_mosh", lambda: tag("Mosh", (175, 178, 186), 102, "star", 0.9, "Tag \"Mosh\" (silver)")),
    ("gr_tag_drek", lambda: tag("Drek", (190, 25, 35), 103, "crown", 1.0, "Tag \"Drek\" (red, with crown)")),
    ("gr_tag_vexa", lambda: tag("Vexa", (30, 80, 190), 104, "swoosh", 0.9, "Tag \"Vexa\" (blue)")),
    ("gr_throwup_chrome", lambda: throwup("OZ", (240, 240, 244), (140, 142, 152), (15, 15, 18), 105, 1.4, "Throw-up \"OZ\" (chrome, black outline)")),
    ("gr_throwup_pink", lambda: throwup("KB", (255, 120, 190), (200, 40, 120), (20, 20, 25), 106, 1.2, "Throw-up \"KB\" (pink)")),
    ("gr_piece_rokit", lambda: piece("ROKIT", (255, 215, 40), (240, 90, 20), (70, 20, 90), (255, 255, 255), (25, 15, 30), 107, 2.6, "Piece \"ROKIT\" (yellow-orange, 3D)")),
    ("gr_piece_vexa", lambda: piece("VEXA", (90, 230, 210), (20, 110, 190), (255, 255, 255), (15, 20, 40), (60, 20, 120), 108, 2.4, "Piece \"VEXA\" (teal, double outline)")),
    ("gr_piece_skoe", lambda: piece("SKOE", (170, 240, 60), (40, 150, 60), (20, 30, 20), (250, 250, 250), (20, 20, 20), 109, 2.2, "Piece \"SKOE\" (green, arrows)", arrows=True)),
    ("gr_stencil_keep_out", lambda: stencil("KEEP OUT", (18, 18, 20), 110, 1.0, "Stencil \"KEEP OUT\" (black)")),
    ("gr_stencil_eye", lambda: stencil("WHO?", (175, 20, 30), 111, 0.7, "Stencil eye \"WHO?\" (red)", eye=True)),
    ("gr_drips_bored", lambda: drippy("BORED", (200, 25, 35), 112, 1.0, "\"BORED\" (red, dripping)")),
    ("gr_drips_why", lambda: drippy("WHY?", (20, 20, 22), 113, 0.8, "\"WHY?\" (black, dripping)")),
    ("gr_heart_jk", lambda: heart(114)),
    ("gr_marker_woz_ere", lambda: marker(["Gaz woz ere 26", "Shaz + Dean", "Mrs P is sound x"], (25, 45, 140), 115, 0.5, "Marker scrawl \"woz ere\" (blue felt-tip)")),
    ("gr_marker_doodles", lambda: marker(["KRAYZ  MOSH  OZ", "bored bored BORED", ":)  <3  ->"], (20, 20, 22), 116, 0.45, "Marker scrawl and doodles (black felt-tip)", kind="print")),
    ("gr_scratched_tally", lambda: scratched(117, tally=True)),
    ("gr_scratched_words", lambda: scratched(118, tally=False)),
    ("gr_buffed", lambda: buffed(119)),
    ("gr_stickers", lambda: stickers(120)),
    ("gr_splat_green", lambda: splat(121)),
    ("gr_symbols_crown_arrow", lambda: symbols(122)),
    ("gr_smiley", lambda: smiley(123)),
]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(OUT, "decals.json")
    idx = json.load(open(idx_path, encoding="utf-8")) if os.path.exists(idx_path) else {"decals": []}
    keep = [x for x in idx["decals"] if x.get("source") != SOURCE]          # everything else stays as it was
    made = []
    for did, fn in PACK:
        img, name, width_m = fn()
        bb = img.getchannel("A").getbbox()                                  # trim empty margins (keep a little)
        if bb: img = img.crop((max(0, bb[0] - 20), max(0, bb[1] - 20), min(img.width, bb[2] + 20), min(img.height, bb[3] + 20)))
        if img.width > 1600: img = img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS)
        img.save(os.path.join(OUT, did + ".png"), optimize=True)
        made.append({"id": did, "name": name, "file": did + ".png", "width": width_m, "aspect": round(img.height / img.width, 4),
                     "category": "graffiti", "source": SOURCE, "licence": "Own work"})
        print("wrote", did, img.size)
    json.dump({"decals": keep + made}, open(idx_path, "w", encoding="utf-8"), indent=1)
    print("decals now:", len(keep) + len(made))
