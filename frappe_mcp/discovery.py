from __future__ import annotations

import json

import frappe
from werkzeug.wrappers import Response

from frappe_mcp.config import (
    AUTHORIZATION_PATH,
    OAUTH_EXCHANGE_PATH,
    issuer,
    origin,
    resource,
    scopes_supported,
)
from frappe_mcp.protocol import JsonObject, JsonValue


@frappe.whitelist(allow_guest=True, methods=["GET"])
def protected_resource() -> Response:
    scopes: list[JsonValue] = []
    scopes.extend(scopes_supported())
    payload: JsonObject = {
        "resource": resource(),
        "authorization_servers": [issuer()],
        "scopes_supported": scopes,
        "bearer_methods_supported": ["header"],
    }
    return _json(payload)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def authorization_server() -> Response:
    scopes: list[JsonValue] = []
    scopes.extend(scopes_supported())
    payload: JsonObject = {
        "issuer": issuer(),
        "authorization_endpoint": f"{origin()}{AUTHORIZATION_PATH}",
        "token_endpoint": f"{origin()}{OAUTH_EXCHANGE_PATH}",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "scopes_supported": scopes,
        "authorization_response_iss_parameter_supported": True,
    }
    return _json(payload)


def _json(payload: JsonObject, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, separators=(",", ":")), status=status, content_type="application/json"
    )
