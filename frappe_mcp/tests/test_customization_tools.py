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
    identity = SimpleNamespace(user="manager@example.com", scope="mcp:read mcp:write")
    _set(auth, "require_identity", lambda: identity)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe_mcp.auth", auth)
    sys.modules.pop("frappe_mcp.customization_tools", None)
    module = importlib.import_module("frappe_mcp.customization_tools")
    return module, frappe, identity, FrappePermissionError


def test_get_doctype_meta_returns_only_safe_effective_fields(customization_tools) -> None:
    module, frappe, _identity, _permission_error = customization_tools
    meta = FakeMeta(
        [
            FakeField(
                "date_of_birth",
                "Date of Birth",
                "Date",
                reqd=1,
            )
        ]
    )
    _set(frappe, "get_meta", lambda _doctype, **_kwargs: meta)

    result = module.get_doctype_meta({"doctype": "Employee", "fieldname": "date_of_birth"})

    assert result == {
        "doctype": "Employee",
        "fields": [
            {
                "fieldname": "date_of_birth",
                "label": "Date of Birth",
                "fieldtype": "Date",
                "options": None,
                "reqd": True,
                "hidden": False,
                "read_only": False,
                "permlevel": 0,
                "is_custom_field": False,
            }
        ],
    }


def test_update_field_property_requires_write_scope(customization_tools) -> None:
    module, _frappe, identity, permission_error = customization_tools
    identity.scope = "mcp:read"

    with pytest.raises(permission_error, match="mcp:write"):
        module.update_field_property(
            {
                "doctype": "Employee",
                "fieldname": "date_of_birth",
                "property": "hidden",
                "value": True,
            }
        )


def test_standard_mandatory_field_cannot_be_relaxed(customization_tools) -> None:
    module, frappe, _identity, _permission_error = customization_tools
    field = FakeField("date_of_birth", reqd=1)
    _set(frappe, "get_meta", lambda _doctype, **_kwargs: FakeMeta([field]))
    _set(
        frappe,
        "db",
        SimpleNamespace(
            get_value=lambda doctype, *_args, **_kwargs: 1 if doctype == "DocField" else None
        ),
    )

    with pytest.raises(
        module.CustomizationError,
        match="cannot disable reqd for a mandatory standard field",
    ):
        module.update_field_property(
            {
                "doctype": "Employee",
                "fieldname": "date_of_birth",
                "property": "reqd",
                "value": False,
            }
        )


def test_standard_field_property_uses_permission_checked_property_setter(
    customization_tools,
) -> None:
    module, frappe, _identity, _permission_error = customization_tools
    inserted = []
    cleared = []
    field = FakeField("date_of_birth")
    meta = FakeMeta([field])

    class FakePropertySetter:
        def __init__(self, values) -> None:
            self.values = values

        def insert(self):
            inserted.append(self.values)
            return self

    def get_value(doctype, filters, fieldname=None):
        if doctype == "Custom Field":
            return None
        if doctype == "DocField":
            return 0
        if doctype == "Property Setter":
            return None
        raise AssertionError(doctype)

    _set(frappe, "get_meta", lambda _doctype, **_kwargs: meta)
    _set(frappe, "db", SimpleNamespace(get_value=get_value))
    _set(frappe, "get_doc", lambda values: FakePropertySetter(values))
    _set(frappe, "clear_cache", lambda *, doctype: cleared.append(doctype))

    result = module.update_field_property(
        {
            "doctype": "Employee",
            "fieldname": "date_of_birth",
            "property": "hidden",
            "value": True,
        }
    )

    assert inserted == [
        {
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": "Employee",
            "field_name": "date_of_birth",
            "property": "hidden",
            "value": "1",
            "property_type": "Check",
            "is_system_generated": 0,
        }
    ]
    assert cleared == ["Employee"]
    assert result["fieldname"] == "date_of_birth"


def test_custom_field_property_updates_custom_field_document(customization_tools) -> None:
    module, frappe, _identity, _permission_error = customization_tools
    saved = []
    field = FakeField("custom_research_id", is_custom_field=True)
    meta = FakeMeta([field])

    class FakeCustomField:
        is_system_generated = 0

        def check_permission(self, permission):
            assert permission == "write"

        def update(self, values):
            saved.append(values)

        def save(self):
            return self

    _set(frappe, "get_meta", lambda _doctype, **_kwargs: meta)
    _set(
        frappe,
        "db",
        SimpleNamespace(
            get_value=lambda doctype, *_args, **_kwargs: (
                "Employee-custom_research_id" if doctype == "Custom Field" else None
            )
        ),
    )
    _set(frappe, "get_doc", lambda *_args, **_kwargs: FakeCustomField())

    module.update_field_property(
        {
            "doctype": "Employee",
            "fieldname": "custom_research_id",
            "property": "reqd",
            "value": True,
        }
    )

    assert saved == [{"reqd": 1}]


def test_upsert_custom_field_creates_only_allowlisted_values(customization_tools) -> None:
    module, frappe, _identity, _permission_error = customization_tools
    inserted = []

    class FakeCustomField:
        def __init__(self, values) -> None:
            self.values = values

        def insert(self):
            inserted.append(self.values)
            return self

    _set(frappe, "db", SimpleNamespace(get_value=lambda *_args, **_kwargs: None))
    _set(frappe, "get_doc", lambda values: FakeCustomField(values))
    _set(
        frappe,
        "get_meta",
        lambda _doctype, **_kwargs: FakeMeta(
            [FakeField("custom_research_id", "Research ID", is_custom_field=True)]
        ),
    )

    result = module.upsert_custom_field(
        {
            "doctype": "Employee",
            "fieldname": "custom_research_id",
            "label": "Research ID",
            "fieldtype": "Data",
            "insert_after": "employee_name",
            "reqd": True,
        }
    )

    assert inserted == [
        {
            "doctype": "Custom Field",
            "dt": "Employee",
            "fieldname": "custom_research_id",
            "label": "Research ID",
            "fieldtype": "Data",
            "insert_after": "employee_name",
            "reqd": 1,
            "is_system_generated": 0,
        }
    ]
    assert result["is_custom_field"] is True
