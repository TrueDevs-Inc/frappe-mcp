from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest


def _set(module, name, value) -> None:
    setattr(module, name, value)


@dataclass(frozen=True, slots=True)
class FakeField:
    fieldname: str
    fieldtype: str = "Data"
    options: str = ""
    read_only: bool = False


class FakeMeta:
    def __init__(self, fields, permitted):
        self._fields = {field.fieldname: field for field in fields}
        self._permitted = permitted

    def get_field(self, fieldname):
        return self._fields.get(fieldname)

    def get_permitted_fieldnames(self, **_kwargs):
        return self._permitted


@pytest.fixture
def write_tools(monkeypatch):
    frappe = ModuleType("frappe")

    class FrappePermissionError(Exception):
        pass

    _set(frappe, "PermissionError", FrappePermissionError)
    _set(frappe, "session", SimpleNamespace(user="limited@example.com"))
    _set(frappe, "model", SimpleNamespace(table_fields={"Table", "Table MultiSelect"}))
    _set(frappe, "parse_json", json.loads)
    _set(frappe, "as_json", json.dumps)

    auth = ModuleType("frappe_mcp.auth")
    _set(auth, "require_identity", lambda: SimpleNamespace(scope="mcp:read mcp:write"))
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe_mcp.auth", auth)
    sys.modules.pop("frappe_mcp.write_tools", None)
    module = importlib.import_module("frappe_mcp.write_tools")
    return module, frappe, FrappePermissionError


def test_internal_and_server_owned_fields_are_rejected(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    meta = FakeMeta([FakeField("title"), FakeField("amended_from")], ["title", "amended_from"])
    _set(frappe, "get_meta", lambda _doctype: meta)

    with pytest.raises(module.WriteFieldError):
        module._write_fields({"fields": {"_action": "cancel"}}, module.WriteTarget("Note"))
    with pytest.raises(module.WriteFieldError):
        module._write_fields({"fields": {"amended_from": "NOTE-0001"}}, module.WriteTarget("Note"))


def test_field_level_write_permission_is_enforced(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    meta = FakeMeta([FakeField("public"), FakeField("restricted")], ["public"])
    _set(frappe, "get_meta", lambda _doctype: meta)

    with pytest.raises(module.WriteFieldError, match="Field is not writable: restricted"):
        module._write_fields(
            {"fields": {"restricted": "secret"}}, module.WriteTarget("Secure Note")
        )


def test_child_row_must_belong_to_the_document_being_updated(write_tools) -> None:
    module, frappe, permission_error = write_tools
    parent_meta = FakeMeta([FakeField("items", "Table", "Invoice Item")], ["items"])
    child_meta = FakeMeta([FakeField("qty", "Int")], ["qty"])
    _set(
        frappe,
        "get_meta",
        lambda doctype: parent_meta if doctype == "Invoice" else child_meta,
    )
    _set(
        frappe,
        "db",
        SimpleNamespace(
            get_value=lambda *_args, **_kwargs: SimpleNamespace(
                parent="OTHER", parenttype="Invoice", parentfield="items"
            )
        ),
    )

    with pytest.raises(permission_error):
        module._write_fields(
            {"fields": {"items": [{"name": "ROW-1", "qty": 1}]}},
            module.WriteTarget("Invoice", "INV-1"),
        )


def test_document_result_applies_field_level_read_filter(write_tools) -> None:
    module, _frappe, _permission_error = write_tools

    class FakeDocument:
        doctype = "Secure Note"
        name = "NOTE-1"

        def __init__(self):
            self.values = {"name": self.name, "public": "yes", "restricted": "secret"}

        def has_permission(self, _permission):
            return True

        def apply_fieldlevel_read_permissions(self):
            self.values.pop("restricted")

        def as_dict(self):
            return self.values

    assert module._document_result(FakeDocument()) == {"name": "NOTE-1", "public": "yes"}
