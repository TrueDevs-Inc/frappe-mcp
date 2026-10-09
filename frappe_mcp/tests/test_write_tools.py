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
    permlevel: int = 0


class FakeMeta:
    def __init__(self, fields, permitted, writable_permlevels=frozenset({0})):
        self._fields = {field.fieldname: field for field in fields}
        self._permitted = permitted
        self._writable_permlevels = writable_permlevels

    def get_field(self, fieldname):
        return self._fields.get(fieldname)

    def get_permitted_fieldnames(self, **_kwargs):
        return self._permitted

    def get_permissions(self, **_kwargs):
        return [True]

    def get_permlevel_access(self, **_kwargs):
        return self._writable_permlevels


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
    meta = FakeMeta(
        [FakeField("title"), FakeField("amended_from"), FakeField("name")],
        ["title", "amended_from", "name"],
    )
    _set(frappe, "get_meta", lambda _doctype: meta)

    with pytest.raises(module.WriteFieldError):
        module._write_fields({"fields": {"_action": "cancel"}}, module.WriteTarget("Note"))
    with pytest.raises(module.WriteFieldError):
        module._write_fields({"fields": {"amended_from": "NOTE-0001"}}, module.WriteTarget("Note"))
    with pytest.raises(module.WriteFieldError):
        module._write_fields({"fields": {"name": "NOTE-0001"}}, module.WriteTarget("Note"))


def test_server_script_creation_accepts_only_top_level_name(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    meta = FakeMeta([FakeField("script_type"), FakeField("script")], ["script_type", "script"])
    _set(frappe, "get_meta", lambda _doctype: meta)
    insert_names = []

    class FakeDocument:
        doctype = "Server Script"
        name = None

        def __init__(self, values):
            self.values = values

        def insert(self, *, set_name=None):
            insert_names.append(set_name)
            self.name = set_name
            self.values["name"] = self.name
            return self

        def has_permission(self, _permission):
            return True

        def apply_fieldlevel_read_permissions(self):
            return None

        def as_dict(self):
            return self.values

    _set(frappe, "get_doc", lambda values: FakeDocument(values))

    result = module.create_document(
        {
            "doctype": "Server Script",
            "name": "Lead Account Tiering Calculation",
            "fields": {"script_type": "DocType Event", "script": "doc.save()"},
        }
    )

    assert result["name"] == "Lead Account Tiering Calculation"
    assert insert_names == ["Lead Account Tiering Calculation"]


def test_server_script_creation_requires_top_level_name(write_tools) -> None:
    module, _frappe, _permission_error = write_tools

    with pytest.raises(ValueError, match="name must be a non-empty string"):
        module.create_document(
            {"doctype": "Server Script", "fields": {"script_type": "API", "script": ""}}
        )


def test_non_server_script_rejects_top_level_name(write_tools) -> None:
    module, _frappe, _permission_error = write_tools

    with pytest.raises(module.WriteFieldError, match="Field is not writable: name"):
        module.create_document({"doctype": "Note", "name": "NOTE-1", "fields": {"title": "No"}})


def test_server_script_rejects_nested_name(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    meta = FakeMeta(
        [FakeField("script_type"), FakeField("script"), FakeField("name")],
        ["script_type", "script", "name"],
    )
    _set(frappe, "get_meta", lambda _doctype: meta)

    with pytest.raises(module.WriteFieldError, match="Field is not writable: name"):
        module.create_document(
            {
                "doctype": "Server Script",
                "name": "Lead Account Tiering Calculation",
                "fields": {"name": "Other", "script_type": "API", "script": ""},
            }
        )


def test_server_script_duplicate_name_error_is_preserved(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    meta = FakeMeta([FakeField("script_type"), FakeField("script")], ["script_type", "script"])
    _set(frappe, "get_meta", lambda _doctype: meta)

    class DuplicateNameError(Exception):
        pass

    class FakeDocument:
        doctype = "Server Script"
        name = None

        def __init__(self, _values):
            pass

        def insert(self, **_kwargs):
            raise DuplicateNameError("Duplicate name")

    _set(frappe, "get_doc", lambda values: FakeDocument(values))

    with pytest.raises(DuplicateNameError, match="Duplicate name"):
        module.create_document(
            {
                "doctype": "Server Script",
                "name": "Lead Account Tiering Calculation",
                "fields": {"script_type": "DocType Event", "script": "doc.save()"},
            }
        )


def test_server_script_permission_error_is_preserved(write_tools) -> None:
    module, frappe, permission_error = write_tools
    meta = FakeMeta([FakeField("script_type"), FakeField("script")], ["script_type", "script"])
    _set(frappe, "get_meta", lambda _doctype: meta)

    class FakeDocument:
        doctype = "Server Script"
        name = None

        def __init__(self, _values):
            pass

        def insert(self, **_kwargs):
            raise permission_error("Not permitted")

    _set(frappe, "get_doc", lambda values: FakeDocument(values))

    with pytest.raises(permission_error, match="Not permitted"):
        module.create_document(
            {
                "doctype": "Server Script",
                "name": "Lead Account Tiering Calculation",
                "fields": {"script_type": "DocType Event", "script": "doc.save()"},
            }
        )


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


def test_create_document_accepts_permitted_child_table(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    parent_meta = FakeMeta([FakeField("accounts", "Table", "Journal Entry Account")], [])
    child_meta = FakeMeta(
        [
            FakeField("account"),
            FakeField("debit_in_account_currency", "Currency"),
        ],
        ["account", "debit_in_account_currency"],
    )
    _set(
        frappe,
        "get_meta",
        lambda doctype: parent_meta if doctype == "Journal Entry" else child_meta,
    )

    class FakeDocument:
        doctype = "Journal Entry"
        name = "ACC-JV-0001"

        def __init__(self, values):
            self.values = values

        def insert(self):
            return self

        def has_permission(self, _permission):
            return True

        def apply_fieldlevel_read_permissions(self):
            return None

        def as_dict(self):
            return self.values

    _set(frappe, "get_doc", lambda values: FakeDocument(values))

    result = module.create_document(
        {
            "doctype": "Journal Entry",
            "fields": {
                "accounts": [{"account": "Salary - TD-M", "debit_in_account_currency": 150000}]
            },
        }
    )

    assert result == {
        "doctype": "Journal Entry",
        "accounts": [{"account": "Salary - TD-M", "debit_in_account_currency": 150000}],
    }


def test_create_document_rejects_child_table_without_permlevel_access(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    parent_meta = FakeMeta(
        [FakeField("accounts", "Table", "Journal Entry Account", permlevel=1)],
        [],
        writable_permlevels=frozenset({0}),
    )
    _set(frappe, "get_meta", lambda _doctype: parent_meta)

    with pytest.raises(module.WriteFieldError, match="Field is not writable: accounts"):
        module.create_document(
            {"doctype": "Journal Entry", "fields": {"accounts": [{"account": "Cash"}]}},
        )


def test_create_document_rejects_protected_child_field(write_tools) -> None:
    module, frappe, _permission_error = write_tools
    parent_meta = FakeMeta([FakeField("accounts", "Table", "Journal Entry Account")], [])
    child_meta = FakeMeta([FakeField("account"), FakeField("restricted")], ["account"])
    _set(
        frappe,
        "get_meta",
        lambda doctype: parent_meta if doctype == "Journal Entry" else child_meta,
    )

    with pytest.raises(module.WriteFieldError, match="Field is not writable: restricted"):
        module.create_document(
            {
                "doctype": "Journal Entry",
                "fields": {"accounts": [{"account": "Cash", "restricted": "secret"}]},
            },
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
