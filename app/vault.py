"""Encrypts the secrets kept in the database (Meta keys, TOTP secrets) with SECRET_KEY."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    """A sealed value can't be opened, usually because SECRET_KEY changed."""


class Vault:
    def __init__(self, secret_key: str) -> None:
        if not secret_key:
            raise ValueError("SECRET_KEY is empty")
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))

    def seal(self, text: str) -> str:
        return self._fernet.encrypt(text.encode()).decode()

    def open(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            raise VaultError("A saved secret can't be read; was SECRET_KEY changed?") from None
