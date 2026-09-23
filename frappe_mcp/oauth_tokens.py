from __future__ import annotations

import json
from collections.abc import Callable

import frappe
from werkzeug.wrappers import Response

from frappe_mcp.config import resource
from frappe_mcp.oauth_core import hash_secret, issue_secret, verify_password, verify_pkce_s256
from frappe_mcp.protocol import JsonObject


def handle_token() -> Response:
    form = frappe.form_dict
    client_id = str(form.get("client_id") or "")
    client_name = frappe.db.get_value("Frappe MCP OAuth Client", {"client_id": client_id}, "name")
    if not client_name:
        return _oauth_error("invalid_client", "client authentication failed", 401)
    client = frappe.get_doc("Frappe MCP OAuth Client", client_name)
    if not client.enabled or not verify_password(
        str(form.get("client_secret") or ""), client.client_secret_hash
    ):
        return _oauth_error("invalid_client", "client authentication failed", 401)

    grants: dict[str, Callable[[frappe.model.document.Document], Response]] = {
        "authorization_code": _authorization_code_grant,
        "refresh_token": _refresh_token_grant,
    }
    grant = grants.get(str(form.get("grant_type") or ""))
    if grant is None:
        return _oauth_error("unsupported_grant_type", "grant type is not supported", 400)
    return grant(client)


def _authorization_code_grant(client: frappe.model.document.Document) -> Response:
    form = frappe.form_dict
    code_name = frappe.db.get_value(
        "Frappe MCP Authorization Code",
        {"code_hash": hash_secret(str(form.get("code") or ""))},
        "name",
    )
    if not code_name:
        return _oauth_error("invalid_grant", "authorization code is invalid", 400)

    auth_code = frappe.get_doc("Frappe MCP Authorization Code", code_name, for_update=True)
    valid = (
        not auth_code.used
        and auth_code.client == client.name
        and auth_code.redirect_uri == form.get("redirect_uri")
        and auth_code.resource == form.get("resource")
        and auth_code.resource == resource()
        and frappe.utils.get_datetime(auth_code.expires_at) > frappe.utils.now_datetime()
        and bool(frappe.db.get_value("User", auth_code.user, "enabled"))
        and verify_pkce_s256(str(form.get("code_verifier") or ""), auth_code.code_challenge)
    )
    if not valid:
        return _oauth_error("invalid_grant", "authorization code is invalid", 400)

    auth_code.used = True
    auth_code.save(ignore_permissions=True)
    payload = _access_token_payload(
        client=client.name,
        user=auth_code.user,
        token_resource=auth_code.resource,
        scope=auth_code.scope,
    )
    if "offline_access" in auth_code.scope.split():
        refresh_token, refresh_hash = _refresh_secret()
        family_id = frappe.generate_hash(length=32)
        expires_at = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=30)
        _insert_refresh_token(
            token_hash=refresh_hash,
            family_id=family_id,
            client=client.name,
            user=auth_code.user,
            token_resource=auth_code.resource,
            scope=auth_code.scope,
            expires_at=expires_at,
        )
        payload["refresh_token"] = refresh_token
    return _json(payload)


def _refresh_token_grant(client: frappe.model.document.Document) -> Response:
    form = frappe.form_dict
    refresh_hash = hash_secret(str(form.get("refresh_token") or ""))
    token_name = frappe.db.get_value(
        "Frappe MCP Refresh Token", {"token_hash": refresh_hash}, "name"
    )
    if not token_name:
        return _oauth_error("invalid_grant", "refresh token is invalid", 400)

    token = frappe.get_doc("Frappe MCP Refresh Token", token_name, for_update=True)
    if token.consumed_at:
        for name in frappe.get_all(
            "Frappe MCP Refresh Token",
            filters={"family_id": token.family_id, "consumed_at": ["is", "not set"]},
            pluck="name",
        ):
            frappe.db.set_value(
                "Frappe MCP Refresh Token", name, "revoked", True, update_modified=False
            )
        return _oauth_error("invalid_grant", "refresh token was already used", 400)

    valid = (
        not token.revoked
        and token.client == client.name
        and token.resource == form.get("resource")
        and token.resource == resource()
        and frappe.utils.get_datetime(token.expires_at) > frappe.utils.now_datetime()
        and bool(frappe.db.get_value("User", token.user, "enabled"))
    )
    if not valid:
        return _oauth_error("invalid_grant", "refresh token is invalid", 400)

    token.consumed_at = frappe.utils.now_datetime()
    token.save(ignore_permissions=True)
    successor, successor_hash = _refresh_secret()
    _insert_refresh_token(
        token_hash=successor_hash,
        family_id=token.family_id,
        client=token.client,
        user=token.user,
        token_resource=token.resource,
        scope=token.scope,
        expires_at=token.expires_at,
    )
    payload = _access_token_payload(
        client=token.client,
        user=token.user,
        token_resource=token.resource,
        scope=token.scope,
    )
    payload["refresh_token"] = successor
    return _json(payload)


def _access_token_payload(*, client: str, user: str, token_resource: str, scope: str) -> JsonObject:
    token_value, _ = issue_secret()
    access_token = f"fmcp_{token_value}"
    frappe.get_doc(
        {
            "doctype": "Frappe MCP Access Token",
            "token_hash": hash_secret(access_token),
            "client": client,
            "user": user,
            "resource": token_resource,
            "scope": scope,
            "expires_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=1),
        }
    ).insert(ignore_permissions=True)
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": scope,
    }


def _refresh_secret() -> tuple[str, str]:
    value, _ = issue_secret()
    token = f"fmcp_refresh_{value}"
    return token, hash_secret(token)


def _insert_refresh_token(
    *,
    token_hash: str,
    family_id: str,
    client: str,
    user: str,
    token_resource: str,
    scope: str,
    expires_at: str,
) -> None:
    frappe.get_doc(
        {
            "doctype": "Frappe MCP Refresh Token",
            "token_hash": token_hash,
            "family_id": family_id,
            "client": client,
            "user": user,
            "resource": token_resource,
            "scope": scope,
            "expires_at": expires_at,
        }
    ).insert(ignore_permissions=True)


def _oauth_error(code: str, description: str, status: int) -> Response:
    return _json({"error": code, "error_description": description}, status)


def _json(payload: JsonObject, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, separators=(",", ":")),
        status=status,
        content_type="application/json",
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
