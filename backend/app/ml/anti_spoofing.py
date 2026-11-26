"""
Passive Facial Anti-Spoofing Service (MiniFASNet ONNX).
Detects printed photos, screen presentation attacks, and texture anomalies.
"""
from typing import Dict, Any, List
import cv2
import numpy as np
import onnxruntime as ort
from backend.app.ml.model_registry import WEIGHTS_DIR


def _softmax(logits: np.ndarray) -> np.ndarray:
    e = np.exp(logits - np.max(logits))
    return e / np.sum(e)


def _crop_with_scale(bgr_image: np.ndarray, bbox: List[int], out_w: int, out_h: int, scale: float = 2.7) -> np.ndarray:
    src_h, src_w = bgr_image.shape[:2]
    x1, y1, x2, y2 = bbox
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)

    s = min((src_h - 1) / bh, min((src_w - 1) / bw, scale))
    new_w = bw * s
    new_h = bh * s
    cx = x1 + bw / 2.0
    cy = y1 + bh / 2.0

    nx1 = max(0, int(cx - new_w / 2.0))
    ny1 = max(0, int(cy - new_h / 2.0))
    nx2 = min(src_w - 1, int(cx + new_w / 2.0))
    ny2 = min(src_h - 1, int(cy + new_h / 2.0))

    crop = bgr_image[ny1 : ny2 + 1, nx1 : nx2 + 1]
    if crop.size == 0:
        crop = bgr_image
    return cv2.resize(crop, (out_w, out_h))


class MiniFASNetService:
    def __init__(self) -> None:
        self._model_path = WEIGHTS_DIR / "minifasnet_v2.onnx"
        self._session: ort.InferenceSession | None = None

    def is_ready(self) -> bool:
        return self._model_path.is_file() and self._model_path.stat().st_size > 1024

    def _get_session(self) -> ort.InferenceSession:
        if self._session is None:
            if not self.is_ready():
                raise RuntimeError("MiniFASNet ONNX weight (minifasnet_v2.onnx) is missing.")
            self._session = ort.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])
        return self._session

    def predict_liveness(self, bgr_image: np.ndarray, bbox: List[int], threshold: float = 0.70) -> Dict[str, Any]:
        sess = self._get_session()
        in_meta = sess.get_inputs()[0]
        in_shape = in_meta.shape
        # Handle dynamic or fixed HxW (80x80 for Silent-Face MiniFASNetV2, 128x128 for facenox MiniFASNetV2-SE)
        target_h = int(in_shape[2]) if isinstance(in_shape[2], int) else 80
        target_w = int(in_shape[3]) if isinstance(in_shape[3], int) else 80

        crop = _crop_with_scale(bgr_image, bbox, target_w, target_h, scale=2.7)
        # MiniFASNet expects float32 BGR tensor NCHW
        blob = crop.astype(np.float32).transpose(2, 0, 1)[None, ...]
        # Check normalization convention based on input size (128x128 SE variants often use [0,1] or ImageNet, 80x80 Silent-Face uses [0,255] raw BGR)
        if target_h == 128:
            blob = blob / 255.0

        logits = sess.run(None, {in_meta.name: blob})[0][0]
        probs = _softmax(np.asarray(logits, dtype=np.float32))

        if probs.shape[0] == 3:
            # Silent-Face 3-class convention: class 1 = Live, class 0 & 2 = Spoof
            live_score = float(probs[1])
            spoof_score = float(probs[0] + probs[2])
        elif probs.shape[0] == 2:
            # Binary convention: class 1 = Live (or check standard)
            live_score = float(probs[1])
            spoof_score = float(probs[0])
        else:
            live_score = float(probs[0])
            spoof_score = 1.0 - live_score

        return {
            "live_score": round(live_score, 4),
            "spoof_score": round(spoof_score, 4),
            "is_live": live_score >= threshold,
            "num_classes": int(probs.shape[0]),
            "input_size": [target_h, target_w],
        }
