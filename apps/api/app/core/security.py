from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
ALGORITHM = "HS256"
_DUMMY_PASSWORD_HASH = pwd_context.hash("mingrun-security-dummy-password")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def verify_password_or_dummy(plain_password: str, hashed_password: str | None) -> bool:
    verified = pwd_context.verify(plain_password, hashed_password or _DUMMY_PASSWORD_HASH)
    return hashed_password is not None and verified


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + timedelta(minutes=settings.jwt_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "iat": issued_at, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("invalid_token") from exc
