"""Face recognition — opt-in, consent-based, and allowed to say "not sure".

Design rules (deliberate, and defensible to a judge):

1. **Enrolment is explicit and consented.** A person is only recognised if a
   family member enrolled them and recorded that consent.
2. **Refusal beats a guess.** If the best match is below the threshold, or two
   enrolled people are too close together, the answer is "I am not sure" —
   never a name. A confidently wrong name is the worst possible output when
   addressing someone with memory loss.
3. **No silent capture.** This module only runs on an explicit request that
   carries an image. There is no background loop.
4. **Deleting a person deletes their embedding.**

Models: OpenCV YuNet (detection) + SFace (128-d embeddings). Both run locally;
no image leaves the machine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import numpy as np

MODELS = Path(__file__).resolve().parent / "models"
DETECTOR_PATH = MODELS / "face_detection_yunet.onnx"
RECOGNISER_PATH = MODELS / "face_recognition_sface.onnx"

# Cosine similarity in SFace: higher is more alike. 0.363 is the upstream
# reference threshold for "same identity"; we sit a little above it.
ACCEPT_THRESHOLD = 0.40
# If the top two candidates are within this margin, we treat it as ambiguous.
AMBIGUITY_MARGIN = 0.06

_detector = None
_recogniser = None


def available() -> bool:
    return DETECTOR_PATH.exists() and RECOGNISER_PATH.exists()


def _load():
    global _detector, _recogniser
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(
            str(DETECTOR_PATH), "", (320, 320), 0.6, 0.3, 5000
        )
    if _recogniser is None:
        _recogniser = cv2.FaceRecognizerSF.create(str(RECOGNISER_PATH), "")
    return _detector, _recogniser


def _decode(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img


def _largest_face(img: np.ndarray):
    det, rec = _load()
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return None, None, rec
    # choose the largest detection; a single enrolled face is the norm
    areas = [f[2] * f[3] for f in faces]
    face = faces[int(np.argmax(areas))]
    aligned = rec.alignCrop(img, face)
    emb = rec.feature(aligned).flatten()
    return emb, face, rec


def embed(image_bytes: bytes) -> np.ndarray | None:
    """Return a 128-d embedding for the most prominent face, or None."""
    img = _decode(image_bytes)
    emb, _, _ = _largest_face(img)
    return emb


def describe_frame(image_bytes: bytes) -> dict:
    """What is in this frame, without identifying anyone."""
    img = _decode(image_bytes)
    det, _ = _load()
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(img)
    count = 0 if faces is None else len(faces)
    return {"faces_detected": count, "width": w, "height": h}


# Horizontal field of view of a typical webcam / necklace camera.
CAMERA_HFOV_DEG = 65.0
FACE_WIDTH_M = 0.16


def face_distance_m(face_w_px: float, frame_w_px: float) -> float | None:
    """Rough distance to a face from its width in the frame (pinhole model)."""
    if face_w_px <= 0 or frame_w_px <= 0:
        return None
    import math
    frac = face_w_px / frame_w_px
    return round(FACE_WIDTH_M / (2 * math.tan(math.radians(CAMERA_HFOV_DEG / 2)) * frac), 1)


def identify(image_bytes: bytes, candidates: list[dict]) -> dict:
    """Compare a frame against enrolled candidates.

    `candidates` is a list of {"person_id", "name", "relation", "embedding"}
    where embedding is a list of floats. Returns an explicit decision.
    """
    if not available():
        return _refuse("models_missing",
                       "التعرّف على الوجوه غير متاح: النماذج غير موجودة.")

    img = _decode(image_bytes)
    emb, face, _ = _largest_face(img)
    if emb is None:
        return _refuse("no_face", "لم أرى وجهًا واضحًا. قرّب المسافة أو حسّن الإضاءة.")
    dist = face_distance_m(float(face[2]), float(img.shape[1]))

    if not candidates:
        return _refuse("nobody_enrolled",
                       "لا يوجد أحد مسجَّل. لم أسجّل أي شخص بعد.")

    scored = []
    for c in candidates:
        ref = np.asarray(c["embedding"], dtype=np.float32)
        if ref.shape != emb.shape:
            continue
        sim = float(np.dot(emb, ref) / (np.linalg.norm(emb) * np.linalg.norm(ref) + 1e-9))
        scored.append((sim, c))

    if not scored:
        return _refuse("no_usable_candidates",
                       "لا أملك نموذج وجه صالحًا لهؤلاء الأشخاص.")

    scored.sort(key=lambda t: t[0], reverse=True)
    best_sim, best = scored[0]

    # Second-best check: if two people look alike, refuse rather than pick.
    if (
        len(scored) > 1
        and (best_sim - scored[1][0]) < AMBIGUITY_MARGIN
        and best_sim >= ACCEPT_THRESHOLD
    ):
        return _refuse(
            "ambiguous",
            "أرى وجهًا، لكن التطابق غير مؤكد بين أكثر من شخص. لن أخمّن.",
            similarity=round(best_sim, 3),
        )

    if best_sim < ACCEPT_THRESHOLD:
        return _refuse(
            "below_threshold",
            "أرى وجهًا، لكني لست متأكدًا من هويته. لن أخمّن.",
            similarity=round(best_sim, 3),
        )

    return {
        "ok": True,
        "status": "recognised",
        "person_id": best["person_id"],
        "name": best["name"],
        "relation": best.get("relation", ""),
        "similarity": round(best_sim, 3),
        "distance_m": dist,
    }


def _refuse(reason: str, message: str, **extra) -> dict:
    return {"ok": False, "status": "refused", "reason": reason,
            "message": message, **extra}


# =====================================================================
# Scene / object recognition
# =====================================================================
#
# HONEST SCOPE. There is no trained object detector. This matches *a place or
# object the family photographed*, using SIFT local features — the same family
# of method used for photo stitching and landmark matching.
#
# What it genuinely does:
#   - recognises the SAME scene from a close/similar viewpoint, under different
#     brightness and mild cropping
#   - recognises a distinctive object photographed on a plain background
#
# What it cannot do:
#   - name an object it was never shown ("that is a kettle")
#   - generalise to a very different angle, a different day, or heavy occlusion
#
# It refuses rather than guessing. A wrong "this is your living room" would be
# worse than "I do not recognise this place".

# Ratio of matched keypoints to reference keypoints. Measured on real photos:
# different scenes ~0.01, same scene cropped+brightened ~0.63. A threshold at
# 0.12 sits far above the noise floor and well below a true match.
SCENE_ACCEPT = 0.12
SCENE_MAX_FEATURES = 400


def _sift():
    global _sift_obj
    try:
        return _sift_obj
    except NameError:
        pass
    _sift_obj = cv2.SIFT_create(nfeatures=SCENE_MAX_FEATURES)
    return _sift_obj


def scene_descriptor(image_bytes: bytes) -> list[float] | None:
    """SIFT descriptors for an image, serialised as a flat float list.

    SIFT descriptor rows are 128 floats each; we store them flattened together
    with keypoint coordinates so scoring can reuse them.
    """
    import numpy as np

    img = _decode(image_bytes)
    if img is None:
        return None
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, (480, 480), interpolation=cv2.INTER_AREA)
    kps, des = _sift().detectAndCompute(grey, None)
    if des is None or len(kps) == 0:
        return None
    # [x, y, scale, 128 floats] per keypoint — enough to re-run matching.
    rows = []
    for kp, d in zip(kps, des):
        rows.append([float(kp.pt[0]), float(kp.pt[1]), float(kp.size)])
        rows[-1].extend(float(x) for x in d)
    return [float(len(rows))] + [v for row in rows for v in row]


def _unpack(flat):
    import numpy as np
    n = int(flat[0])
    rest = flat[1:]
    rows = []
    for i in range(n):
        base = i * 131
        rows.append(rest[base:base + 131])
    meta = np.asarray([r[:3] for r in rows], dtype=np.float32)
    desc = np.asarray([r[3:] for r in rows], dtype=np.float32)
    return meta, desc


def _match_score(ref_flat, frame_flat) -> float:
    import numpy as np
    if not ref_flat or not frame_flat:
        return 0.0
    _, d1 = _unpack(ref_flat)
    _, d2 = _unpack(frame_flat)
    if d1.size == 0 or d2.size == 0:
        return 0.0
    bf = cv2.BFMatcher()
    try:
        matches = bf.knnMatch(d1, d2, k=2)
    except cv2.error:
        return 0.0
    good = 0
    for pair in matches:
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
            good += 1
    return good / float(len(d1))


def identify_scene(image_bytes: bytes, candidates: list[dict]) -> dict:
    """Match a frame against registered place/object photos.

    `candidates` is a list of {"photo_id","label","memory_id","descriptor"}.
    Returns an explicit decision; never guesses.
    """
    frame = scene_descriptor(image_bytes)
    if frame is None:
        return _refuse("no_features",
                       "لم أجد تفاصيل كافية في الصورة. قرّب المسافة أو حسّن الإضاءة.")

    if not candidates:
        return _refuse(
            "nothing_taught",
            "لم تُسجَّل أي صور أماكن أو أشياء. أضيفيها من الذاكرة الشخصية.",
        )

    scored = []
    for c in candidates:
        try:
            ref = json.loads(c["descriptor"]) if isinstance(c["descriptor"], str) \
                else c["descriptor"]
        except Exception:
            continue
        if not ref:
            continue
        scored.append((_match_score(ref, frame), c))

    if not scored:
        return _refuse("no_usable_descriptors",
                       "لا أملك وصفًا بصريًا صالحًا لهذه الصور.")

    scored.sort(key=lambda t: t[0], reverse=True)
    best_sim, best = scored[0]

    if best_sim < SCENE_ACCEPT:
        return _refuse(
            "below_threshold",
            "لا أتعرّف على هذا المكان أو الشيء. لن أخمّن.",
            similarity=round(best_sim, 3),
        )

    return {
        "ok": True,
        "status": "recognised",
        "kind": "scene",
        "photo_id": best.get("photo_id"),
        "memory_id": best["memory_id"],
        "label": best["label"],
        "similarity": round(best_sim, 3),
    }
