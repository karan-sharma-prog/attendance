from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hmac
import hashlib
import secrets
from backend.app.core.config import settings

# Argon2id password hashing
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__type="ID",
    argon2__memory_cost=65536,
    argon2__time_cost=3,
    argon2__parallelism=4
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": now, "type": "access", "jti": secrets.token_hex(12)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": now, "type": "refresh", "jti": secrets.token_hex(16)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


# Biometric AES-256-GCM Encryption / Decryption
def encrypt_biometric_embedding(embedding_bytes: bytes) -> bytes:
    key = bytes.fromhex(settings.BIOMETRIC_ENCRYPTION_KEY_HEX[:64])
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, embedding_bytes, None)
    return nonce + ciphertext


def decrypt_biometric_embedding(encrypted_data: bytes) -> bytes:
    key = bytes.fromhex(settings.BIOMETRIC_ENCRYPTION_KEY_HEX[:64])
    aesgcm = AESGCM(key)
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)


# Dynamic QR HMAC-SHA256 Signature
def sign_qr_payload(session_id: str, nonce: str, issued_at: int, expires_at: int) -> str:
    payload = f"{session_id}:{nonce}:{issued_at}:{expires_at}".encode("utf-8")
    secret = settings.QR_HMAC_SECRET.encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify_qr_signature(session_id: str, nonce: str, issued_at: int, expires_at: int, signature: str) -> bool:
    expected_signature = sign_qr_payload(session_id, nonce, issued_at, expires_at)
    return hmac.compare_digest(expected_signature, signature)
