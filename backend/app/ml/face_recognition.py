"""
Credential-Based Facial Identity Verification (ArcFace ResNet-100 ONNX).
Generates 512-D L2-normalized facial embeddings and computes 1:1 cosine similarity.
"""
from typing import Dict, Any
import cv2
import numpy as np
import onnxruntime as ort
from backend.app.ml.model_registry import WEIGHTS_DIR
from backend.app.ml.alignment import align_face_112


def cosine_similarity(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    a = np.asarray(emb_a, dtype=np.float32).flatten()
    b = np.asarray(emb_b, dtype=np.float32).flatten()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-8:
        return 0.0
    return float(np.dot(a, b) / denom)


class ArcFaceService:
    def __init__(self) -> None:
        self._model_path = WEIGHTS_DIR / "glintr100.onnx"
        self._session: ort.InferenceSession | None = None

    def is_ready(self) -> bool:
        return self._model_path.is_file() and self._model_path.stat().st_size > 1024

    def _get_session(self) -> ort.InferenceSession:
        if self._session is None:
            if not self.is_ready():
                raise RuntimeError("ArcFace ResNet-100 weight (glintr100.onnx) is missing.")
            self._session = ort.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])
        return self._session

    def get_embedding(self, bgr_image: np.ndarray, five_points: np.ndarray) -> np.ndarray:
        sess = self._get_session()
        aligned_bgr = align_face_112(bgr_image, five_points)
        rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
        # Standard InsightFace normalization: (pixel - 127.5) / 127.5 -> [-1, 1]
        normed = (rgb - 127.5) / 127.5
        nchw = np.transpose(normed, (2, 0, 1))[None, ...]

        in_name = sess.get_inputs()[0].name
        emb = sess.run(None, {in_name: nchw})[0][0].astype(np.float32)
        norm = np.linalg.norm(emb)
        if norm > 1e-8:
            emb = emb / norm
        return emb

    def verify_1_to_1(
        self,
        live_bgr: np.ndarray,
        five_points: np.ndarray,
        enrolled_embedding_bytes: bytes,
        threshold: float = 0.68,
    ) -> Dict[str, Any]:
        live_emb = self.get_embedding(live_bgr, five_points)
        enrolled_emb = np.frombuffer(enrolled_embedding_bytes, dtype=np.float32)
        score = cosine_similarity(live_emb, enrolled_emb)
        return {
            "similarity": round(score, 4),
            "threshold": threshold,
            "matched": score >= threshold,
            "embedding_dim": int(live_emb.shape[0]),
        }
