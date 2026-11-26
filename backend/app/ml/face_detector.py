"""
Face Detection Services:
1. BlazeFace (MediaPipe Tasks FaceDetector) — fast real-time detection & single-face validation.
2. RetinaFace / SCRFD-10G (det_10g.onnx) — registration & 5-landmark detection.
"""
from typing import List, Dict, Any
import cv2
import numpy as np
import mediapipe as mp
import onnxruntime as ort
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions
from backend.app.ml.model_registry import WEIGHTS_DIR


class BlazeFaceService:
    def __init__(self) -> None:
        self._model_path = WEIGHTS_DIR / "blaze_face_short_range.tflite"

    def is_ready(self) -> bool:
        return self._model_path.is_file() and self._model_path.stat().st_size > 1024

    def detect(self, bgr_image: np.ndarray, min_conf: float = 0.6) -> List[Dict[str, Any]]:
        if not self.is_ready():
            raise RuntimeError("BlazeFace weight (blaze_face_short_range.tflite) is missing.")

        h, w = bgr_image.shape[:2]
        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(self._model_path)),
            min_detection_confidence=min_conf,
        )
        with FaceDetector.create_from_options(options) as detector:
            res = detector.detect(mp_img)

        detections: List[Dict[str, Any]] = []
        for det in res.detections:
            bb = det.bounding_box
            x1 = max(0, int(bb.origin_x))
            y1 = max(0, int(bb.origin_y))
            x2 = min(w, int(bb.origin_x + bb.width))
            y2 = min(h, int(bb.origin_y + bb.height))
            score = float(det.categories[0].score) if det.categories else 0.0
            kps = [[kp.x * w, kp.y * h] for kp in (det.keypoints or [])]
            detections.append({"bbox": [x1, y1, x2, y2], "score": round(score, 4), "keypoints": kps})
        return detections


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, i % 2] + distance[:, i]
        py = points[:, i % 2 + 1] + distance[:, i + 1]
        preds.extend([px, py])
    return np.stack(preds, axis=-1)


def _nms(dets: np.ndarray, thresh: float = 0.4) -> List[int]:
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(ovr <= thresh)[0]
        order = order[inds + 1]
    return keep


class RetinaFaceSCRFDService:
    """InsightFace SCRFD-10G (det_10g.onnx) RetinaFace-family detector with 5 landmarks."""

    def __init__(self) -> None:
        self._model_path = WEIGHTS_DIR / "det_10g.onnx"
        self._session: ort.InferenceSession | None = None
        self._input_size = (640, 640)
        self._feat_stride_fpn = [8, 16, 32]
        self._num_anchors = 2

    def is_ready(self) -> bool:
        return self._model_path.is_file() and self._model_path.stat().st_size > 1024

    def _get_session(self) -> ort.InferenceSession:
        if self._session is None:
            if not self.is_ready():
                raise RuntimeError("RetinaFace/SCRFD weight (det_10g.onnx) is missing.")
            self._session = ort.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])
        return self._session

    def detect(self, bgr_image: np.ndarray, conf_thresh: float = 0.5) -> List[Dict[str, Any]]:
        sess = self._get_session()
        in_w, in_h = self._input_size
        orig_h, orig_w = bgr_image.shape[:2]

        im_ratio = float(orig_h) / orig_w
        model_ratio = float(in_h) / in_w
        if im_ratio > model_ratio:
            new_h = in_h
            new_w = int(new_h / im_ratio)
        else:
            new_w = in_w
            new_h = int(new_w * im_ratio)
        det_scale = float(new_h) / orig_h

        resized = cv2.resize(bgr_image, (new_w, new_h))
        det_img = np.zeros((in_h, in_w, 3), dtype=np.uint8)
        det_img[:new_h, :new_w, :] = resized

        blob = cv2.dnn.blobFromImage(
            det_img, 1.0 / 128.0, (in_w, in_h), (127.5, 127.5, 127.5), swapRB=True
        )
        input_name = sess.get_inputs()[0].name
        net_outs = sess.run(None, {input_name: blob})

        fmc = len(self._feat_stride_fpn)
        scores_list, bboxes_list, kpss_list = [], [], []
        for idx, stride in enumerate(self._feat_stride_fpn):
            raw_scores = net_outs[idx]
            raw_bboxes = net_outs[idx + fmc]
            raw_kpss = net_outs[idx + fmc * 2]

            scores = raw_scores[0] if raw_scores.ndim == 3 else raw_scores
            bbox_preds = (raw_bboxes[0] if raw_bboxes.ndim == 3 else raw_bboxes) * stride
            kps_preds = (raw_kpss[0] if raw_kpss.ndim == 3 else raw_kpss) * stride

            height = in_h // stride
            width = in_w // stride
            anchor_centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
            anchor_centers = (anchor_centers * stride).reshape((-1, 2))
            anchor_centers = np.stack([anchor_centers] * self._num_anchors, axis=1).reshape((-1, 2))

            pos_inds = np.where(scores >= conf_thresh)[0]
            if len(pos_inds) == 0:
                continue
            bboxes = _distance2bbox(anchor_centers, bbox_preds)[pos_inds]
            kpss = _distance2kps(anchor_centers, kps_preds)[pos_inds]
            scores_list.append(scores[pos_inds])
            bboxes_list.append(bboxes)
            kpss_list.append(kpss)

        if not scores_list:
            return []

        scores_all = np.vstack(scores_list)
        bboxes_all = np.vstack(bboxes_list) / det_scale
        kpss_all = np.vstack(kpss_list).reshape((-1, 5, 2)) / det_scale

        pre_det = np.hstack((bboxes_all, scores_all)).astype(np.float32)
        keep = _nms(pre_det, 0.4)

        results: List[Dict[str, Any]] = []
        for i in keep:
            x1, y1, x2, y2, sc = pre_det[i]
            results.append(
                {
                    "bbox": [max(0, int(x1)), max(0, int(y1)), min(orig_w, int(x2)), min(orig_h, int(y2))],
                    "score": round(float(sc), 4),
                    "landmarks_5": kpss_all[i].tolist(),
                }
            )
        return results
