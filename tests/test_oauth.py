from __future__ import annotations

import base64
import hashlib

import pytest

from frappe_mcp.oauth_core import (
    OAuthInputError,
    hash_password,
    hash_secret,
    issue_secret,
    normalize_scope,
    require_exact_redirect,
    require_resource,
    verify_password,
    verify_pkce_s256,
    verify_secret,
)


def test_issued_secret_is_stored_as_a_one_way_hash() -> None:
    secret, secret_hash = issue_secret()

    assert secret not in secret_hash
    assert verify_secret(secret, secret_hash)
    assert not verify_secret(f"{secret}x", secret_hash)


def test_pkce_s256_accepts_matching_verifier() -> None:
    verifier = "a" * 43
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    assert verify_pkce_s256(verifier, challenge)


def test_pkce_s256_rejects_plain_or_short_verifier() -> None:
    assert not verify_pkce_s256("short", "short")


def test_redirect_uri_must_match_registered_value_exactly() -> None:
    registered = ("https://client.example/callback",)

    assert require_exact_redirect("https://client.example/callback", registered) == registered[0]
    with pytest.raises(OAuthInputError):
        require_exact_redirect("https://client.example/callback/", registered)


def test_resource_must_be_canonical_mcp_url() -> None:
    canonical = "https://erp.truedevs.tech/mcp"

    assert require_resource(canonical, canonical) == canonical
    with pytest.raises(OAuthInputError):
        require_resource("https://erp.truedevs.tech", canonical)


def test_hash_secret_is_deterministic_for_database_lookup() -> None:
    assert hash_secret("token") == hash_secret("token")


def test_client_password_hash_is_salted() -> None:
    first = hash_password("client-secret")
    second = hash_password("client-secret")

    assert first != second
    assert verify_password("client-secret", first)
    assert not verify_password("wrong", first)


def test_scope_order_is_normalized() -> None:
    assert normalize_scope("offline_access mcp:write mcp:read") == (
        "mcp:read mcp:write offline_access"
    )


@pytest.mark.parametrize(
    "scope",
    ["", "mcp:write", "mcp:read unknown"],
)
def test_scope_requires_read_and_rejects_unknown_values(scope: str) -> None:
    with pytest.raises(OAuthInputError):
        normalize_scope(scope)
