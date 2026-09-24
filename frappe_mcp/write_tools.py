from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import frappe

from frappe_mcp.auth import require_identity
from frappe_mcp.protocol import JsonValue

SERVER_OWNED_FIELDS = frozenset({"amended_from"})


class WriteFieldError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WriteTarget:
    doctype: str
    name: str | None = None
    parenttype: str | None = None


def create_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doctype = _required_str(arguments, "doctype")
    fields = _write_fields(arguments, WriteTarget(doctype))
    doc = frappe.get_doc({"doctype": doctype, **fields})
    doc.insert()
    return _document_result(doc)


def update_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doctype = _required_str(arguments, "doctype")
    name = _required_str(arguments, "name")
    doc = frappe.get_doc(doctype, name, for_update=True)
    doc.check_permission("write")
    doc.update(_write_fields(arguments, WriteTarget(doctype, name)))
    doc.save()
    return _document_result(doc)


def delete_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doctype = _required_str(arguments, "doctype")
    name = _required_str(arguments, "name")
    frappe.get_doc(doctype, name).check_permission("delete")
    frappe.delete_doc(doctype, name)
    return {"deleted": True, "doctype": doctype, "name": name}


def submit_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doc = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    doc.check_permission("submit")
    doc.submit()
    return _document_result(doc)


def cancel_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doc = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    doc.check_permission("cancel")
    doc.cancel()
    return _document_result(doc)


def amend_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doctype = _required_str(arguments, "doctype")
    source = frappe.get_doc(doctype, _required_str(arguments, "name"))
    source.check_permission("amend")
    amended = frappe.copy_doc(source)
    amended.name = None
    amended.docstatus = 0
    amended.amended_from = source.name
    amended.update(_write_fields(arguments, WriteTarget(doctype)))
    amended.insert()
    return _document_result(amended)


def apply_workflow(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    from frappe.model.workflow import apply_workflow as frappe_apply_workflow

    doc = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    result = frappe_apply_workflow(doc, _required_str(arguments, "action"))
    return _document_result(result) if result else {"queued": True}


def _require_write_scope() -> None:
    if "mcp:write" not in require_identity().scope.split():
        frappe.throw("This token does not have mcp:write scope", frappe.PermissionError)


def _write_fields(arguments: Mapping[str, JsonValue], target: WriteTarget) -> dict[str, JsonValue]:
    fields = _required_mapping(arguments, "fields")
    meta = frappe.get_meta(target.doctype)
    permitted = set(
        meta.get_permitted_fieldnames(
            parenttype=target.parenttype,
            user=frappe.session.user,
            permission_type="write",
            with_virtual_fields=False,
        )
    )
    permissions = meta.get_permissions(parenttype=target.parenttype)
    writable_permlevels = (
        set(
            meta.get_permlevel_access(
                permission_type="write", parenttype=target.parenttype, user=frappe.session.user
            )
        )
        if permissions
        else set()
    )
    validated: dict[str, JsonValue] = {}
    for fieldname, value in fields.items():
        field = meta.get_field(fieldname)
        table_field = field is not None and field.fieldtype in frappe.model.table_fields
        writable_table = table_field and (not permissions or field.permlevel in writable_permlevels)
        if (
            field is None
            or (fieldname not in permitted and not writable_table)
            or field.read_only
            or fieldname in SERVER_OWNED_FIELDS
        ):
            raise WriteFieldError(f"Field is not writable: {fieldname}")
        if table_field:
            validated[fieldname] = _child_rows(target, field, value)
        else:
            validated[fieldname] = value
    return validated


def _child_rows(target: WriteTarget, table_field, value: JsonValue) -> JsonValue:
    if not isinstance(value, list):
        raise ValueError(f"{table_field.fieldname} must be an array")
    rows: list[JsonValue] = []
    for value_row in value:
        if not isinstance(value_row, dict):
            raise ValueError(f"{table_field.fieldname} rows must be objects")
        row = dict(value_row)
        child_name = row.pop("name", None)
        if child_name is not None:
            if not isinstance(child_name, str) or not child_name or target.name is None:
                raise frappe.PermissionError("Child row name is not writable")
            _require_owned_child(target, table_field, child_name)
        child = _write_fields(
            {"fields": row},
            WriteTarget(str(table_field.options), parenttype=target.doctype),
        )
        if isinstance(child_name, str):
            child["name"] = child_name
        rows.append(child)
    return rows


def _require_owned_child(target: WriteTarget, table_field, child_name: str) -> None:
    owner = frappe.db.get_value(
        str(table_field.options),
        child_name,
        ["parent", "parenttype", "parentfield"],
        as_dict=True,
    )
    if (
        not owner
        or owner.parent != target.name
        or owner.parenttype != target.doctype
        or owner.parentfield != table_field.fieldname
    ):
        raise frappe.PermissionError("Child row does not belong to this document")


def _document_result(doc) -> JsonValue:
    if not doc.has_permission("read"):
        return {"doctype": str(doc.doctype), "name": str(doc.name)}
    doc.apply_fieldlevel_read_permissions()
    return _json_value(doc.as_dict())


def _required_str(arguments: Mapping[str, JsonValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_mapping(arguments: Mapping[str, JsonValue], name: str) -> dict[str, JsonValue]:
    value = arguments.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _json_value(value) -> JsonValue:
    return frappe.parse_json(frappe.as_json(value))
