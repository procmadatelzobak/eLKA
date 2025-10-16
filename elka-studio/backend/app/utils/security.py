"""Simple encryption helpers for storing sensitive credentials."""

from __future__ import annotations

import base64
import os
from hashlib import sha256

from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()


def _derive_key(secret_key: str) -> bytes:
    """Derive a Fernet-compatible key from the provided secret string."""
    if not secret_key:
        raise ValueError("A non-empty secret key is required for encryption")
    digest = sha256(secret_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(data: str, key: str) -> str:
    """Encrypt the given string using Fernet symmetric encryption."""
    fernet = Fernet(_derive_key(key))
    token = fernet.encrypt(data.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(token: str, key: str) -> str:
    """Decrypt the provided token using Fernet symmetric encryption."""
    fernet = Fernet(_derive_key(key))
    data = fernet.decrypt(token.encode("utf-8"))
    return data.decode("utf-8")


def get_secret_key() -> str:
    """Return the SECRET_KEY from the environment, raising if it is missing."""
    secret = os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY environment variable is not set")
    return secret


__all__ = ["encrypt", "decrypt", "get_secret_key"]
