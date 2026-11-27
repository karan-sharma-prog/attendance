"""
Dynamic QR Generation & Cryptographic Verification Service.
Encodes a complete HTTPS attendance verification URL containing a compact,
URL-safe HMAC-SHA256 signed token (v1.<b64url>.<hmac>) so Android/iOS default
cameras open the verification route cleanly rather than detecting raw numbers
as phone numbers.
"""
import base64
import io
import json
import secrets
import time
from typing import Tuple, Dict, Any
from urllib.parse import urlparse, parse_qs, quote
import qrcode
from backend.app.core.config import settings
from backend.app.core.security import sign_qr_payload, verify_qr_signature
from backend.app.services.redis_service import ttl_store


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _get_qr_base_url() -> str:
    base = (settings.APP_BASE_URL or settings.FRONTEND_URL or "https://localhost:5173").strip().rstrip("/")
    return base


async def generate_dynamic_qr_for_session(session_id: str, refresh_interval: int) -> Dict[str, Any]:
    """
    Generates a URL-safe HMAC-SHA256 signed attendance token embedded inside
    a complete HTTPS attendance verification URL:
        <APP_BASE_URL>/attend/verify?token=v1.<b64url_payload>.<hmac_hex>
    """
    now = int(time.time())
    # Fast 20-second validity window (student session is already saved for instant scan-to-face)
    ttl_seconds = 20
    expires_at = now + ttl_seconds
    nonce = secrets.token_urlsafe(16)
    signature = sign_qr_payload(session_id, nonce, now, expires_at)

    payload_dict = {
        "sid": session_id,
        "iat": now,
        "exp": expires_at,
        "n": nonce,
    }
    encoded_payload = _b64url_encode(json.dumps(payload_dict, separators=(",", ":")).encode("utf-8"))
    compact_token = f"v1.{encoded_payload}.{signature}"

    base_url = _get_qr_base_url()
    verification_url = f"{base_url}/attend/verify?token={quote(compact_token, safe='._-')}"

    # Store active nonce in Redis/TTL store; shared across enrolled students during this window
    await ttl_store.set_ex(f"qr_nonce:{session_id}:{nonce}", ttl_seconds, "active")

    # Encode the full HTTPS verification URL directly into the QR code
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(verification_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#080F1F", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "session_id": session_id,
        "qr_url": verification_url,
        "qr_token": compact_token,
        "qr_image_data_url": f"data:image/png;base64,{qr_b64}",
        "issued_at": now,
        "expires_at": expires_at,
        "refresh_interval": refresh_interval,
        "nonce": nonce,
    }


def extract_token_from_qr_input(raw_input: str) -> str:
    """Extracts the token from a full verification URL or returns the raw token string."""
    text = raw_input.strip()
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        qs = parse_qs(parsed.query)
        if "token" in qs and qs["token"]:
            return qs["token"][0].strip()
    return text


async def validate_qr_token_payload(qr_input: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates a scanned verification URL, compact v1 token, or legacy JSON token.
    Verifies format, HMAC-SHA256 signature, server-side expiration, and active TTL state.
    """
    token_str = extract_token_from_qr_input(qr_input)

    session_id = ""
    nonce = ""
    signature = ""
    issued_at = 0
    expires_at = 0

    if token_str.startswith("v1."):
        parts = token_str.split(".")
        if len(parts) != 3:
            return False, "Malformed SmartPresence verification token format.", {}
        try:
            payload_bytes = _b64url_decode(parts[1])
            data = json.loads(payload_bytes.decode("utf-8"))
            signature = parts[2]
            session_id = str(data["sid"])
            nonce = str(data["n"])
            issued_at = int(data["iat"])
            expires_at = int(data["exp"])
        except Exception:
            return False, "Invalid or corrupted attendance verification token.", {}
    else:
        # Legacy JSON fallback
        try:
            data = json.loads(token_str)
            required = ("sid", "iat", "exp", "n", "sig")
            if not all(k in data for k in required):
                return False, "Incomplete QR token fields.", {}
            session_id = str(data["sid"])
            nonce = str(data["n"])
            signature = str(data["sig"])
            issued_at = int(data["iat"])
            expires_at = int(data["exp"])
        except Exception:
            return False, "Invalid QR code. Expected a SmartPresence verification URL or signed token.", {}

    if not verify_qr_signature(session_id, nonce, issued_at, expires_at, signature):
        return False, "Cryptographic QR signature verification failed. Possible tampered QR.", {}

    now = int(time.time())
    if now > expires_at:
        return False, "QR token has expired. Please scan the refreshed QR code on the classroom screen.", {}

    active = await ttl_store.get(f"qr_nonce:{session_id}:{nonce}")
    if not active:
        return False, "QR token is no longer active or has expired.", {}

    return True, "OK", {
        "session_id": session_id,
        "nonce": nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
