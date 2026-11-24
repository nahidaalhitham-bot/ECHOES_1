"""Fetch the face-recognition models.

The two ONNX files total ~37 MB, so they are downloaded once rather than
shipped. If the download cannot happen, face recognition reports itself as
unavailable and every other feature keeps working.

Why this file is defensive: on Windows, a fresh Python install often has no
trusted root certificate bundle, so any HTTPS request fails with
    SSL: CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate
That is not a bug in this app, but it stops a first-time user dead. So we try,
in order:

  1. the normal request (works when certificates are configured);
  2. the same request using `certifi`'s bundle, if that package is installed;
  3. a mirror host, in case one domain is blocked;
  4. a clear, actionable message — never a raw traceback.

A manual fallback is always available: drop the two .onnx files into
app/models/ yourself.
"""

from __future__ import annotations

import shutil
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODELS = Path(__file__).resolve().parent / "models"

# Each entry: filename -> (expected size, [candidate urls])
SOURCES = {
    "face_detection_yunet.onnx": (
        232589,
        [
            "https://github.com/opencv/opencv_zoo/raw/main/models/"
            "face_detection_yunet/face_detection_yunet_2023mar.onnx",
            "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/"
            "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        ],
    ),
    "face_recognition_sface.onnx": (
        38696353,
        [
            "https://github.com/opencv/opencv_zoo/raw/main/models/"
            "face_recognition_sface/face_recognition_sface_2021dec.onnx",
            "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/"
            "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        ],
    ),
    # Everyday-object detector (COCO, 80 classes) for camera reminders and
    # allergy / danger alerts. Optional: the camera still works without it.
    "object_detection_yolox.onnx": (
        35858002,
        [
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
            "object_detection_yolox/object_detection_yolox_2022nov.onnx",
            "https://github.com/opencv/opencv_zoo/raw/main/models/"
            "object_detection_yolox/object_detection_yolox_2022nov.onnx",
        ],
    ),
    # 1000 kinds of objects (ImageNet) for «وش هذا؟» without an AI key.
    "image_classification_mobilenet.onnx": (
        13964571,
        [
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
            "image_classification_mobilenet/image_classification_mobilenetv2_2022apr.onnx",
            "https://github.com/opencv/opencv_zoo/raw/main/models/"
            "image_classification_mobilenet/image_classification_mobilenetv2_2022apr.onnx",
        ],
    ),
    # Hand landmarks (Google MediaPipe) for «كم إصبع؟». Needs `pip install mediapipe`.
    "hand_landmarker.task": (
        7000000,   # about 7.8 MB
        [
            "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
            "hand_landmarker/float16/latest/hand_landmarker.task",
        ],
    ),
}

CERT_HELP = """
كيف تحلّين مشكلة الشهادة (CERTIFICATE_VERIFY_FAILED):

  الحل الأول (الأسهل): شغّلي هذا الأمر مرة واحدة في نفس النافذة
      python -m pip install --upgrade certifi

  الحل الثاني: نزّلي الملفين يدويًا وضعيهما في مجلد app\\models\\
     - face_detection_yunet.onnx
     - face_recognition_sface.onnx
     من: https://github.com/opencv/opencv_zoo/tree/main/models

  ملاحظة: باقي التطبيق يعمل بلا التعرف على الوجوه إذا فشل هذا التنزيل.
"""


def _contexts() -> list[tuple[str, ssl.SSLContext | None]]:
    """SSL contexts to try, best first."""
    out: list[tuple[str, ssl.SSLContext | None]] = [("default", None)]
    try:
        import certifi  # type: ignore

        out.append(("certifi", ssl.create_default_context(cafile=certifi.where())))
    except Exception:
        pass
    return out


def _download(url: str, dest: Path, ctx: ssl.SSLContext | None) -> None:
    with urllib.request.urlopen(url, context=ctx, timeout=60) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _is_complete(dest: Path, expected: int) -> bool:
    return dest.exists() and dest.stat().st_size >= expected * 0.95


def ensure_models(verbose: bool = True) -> bool:
    """Download any missing model. Returns True if both are present afterwards."""
    MODELS.mkdir(parents=True, exist_ok=True)
    ok = True
    cert_failed = False

    for name, (expected, urls) in SOURCES.items():
        dest = MODELS / name
        if _is_complete(dest, expected):
            if verbose:
                print(f"  {name}: موجود بالفعل")
            continue

        if verbose:
            print(f"downloading {name} …", file=sys.stderr)

        got = False
        for ctx_label, ctx in _contexts():
            for url in urls:
                try:
                    _download(url, dest, ctx)
                except ssl.SSLCertVerificationError:
                    cert_failed = True
                    continue
                except Exception as exc:  # noqa: BLE001 - network errors vary
                    if verbose:
                        print(f"    ({ctx_label}) {type(exc).__name__}", file=sys.stderr)
                    continue
                if _is_complete(dest, expected):
                    if verbose:
                        print(f"    ✓ تم ({ctx_label})", file=sys.stderr)
                    got = True
                    break
                if verbose:
                    print("    file looks truncated", file=sys.stderr)
            if got:
                break

        if not got:
            ok = False
            if dest.exists():
                dest.unlink(missing_ok=True)

    if not ok and verbose:
        if cert_failed:
            print(CERT_HELP, file=sys.stderr)
        else:
            print(
                "\nتعذّر تنزيل النماذج. التطبيق سيعمل بدون التعرف على الوجوه.\n"
                "يمكنك تنزيلها يدويًا ووضعها في app\\models\\\n",
                file=sys.stderr,
            )
    return ok


if __name__ == "__main__":
    print("models ready" if ensure_models() else "models unavailable")
