"""Generate 1,500+ varied test images (shapes, colours, counts) and evaluate visual_qa."""
import sys, math, random, json
import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2, numpy as np
from app import visual_qa as v

rng = random.Random(7)
COLS = {  # BGR -> expected Arabic name
    "أحمر": (30, 30, 215), "أخضر": (50, 170, 40), "أزرق": (200, 70, 20), "أصفر": (20, 215, 235),
    "برتقالي": (10, 130, 250), "بنفسجي": (150, 40, 120), "وردي": (175, 110, 250), "أسود": (25, 25, 25),
    "بني": (30, 65, 120), "أبيض": (245, 245, 245),
}
SHAPES = ["circle", "oval", "triangle", "square", "rectangle", "pentagon", "hexagon", "star"]

def background(h, w, dark=False):
    kind = rng.choice(["plain", "noise", "gradient", "paper"])
    base = np.full((h, w, 3), rng.randint(15, 60) if dark else rng.randint(200, 250), np.uint8)
    if kind == "noise":
        base = cv2.add(base, np.random.randint(0, 18, (h, w, 3), dtype=np.uint8))
    elif kind == "gradient":
        g = np.linspace(0, 30, w, dtype=np.float32)[None, :, None]
        base = np.clip(base.astype(np.float32) + (g if dark else -g), 0, 255).astype(np.uint8)
    elif kind == "paper":
        base = cv2.GaussianBlur(cv2.add(base, np.random.randint(0, 25, (h, w, 3), dtype=np.uint8)), (7, 7), 0)
    return base

def poly(n, cx, cy, r, rot, star=False):
    pts = []
    k = n * 2 if star else n
    for i in range(k):
        rr = r if (not star or i % 2 == 0) else r * 0.45
        a = rot + 2 * math.pi * i / k
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return np.array(pts, np.int32)

def draw(img, shape, colour, cx, cy, r):
    rot = rng.uniform(0, 2 * math.pi)
    if shape == "circle":
        cv2.circle(img, (cx, cy), r, colour, -1, cv2.LINE_AA)
    elif shape == "oval":
        cv2.ellipse(img, (cx, cy), (r, int(r * rng.uniform(0.45, 0.65))), math.degrees(rot), 0, 360, colour, -1, cv2.LINE_AA)
    elif shape == "triangle":
        cv2.fillPoly(img, [poly(3, cx, cy, r, rot)], colour, cv2.LINE_AA)
    elif shape == "square":
        cv2.fillPoly(img, [poly(4, cx, cy, r, rot)], colour, cv2.LINE_AA)
    elif shape == "rectangle":
        w2, h2 = r, int(r * rng.uniform(0.4, 0.6))
        box = cv2.boxPoints(((cx, cy), (2 * w2, 2 * h2), math.degrees(rot))).astype(np.int32)
        cv2.fillPoly(img, [box], colour, cv2.LINE_AA)
    elif shape == "pentagon":
        cv2.fillPoly(img, [poly(5, cx, cy, r, rot)], colour, cv2.LINE_AA)
    elif shape == "hexagon":
        cv2.fillPoly(img, [poly(6, cx, cy, r, rot)], colour, cv2.LINE_AA)
    elif shape == "star":
        cv2.fillPoly(img, [poly(5, cx, cy, r, rot, star=True)], colour, cv2.LINE_AA)

def degrade(img):
    if rng.random() < 0.5:
        img = cv2.GaussianBlur(img, (3, 3), 0)
    if rng.random() < 0.6:
        q = rng.randint(55, 90)
        img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], 1)
    if rng.random() < 0.3:  # lighting change
        img = cv2.convertScaleAbs(img, alpha=rng.uniform(0.85, 1.1), beta=rng.randint(-15, 15))
    return img

results = {"single": [], "count": []}
# 1) single shapes: 8 shapes x 10 colours x 15 variations = 1200 images
for shape in SHAPES:
    for cname, col in COLS.items():
        for k in range(15):
            h, w = rng.choice([(360, 480), (480, 640), (300, 300)])
            img = background(h, w, dark=(cname == "أبيض" or (cname not in ("أسود",) and rng.random() < 0.2)))
            if cname == "أسود":
                img = background(h, w, dark=False)
            r = int(min(h, w) * rng.uniform(0.18, 0.38))
            cx = rng.randint(r + 5, w - r - 5); cy = rng.randint(r + 5, h - r - 5)
            draw(img, shape, col, cx, cy, r)
            img = degrade(img)
            s = v.detect_shapes(img)
            got = s[0] if s else {"shape": None, "colour": None}
            results["single"].append({"shape": shape, "colour": cname, "got_shape": got["shape"], "got_colour": got["colour"],
                                      "n": len(s)})
# 2) counting: 1-6 shapes, 360 images
for k in range(360):
    n = rng.randint(1, 6)
    h, w = 480, 640
    img = background(h, w)
    placed = []
    tries = 0
    while len(placed) < n and tries < 400:
        tries += 1
        r = rng.randint(28, 60)
        cx = rng.randint(r + 5, w - r - 5); cy = rng.randint(r + 5, h - r - 5)
        if all(math.hypot(cx - a, cy - b) > r + rb + 12 for a, b, rb in placed):
            placed.append((cx, cy, r))
            cname = rng.choice([c for c in COLS if c not in ("أبيض",)])
            draw(img, rng.choice(SHAPES), COLS[cname], cx, cy, r)
    img = degrade(img)
    got = len(v.detect_shapes(img))
    results["count"].append({"n": len(placed), "got": got})

single = results["single"]; count = results["count"]
acc_shape = sum(r["shape"] == r["got_shape"] for r in single) / len(single)
acc_col = sum(r["colour"] == r["got_colour"] for r in single) / len(single)
acc_cnt = sum(r["n"] == r["got"] for r in count) / len(count)
print(f"images: {len(single) + len(count)}  (single-shape {len(single)}, counting {len(count)})")
print(f"shape accuracy: {acc_shape:.1%} | colour accuracy: {acc_col:.1%} | counting accuracy: {acc_cnt:.1%}")
from collections import Counter
per = {s: sum(1 for r in single if r['shape'] == s and r['got_shape'] == s) / sum(1 for r in single if r['shape'] == s) for s in SHAPES}
print("per shape:", {k: f"{v_:.0%}" for k, v_ in per.items()})
perc = {c: sum(1 for r in single if r['colour'] == c and r['got_colour'] == c) / sum(1 for r in single if r['colour'] == c) for c in COLS}
print("per colour:", {k: f"{v_:.0%}" for k, v_ in perc.items()})
conf = Counter((r["shape"], r["got_shape"]) for r in single if r["shape"] != r["got_shape"])
print("top shape confusions:", conf.most_common(8))
confc = Counter((r["colour"], r["got_colour"]) for r in single if r["colour"] != r["got_colour"])
print("top colour confusions:", confc.most_common(8))
json.dump({"shape": acc_shape, "colour": acc_col, "count": acc_cnt, "per_shape": per, "per_colour": perc,
           "images": len(single) + len(count)}, open(os.path.join(os.path.dirname(__file__), "eval_results.json"), "w"), ensure_ascii=False)

# 3) HARD set: shape printed on a sheet of paper, held in front of real photos,
#    with perspective tilt, shadow and noise — 640 images
import skimage.data as sd
photos = [sd.brick(), sd.grass(), sd.gravel(), sd.coffee(), sd.chelsea(), sd.astronaut(), sd.rocket(), sd.camera()]
photos = [cv2.cvtColor(p, cv2.COLOR_GRAY2BGR) if p.ndim == 2 else cv2.cvtColor(p, cv2.COLOR_RGB2BGR) for p in photos]
hard = []
for k in range(640):
    shape = SHAPES[k % len(SHAPES)]
    cname = [c for c in COLS if c != "أبيض"][k % 9]
    ph = rng.choice(photos)
    H, W = 480, 640
    y0 = rng.randint(0, max(0, ph.shape[0] - H)) if ph.shape[0] > H else 0
    x0 = rng.randint(0, max(0, ph.shape[1] - W)) if ph.shape[1] > W else 0
    bg = cv2.resize(ph[y0:y0 + H, x0:x0 + W], (W, H))
    paper = np.full((300, 300, 3), rng.randint(225, 250), np.uint8)
    draw(paper, shape, COLS[cname], 150, 150, rng.randint(80, 115))
    # perspective: the sheet is tilted
    s = rng.randint(220, 330)
    cx, cy = rng.randint(s // 2 + 10, W - s // 2 - 10), rng.randint(s // 2 + 10, H - s // 2 - 10)
    j = lambda: rng.uniform(-0.12, 0.12) * s
    dst = np.float32([[cx - s/2 + j(), cy - s/2 + j()], [cx + s/2 + j(), cy - s/2 + j()],
                      [cx + s/2 + j(), cy + s/2 + j()], [cx - s/2 + j(), cy + s/2 + j()]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [300, 0], [300, 300], [0, 300]]), dst)
    warped = cv2.warpPerspective(paper, M, (W, H))
    mask = cv2.warpPerspective(np.full((300, 300), 255, np.uint8), M, (W, H))
    img = bg.copy(); img[mask > 0] = warped[mask > 0]
    if rng.random() < 0.5:  # soft shadow
        sh = np.zeros((H, W), np.float32); cv2.circle(sh, (rng.randint(0, W), rng.randint(0, H)), rng.randint(150, 400), 1.0, -1)
        sh = cv2.GaussianBlur(sh, (151, 151), 0)[..., None]
        img = np.clip(img * (1 - 0.25 * sh), 0, 255).astype(np.uint8)
    img = cv2.add(img, np.random.randint(0, 10, img.shape, dtype=np.uint8))
    img = degrade(img)
    sres = v.detect_shapes(img)
    got = sres[0] if sres else {"shape": None, "colour": None}
    hard.append({"shape": shape, "colour": cname, "got_shape": got["shape"], "got_colour": got["colour"],
                 "paper": v._find_paper(img) is not None})
hs = sum(r["shape"] == r["got_shape"] for r in hard) / len(hard)
hc = sum(r["colour"] == r["got_colour"] for r in hard) / len(hard)
print(f"HARD set ({len(hard)} images, paper on real photos, tilted): shape {hs:.1%} | colour {hc:.1%}")
print("hard confusions:", Counter((r['shape'], r['got_shape']) for r in hard if r['shape'] != r['got_shape']).most_common(8))
print("hard colour confusions:", Counter((r['colour'], r['got_colour']) for r in hard if r['colour'] != r['got_colour']).most_common(6))
pf = [r for r in hard if r["paper"]]; pn = [r for r in hard if not r["paper"]]
print(f"  paper found {len(pf)}: shape {sum(r['shape']==r['got_shape'] for r in pf)/max(1,len(pf)):.1%} colour {sum(r['colour']==r['got_colour'] for r in pf)/max(1,len(pf)):.1%}")
print(f"  paper NOT found {len(pn)}: shape {sum(r['shape']==r['got_shape'] for r in pn)/max(1,len(pn)):.1%}; answered-nothing {sum(r['got_shape'] is None for r in pn)}")
print("  found-paper confusions:", Counter((r['shape'], r['got_shape']) for r in pf if r['shape'] != r['got_shape']).most_common(6))
wrong = sum(1 for r in hard if r["got_shape"] is not None and r["got_shape"] != r["shape"])
abst = sum(1 for r in hard if r["got_shape"] is None)
print(f"  HARD: wrong answers {wrong} ({wrong/len(hard):.1%}) | said 'can't see clearly' {abst} ({abst/len(hard):.1%})")
print("TOTAL images:", len(single) + len(count) + len(hard))
d = json.load(open(os.path.join(os.path.dirname(__file__), "eval_results.json"))); d.update(hard_shape=hs, hard_colour=hc, images=len(single) + len(count) + len(hard))
json.dump(d, open(os.path.join(os.path.dirname(__file__), "eval_results.json"), "w"), ensure_ascii=False)
cv2.imwrite(os.path.join(os.path.dirname(__file__), "hard_example.jpg"), img)
