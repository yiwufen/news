from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Literal

import jwt

Role = Literal["admin", "viewer"]

ACCESS_TOKEN_TTL = 3600       # 1 hour
REFRESH_TOKEN_TTL = 604800    # 7 days
JWT_ALGORITHM = "HS256"

_JWT_SECRET: str | None = None


def _get_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.environ.get("JWT_SECRET") or hashlib.sha256(
            os.urandom(64)
        ).hexdigest()
    return _JWT_SECRET


def hash_password(password: str) -> str:
    salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2:sha256:600000:{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, iterations, salt_hex, dk_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        dk = bytes.fromhex(dk_hex)
        new_dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt, int(iterations))
        return new_dk == dk
    except (ValueError, TypeError):
        return False


@dataclass
class TokenPayload:
    user_id: int
    username: str
    role: Role


def create_access_token(payload: TokenPayload) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(payload.user_id),
            "username": payload.username,
            "role": payload.role,
            "type": "access",
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL,
        },
        _get_secret(),
        algorithm=JWT_ALGORITHM,
    )


def create_refresh_token(user_id: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": "refresh",
            "iat": now,
            "exp": now + REFRESH_TOKEN_TTL,
        },
        _get_secret(),
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> TokenPayload:
    claims = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    if claims.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return TokenPayload(
        user_id=int(claims["sub"]),
        username=claims["username"],
        role=claims["role"],
    )


def decode_refresh_token(token: str) -> int:
    claims = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    if claims.get("type") != "refresh":
        raise jwt.InvalidTokenError("not a refresh token")
    return int(claims["sub"])
