"""
SmartPresence Phase 6 Weight Downloader & Verifier.
Downloads verified pretrained models into backend/app/ml/weights/ and inspects
exact ONNX input/output tensor signatures with onnxruntime.
"""
import io
import os
import sys
import zipfile
from pathlib import Path
import httpx

WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)


def download_file(url: str, dest: Path) -> bool:
    if dest.is_file() and dest.stat().st_size > 10_000:
        print(f"[SKIP] {dest.name} already exists ({dest.stat().st_size:,} bytes)")
        return True
    print(f"[GET] Downloading {dest.name} from {url} ...")
    try:
        with httpx.Client(follow_redirects=True, timeout=180.0) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    print(f"[WARN] HTTP {resp.status_code} for {url}")
                    return False
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                tmp.replace(dest)
        print(f"[OK] Saved {dest.name} ({dest.stat().st_size:,} bytes)")
        return True
    except Exception as exc:
        print(f"[ERR] Failed downloading {url}: {exc}")
        return False


def download_and_extract_antelopev2() -> None:
    det_dest = WEIGHTS_DIR / "det_10g.onnx"
    arc_dest = WEIGHTS_DIR / "glintr100.onnx"
    if det_dest.is_file() and arc_dest.is_file():
        print("[SKIP] InsightFace det_10g.onnx & glintr100.onnx already exist.")
        return

    zip_path = WEIGHTS_DIR / "antelopev2.zip"
    url = "https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip"
    if not download_file(url, zip_path):
        return

    print("[*] Extracting scrfd_10g_bnkps.onnx (-> det_10g.onnx) and glintr100.onnx from antelopev2.zip ...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            fname = os.path.basename(member)
            if fname == "scrfd_10g_bnkps.onnx":
                det_dest.write_bytes(zf.read(member))
                print(f"[OK] Extracted {det_dest.name} ({det_dest.stat().st_size:,} bytes)")
            elif fname == "glintr100.onnx":
                arc_dest.write_bytes(zf.read(member))
                print(f"[OK] Extracted {arc_dest.name} ({arc_dest.stat().st_size:,} bytes)")
    zip_path.unlink(missing_ok=True)


def download_minifasnet() -> None:
    dest = WEIGHTS_DIR / "minifasnet_v2.onnx"
    if dest.is_file() and dest.stat().st_size > 10_000:
        print(f"[SKIP] {dest.name} already exists ({dest.stat().st_size:,} bytes)")
        return

    candidates = [
        "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx",
        "https://huggingface.co/garciafido/minifasnet-v2-anti-spoofing-onnx/resolve/main/MiniFASNetV2.onnx",
        "https://github.com/facenox/face-antispoof-onnx/raw/main/models/best_model.onnx",
    ]
    for url in candidates:
        if download_file(url, dest):
            return
    print("[WARN] Could not auto-download MiniFASNetV2 ONNX from candidate URLs.")


def inspect_models() -> None:
    import onnxruntime as ort
    print("\n=== ONNX Runtime Model Input/Output Inspection ===")
    for onnx_file in sorted(WEIGHTS_DIR.glob("*.onnx")):
        try:
            sess = ort.InferenceSession(str(onnx_file), providers=["CPUExecutionProvider"])
            ins = [(i.name, i.shape, i.type) for i in sess.get_inputs()]
            outs = [(o.name, o.shape, o.type) for o in sess.get_outputs()]
            print(f" - {onnx_file.name}: inputs={ins} -> outputs={outs}")
        except Exception as exc:
            print(f" - {onnx_file.name}: FAILED TO LOAD ({exc})")


def main():
    download_file(
        "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
        WEIGHTS_DIR / "blaze_face_short_range.tflite",
    )
    download_file(
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
        WEIGHTS_DIR / "face_landmarker.task",
    )
    download_and_extract_antelopev2()
    download_minifasnet()
    inspect_models()


if __name__ == "__main__":
    main()
