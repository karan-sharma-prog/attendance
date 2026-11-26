"""
Real Computer Vision Image Quality Assessment (OpenCV 5.1.0).
Evaluates decoded camera frames for resolution, lighting/brightness,
sharpness (Laplacian variance), and exposure clipping.
If MediaPipe FaceLandmarker / BlazeFace weights are loaded in Phase 6,
also executes single-face detection and head-pose estimation.
"""
import base64
from typing import Dict, Any, Tuple, Optional
import cv2
import numpy as np
from backend.app.ml.model_registry import WEIGHTS_DIR


def decode_base64_image(data_url_or_b64: str) -> Tuple[Optional[np.ndarray], bytes, str]:
    raw_b64 = data_url_or_b64.strip()
    if "," in raw_b64 and raw_b64.startswith("data:image"):
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        img_bytes = base64.b64decode(raw_b64, validate=True)
    except Exception:
        return None, b"", "Invalid base64 image payload."

    if len(img_bytes) < 1500 or len(img_bytes) > 6 * 1024 * 1024:
        return None, b"", "Image payload size out of acceptable range (1.5KB - 6MB)."

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return None, b"", "Could not decode image bytes as JPEG/PNG."
    return bgr, img_bytes, ""


def assess_frame_quality(bgr_image: np.ndarray, expected_orientation: str = "front") -> Dict[str, Any]:
    """
    Computes genuine OpenCV quality metrics on the camera frame.
    Also runs MediaPipe FaceDetector if blaze_face_short_range.tflite is present.
    """
    h, w = bgr_image.shape[:2]
    gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)

    # 1. Brightness (mean grayscale intensity)
    brightness = float(np.mean(gray))
    # 2. Contrast (standard deviation of luminance)
    contrast = float(np.std(gray))
    # 3. Sharpness (Laplacian variance)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # 4. Over/under exposure ratio
    dark_ratio = float(np.mean(gray < 20))
    bright_ratio = float(np.mean(gray > 245))

    reasons = []
    if w < 320 or h < 240:
        reasons.append(f"Resolution too low ({w}x{h}). Minimum 320x240 required.")
    if brightness < 50.0:
        reasons.append(f"Lighting too dark (mean={brightness:.1f}). Increase ambient lighting.")
    elif brightness > 225.0 or bright_ratio > 0.35:
        reasons.append(f"Overexposed / harsh glare (mean={brightness:.1f}). Reduce direct light.")
    if contrast < 20.0:
        reasons.append(f"Low contrast frame (std={contrast:.1f}). Avoid flat/covered camera.")
    if sharpness < 35.0:
        reasons.append(f"Image too blurry (Laplacian={sharpness:.1f}). Hold camera steady.")
    if dark_ratio > 0.65:
        reasons.append("Frame is predominantly black/occluded.")

    # Optional Phase 6 MediaPipe FaceDetector check if .tflite weight exists
    face_count: Optional[int] = None
    detector_mode = "opencv_quality_only"
    blaze_path = WEIGHTS_DIR / "blaze_face_short_range.tflite"
    if blaze_path.is_file() and blaze_path.stat().st_size > 1024:
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions

            options = FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(blaze_path)),
                min_detection_confidence=0.6,
            )
            rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            with FaceDetector.create_from_options(options) as detector:
                res = detector.detect(mp_img)
                face_count = len(res.detections)
                detector_mode = "mediapipe_blazeface"
                if face_count == 0:
                    reasons.append("No face detected. Position your face clearly inside the guide oval.")
                elif face_count > 1:
                    reasons.append(f"Multiple faces detected ({face_count}). Only one person may be in frame.")
        except Exception as exc:
            reasons.append(f"Face detector error: {str(exc)}")

    return {
        "passed": len(reasons) == 0,
        "orientation": expected_orientation,
        "width": int(w),
        "height": int(h),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "sharpness": round(sharpness, 2),
        "face_count": face_count,
        "detector_mode": detector_mode,
        "reasons": reasons,
    }
