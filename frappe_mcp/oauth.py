from __future__ import annotations

import html
import json
from urllib.parse import quote, urlencode

import frappe
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

from frappe_mcp.config import issuer, resource, write_enabled
from frappe_mcp.oauth_core import (
    OAuthInputError,
    hash_password,
    issue_secret,
    normalize_scope,
    require_exact_redirect,
    require_resource,
)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def authorize() -> Response:
    if frappe.session.user == "Guest":
        target = frappe.request.full_path.rstrip("?")
        return redirect(f"/login?redirect-to={quote(target)}")

    try:
        request = _authorization_request()
    except OAuthInputError as error:
        return _authorization_error(error)

    if frappe.request.method == "GET":
        return _consent_page(request)

    code, code_hash = issue_secret()
    frappe.get_doc(
        {
            "doctype": "Frappe MCP Authorization Code",
            "code_hash": code_hash,
            "client": request["client_id"],
            "user": frappe.session.user,
            "redirect_uri": request["redirect_uri"],
            "code_challenge": request["code_challenge"],
            "resource": request["resource"],
            "scope": request["scope"],
            "expires_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=5),
        }
    ).insert(ignore_permissions=True)
    return _redirect_with_query(
        request["redirect_uri"], {"code": code, "state": request["state"], "iss": issuer()}
    )


@frappe.whitelist(allow_guest=True, methods=["POST"])
def token() -> Response:
    from frappe_mcp.oauth_tokens import handle_token

    return handle_token()


def create_client(label: str, redirect_uris: str, allowed_origins: str = "") -> dict[str, str]:
    client_id = f"fmcp_client_{frappe.generate_hash(length=24)}"
    client_secret, _ = issue_secret()
    frappe.get_doc(
        {
            "doctype": "Frappe MCP OAuth Client",
            "client_id": client_id,
            "label": label,
            "client_secret_hash": hash_password(client_secret),
            "redirect_uris": redirect_uris,
            "allowed_origins": allowed_origins,
            "enabled": True,
        }
    ).insert(ignore_permissions=True)
    return {"client_id": client_id, "client_secret": client_secret}


def _authorization_request() -> dict[str, str]:
    form = frappe.form_dict
    client_id = str(form.get("client_id") or "")
    client_name = frappe.db.get_value("Frappe MCP OAuth Client", {"client_id": client_id}, "name")
    if not client_name:
        raise OAuthInputError(parameter="client_id", reason="client is unknown")
    client = frappe.get_doc("Frappe MCP OAuth Client", client_name)
    if not client.enabled:
        raise OAuthInputError(parameter="client_id", reason="client is disabled")
    if form.get("response_type") != "code":
        raise OAuthInputError(parameter="response_type", reason="code is required")
    if form.get("code_challenge_method") != "S256":
        raise OAuthInputError(parameter="code_challenge_method", reason="S256 is required")
    state = str(form.get("state") or "")
    challenge = str(form.get("code_challenge") or "")
    if not state or not challenge:
        raise OAuthInputError(parameter="state", reason="state and code_challenge are required")
    requested_scope = normalize_scope(str(form.get("scope") or "mcp:read"))
    if "mcp:write" in requested_scope.split() and not write_enabled():
        raise OAuthInputError(parameter="scope", reason="mcp:write is disabled")
    return {
        "client_id": client_id,
        "redirect_uri": require_exact_redirect(
            str(form.get("redirect_uri") or ""), tuple(client.redirect_uris.splitlines())
        ),
        "resource": require_resource(str(form.get("resource") or ""), resource()),
        "scope": requested_scope,
        "state": state,
        "code_challenge": challenge,
    }


def _consent_page(request: dict[str, str]) -> Response:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
        for key, value in request.items()
    )
    hidden += '<input type="hidden" name="response_type" value="code">'
    hidden += '<input type="hidden" name="code_challenge_method" value="S256">'
    csrf_token = html.escape(frappe.sessions.get_csrf_token())
    hidden += f'<input type="hidden" name="csrf_token" value="{csrf_token}">'
    body = (
        "<!doctype html><title>Authorize Frappe MCP</title>"
        "<main><h1>Authorize Frappe MCP</h1>"
        f"<p>Allow {html.escape(request['client_id'])} to use {html.escape(request['scope'])} "
        "with your ERP permissions?</p>"
        f'<form method="post">{hidden}<button type="submit">Allow</button></form></main>'
    )
    return Response(body, content_type="text/html; charset=utf-8")


def _oauth_error(code: str, description: str, status: int) -> Response:
    return _json({"error": code, "error_description": description}, status)


def _authorization_error(error: OAuthInputError) -> Response:
    form = frappe.form_dict
    client_id = str(form.get("client_id") or "")
    redirect_uri = str(form.get("redirect_uri") or "")
    client_name = frappe.db.get_value(
        "Frappe MCP OAuth Client", {"client_id": client_id, "enabled": True}, "name"
    )
    if client_name:
        registered = str(
            frappe.db.get_value("Frappe MCP OAuth Client", client_name, "redirect_uris") or ""
        ).splitlines()
        if redirect_uri in registered:
            query = {
                "error": "invalid_request",
                "error_description": str(error),
                "iss": issuer(),
            }
            if state := str(form.get("state") or ""):
                query["state"] = state
            return _redirect_with_query(redirect_uri, query)
    return _oauth_error("invalid_request", str(error), 400)


def _redirect_with_query(uri: str, query: dict[str, str]) -> Response:
    delimiter = "&" if "?" in uri else "?"
    return redirect(f"{uri}{delimiter}{urlencode(query)}")


def _json(payload: dict[str, str], status: int = 200) -> Response:
    return Response(
        json.dumps(payload, separators=(",", ":")), status=status, content_type="application/json"
    )
