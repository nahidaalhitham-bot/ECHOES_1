"""Local object detection for the camera (YOLOX-s, COCO 80 classes).

Runs entirely on the device through OpenCV DNN — no image leaves the machine.
It tells the companion *what kind of thing* is in front of the patient
("a couch", "a knife", "a cup") so that it can be matched against the memory
network and the caregiver's allergy / danger lists.

Honest scope:
- It knows 80 everyday categories (COCO). It cannot tell *whose* couch it is;
  that comes from the family's own photos (SIFT scene matching in vision.py).
- "Touching" is estimated: the necklace camera faces outward, so an object the
  patient is holding is large and in the lower part of the frame. When an AI
  key is configured, the vision model is asked directly instead.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

MODELS = Path(__file__).resolve().parent / "models"
YOLOX_PATH = MODELS / "object_detection_yolox.onnx"

INPUT = 640
SCORE_MIN = 0.45
NMS_IOU = 0.45

COCO = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]

# Arabic names (first = spoken name) and the synonyms a family is likely to
# have written in the profile. Matching uses all of them.
ARABIC: dict[str, list[str]] = {
    "person": ["شخص"],
    "bicycle": ["دراجة", "سيكل", "دراجه"],
    "car": ["سيارة", "سياره", "السيارة", "موتر"],
    "motorcycle": ["دباب", "دراجة نارية"],
    "bus": ["باص", "حافلة"],
    "boat": ["قارب", "سفينة", "طراد"],
    "bench": ["مقعد", "كرسي الحديقة"],
    "bird": ["طير", "عصفور", "طيور", "حمام"],
    "cat": ["قطة", "قطه", "قط", "بسة", "قطط"],
    "dog": ["كلب", "كلاب"],
    "horse": ["حصان", "خيل", "فرس"],
    "sheep": ["خروف", "غنم", "خرفان"],
    "cow": ["بقرة", "بقر"],
    "umbrella": ["مظلة", "شمسية"],
    "handbag": ["شنطة", "حقيبة"],
    "suitcase": ["شنطة سفر", "حقيبة سفر"],
    "sports ball": ["كرة", "كوره", "كورة"],
    "bottle": ["قارورة", "زجاجة", "علبة", "قزازة"],
    "wine glass": ["كأس", "كاسة"],
    "cup": ["كوب", "فنجان", "فنجال", "بيالة", "استكانة", "كاسة", "قهوة", "شاي"],
    "fork": ["شوكة"],
    "knife": ["سكين", "سكاكين", "سكينة"],
    "spoon": ["ملعقة", "ملاعق"],
    "bowl": ["صحن", "وعاء", "زبدية"],
    "banana": ["موز", "موزة"],
    "apple": ["تفاح", "تفاحة"],
    "sandwich": ["ساندويتش", "سندويشة", "شطيرة"],
    "orange": ["برتقال", "برتقالة"],
    "broccoli": ["بروكلي"],
    "carrot": ["جزر"],
    "hot dog": ["نقانق", "هوت دوق"],
    "pizza": ["بيتزا"],
    "donut": ["دونات"],
    "cake": ["كيك", "كعكة", "كيكة", "حلى"],
    "chair": ["كرسي", "كراسي"],
    "couch": ["أريكة", "اريكة", "كنبة", "كنب", "الكنبة", "صوفا", "كنبه"],
    "potted plant": ["نبتة", "زرع", "زرعة", "نباتات", "شجرة", "زهور"],
    "bed": ["سرير", "فراش"],
    "dining table": ["طاولة", "سفرة", "طاولة الطعام"],
    "toilet": ["حمام", "دورة المياه"],
    "tv": ["تلفزيون", "تلفاز", "التلفزيون", "شاشة"],
    "laptop": ["لابتوب", "حاسوب", "كمبيوتر"],
    "remote": ["ريموت", "جهاز التحكم"],
    "keyboard": ["لوحة مفاتيح", "كيبورد"],
    "cell phone": ["جوال", "هاتف", "تلفون", "موبايل", "الجوال"],
    "microwave": ["مايكرويف", "ميكروويف"],
    "oven": ["فرن", "موقد", "غاز", "الفرن", "البوتاجاز"],
    "toaster": ["محمصة"],
    "sink": ["مغسلة", "حوض"],
    "refrigerator": ["ثلاجة", "براد", "الثلاجة"],
    "book": ["كتاب", "مصحف", "كتب", "دفتر"],
    "clock": ["ساعة", "ساعة الحائط"],
    "vase": ["مزهرية", "فازة"],
    "scissors": ["مقص"],
    "teddy bear": ["دبدوب", "دمية", "لعبة"],
    "hair drier": ["سشوار", "مجفف الشعر"],
    "toothbrush": ["فرشاة أسنان", "فرشاة"],
}

# Categories that are dangerous by default, even if the caregiver did not list
# them. The caregiver's own list is added on top.
DEFAULT_DANGER = {"knife", "scissors", "oven"}

# Large furniture / scenery: seen, but never "in the patient's hand".
BACKGROUND = {"person", "dining table", "couch", "bed", "refrigerator", "toilet",
              "tv", "sink", "chair", "bench", "car", "bus", "train", "truck",
              "boat", "airplane", "potted plant", "horse", "cow", "elephant"}

_net = None


def available() -> bool:
    return YOLOX_PATH.exists() and YOLOX_PATH.stat().st_size > 30_000_000


def _load():
    global _net
    if _net is None:
        _net = cv2.dnn.readNet(str(YOLOX_PATH))
    return _net


def _grids():
    grids, strides = [], []
    for s in (8, 16, 32):
        n = INPUT // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        g = np.stack((xv, yv), 2).reshape(-1, 2)
        grids.append(g)
        strides.append(np.full((g.shape[0], 1), s))
    return np.concatenate(grids, 0).astype(np.float32), \
        np.concatenate(strides, 0).astype(np.float32)


_GRID, _STRIDE = None, None


def detect(img: np.ndarray) -> list[dict]:
    """Return detections: {"en","ar","synonyms","score","box":[x,y,w,h],
    "area":fraction of frame,"near_hand":bool}."""
    global _GRID, _STRIDE
    if not available():
        return []
    if _GRID is None:
        _GRID, _STRIDE = _grids()
    h, w = img.shape[:2]
    ratio = min(INPUT / h, INPUT / w)
    resized = cv2.resize(img, (int(w * ratio), int(h * ratio)),
                         interpolation=cv2.INTER_LINEAR)
    padded = np.full((INPUT, INPUT, 3), 114, dtype=np.uint8)
    padded[: resized.shape[0], : resized.shape[1]] = resized
    blob = padded.transpose(2, 0, 1)[None].astype(np.float32)

    net = _load()
    net.setInput(blob)
    out = net.forward()[0]                      # (8400, 85)
    out[:, :2] = (out[:, :2] + _GRID) * _STRIDE
    out[:, 2:4] = np.exp(out[:, 2:4]) * _STRIDE

    obj = out[:, 4:5]
    cls = out[:, 5:]
    scores_all = obj * cls
    cls_id = np.argmax(scores_all, axis=1)
    scores = scores_all[np.arange(len(cls_id)), cls_id]
    keep = scores >= SCORE_MIN
    if not np.any(keep):
        return []
    boxes = out[keep, :4] / ratio
    scores = scores[keep]
    cls_id = cls_id[keep]
    xywh = [[float(b[0] - b[2] / 2), float(b[1] - b[3] / 2), float(b[2]), float(b[3])]
            for b in boxes]
    idx = cv2.dnn.NMSBoxesBatched(xywh, scores.tolist(), cls_id.tolist(),
                                  SCORE_MIN, NMS_IOU)
    dets = []
    for i in np.array(idx).flatten():
        x, y, bw, bh = xywh[i]
        en = COCO[int(cls_id[i])]
        area = max(0.0, bw * bh) / float(w * h)
        cx, bottom = x + bw / 2, y + bh
        # Outward-facing necklace camera: a held object is big and low.
        near_hand = en not in BACKGROUND and area < 0.6 and (
            area >= 0.10 or (area >= 0.03 and bottom >= 0.80 * h
                             and 0.15 * w <= cx <= 0.85 * w))
        names = ARABIC.get(en, [en])
        dets.append({
            "en": en, "ar": names[0], "synonyms": names,
            "score": round(float(scores[i]), 3),
            "box": [round(x), round(y), round(bw), round(bh)],
            "area": round(area, 3), "near_hand": bool(near_hand),
        })
    dets.sort(key=lambda d: -d["score"])
    return dets
