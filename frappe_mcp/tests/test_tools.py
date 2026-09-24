from __future__ import annotations

import importlib
import sys
from types import ModuleType


def _set(module, name, value) -> None:
    setattr(module, name, value)


def test_registered_tools_expose_safe_customization_surface(monkeypatch) -> None:
    frappe = ModuleType("frappe")
    auth = ModuleType("frappe_mcp.auth")
    customization_tools = ModuleType("frappe_mcp.customization_tools")
    write_tools = ModuleType("frappe_mcp.write_tools")
    _set(auth, "require_identity", lambda: None)
    for name in "get_doctype_meta update_field_property upsert_custom_field".split():
        _set(customization_tools, name, lambda _arguments: {})
    write_names = "amend_document apply_workflow cancel_document create_document"
    for name in f"{write_names} delete_document submit_document update_document".split():
        _set(write_tools, name, lambda _arguments: {})
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe_mcp.auth", auth)
    monkeypatch.setitem(sys.modules, "frappe_mcp.customization_tools", customization_tools)
    monkeypatch.setitem(sys.modules, "frappe_mcp.write_tools", write_tools)
    sys.modules.pop("frappe_mcp.tools", None)
    tools_module = importlib.import_module("frappe_mcp.tools")

    tools = {tool.name: tool for tool in tools_module.registered_tools()}

    assert tools["get_doctype_meta"].read_only is True
    assert tools["update_field_property"].destructive is True
    assert tools["upsert_custom_field"].destructive is True
