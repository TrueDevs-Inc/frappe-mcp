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
    label: str = "Field"
    fieldtype: str = "Data"
    options: str | None = None
    reqd: int = 0
    hidden: int = 0
    read_only: int = 0
    permlevel: int = 0
    is_custom_field: bool = False


class FakeMeta:
    name = "Employee"

    def __init__(self, fields, readable_permlevels=frozenset({0})) -> None:
        self.fields = fields
        self._readable_permlevels = readable_permlevels

    def get_field(self, fieldname):
        return next((field for field in self.fields if field.fieldname == fieldname), None)

    def get_permissions(self, **_kwargs):
        return [True]

    def get_permlevel_access(self, **_kwargs):
        return self._readable_permlevels


@pytest.fixture
def customization_tools(monkeypatch):
    frappe = ModuleType("frappe")

    class FrappePermissionError(Exception):
        pass

    _set(frappe, "PermissionError", FrappePermissionError)
    _set(frappe, "session", SimpleNamespace(user="manager@example.com"))
    _set(frappe, "parse_json", json.loads)
    _set(frappe, "as_json", json.dumps)
    _set(frappe, "has_permission", lambda *_args, **_kwargs: True)
    _set(
        frappe,
        "throw",
        lambda message, error_type: (_ for _ in ()).throw(error_type(message)),
    )
    auth = ModuleType("frappe_mcp.auth")
    _set(
        auth,
        "require_identity",
        lambda: SimpleNamespace(user="manager@example.com", scope="mcp:read mcp:write"),
    )
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe_mcp.auth", auth)
    sys.modules.pop("frappe_mcp.customization_tools", None)
    return importlib.import_module("frappe_mcp.customization_tools"), frappe


def test_metadata_hides_fields_above_the_users_read_permlevel(customization_tools) -> None:
    module, frappe = customization_tools
    meta = FakeMeta([FakeField("public"), FakeField("restricted", permlevel=1)])
    _set(frappe, "get_meta", lambda _doctype, **_kwargs: meta)

    result = module.get_doctype_meta({"doctype": "Employee"})

    assert [field["fieldname"] for field in result["fields"]] == ["public"]
    with pytest.raises(module.CustomizationError, match="Unknown field: restricted"):
        module.get_doctype_meta({"doctype": "Employee", "fieldname": "restricted"})


def test_existing_custom_field_rejects_fieldtype_changes(customization_tools) -> None:
    module, frappe = customization_tools

    class FakeCustomField:
        fieldtype = "Data"
        options = None
        is_system_generated = 0

    _set(
        frappe,
        "db",
        SimpleNamespace(get_value=lambda *_args, **_kwargs: "Employee-custom_research_id"),
    )
    _set(frappe, "get_doc", lambda *_args, **_kwargs: FakeCustomField())

    with pytest.raises(module.CustomizationError, match="fieldtype cannot be changed"):
        module.upsert_custom_field(
            {
                "doctype": "Employee",
                "fieldname": "custom_research_id",
                "label": "Research ID",
                "fieldtype": "Int",
            }
        )


def test_existing_custom_field_rejects_options_changes(customization_tools) -> None:
    module, frappe = customization_tools

    class FakeCustomField:
        fieldtype = "Link"
        options = "User"
        is_system_generated = 0

    _set(
        frappe,
        "db",
        SimpleNamespace(get_value=lambda *_args, **_kwargs: "Employee-custom_reviewer"),
    )
    _set(frappe, "get_doc", lambda *_args, **_kwargs: FakeCustomField())

    with pytest.raises(module.CustomizationError, match="options cannot be changed"):
        module.upsert_custom_field(
            {
                "doctype": "Employee",
                "fieldname": "custom_reviewer",
                "label": "Reviewer",
                "fieldtype": "Link",
                "options": "Role",
            }
        )


def test_system_generated_custom_field_cannot_be_updated(customization_tools) -> None:
    module, frappe = customization_tools
    meta = FakeMeta([FakeField("custom_system", is_custom_field=True)])

    class FakeCustomField:
        is_system_generated = 1

    _set(frappe, "get_meta", lambda _doctype, **_kwargs: meta)
    _set(
        frappe,
        "db",
        SimpleNamespace(get_value=lambda *_args, **_kwargs: "Employee-custom_system"),
    )
    _set(frappe, "get_doc", lambda *_args, **_kwargs: FakeCustomField())

    with pytest.raises(module.CustomizationError, match="system-generated Custom Field"):
        module.update_field_property(
            {
                "doctype": "Employee",
                "fieldname": "custom_system",
                "property": "hidden",
                "value": True,
            }
        )


def test_system_generated_property_setter_cannot_be_updated(customization_tools) -> None:
    module, frappe = customization_tools
    meta = FakeMeta([FakeField("date_of_birth")])

    class FakePropertySetter:
        is_system_generated = 1

    def get_value(doctype, *_args, **_kwargs):
        if doctype == "DocField":
            return 0
        if doctype == "Property Setter":
            return "Employee-date_of_birth-hidden"
        return None

    _set(frappe, "get_meta", lambda _doctype, **_kwargs: meta)
    _set(frappe, "db", SimpleNamespace(get_value=get_value))
    _set(frappe, "get_doc", lambda *_args, **_kwargs: FakePropertySetter())

    with pytest.raises(module.CustomizationError, match="system-generated Property Setter"):
        module.update_field_property(
            {
                "doctype": "Employee",
                "fieldname": "date_of_birth",
                "property": "hidden",
                "value": True,
            }
        )
