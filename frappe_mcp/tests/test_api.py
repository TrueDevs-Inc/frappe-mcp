from __future__ import annotations

import importlib
import json
import sys
from types import ModuleType, SimpleNamespace


def _set(module, name, value) -> None:
    setattr(module, name, value)


def test_permission_error_rolls_back_before_response(monkeypatch) -> None:
    frappe = ModuleType("frappe")

    class FrappePermissionError(Exception):
        pass

    rolled_back = []
    request = SimpleNamespace(get_json=lambda **_kwargs: {"jsonrpc": "2.0", "id": 7})
    db = SimpleNamespace(
        get_value=lambda *_args, **_kwargs: "",
        rollback=lambda: rolled_back.append(True),
    )
    _set(frappe, "PermissionError", FrappePermissionError)
    _set(frappe, "request", request)
    _set(frappe, "db", db)
    _set(frappe, "get_request_header", lambda _name: "")
    _set(frappe, "whitelist", lambda **_kwargs: lambda function: function)

    auth = ModuleType("frappe_mcp.auth")
    _set(auth, "require_identity", lambda: SimpleNamespace(client="client"))
    config = ModuleType("frappe_mcp.config")
    _set(config, "bearer_challenge", lambda: "Bearer")
    _set(config, "enabled", lambda: True)
    _set(config, "write_enabled", lambda: True)
    protocol = ModuleType("frappe_mcp.protocol")
    _set(protocol, "JsonObject", dict)
    _set(protocol, "JsonValue", str | int | float | bool | None | list | dict)
    _set(protocol, "dispatch", lambda *_args: (_ for _ in ()).throw(FrappePermissionError()))
    tools = ModuleType("frappe_mcp.tools")
    _set(tools, "registered_tools", lambda: ())

    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe_mcp.auth", auth)
    monkeypatch.setitem(sys.modules, "frappe_mcp.config", config)
    monkeypatch.setitem(sys.modules, "frappe_mcp.protocol", protocol)
    monkeypatch.setitem(sys.modules, "frappe_mcp.tools", tools)
    sys.modules.pop("frappe_mcp.api", None)
    api = importlib.import_module("frappe_mcp.api")

    response = api.handle()

    assert rolled_back == [True]
    assert response.status_code == 403
    assert json.loads(response.get_data(as_text=True))["error"]["code"] == -32003
