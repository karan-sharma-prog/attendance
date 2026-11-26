"""
ML Model Registry & Weight Readiness Inspector.
Strictly verifies whether real pretrained weights exist on disk before permitting biometric inference.
Never fabricates embeddings or liveness predictions.
"""
import os
from pathlib import Path
from typing import Dict, Any

WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"

REQUIRED_MODELS: Dict[str, Dict[str, Any]] = {
    "blazeface": {
        "filename": "blaze_face_short_range.tflite",
        "runtime": "mediapipe.tasks.vision.FaceDetector",
        "source": "Google MediaPipe Solutions (Apache-2.0)",
        "url": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
        "input_spec": "128x128 RGB [0, 255] via mp.Image",
    },
    "face_landmarker": {
        "filename": "face_landmarker.task",
        "runtime": "mediapipe.tasks.vision.FaceLandmarker",
        "source": "Google MediaPipe Solutions (Apache-2.0)",
        "url": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
        "input_spec": "RGB frame via mp.Image -> 478 3D landmarks + 52 blendshapes",
    },
    "retinaface": {
        "filename": "det_10g.onnx",
        "runtime": "onnxruntime (CPUExecutionProvider)",
        "source": "InsightFace buffalo_l (MIT code / non-commercial model weights)",
        "input_spec": "640x640 RGB normalized (img - 127.5) / 128.0",
    },
    "arcface_r100": {
        "filename": "glintr100.onnx",
        "runtime": "onnxruntime (CPUExecutionProvider)",
        "source": "InsightFace antelopev2 / Glint360K ResNet-100 (research/non-commercial license; verify deployment terms)",
        "input_spec": "112x112 aligned RGB normalized (img - 127.5) / 127.5 -> 512-D L2 embedding",
    },
    "minifasnet": {
        "filename": "minifasnet_v2.onnx",
        "runtime": "onnxruntime (CPUExecutionProvider)",
        "source": "Silent-Face-Anti-Spoofing MiniFASNetV2 / V1SE (Apache-2.0)",
        "input_spec": "80x80 BGR crop scale 2.7x -> 3-class spoof/live softmax",
    },
    "faceqnet": {
        "filename": "faceqnet_v1.onnx",
        "runtime": "onnxruntime (CPUExecutionProvider)",
        "source": "Biometrics & Pattern Recognition Lab FaceQnet v1 (MIT/Academic)",
        "input_spec": "224x224 RGB normalized -> scalar quality score [0, 1]",
    },
}


def get_ml_readiness() -> Dict[str, Any]:
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    statuses = {}
    core_ready = True
    for key, spec in REQUIRED_MODELS.items():
        path = WEIGHTS_DIR / spec["filename"]
        exists = path.is_file() and path.stat().st_size > 1024
        optional = key == "faceqnet"
        if not exists and not optional:
            core_ready = False
        statuses[key] = {
            "filename": spec["filename"],
            "loaded": exists,
            "optional": optional,
            "size_bytes": path.stat().st_size if path.is_file() else 0,
            "runtime": spec["runtime"],
            "source": spec["source"],
            "input_spec": spec["input_spec"],
        }
    return {
        "weights_directory": str(WEIGHTS_DIR),
        "all_models_ready": core_ready,
        "models": statuses,
    }
