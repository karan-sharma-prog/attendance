"""
Facial Alignment Utilities for ArcFace ResNet-100 (112x112 standard reference template).
Uses 5-point facial landmarks (left eye, right eye, nose tip, left mouth, right mouth)
with OpenCV similarity transform (estimateAffinePartial2D + warpAffine).
"""
import cv2
import numpy as np

# Standard InsightFace / ArcFace 112x112 destination reference points
ARCFACE_DST_112 = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def align_face_112(bgr_image: np.ndarray, five_points: np.ndarray) -> np.ndarray:
    """
    Aligns a BGR face image to 112x112 BGR using a 5x2 landmark array.
    """
    src = np.asarray(five_points, dtype=np.float32).reshape(5, 2)
    M, _ = cv2.estimateAffinePartial2D(src, ARCFACE_DST_112, method=cv2.LMEDS)
    if M is None:
        # Fallback affine from first 3 points (eyes + nose)
        M = cv2.getAffineTransform(src[:3], ARCFACE_DST_112[:3])
    aligned = cv2.warpAffine(bgr_image, M, (112, 112), flags=cv2.INTER_LINEAR, borderValue=0)
    return aligned
