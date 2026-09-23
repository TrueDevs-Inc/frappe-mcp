from __future__ import annotations

from dataclasses import dataclass

import frappe
from werkzeug.exceptions import Unauthorized

from frappe_mcp.config import MCP_PATH, bearer_challenge, resource
from frappe_mcp.oauth_core import hash_secret


@dataclass(frozen=True, slots=True)
class McpIdentity:
    user: str
    client: str
    scope: str


def validate_mcp_bearer() -> None:
    if frappe.request.path != MCP_PATH:
        return

    header = frappe.get_request_header("Authorization", "")
    if not header.startswith("Bearer fmcp_"):
        return

    token = header.removeprefix("Bearer ")
    row = frappe.db.get_value(
        "Frappe MCP Access Token",
        {"token_hash": hash_secret(token)},
        ["user", "client", "scope", "resource", "expires_at", "revoked"],
        as_dict=True,
    )
    if not row or row.revoked or row.resource != resource():
        raise _unauthorized()
    if frappe.utils.get_datetime(row.expires_at) <= frappe.utils.now_datetime():
        raise _unauthorized()
    if not frappe.db.get_value("User", row.user, "enabled"):
        raise _unauthorized()
    if not frappe.db.get_value("Frappe MCP OAuth Client", row.client, "enabled"):
        raise _unauthorized()

    frappe.set_user(row.user)
    frappe.local.mcp_identity = McpIdentity(user=row.user, client=row.client, scope=row.scope)


def require_identity() -> McpIdentity:
    identity = getattr(frappe.local, "mcp_identity", None)
    if not isinstance(identity, McpIdentity):
        raise _unauthorized()
    return identity


def _unauthorized() -> Unauthorized:
    return Unauthorized(www_authenticate=bearer_challenge())
