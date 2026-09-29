"""Dashboard logins: users, invite links, passwords, sessions, two-step codes (TOTP) and a login rate limit."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import struct
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from urllib.parse import quote

from app.db import Db
from app.vault import Vault

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL CHECK (role IN ('admin', 'business')),
  business_id TEXT REFERENCES businesses(id),
  password_hash TEXT,
  totp_secret TEXT,
  invite_hash TEXT,
  invite_expires REAL,
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  CHECK ((role = 'admin') = (business_id IS NULL))
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  csrf TEXT NOT NULL,
  mfa_ok INTEGER NOT NULL DEFAULT 0,
  totp_pending TEXT,
  expires_at REAL NOT NULL
);
"""
INVITE_TTL = 7 * 86_400
ADMIN_SESSION_TTL = 12 * 3600
BUSINESS_SESSION_TTL = 7 * 86_400
MIN_PASSWORD = 10
MAX_FAILURES, PAUSE = 5, 15 * 60
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


class AuthError(Exception):
    """Shown to the person: wrong password, expired link, too many tries, ..."""


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    role: str  # "admin" or "business"
    business_id: str | None
    has_password: bool
    has_totp: bool
    disabled: bool


@dataclass(frozen=True)
class Session:
    user: User
    csrf: str
    mfa_ok: bool


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, n, r, p, salt, digest = (stored or "").split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), digest)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, at: float) -> str:
    """RFC 6238 with SHA-1, 30-second steps and 6 digits, as authenticator apps expect."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", int(at // 30)), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_ok(secret: str, code: str, at: float) -> bool:
    code = code.replace(" ", "").strip()
    return any(hmac.compare_digest(totp(secret, at + drift * 30), code) for drift in (-1, 0, 1))


def totp_uri(secret: str, email: str) -> str:
    return f"otpauth://totp/{quote('WhatsApp Assistant:' + email)}?secret={secret}&issuer=WhatsApp%20Assistant"


class RateLimit:
    """MAX_FAILURES failures within PAUSE seconds pause a key for PAUSE seconds (in memory)."""

    def __init__(self) -> None:
        self._failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self._until: dict[str, float] = {}

    def blocked(self, key: str, now: float) -> bool:
        return self._until.get(key, 0.0) > now

    def fail(self, key: str, now: float) -> None:
        failures = self._failures[key]
        failures.append(now)
        while failures and failures[0] <= now - PAUSE:
            failures.popleft()
        if len(failures) >= MAX_FAILURES:
            self._until[key] = now + PAUSE
            failures.clear()

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)
        self._until.pop(key, None)


class Auth:
    def __init__(self, db: Db, vault: Vault, clock=time.time) -> None:
        self.db, self.vault, self.clock = db, vault, clock
        self.limits = RateLimit()
        db.script(SCHEMA)

    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(id=row["id"], email=row["email"], name=row["name"], role=row["role"],
                    business_id=row["business_id"], has_password=bool(row["password_hash"]),
                    has_totp=bool(row["totp_secret"]), disabled=bool(row["disabled"]))

    def users(self, business_id: str | None = None, role: str | None = None) -> list[User]:
        sql, args = "SELECT * FROM users WHERE 1 = 1", []
        if business_id is not None:
            sql += " AND business_id = ?"
            args.append(business_id)
        if role is not None:
            sql += " AND role = ?"
            args.append(role)
        return [self._user(r) for r in self.db.all(sql + " ORDER BY email", tuple(args))]

    def user(self, user_id: int) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._user(row) if row else None

    def by_email(self, email: str) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE email = ?", (email.strip(),))
        return self._user(row) if row else None

    def invite(self, email: str, name: str, role: str, business_id: str | None) -> str:
        """Create a login and return its one-time invite token, for {public_url}/invite/{token}."""
        email = email.strip()
        if "@" not in email or len(email) > 254:
            raise AuthError("Enter a valid email address.")
        if role not in ("admin", "business") or (role == "business") != bool(business_id):
            raise AuthError("A business login needs a business; an admin login must not have one.")
        token, now = secrets.token_urlsafe(32), self.clock()
        try:
            self.db.write("INSERT INTO users (email, name, role, business_id, invite_hash, invite_expires,"
                          " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (email, name.strip(), role, business_id or None, _sha(token), now + INVITE_TTL, now))
        except sqlite3.IntegrityError as e:
            if "FOREIGN KEY" in str(e):
                raise AuthError("No such business.") from None
            raise AuthError("That email already has a login.") from None
        return token

    def new_link(self, user_id: int, reset_totp: bool = False) -> str:
        """A fresh invite link: the old password stops working and every session ends."""
        token = secrets.token_urlsafe(32)
        with self.db.transaction():
            sql = "UPDATE users SET password_hash = NULL, invite_hash = ?, invite_expires = ?"
            if reset_totp:
                sql += ", totp_secret = NULL"
            if not self.db.write(sql + " WHERE id = ?", (_sha(token), self.clock() + INVITE_TTL, user_id)):
                raise AuthError("No such login.")
            self.db.write("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return token

    def invited_user(self, token: str) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE invite_hash = ? AND invite_expires > ? AND disabled = 0",
                          (_sha(token), self.clock()))
        return self._user(row) if row else None

    def accept_invite(self, token: str, password: str) -> User:
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"Use at least {MIN_PASSWORD} characters.")
        user = self.invited_user(token)
        if user is None:
            raise AuthError("This link has expired or was already used. Ask for a new one.")
        self.db.write("UPDATE users SET password_hash = ?, invite_hash = NULL, invite_expires = NULL WHERE id = ?",
                      (hash_password(password), user.id))
        return user

    def login(self, email: str, password: str) -> tuple[str, User]:
        key, now = f"login:{email.strip().lower()}", self.clock()
        if self.limits.blocked(key, now):
            raise AuthError("Too many tries. Wait 15 minutes and try again.")
        row = self.db.one("SELECT * FROM users WHERE email = ? AND disabled = 0", (email.strip(),))
        if row is None or not verify_password(password, row["password_hash"]):
            self.limits.fail(key, now)
            raise AuthError("Wrong email or password.")
        self.limits.clear(key)
        user = self._user(row)
        token = secrets.token_urlsafe(32)
        ttl = ADMIN_SESSION_TTL if user.role == "admin" else BUSINESS_SESSION_TTL
        self.db.write("INSERT INTO sessions (token_hash, user_id, csrf, mfa_ok, expires_at) VALUES (?, ?, ?, ?, ?)",
                      (_sha(token), user.id, secrets.token_urlsafe(24), int(user.role != "admin"), now + ttl))
        return token, user

    def session(self, token: str) -> Session | None:
        row = self.db.one("SELECT s.csrf, s.mfa_ok, s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id"
                          " WHERE s.token_hash = ?", (_sha(token),))
        if row is None:
            return None
        if row["expires_at"] <= self.clock() or row["disabled"]:
            self.db.write("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))
            return None
        return Session(user=self._user(row), csrf=row["csrf"], mfa_ok=bool(row["mfa_ok"]))

    def totp_setup_secret(self, token: str) -> str:
        """The secret to show during an admin's first two-step setup; kept with the session until confirmed."""
        row = self.db.one("SELECT totp_pending FROM sessions WHERE token_hash = ?", (_sha(token),))
        if row is None:
            raise AuthError("Your session ended. Log in again.")
        if row["totp_pending"]:
            return self.vault.open(row["totp_pending"])
        secret = new_totp_secret()
        self.db.write("UPDATE sessions SET totp_pending = ? WHERE token_hash = ?",
                      (self.vault.seal(secret), _sha(token)))
        return secret

    def pass_totp(self, token: str, code: str) -> bool:
        row = self.db.one("SELECT s.user_id, s.totp_pending, u.totp_secret FROM sessions s"
                          " JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (_sha(token),))
        if row is None:
            return False
        key, now = f"totp:{row['user_id']}", self.clock()
        if self.limits.blocked(key, now):
            raise AuthError("Too many wrong codes. Wait 15 minutes and try again.")
        sealed = row["totp_secret"] or row["totp_pending"]
        if not sealed or not totp_ok(self.vault.open(sealed), code, now):
            self.limits.fail(key, now)
            return False
        self.limits.clear(key)
        with self.db.transaction():
            if not row["totp_secret"]:
                self.db.write("UPDATE users SET totp_secret = ? WHERE id = ?", (row["totp_pending"], row["user_id"]))
            self.db.write("UPDATE sessions SET mfa_ok = 1, totp_pending = NULL WHERE token_hash = ?", (_sha(token),))
        return True

    def logout(self, token: str) -> None:
        self.db.write("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))

    def set_disabled(self, user_id: int, disabled: bool) -> None:
        with self.db.transaction():
            self.db.write("UPDATE users SET disabled = ? WHERE id = ?", (int(disabled), user_id))
            if disabled:
                self.db.write("DELETE FROM sessions WHERE user_id = ?", (user_id,))
