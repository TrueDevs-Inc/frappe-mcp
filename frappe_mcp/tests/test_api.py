from __future__ import annotations

import importlib
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest


def _set(module, name, value) -> None:
    setattr(module, name, value)


@pytest.fixture
def api_with_dispatch_error(monkeypatch):
    frappe = ModuleType("frappe")

    class FrappePermissionError(Exception):
        pass

    class FrappeValidationError(Exception):
        pass

    rolled_back = []
    dispatch_error = SimpleNamespace(value=FrappePermissionError())
    request = SimpleNamespace(get_json=lambda **_kwargs: {"jsonrpc": "2.0", "id": 7})
    db = SimpleNamespace(
        get_value=lambda *_args, **_kwargs: "",
        rollback=lambda: rolled_back.append(True),
    )
    _set(frappe, "PermissionError", FrappePermissionError)
    _set(frappe, "ValidationError", FrappeValidationError)
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
    _set(protocol, "dispatch", lambda *_args: (_ for _ in ()).throw(dispatch_error.value))
    tools = ModuleType("frappe_mcp.tools")
    _set(tools, "registered_tools", lambda: ())
    write_tools = ModuleType("frappe_mcp.write_tools")
    customization_tools = ModuleType("frappe_mcp.customization_tools")

    class WriteFieldError(ValueError):
        pass

    _set(write_tools, "WriteFieldError", WriteFieldError)

    class CustomizationError(ValueError):
        pass

    _set(customization_tools, "CustomizationError", CustomizationError)
    _set(dispatch_error, "customization_error", CustomizationError)
    _set(dispatch_error, "validation_error", FrappeValidationError)

    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe_mcp.auth", auth)
    monkeypatch.setitem(sys.modules, "frappe_mcp.config", config)
    monkeypatch.setitem(sys.modules, "frappe_mcp.protocol", protocol)
    monkeypatch.setitem(sys.modules, "frappe_mcp.tools", tools)
    monkeypatch.setitem(sys.modules, "frappe_mcp.write_tools", write_tools)
    monkeypatch.setitem(sys.modules, "frappe_mcp.customization_tools", customization_tools)
    sys.modules.pop("frappe_mcp.api", None)
    api = importlib.import_module("frappe_mcp.api")
    return api, rolled_back, dispatch_error, WriteFieldError


def test_permission_error_rolls_back_before_response(api_with_dispatch_error) -> None:
    api, rolled_back, _dispatch_error, _write_field_error = api_with_dispatch_error

    response = api.handle()

    assert rolled_back == [True]
    assert response.status_code == 403
    assert json.loads(response.get_data(as_text=True))["error"]["code"] == -32003


def test_write_field_error_returns_actionable_invalid_params(api_with_dispatch_error) -> None:
    api, rolled_back, dispatch_error, write_field_error = api_with_dispatch_error
    dispatch_error.value = write_field_error("Field is not writable: currency")

    response = api.handle()

    assert rolled_back == [True]
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))["error"] == {
        "code": -32602,
        "message": "Field is not writable: currency",
    }


def test_customization_error_returns_actionable_invalid_params(api_with_dispatch_error) -> None:
    api, rolled_back, dispatch_error, _write_field_error = api_with_dispatch_error
    dispatch_error.value = dispatch_error.customization_error(
        "cannot disable reqd for a mandatory standard field"
    )

    response = api.handle()

    assert rolled_back == [True]
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))["error"] == {
        "code": -32602,
        "message": "cannot disable reqd for a mandatory standard field",
    }


def test_frappe_validation_error_returns_actionable_invalid_params(api_with_dispatch_error) -> None:
    api, rolled_back, dispatch_error, _write_field_error = api_with_dispatch_error
    dispatch_error.value = dispatch_error.validation_error("Fieldname must start with custom_")

    response = api.handle()

    assert rolled_back == [True]
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))["error"] == {
        "code": -32602,
        "message": "Fieldname must start with custom_",
    }
