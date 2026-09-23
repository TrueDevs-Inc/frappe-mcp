from __future__ import annotations

from typing import Final

import frappe

MCP_PATH: Final = "/api/method/frappe_mcp.api.handle"
AUTHORIZATION_PATH: Final = "/api/method/frappe_mcp.oauth.authorize"
OAUTH_EXCHANGE_PATH: Final = "/api/method/frappe_mcp.oauth.token"
PROTECTED_RESOURCE_PATH: Final = "/.well-known/oauth-protected-resource"
AUTHORIZATION_SERVER_PATH: Final = "/.well-known/oauth-authorization-server"


def origin() -> str:
    return frappe.utils.get_url().rstrip("/")


def resource() -> str:
    configured = frappe.conf.get("frappe_mcp_resource")
    return str(configured or f"{origin()}{MCP_PATH}")


def issuer() -> str:
    configured = frappe.conf.get("frappe_mcp_issuer")
    return str(configured or origin())


def enabled() -> bool:
    return bool(frappe.conf.get("frappe_mcp_enabled", False))


def write_enabled() -> bool:
    return bool(frappe.conf.get("frappe_mcp_write_enabled", False))


def scopes_supported() -> list[str]:
    scopes = ["mcp:read"]
    if write_enabled():
        scopes.append("mcp:write")
    scopes.append("offline_access")
    return scopes


def bearer_challenge() -> str:
    scope = " ".join(scopes_supported())
    return f'Bearer resource_metadata="{origin()}{PROTECTED_RESOURCE_PATH}", scope="{scope}"'
