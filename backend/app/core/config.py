from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List, Optional, Union
import json

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    APP_NAME: str = "SmartPresence"
    API_V1_STR: str = "/api/v1"
    
    SECRET_KEY: str = "smartpresence-insecure-secret-key-change-in-env"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Server Binding & Public/LAN Base URL for QR Verification Links
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    FRONTEND_URL: str = "https://localhost:5173"
    APP_BASE_URL: str = "https://localhost:5173"
    DEFAULT_GEOFENCE_RADIUS_METERS: float = 150.0
    CORS_ORIGINS: Union[List[str], str] = [
        "https://localhost:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    
    # Neon PostgreSQL Database Connection Strings
    DATABASE_URL: Optional[str] = None
    DATABASE_URL_SYNC: Optional[str] = None
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Biometric Cryptography & Dynamic QR Secrets
    BIOMETRIC_ENCRYPTION_KEY_HEX: str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    QR_HMAC_SECRET: str = "smartpresence-qr-hmac-secret-change-in-env"
    
    # AI Thresholds
    ARCFACE_SIMILARITY_THRESHOLD: float = 0.68
    MINIFASNET_LIVENESS_THRESHOLD: float = 0.85
    BLINK_EAR_THRESHOLD: float = 0.22
    MOUTH_MAR_THRESHOLD: float = 0.55
    
    # SMTP Alerting (Low-Attendance Warning System)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "smartpresence-alerts@institution.edu"
    SMTP_TLS: bool = True
    ATTENDANCE_WARNING_THRESHOLD_PERCENT: float = 75.0
    
    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
