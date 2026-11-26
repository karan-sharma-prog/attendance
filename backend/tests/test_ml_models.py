"""
Phase 6 Standalone Inference Tests for Every Pretrained ML Model:
1. BlazeFace (MediaPipe FaceDetector)
2. MediaPipe FaceLandmarker (EAR, MAR, SolvePnP head pose, temporal challenges)
3. RetinaFace / SCRFD-10G (det_10g.onnx)
4. MiniFASNetV2 Anti-Spoofing (minifasnet_v2.onnx on genuine vs spoof samples)
5. ArcFace ResNet-100 (glintr100.onnx + 112x112 affine alignment + cosine similarity)
"""
import os
import sys
import time
from pathlib import Path
import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.ml.model_registry import get_ml_readiness
from backend.app.ml.face_detector import BlazeFaceService, RetinaFaceSCRFDService
from backend.app.ml.landmarker import FaceLandmarkerService, evaluate_temporal_challenges
from backend.app.ml.anti_spoofing import MiniFASNetService
from backend.app.ml.face_recognition import ArcFaceService, cosine_similarity

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _load_img(name: str) -> np.ndarray:
    img = cv2.imread(str(ASSETS_DIR / name))
    assert img is not None, f"Missing test asset {name}"
    return img


def test_ml_registry_all_core_weights_present():
    state = get_ml_readiness()
    assert state["all_models_ready"] is True
    for k in ("blazeface", "face_landmarker", "retinaface", "arcface_r100", "minifasnet"):
        assert state["models"][k]["loaded"] is True


def test_blazeface_inference():
    svc = BlazeFaceService()
    assert svc.is_ready()

    real_img = _load_img("real_sample.jpg")
    t0 = time.perf_counter()
    dets = svc.detect(real_img, min_conf=0.5)
    ms = (time.perf_counter() - t0) * 1000
    print(f"\n[BlazeFace] real_sample.jpg -> {len(dets)} face(s) in {ms:.2f} ms, score={dets[0]['score']}")
    assert len(dets) == 1
    assert dets[0]["score"] >= 0.5
    assert len(dets[0]["keypoints"]) >= 4

    # Short-range selfie detector multi-face check (two faces side-by-side at selfie distance)
    multi_img = cv2.hconcat([real_img, real_img])
    multi_dets = svc.detect(multi_img, min_conf=0.5)
    print(f"[BlazeFace] side-by-side multi-face -> {len(multi_dets)} faces detected")
    assert len(multi_dets) == 2


def test_mediapipe_landmarker_ear_mar_pose():
    svc = FaceLandmarkerService()
    assert svc.is_ready()

    real_img = _load_img("real_sample.jpg")
    t0 = time.perf_counter()
    res = svc.analyze_frame(real_img)
    ms = (time.perf_counter() - t0) * 1000
    print(
        f"\n[FaceLandmarker] {ms:.2f} ms | EAR={res['ear_avg']} | MAR={res['mar']} | Pose={res['pose']}"
    )
    assert res["face_detected"] is True
    assert res["face_count"] == 1
    assert 0.05 < res["ear_avg"] < 0.65
    assert 0.0 <= res["mar"] < 1.5
    assert abs(res["pose"]["pitch"]) < 35.0
    assert len(res["five_points"]) == 5

    # Temporal challenge evaluation unit check (EAR drop blink + yaw turn)
    seq = [
        {"face_count": 1, "ear_avg": 0.30, "mar": 0.12, "pose": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}},
        {"face_count": 1, "ear_avg": 0.16, "mar": 0.12, "pose": {"yaw": -14.0, "pitch": 0.0, "roll": 0.0}},
        {"face_count": 1, "ear_avg": 0.29, "mar": 0.62, "pose": {"yaw": 13.0, "pitch": 0.0, "roll": 0.0}},
    ]
    eval_res = evaluate_temporal_challenges(seq, ["blink_twice", "turn_head_left", "open_mouth"])
    assert eval_res["passed"] is True


def test_retinaface_scrfd_inference():
    svc = RetinaFaceSCRFDService()
    assert svc.is_ready()

    real_img = _load_img("real_sample.jpg")
    t0 = time.perf_counter()
    dets = svc.detect(real_img, conf_thresh=0.5)
    ms = (time.perf_counter() - t0) * 1000
    print(f"\n[RetinaFace/SCRFD-10G] real_sample.jpg -> {len(dets)} face(s) in {ms:.2f} ms, score={dets[0]['score']}")
    assert len(dets) == 1
    assert len(dets[0]["landmarks_5"]) == 5

    multi_img = _load_img("t1.jpg")
    multi_dets = svc.detect(multi_img, conf_thresh=0.5)
    print(f"[RetinaFace/SCRFD-10G] t1.jpg -> {len(multi_dets)} faces detected")
    assert len(multi_dets) >= 2


def test_minifasnet_antispoof_real_vs_spoof():
    det = RetinaFaceSCRFDService()
    spoof_svc = MiniFASNetService()
    assert spoof_svc.is_ready()

    real_img = _load_img("real_sample.jpg")
    real_dets = det.detect(real_img)
    assert len(real_dets) == 1
    t0 = time.perf_counter()
    real_pred = spoof_svc.predict_liveness(real_img, real_dets[0]["bbox"], threshold=0.5)
    ms = (time.perf_counter() - t0) * 1000
    print(f"\n[MiniFASNetV2] real_sample.jpg ({ms:.2f} ms) -> {real_pred}")

    spoof_img = _load_img("spoof_sample.jpg")
    spoof_dets = det.detect(spoof_img)
    assert len(spoof_dets) >= 1
    spoof_pred = spoof_svc.predict_liveness(spoof_img, spoof_dets[0]["bbox"], threshold=0.5)
    print(f"[MiniFASNetV2] spoof_sample.jpg -> {spoof_pred}")

    assert real_pred["live_score"] > spoof_pred["live_score"]
    assert real_pred["is_live"] is True
    assert spoof_pred["is_live"] is False


def test_arcface_resnet100_1_to_1_similarity():
    det = RetinaFaceSCRFDService()
    arc = ArcFaceService()
    assert arc.is_ready()

    img_a = _load_img("real_sample.jpg")
    dets_a = det.detect(img_a)
    assert len(dets_a) == 1
    pts_a = np.asarray(dets_a[0]["landmarks_5"], dtype=np.float32)

    t0 = time.perf_counter()
    emb_a = arc.get_embedding(img_a, pts_a)
    ms = (time.perf_counter() - t0) * 1000
    print(f"\n[ArcFace ResNet-100] {ms:.2f} ms | dim={emb_a.shape[0]} | norm={np.linalg.norm(emb_a):.4f}")
    assert emb_a.shape == (512,)
    assert abs(float(np.linalg.norm(emb_a)) - 1.0) < 1e-3

    # Slightly brightness-adjusted same person -> genuine pair
    img_a_bright = np.clip(img_a.astype(np.int16) + 12, 0, 255).astype(np.uint8)
    dets_a2 = det.detect(img_a_bright)
    emb_a2 = arc.get_embedding(img_a_bright, np.asarray(dets_a2[0]["landmarks_5"], dtype=np.float32))
    genuine_sim = cosine_similarity(emb_a, emb_a2)

    # Distinct person from t1.jpg -> impostor pair
    img_b = _load_img("t1.jpg")
    dets_b = det.detect(img_b)
    assert len(dets_b) >= 1
    emb_b = arc.get_embedding(img_b, np.asarray(dets_b[0]["landmarks_5"], dtype=np.float32))
    impostor_sim = cosine_similarity(emb_a, emb_b)

    print(f"[ArcFace Cosine] Genuine similarity={genuine_sim:.4f} | Impostor similarity={impostor_sim:.4f}")
    assert genuine_sim > 0.85
    assert impostor_sim < 0.45
