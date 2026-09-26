"""Lightweight authenticated obfuscation for account passwords at rest.

Uses only stdlib (Python Workers friendly). ACCOUNT_SECRET must be a
Worker secret. This is not a substitute for a KMS — rotate the secret
and re-seal if compromised.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + iv + counter.to_bytes(4, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def seal(plaintext: str, secret: str) -> str:
    if not secret:
        raise ValueError("ACCOUNT_SECRET is required")
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    iv = os.urandom(16)
    data = plaintext.encode("utf-8")
    stream = _keystream(key, iv, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, iv + cipher, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(iv + tag + cipher).decode("ascii")


def open_sealed(token: str, secret: str) -> str:
    if not secret:
        raise ValueError("ACCOUNT_SECRET is required")
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    if len(raw) < 33:
        raise ValueError("ciphertext too short")
    iv, tag, cipher = raw[:16], raw[16:32], raw[32:]
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    expect = hmac.new(key, iv + cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expect):
        raise ValueError("invalid ciphertext")
    stream = _keystream(key, iv, len(cipher))
    plain = bytes(a ^ b for a, b in zip(cipher, stream))
    return plain.decode("utf-8")
