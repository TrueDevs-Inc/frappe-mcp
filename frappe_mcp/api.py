from __future__ import annotations

import json

import frappe
from werkzeug.exceptions import Unauthorized
from werkzeug.wrappers import Response

from frappe_mcp.auth import require_identity
from frappe_mcp.config import bearer_challenge, enabled, write_enabled
from frappe_mcp.protocol import JsonObject, JsonValue, dispatch
from frappe_mcp.tools import registered_tools


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle() -> Response:
    if not enabled():
        return _json({"error": "MCP service disabled"}, 503)

    try:
        identity = require_identity()
    except Unauthorized:
        return Response(
            json.dumps({"error": "unauthorized"}),
            status=401,
            content_type="application/json",
            headers={"WWW-Authenticate": bearer_challenge()},
        )

    origin = frappe.get_request_header("Origin")
    allowed_origins = frappe.db.get_value(
        "Frappe MCP OAuth Client", identity.client, "allowed_origins"
    )
    if origin and origin not in str(allowed_origins or "").splitlines():
        return _json({"error": "origin_not_allowed"}, 403)

    try:
        request = frappe.request.get_json(force=True)
        if not isinstance(request, dict):
            return _rpc_error(None, -32600, "Invalid Request")
        tools = registered_tools()
        if not write_enabled():
            tools = tuple(tool for tool in tools if tool.read_only)
        response = dispatch(request, tools)
    except frappe.PermissionError:
        return _rpc_error(_request_id(), -32003, "Forbidden", 403)
    except (TypeError, ValueError, KeyError):
        return _rpc_error(_request_id(), -32602, "Invalid params")

    if response is None:
        return Response(status=202)
    return _json(response)


def _request_id() -> JsonValue:
    request = frappe.request.get_json(silent=True)
    return request.get("id") if isinstance(request, dict) else None


def _rpc_error(request_id: JsonValue, code: int, message: str, status: int = 200) -> Response:
    return _json(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status
    )


def _json(payload: JsonObject | dict[str, str], status: int = 200) -> Response:
    return Response(
        json.dumps(payload, separators=(",", ":")), status=status, content_type="application/json"
    )
