"""Answer questions about what is in front of the camera — on the device,
without any API key.

Pre-trained models (trained by their authors on large public datasets):
  - ImageNet classifier (MobileNetV2): 1000 kinds of objects, animals, foods,
    places and tools, with Arabic names in data/imagenet_ar.txt.
  - COCO detector (YOLOX, objects.py): 80 everyday categories with positions,
    used for counting ("كم كوب؟", "كم شخص؟").
  - MediaPipe Hand Landmarker: 21 points per hand -> counting raised fingers.
Plus classic computer vision for geometric shapes and colours.

Every answer is one short Arabic sentence. When unsure it says so instead of
guessing.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import cv2
import numpy as np

from . import objects

BASE = Path(__file__).resolve().parent
MODELS = BASE / "models"
CLS_PATH = MODELS / "image_classification_mobilenet.onnx"
HAND_PATH = MODELS / "hand_landmarker.task"
AR_LABELS = BASE / "data" / "imagenet_ar.txt"

_cls_net = None
_labels: list[str] | None = None
_hand = None


# ------------------------------------------------------------ helpers -----

_DIAC = re.compile(r"[ً-ْـ]")


def _norm(s: str) -> str:
    s = _DIAC.sub("", (s or "").lower())
    s = re.sub("[أإآ]", "ا", s)
    return s.replace("ة", "ه").replace("ى", "ي")


def _has(q: str, *words: str) -> bool:
    n = _norm(q)
    return any(_norm(w) in n for w in words)


AR_NUM = {0: "ولا إصبع", 1: "إصبع واحد", 2: "إصبعان", 3: "ثلاثة أصابع", 4: "أربعة أصابع",
          5: "خمسة أصابع", 6: "ستة أصابع", 7: "سبعة أصابع", 8: "ثمانية أصابع",
          9: "تسعة أصابع", 10: "عشرة أصابع"}
AR_COUNT = {1: "واحد", 2: "اثنان", 3: "ثلاثة", 4: "أربعة", 5: "خمسة", 6: "ستة",
            7: "سبعة", 8: "ثمانية", 9: "تسعة", 10: "عشرة"}


# ------------------------------------------------- 1000-class classifier --

def classifier_available() -> bool:
    return CLS_PATH.exists() and CLS_PATH.stat().st_size > 10_000_000 and AR_LABELS.exists()


def classify(img: np.ndarray, top: int = 3) -> list[tuple[str, float]]:
    """[(arabic name, probability)] for the whole image (or a crop)."""
    global _cls_net, _labels
    if not classifier_available():
        return []
    if _cls_net is None:
        _cls_net = cv2.dnn.readNet(str(CLS_PATH))
        _labels = AR_LABELS.read_text(encoding="utf-8").splitlines()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    s = 256 / min(h, w)
    rgb = cv2.resize(rgb, (max(224, int(w * s)), max(224, int(h * s))))
    h, w = rgb.shape[:2]
    y, x = (h - 224) // 2, (w - 224) // 2
    rgb = rgb[y:y + 224, x:x + 224]
    blob = ((rgb / 255.0 - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225])
    blob = blob.transpose(2, 0, 1)[None].astype(np.float32)
    _cls_net.setInput(blob)
    o = _cls_net.forward()[0]
    e = np.exp(o - o.max())
    p = e / e.sum()
    # merge identical Arabic names (e.g. the 118 dog breeds -> «كلب»)
    merged: dict[str, float] = {}
    for i in p.argsort()[::-1][:25]:
        merged[_labels[i]] = merged.get(_labels[i], 0.0) + float(p[i])
    return sorted(merged.items(), key=lambda t: -t[1])[:top]


# ---------------------------------------------------------------- hands ---

def hands_available() -> bool:
    if not HAND_PATH.exists():
        return False
    try:
        import mediapipe  # noqa: F401
        return True
    except Exception:
        return False


def _landmarker():
    global _hand
    if _hand is None:
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        opts = vision.HandLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(HAND_PATH)),
            num_hands=2, min_hand_detection_confidence=0.4,
            min_hand_presence_confidence=0.4)
        _hand = (mp, vision.HandLandmarker.create_from_options(opts))
    return _hand


def _fingers_up(lm) -> int:
    """Raised fingers from 21 landmarks; works for any hand rotation."""
    def d(a, b):
        return math.hypot(lm[a].x - lm[b].x, lm[a].y - lm[b].y)
    count = 0
    # index, middle, ring, pinky: tip clearly farther from the wrist than the PIP joint
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        if d(tip, 0) > d(pip, 0) * 1.12:
            count += 1
    # thumb: tip away from the palm (index MCP) and the thumb fairly straight
    palm = d(0, 9) or 1e-6
    if d(4, 5) > 0.55 * palm and d(4, 17) > d(3, 17) * 1.04:
        count += 1
    return count


def count_fingers(img: np.ndarray) -> tuple[int, int] | None:
    """(raised fingers, hands seen) or None if the model is not installed."""
    if not hands_available():
        return None
    mp, lmk = _landmarker()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    res = lmk.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    hands = res.hand_landmarks or []
    return sum(_fingers_up(h) for h in hands), len(hands)


# --------------------------------------------------------------- colours ---

COLOURS = [  # (name, hue range in OpenCV 0-180)
    ("أحمر", 0, 8), ("برتقالي", 8, 21), ("أصفر", 21, 34), ("أخضر", 34, 85),
    ("أزرق فاتح", 85, 100), ("أزرق", 100, 130), ("بنفسجي", 130, 150),
    ("وردي", 150, 168), ("أحمر", 168, 181),
]


def colour_name(bgr_pixels: np.ndarray) -> str:
    """Arabic colour name for a set of BGR pixels (median)."""
    px = bgr_pixels.reshape(-1, 3).astype(np.uint8)
    if len(px) == 0:
        return "غير واضح"
    hsv = cv2.cvtColor(px[None], cv2.COLOR_BGR2HSV)[0].astype(np.float32)
    h, s, v = np.median(hsv[:, 0]), np.median(hsv[:, 1]), np.median(hsv[:, 2])
    if v < 50:
        return "أسود"
    if s < 40:
        return "أبيض" if v > 190 else "رمادي"
    if 8 <= h < 21 and v < 150:
        return "بني"
    for name, a, b in COLOURS:
        if a <= h < b:
            return name
    return "غير واضح"


# ---------------------------------------------------------------- shapes ---

SHAPE_AR = {"circle": "دائرة", "oval": "شكل بيضاوي", "triangle": "مثلث",
            "square": "مربع", "rectangle": "مستطيل", "pentagon": "خماسي",
            "hexagon": "سداسي", "star": "نجمة", "polygon": "مضلع"}


def _background_mask(img: np.ndarray) -> np.ndarray:
    """Foreground = pixels that differ clearly from the border colour."""
    lab = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(lab - bg, axis=2)
    mask = (dist > 28).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return mask


def _order(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s_ = pts.sum(1); d = np.diff(pts, axis=1).ravel()
    return np.float32([pts[np.argmin(s_)], pts[np.argmin(d)], pts[np.argmax(s_)], pts[np.argmax(d)]])


def _paper_quad_ok(img: np.ndarray, quad: np.ndarray, hsv: np.ndarray) -> bool:
    """Inside of the quadrilateral looks like paper (bright, colourless border band)."""
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(m, quad.astype(np.int32), 255)
    inner = cv2.erode(m, np.ones((15, 15), np.uint8))
    band = cv2.subtract(inner, cv2.erode(inner, np.ones((25, 25), np.uint8)))
    if band.sum() == 0:
        return False
    v = hsv[..., 2][band > 0]; s_ = hsv[..., 1][band > 0]
    # paper may be in shadow: compare with the scene instead of a fixed level
    scene_v = float(np.median(hsv[..., 2]))
    return (float(np.median(v)) > max(125.0, scene_v + 10) and float(np.median(s_)) < 50
            and float(np.std(v)) < 45)


def _as_quad(c: np.ndarray, w: int, h: int) -> np.ndarray | None:
    """4 corners for a sheet — also when a corner is cut off by the frame edge."""
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
    if len(approx) == 4 and cv2.isContourConvex(approx):
        return approx
    if 4 <= len(approx) <= 7:
        area = cv2.contourArea(c)
        hull = cv2.contourArea(cv2.convexHull(c)) + 1e-6
        touches = (approx[:, 0, 0].min() <= 3 or approx[:, 0, 1].min() <= 3 or
                   approx[:, 0, 0].max() >= w - 4 or approx[:, 0, 1].max() >= h - 4)
        if area / hull > 0.9 and (touches or len(approx) == 5):
            box = cv2.boxPoints(cv2.minAreaRect(c))
            return box.reshape(4, 1, 2).astype(np.int32)
    return None


def _find_paper(img: np.ndarray) -> np.ndarray | None:
    """A sheet of paper held up to the camera: four straight edges around a
    bright colourless area (like a document scanner). Returns it straightened."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cands = []
    # (a) edges -> quadrilaterals
    for lo, hi in ((40, 120), (80, 200)):
        edges = cv2.dilate(cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), lo, hi), np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            if cv2.contourArea(c) < 0.03 * w * h:
                continue
            q = _as_quad(c, w, h)
            if q is not None:
                cands.append(q)
    # (b) bright colourless blobs -> quadrilaterals
    v_thr = max(125, float(np.percentile(hsv[..., 2], 60)))
    mask = ((hsv[..., 1] < 50) & (hsv[..., 2] > v_thr)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        if cv2.contourArea(c) < 0.03 * w * h:
            continue
        q = _as_quad(cv2.convexHull(c), w, h)
        if q is not None:
            cands.append(q)
    best = None
    for q in sorted(cands, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(q) > 0.9 * w * h:
            continue
        if _paper_quad_ok(img, q.reshape(4, 2), hsv):
            best = q
            break
    if best is None:
        return None
    side = 320
    M = cv2.getPerspectiveTransform(_order(best), np.float32([[0, 0], [side, 0], [side, side], [0, side]]))
    return cv2.warpPerspective(img, M, (side, side))


def _cluttered(img: np.ndarray) -> bool:
    """Busy real scene vs plain background: edge density along the border band.
    Gradients, paper texture and sensor noise have almost no edges after blur."""
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    e = cv2.Canny(g, 50, 150) > 0
    h, w = g.shape
    b = max(8, min(h, w) // 12)
    band = np.concatenate([e[:b].ravel(), e[-b:].ravel(), e[:, :b].ravel(), e[:, -b:].ravel()])
    return float(band.mean()) > 0.02


def _paper_mask(img: np.ndarray) -> np.ndarray:
    """Ink on paper, ignoring shadows: flatten the lighting, then keep pixels
    that are clearly darker than the paper or clearly coloured."""
    lab = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0]
    # paper brightness estimate: a large closing removes the drawing, keeps the light falloff
    bgL = cv2.morphologyEx(L, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)))
    bgL = cv2.GaussianBlur(bgL, (41, 41), 0) + 1e-3
    flat = np.clip(L / bgL, 0, 1.5)
    chroma = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    mask = ((flat < 0.78) | (chroma > 22)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def _drop_border_blobs(mask: np.ndarray) -> np.ndarray:
    """Remove regions touching the edge (bits of background / paper edge)."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    h, w = mask.shape
    out = np.zeros_like(mask)
    for i in range(1, n):
        x, y, bw, bh, _a = stats[i]
        if x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1:
            continue
        out[lab == i] = 255
    return out


def _saturated_mask(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1] > 110) & (hsv[..., 2] > 60)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))


def classify_contour(c: np.ndarray) -> str:
    """Geometric shape of one outline. Uses measures that survive blur, tilt
    and rounded corners: solidity (how hollow), fill of the tightest rotated
    box, roundness, and the corner count of the convex hull."""
    area = cv2.contourArea(c)
    hull = cv2.convexHull(c)
    hull_area = cv2.contourArea(hull) + 1e-6
    solidity = area / hull_area
    if solidity < 0.82:
        return "star"
    (_, _), (rw, rh), _ = cv2.minAreaRect(c)
    fill = area / (rw * rh + 1e-6)
    aspect = max(rw, rh) / (min(rw, rh) + 1e-6)
    hp = cv2.arcLength(hull, True)
    circ = 4 * math.pi * hull_area / (hp * hp + 1e-6)
    n = len(cv2.approxPolyDP(hull, 0.03 * hp, True))
    if fill > 0.9 and circ < 0.86:
        return "square" if aspect < 1.18 else "rectangle"
    if n == 3 or fill < 0.58:
        return "triangle"
    if circ > 0.86 and n >= 7:
        return "circle" if aspect < 1.15 else "oval"
    if n == 5:
        return "pentagon"
    if n == 6:
        return "hexagon"
    if n == 4:
        return "square" if aspect < 1.18 else "rectangle"
    if circ > 0.8:
        return "circle" if aspect < 1.15 else "oval"
    return "polygon"


def detect_shapes(img: np.ndarray, min_area_frac: float = 0.004, _depth: int = 0) -> list[dict]:
    h, w = img.shape[:2]
    if _depth == 0:
        # a sheet of paper held up to the camera — whatever the background
        paper = _find_paper(img)
        if paper is not None:
            crop = paper[20:-20, 20:-20]
            mask = _drop_border_blobs(_paper_mask(crop))
            inner = _shapes_from_mask(crop, mask, 0.01)
            if inner:
                return inner
        if _cluttered(img):
            # no paper: strongly coloured objects only (grey/black can't be
            # separated from a busy room reliably)
            cands = _shapes_from_mask(img, _drop_border_blobs(_saturated_mask(img)),
                                      max(min_area_frac, 0.01))
            # only clean, separate coloured shapes; otherwise admit we can't tell
            return [c for c in cands if c["area"] < 0.4 and c["shape"] != "polygon"]
    return _shapes_from_mask(img, _background_mask(img), min_area_frac, _depth)


def _shapes_from_mask(img: np.ndarray, mask: np.ndarray, min_area_frac: float,
                      _depth: int = 1) -> list[dict]:
    h, w = img.shape[:2]
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        area = cv2.contourArea(c)
        if area < min_area_frac * w * h:
            continue
        kind = classify_contour(c)
        m = np.zeros(mask.shape, np.uint8)
        cv2.drawContours(m, [c], -1, 255, -1)
        m = cv2.erode(m, np.ones((5, 5), np.uint8))
        colour = colour_name(img[m > 0])
        x, y, bw, bh = cv2.boundingRect(c)
        out.append({"shape": kind, "ar": SHAPE_AR[kind], "colour": colour,
                    "area": area / (w * h), "box": [x, y, bw, bh]})
    out.sort(key=lambda s: -s["area"])
    # A shape drawn on a sheet of paper held up to the camera: the sheet is the
    # big light rectangle — look inside it instead of reporting the paper.
    if out and out[0]["colour"] in ("أبيض", "رمادي") and out[0]["shape"] in ("square", "rectangle", "polygon") \
            and out[0]["area"] > 0.12 and _depth < 1:
        x, y, bw, bh = out[0]["box"]
        pad = int(0.06 * min(bw, bh))
        crop = img[y + pad:y + bh - pad, x + pad:x + bw - pad]
        if crop.size:
            inner = detect_shapes(crop, min_area_frac=0.01, _depth=1)
            if inner:
                return inner
    return out


# --------------------------------------------------------- question router --

def _count_word(n: int, singular: str, plural: str) -> str:
    if n == 1:
        return f"{singular} واحد"
    if n == 2:
        return f"اثنان من {plural}" if plural else f"{singular}ان"
    return f"{AR_COUNT.get(n, str(n))} {plural}"


PEOPLE_WORDS = ("شخص", "اشخاص", "أشخاص", "ناس", "نفر", "انفار", "أحد", "احد", "واحد قدامي",
                "واحد عندي", "واحد هنا", "رجال", "حريم", "بنات", "عيال", "اطفال", "أطفال")
WHAT_RE = re.compile(
    r"(وش|ايش|ايش|شو|شنو|ما|ماذا|وشو|ايشو|إيش) ?(هذا|هذي|هذه|هاذا|هاذي|ذا|ذي|اللي قدامي|قدامي|اللي بيدي|"
    r"بيدي|في يدي|اللي في يدي|ماسك|اللي ماسكه|اشوف|أشوف|تشوف|اللي اشوفه)|"
    r"(هذا|هذي|هذه|ذا) (وش|ايش|اشيه|شو|شنو|ايش هو|وش هو|وشو)|"
    r"(تعرف|عرفت) (هذا|هذي|وش هذا|ايش هذا)|(وش|ايش|شو) (ذا|ذي)|"
    r"(قول لي|قل لي|علمني) (وش|ايش|شو) (هذا|هذي|قدامي)")


def detect_intent(question: str) -> str | None:
    """fingers | colour | shape | count_people | count_object | count | what | None."""
    q = _norm(question or "")
    if not q.strip():
        return None
    if re.search(r"(اصبع|اصابع|صبع|صباع|صوابع|اصابيع)", q):
        return "fingers"
    if re.search(r"(لون|الوان|الالوان)", q):
        return "colour"
    if re.search(r"(شكل|اشكال|الاشكال|دائره|مثلث|مربع|مستطيل|نجمه|خماسي|سداسي|بيضاوي)", q):
        return "shape"
    if re.search(r"كم (ال)?ساعه(\s|$|؟|\?)", q) and not re.search(r"ساعه (على|في|معلقه)", q):
        return None          # «كم الساعة؟» = what time is it, not counting clocks
    if re.search(r"(^|\s)(كم|عدد|عد|عدي|احسب)(\s|$)", q) or q.startswith(("كم ", "عد ")):
        if any(_norm(w) in q for w in PEOPLE_WORDS):
            return "count_people"
        for en, names in objects.ARABIC.items():
            if en != "person" and any(re.search(r"(^|\s)(ال)?" + re.escape(_norm(n)), q) for n in names):
                return "count_object"
        if re.search(r"(شي|اشياء|حاجه|حاجات|اغراض|غرض)", q):
            return "count"
        return None          # «كم الساعة؟» «كم عمري؟» are not about the camera
    if re.search(r"(فيه|في) (احد|أحد|ناس|شخص)", q):
        return "count_people"
    if WHAT_RE.search(q):
        return "what"
    return None


def answer(question: str, img: np.ndarray, dets: list[dict] | None = None) -> str | None:
    """One short answer about the frame, or None if the question is not visual."""
    intent = detect_intent(question)
    if intent is None:
        return None
    q = question or ""
    h, w = img.shape[:2]

    if intent == "fingers":
        r = count_fingers(img)
        if r is None:
            return "عدّ الأصابع يحتاج نموذج اليد — شغّلي التطبيق مع الإنترنت مرة ليُنزَّل."
        n, hands = r
        if hands == 0:
            return "ما أشوف يد واضحة قدام الكاميرا."
        return f"أشوف {AR_NUM.get(n, str(n) + ' أصابع')}."

    if intent == "colour":
        target = None
        if dets:
            near = [d for d in dets if d.get("en") not in ("person", "") and d.get("box")]
            if near:
                target = max(near, key=lambda d: d.get("area") or 0)
        shapes = detect_shapes(img)
        if shapes:
            return f"اللون {shapes[0]['colour']}."
        if target:
            x, y, bw, bh = [int(v) for v in target["box"]]
            crop = img[max(0, y + bh // 4): y + 3 * bh // 4, max(0, x + bw // 4): x + 3 * bw // 4]
            return f"لون {target['ar']} {colour_name(crop)}."
        crop = img[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
        return f"اللون اللي في النص {colour_name(crop)}."

    if intent == "shape":
        shapes = detect_shapes(img)
        if not shapes:
            return "ما أشوف شكل واضح."
        if _has(q, "كم", "عدد"):
            n = len(shapes)
            return "أشوف شكل واحد." if n == 1 else ("أشوف شكلين." if n == 2 else f"أشوف {AR_COUNT.get(n, str(n))} أشكال.")
        if len(shapes) == 1:
            return f"هذا {shapes[0]['ar']} {shapes[0]['colour']}."
        return "أشوف " + "، ".join(f"{s['ar']} {s['colour']}" for s in shapes[:4]) + "."

    dets = dets if dets is not None else (objects.detect(img) if objects.available() else [])
    if intent == "count_people":
        n = sum(1 for d in dets if d.get("en") == "person")
        return "ما أشوف أحد." if n == 0 else ("أشوف شخص واحد." if n == 1 else
                                                "أشوف شخصين." if n == 2 else f"أشوف {AR_COUNT.get(n, str(n))} أشخاص.")
    if intent == "count_object":
        qn = _norm(q)
        for en, names in objects.ARABIC.items():
            if en != "person" and any(re.search(r"(^|\s)(ال)?" + re.escape(_norm(n)), qn) for n in names):
                n = sum(1 for d in dets if d.get("en") == en)
                return f"ما أشوف {names[0]}." if n == 0 else f"العدد: {AR_COUNT.get(n, str(n))}."
    if intent in ("count", "count_object"):
        things = [d for d in dets if d.get("en") not in ("person", "")]
        n = len(things) or len(detect_shapes(img))
        return "ما أقدر أعدّها بدقة." if n == 0 else f"أشوف {AR_COUNT.get(n, str(n))} أشياء."

    # what is this?
    held = [d for d in dets if d.get("en") not in ("person", "") and d.get("near_hand")]
    if held:
        return f"هذا {held[0]['ar']}."
    top = classify(img, 2)
    if top and top[0][1] >= 0.45:
        return f"هذا {top[0][0]}."
    objs = [d for d in dets if d.get("en") not in ("person", "")]
    if objs:
        return f"أشوف {objs[0]['ar']}."
    shapes = detect_shapes(img)
    if shapes and shapes[0]["area"] > 0.05:
        return f"أشوف {shapes[0]['ar']} {shapes[0]['colour']}."
    if top and top[0][1] >= 0.2:
        return f"غالبًا {top[0][0]}، لكني لست متأكدًا."
    return "ما أقدر أشوفه بوضوح."
