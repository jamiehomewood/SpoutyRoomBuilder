"""Draw the wallpaper / carpet pattern masks used by Room Builder (own work, no licence restrictions).

Each mask is a seamless 1024 x 1024 greyscale tile: black = the ground colour, white = the pattern colour.
One tile covers 0.53 m (a UK wallpaper roll width) on walls. Run with any Python that has Pillow:

    python tools/make_patterns.py
"""
import math, os, random
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "textures", "patterns")
N = 1024; SS = 2; S = N * SS                    # draw at 2x, then downsample for smooth edges


def canvas():
    return Image.new("L", (S, S), 0)


def wrap_draw(img, fn):
    """Call fn(draw, dx, dy) for the 9 tile offsets so shapes crossing an edge wrap round (seamless)."""
    d = ImageDraw.Draw(img)
    for dx in (-S, 0, S):
        for dy in (-S, 0, S):
            fn(d, dx, dy)


def save(img, name, blur=0):
    img = img.resize((N, N), Image.LANCZOS)
    if blur: img = img.filter(ImageFilter.GaussianBlur(blur))
    img.save(os.path.join(OUT, name + ".png"))
    print("wrote", name)


def stripe():
    img = canvas(); d = ImageDraw.Draw(img)
    # regency stripe: two wide bands, each edged by a thin line, across one roll width
    for k in range(2):
        x0 = k * S / 2
        d.rectangle([x0 + S * 0.06, 0, x0 + S * 0.24, S], fill=255)
        for off in (0.035, 0.265):
            d.rectangle([x0 + S * off, 0, x0 + S * (off + 0.008), S], fill=255)
    save(img, "stripe")


def pinstripe():
    img = canvas(); d = ImageDraw.Draw(img)
    n = 12
    for k in range(n):
        x = k * S / n
        d.rectangle([x, 0, x + S * 0.006, S], fill=255)
    save(img, "pinstripe")


def trellis():
    img = canvas()
    w = int(S * 0.012)
    def f(d, dx, dy):
        for k in range(-2, 4):
            a = k * S / 2
            d.line([(a + dx, dy), (a + S + dx, S + dy)], fill=255, width=w)
            d.line([(a + dx, S + dy), (a + S + dx, dy)], fill=255, width=w)
        for i in range(3):
            for j in range(3):
                cx, cy = i * S / 2 + dx, j * S / 2 + dy
                r = S * 0.025
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    wrap_draw(img, f)
    save(img, "trellis")


def sprig(d, cx, cy, s, ang):
    """A small flower: five petals, a centre and two leaves on a curved stem."""
    for k in range(5):
        a = ang + k * 2 * math.pi / 5
        px, py = cx + math.cos(a) * s * 0.55, cy + math.sin(a) * s * 0.55
        r = s * 0.42
        d.ellipse([px - r, py - r, px + r, py + r], fill=255)
    r = s * 0.3; d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)
    r = s * 0.18; d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    pts = [(cx + math.cos(ang + 2.4) * s * t * 2.6 + math.sin(t * 3) * s * 0.3,
            cy + math.sin(ang + 2.4) * s * t * 2.6) for t in [i / 12 for i in range(13)]]
    d.line(pts, fill=255, width=max(2, int(s * 0.12)))
    for t, side in ((0.45, 1), (0.8, -1)):
        lx, ly = pts[int(t * 12)]
        a = ang + 2.4 + side * 1.0
        ex, ey = lx + math.cos(a) * s * 0.9, ly + math.sin(a) * s * 0.9
        d.polygon([(lx, ly), ((lx + ex) / 2 + math.cos(a + 1.57) * s * 0.3, (ly + ey) / 2 + math.sin(a + 1.57) * s * 0.3), (ex, ey),
                   ((lx + ex) / 2 - math.cos(a + 1.57) * s * 0.3, (ly + ey) / 2 - math.sin(a + 1.57) * s * 0.3)], fill=255)


def floral():
    img = canvas(); rnd = random.Random(7)
    spots = []
    for i in range(5):
        for j in range(5):
            spots.append(((i + 0.5 + (0.5 if j % 2 else 0)) * S / 5 + rnd.uniform(-15, 15) * SS,
                          (j + 0.5) * S / 5 + rnd.uniform(-15, 15) * SS, rnd.uniform(0, 6.28), rnd.uniform(0.85, 1.15)))
    def f(d, dx, dy):
        for x, y, a, sc in spots:
            sprig(d, x + dx, y + dy, S * 0.05 * sc, a)
    wrap_draw(img, f)
    save(img, "floral")


def leaf(d, bx, by, ang, length, width, bend=0.0, fill=255):
    """A curved leaf from (bx, by): centreline bends by 'bend' radians along its length, width swells in the middle."""
    left, right = [], []
    for i in range(25):
        t = i / 24
        a = ang + bend * t
        cx = bx + sum(math.cos(ang + bend * (k / 24)) for k in range(i)) * length / 24
        cy = by + sum(math.sin(ang + bend * (k / 24)) for k in range(i)) * length / 24
        w = width * math.sin(math.pi * t) ** 0.8
        left.append((cx + math.cos(a + 1.5708) * w, cy + math.sin(a + 1.5708) * w))
        right.append((cx - math.cos(a + 1.5708) * w, cy - math.sin(a + 1.5708) * w))
    d.polygon(left + right[::-1], fill=fill)


def damask():
    """Ogee lattice of leafy scrolls with a mirrored fleur in each cell (half-drop repeat)."""
    img = canvas()
    def fleur(d, cx, cy, s):
        for side in (-1, 1):
            m = lambda a: math.pi - a if side < 0 else a          # mirror an angle left/right
            leaf(d, cx, cy + s * 0.55, m(-1.25), s * 0.9, s * 0.12, bend=side * -0.9)          # tall outer leaves
            leaf(d, cx, cy + s * 0.35, m(-0.55), s * 0.55, s * 0.1, bend=side * -1.2)
            leaf(d, cx, cy + s * 0.65, m(0.35), s * 0.45, s * 0.09, bend=side * 1.4)            # lower curls
            leaf(d, cx + side * s * 0.05, cy - s * 0.2, m(-0.9), s * 0.35, s * 0.07, bend=side * -1.6)
            r = s * 0.06; px = cx + side * s * 0.55; py = cy - s * 0.35
            d.ellipse([px - r, py - r, px + r, py + r], fill=255)
        leaf(d, cx, cy + s * 0.6, -1.5708, s * 1.25, s * 0.13)                                  # central spire
        r = s * 0.12; d.ellipse([cx - r, cy + s * 0.5, cx + r, cy + s * 0.74], fill=255)
    def f(d, dx, dy):
        w = int(S * 0.009)
        for k in range(3):                                                                     # ogee lattice
            x0 = k * S / 2
            for sgn in (1, -1):
                pts = [(x0 + sgn * S * 0.25 * math.sin(math.pi * y / S) + dx, y + dy) for y in range(0, S + 1, 8)]
                d.line(pts, fill=255, width=w)
        for cx, cy in ((S * 0.25, S * 0.5), (S * 0.75, 0), (S * 0.75, S)):
            fleur(d, cx + dx, cy + dy - S * 0.08, S * 0.27)
        for cx, cy in ((0, 0), (S * 0.5, 0), (S, 0), (0, S), (S * 0.5, S), (S, S)):                # small rosettes where lines cross
            r = S * 0.03; d.ellipse([cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r], fill=255)
    wrap_draw(img, f)
    save(img, "damask")


def geometric():
    """1970s interlocking circles."""
    img = canvas()
    def f(d, dx, dy):
        n = 4; r = S / n / 2
        for i in range(n + 1):
            for j in range(n + 1):
                cx, cy = i * S / n + dx, j * S / n + dy
                for rr, col in ((r * 0.98, 255), (r * 0.78, 0), (r * 0.6, 255), (r * 0.38, 0)):
                    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col)
                cx2, cy2 = cx + S / n / 2, cy + S / n / 2
                rr = r * 0.25; d.ellipse([cx2 - rr, cy2 - rr, cx2 + rr, cy2 + rr], fill=255)
    wrap_draw(img, f)
    save(img, "geometric")


def cord():
    img = canvas(); d = ImageDraw.Draw(img)
    n = 64
    for k in range(n):
        if k % 2: d.rectangle([k * S / n, 0, (k + 1) * S / n - 1, S], fill=255)
    save(img, "cord", blur=1.2)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for fn in (stripe, pinstripe, trellis, floral, damask, geometric, cord):
        fn()
