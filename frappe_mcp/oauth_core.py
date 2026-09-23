from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Final

_PKCE_VERIFIER: Final = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_PASSWORD_ITERATIONS: Final = 600_000
_SCOPES: Final = ("mcp:read", "mcp:write", "offline_access")


@dataclass(frozen=True, slots=True)
class OAuthInputError(Exception):
    parameter: str
    reason: str

    def __str__(self) -> str:
        return f"{self.parameter}: {self.reason}"


def issue_secret() -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    return secret, hash_secret(secret)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_secret(secret: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), expected_hash)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


def verify_pkce_s256(verifier: str, expected_challenge: str) -> bool:
    if _PKCE_VERIFIER.fullmatch(verifier) is None:
        return False
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(challenge, expected_challenge)


def require_exact_redirect(requested: str, registered: tuple[str, ...]) -> str:
    if requested not in registered:
        raise OAuthInputError(parameter="redirect_uri", reason="not registered")
    return requested


def require_resource(requested: str, canonical: str) -> str:
    if requested != canonical:
        raise OAuthInputError(parameter="resource", reason="must identify the MCP endpoint")
    return requested


def normalize_scope(requested: str) -> str:
    scopes = set(requested.split())
    if "mcp:read" not in scopes:
        raise OAuthInputError(parameter="scope", reason="mcp:read is required")
    if unknown := scopes.difference(_SCOPES):
        raise OAuthInputError(parameter="scope", reason=f"unsupported scope: {sorted(unknown)[0]}")
    return " ".join(scope for scope in _SCOPES if scope in scopes)
