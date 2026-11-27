"""
MediaPipe Face Landmarker + EAR / MAR / SolvePnP Head Pose Module.
Uses MediaPipe 1.2.3 Tasks API (face_landmarker.task) to extract 478 3D landmarks,
compute Eye Aspect Ratio (EAR), Mouth Aspect Ratio (MAR), 5-point alignment coords,
and 3D head orientation (yaw, pitch, roll) via cv2.solvePnP.
"""
import math
from typing import Dict, Any, List, Optional
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions
from backend.app.ml.model_registry import WEIGHTS_DIR

# MediaPipe FaceMesh landmark indices
LEFT_EYE_IDX = [33, 160, 158, 133, 153, 144]   # P1, P2, P3, P4, P5, P6
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380] # P1, P2, P3, P4, P5, P6

# Mouth inner/outer landmarks for MAR: horizontal (78, 308), vertical pairs (82-87, 13-14, 312-317)
MOUTH_H = (78, 308)
MOUTH_V = [(82, 87), (13, 14), (312, 317)]

# Canonical 3D facial model points (mm) aligned with OpenCV camera coordinates (+X right, +Y down, +Z into scene)
MODEL_3D_POINTS = np.array(
    [
        [0.0, 0.0, 0.0],          # Nose tip (1)
        [0.0, 63.6, 12.5],        # Chin (152)
        [-43.3, -32.7, 26.0],     # Left eye left corner (33)
        [43.3, -32.7, 26.0],      # Right eye right corner (263)
        [-28.9, 28.9, 24.1],      # Left mouth corner (61)
        [28.9, 28.9, 24.1],       # Right mouth corner (291)
    ],
    dtype=np.float64,
)
POSE_2D_INDICES = [1, 152, 33, 263, 61, 291]


def _dist(p1: np.ndarray, p2: np.ndarray) -> float:
    return float(np.linalg.norm(p1 - p2))


def compute_ear(pts_2d: np.ndarray, indices: List[int]) -> float:
    p1, p2, p3, p4, p5, p6 = [pts_2d[i] for i in indices]
    denom = 2.0 * _dist(p1, p4)
    if denom < 1e-6:
        return 0.0
    return (_dist(p2, p6) + _dist(p3, p5)) / denom


def compute_mar(pts_2d: np.ndarray) -> float:
    horiz = _dist(pts_2d[MOUTH_H[0]], pts_2d[MOUTH_H[1]])
    if horiz < 1e-6:
        return 0.0
    vert_sum = sum(_dist(pts_2d[a], pts_2d[b]) for a, b in MOUTH_V)
    return vert_sum / (len(MOUTH_V) * horiz)


def compute_head_pose_pnp(pts_2d: np.ndarray, width: int, height: int) -> Dict[str, float]:
    image_pts = np.array([pts_2d[idx] for idx in POSE_2D_INDICES], dtype=np.float64)
    focal_length = float(width)
    center = (width / 2.0, height / 2.0)
    cam_matrix = np.array(
        [[focal_length, 0, center[0]], [0, focal_length, center[1]], [0, 0, 1]],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)
    ok, rot_vec, _ = cv2.solvePnP(
        MODEL_3D_POINTS, image_pts, cam_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not ok:
        return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}

    rot_mat, _ = cv2.Rodrigues(rot_vec)
    sy = math.sqrt(rot_mat[0, 0] ** 2 + rot_mat[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        pitch = math.atan2(rot_mat[2, 1], rot_mat[2, 2])
        yaw = math.atan2(-rot_mat[2, 0], sy)
        roll = math.atan2(rot_mat[1, 0], rot_mat[0, 0])
    else:
        pitch = math.atan2(-rot_mat[1, 2], rot_mat[1, 1])
        yaw = math.atan2(-rot_mat[2, 0], sy)
        roll = 0.0

    return {
        "yaw": round(math.degrees(yaw), 2),
        "pitch": round(math.degrees(pitch), 2),
        "roll": round(math.degrees(roll), 2),
    }


class FaceLandmarkerService:
    def __init__(self) -> None:
        self._model_path = WEIGHTS_DIR / "face_landmarker.task"
        self._landmarker = None

    def is_ready(self) -> bool:
        return self._model_path.is_file() and self._model_path.stat().st_size > 1024

    def _get_landmarker(self):
        if self._landmarker is None:
            options = FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self._model_path)),
                num_faces=2,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
            )
            self._landmarker = FaceLandmarker.create_from_options(options)
        return self._landmarker

    def analyze_frame(self, bgr_image: np.ndarray) -> Dict[str, Any]:
        if not self.is_ready():
            raise RuntimeError("MediaPipe face_landmarker.task weight is missing.")

        h, w = bgr_image.shape[:2]
        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        result = self._get_landmarker().detect(mp_img)

        face_count = len(result.face_landmarks)
        if face_count == 0:
            return {"face_detected": False, "face_count": 0}
        if face_count > 1:
            return {"face_detected": True, "face_count": face_count, "multiple_faces": True}

        lms = result.face_landmarks[0]
        pts_2d = np.array([[lm.x * w, lm.y * h] for lm in lms], dtype=np.float32)

        left_ear = compute_ear(pts_2d, LEFT_EYE_IDX)
        right_ear = compute_ear(pts_2d, RIGHT_EYE_IDX)
        avg_ear = (left_ear + right_ear) / 2.0
        mar = compute_mar(pts_2d)
        pose = compute_head_pose_pnp(pts_2d, w, h)

        # Derive 5-point landmarks for ArcFace alignment (eye centers, nose, mouth corners)
        left_eye_center = np.mean(pts_2d[LEFT_EYE_IDX], axis=0)
        right_eye_center = np.mean(pts_2d[RIGHT_EYE_IDX], axis=0)
        nose_tip = pts_2d[1]
        left_mouth = pts_2d[61]
        right_mouth = pts_2d[291]
        five_pts = np.vstack([left_eye_center, right_eye_center, nose_tip, left_mouth, right_mouth])

        xs = pts_2d[:, 0]
        ys = pts_2d[:, 1]
        bbox = [int(max(0, xs.min())), int(max(0, ys.min())), int(min(w, xs.max())), int(min(h, ys.max()))]

        return {
            "face_detected": True,
            "face_count": 1,
            "multiple_faces": False,
            "ear_left": round(left_ear, 4),
            "ear_right": round(right_ear, 4),
            "ear_avg": round(avg_ear, 4),
            "mar": round(mar, 4),
            "pose": pose,
            "bbox": bbox,
            "five_points": five_pts.tolist(),
        }


def evaluate_temporal_challenges(
    frames_metrics: List[Dict[str, Any]],
    required_challenges: List[str],
    mar_threshold: float = 0.50,
) -> Dict[str, Any]:
    """
    Evaluates temporal multi-frame sequences for active liveness challenges.
    Uses relative EAR drop from the user's personal baseline (median/max EAR)
    rather than relying on one universal EAR threshold.
    """
    valid_frames = [m for m in frames_metrics if m.get("face_count") == 1]
    if len(valid_frames) < 2:
        return {"passed": False, "details": {}, "reason": "Insufficient single-face frames captured."}

    ears = [m["ear_avg"] for m in valid_frames]
    mars = [m["mar"] for m in valid_frames]
    yaws = [m["pose"]["yaw"] for m in valid_frames]

    ear_baseline = float(np.percentile(ears, 85))
    ear_min = float(min(ears))
    ear_drop_ratio = (ear_baseline - ear_min) / max(ear_baseline, 1e-5)

    # Count distinct blink dips (drop >= 14% below personal open-eye baseline)
    blink_thresh = ear_baseline * 0.86
    blink_count = 0
    in_blink = False
    for e in ears:
        if not in_blink and e < blink_thresh:
            in_blink = True
        elif in_blink and e >= blink_thresh * 1.03:
            blink_count += 1
            in_blink = False
    if in_blink:
        blink_count += 1

    results: Dict[str, bool] = {}
    for ch in required_challenges:
        if ch == "blink_twice":
            # Any natural eye blink (1 or more times) passes active liveness
            results[ch] = blink_count >= 1 and ear_drop_ratio >= 0.14
        elif ch == "open_mouth":
            results[ch] = max(mars) >= mar_threshold
        elif ch == "turn_head_left":
            results[ch] = min(yaws) <= -10.0 or max(yaws) - min(yaws) >= 12.0
        elif ch == "turn_head_right":
            results[ch] = max(yaws) >= 10.0 or max(yaws) - min(yaws) >= 12.0
        elif ch == "look_straight":
            results[ch] = any(abs(y) <= 20.0 for y in yaws)
        else:
            results[ch] = False

    passed = all(results.values())
    return {
        "passed": passed,
        "details": results,
        "telemetry": {
            "ear_baseline": round(ear_baseline, 4),
            "ear_min": round(ear_min, 4),
            "blink_count": blink_count,
            "mar_max": round(max(mars), 4),
            "yaw_range": [round(min(yaws), 2), round(max(yaws), 2)],
        },
    }
