"""Simple encryption helpers for storing sensitive credentials."""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from hashlib import sha256

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from .config import Config

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


@lru_cache(maxsize=1)
def _resolve_secret_key() -> str:
    """Return the secret key from configuration or the environment."""

    secret = os.getenv("SECRET_KEY")
    if secret:
        return secret

    config = Config()
    secret_from_config = config.secret_key
    if secret_from_config:
        return secret_from_config

    raise RuntimeError(
        "SECRET_KEY is not configured. Set the SECRET_KEY environment variable or "
        "define security.secret_key in config.yml."
    )


def get_secret_key() -> str:
    """Return the secret key used for encrypting stored credentials."""

    return _resolve_secret_key()


__all__ = ["encrypt", "decrypt", "get_secret_key"]
