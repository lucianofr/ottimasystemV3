from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet
from pwdlib import PasswordHash

_pwd = PasswordHash.recommended()  # Argon2id (spec F1 §5.1)


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_access_token(
    *, user_id: int, username: str, role: str, secret: str, ttl_hours: int
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])


def encrypt_secret(plain: str, *, key: str) -> str:
    return Fernet(key.encode()).encrypt(plain.encode()).decode()


def decrypt_secret(token: str, *, key: str) -> str:
    return Fernet(key.encode()).decrypt(token.encode()).decode()
