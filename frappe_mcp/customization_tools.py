from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import frappe

from frappe_mcp.auth import require_identity
from frappe_mcp.protocol import JsonValue

FIELD_PROPERTIES: Final = frozenset({"reqd", "hidden", "read_only"})
CUSTOM_FIELD_STRINGS: Final = ("options", "insert_after")
CUSTOM_FIELD_CHECKS: Final = ("reqd", "hidden", "read_only")


class CustomizationError(ValueError):
    pass


def get_doctype_meta(arguments: Mapping[str, JsonValue]) -> JsonValue:
    identity = require_identity()
    doctype = _required_str(arguments, "doctype")
    frappe.has_permission(doctype, "read", user=identity.user, throw=True)
    meta = frappe.get_meta(doctype)
    readable_fields = _readable_fields(meta, identity.user)
    fieldname = arguments.get("fieldname")
    if fieldname is not None:
        if not isinstance(fieldname, str) or not fieldname:
            raise CustomizationError("fieldname must be a non-empty string")
        field = _named_field(readable_fields, fieldname)
        fields = [_field_result(field)]
    else:
        fields = [_field_result(field) for field in readable_fields]
    return {"doctype": str(meta.name), "fields": fields}


def update_field_property(arguments: Mapping[str, JsonValue]) -> JsonValue:
    identity = _require_write_scope()
    doctype = _required_str(arguments, "doctype")
    fieldname = _required_str(arguments, "fieldname")
    property_name = _required_str(arguments, "property")
    value = _required_bool(arguments, "value")
    if property_name not in FIELD_PROPERTIES:
        raise CustomizationError(f"Unsupported field property: {property_name}")

    frappe.has_permission(doctype, "read", user=identity.user, throw=True)
    field = _named_field(
        _readable_fields(frappe.get_meta(doctype, cached=False), identity.user), fieldname
    )
    custom_field_name = frappe.db.get_value(
        "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
    )
    if custom_field_name:
        custom_field = frappe.get_doc("Custom Field", custom_field_name, for_update=True)
        if custom_field.is_system_generated:
            raise CustomizationError("cannot update a system-generated Custom Field")
        custom_field.check_permission("write")
        custom_field.update({property_name: int(value)})
        custom_field.save()
        return _field_after_change(doctype, fieldname)

    base_value = bool(
        frappe.db.get_value("DocField", {"parent": doctype, "fieldname": fieldname}, property_name)
    )
    if property_name == "reqd" and base_value and not value:
        raise CustomizationError("cannot disable reqd for a mandatory standard field")
    if property_name == "read_only" and base_value and not value:
        raise CustomizationError("cannot disable read_only for a read-only standard field")

    filters = {"doc_type": doctype, "field_name": fieldname, "property": property_name}
    setter_name = frappe.db.get_value("Property Setter", filters, "name")
    setter = (
        frappe.get_doc("Property Setter", setter_name, for_update=True) if setter_name else None
    )
    if setter is not None and setter.is_system_generated:
        raise CustomizationError("cannot update a system-generated Property Setter")
    if value == base_value:
        if setter is not None:
            setter.check_permission("delete")
            setter.delete()
    elif setter is not None:
        setter.check_permission("write")
        setter.update({"value": str(int(value)), "property_type": "Check"})
        setter.save()
    else:
        frappe.has_permission("Property Setter", "create", user=identity.user, throw=True)
        frappe.get_doc(
            {
                "doctype": "Property Setter",
                "doctype_or_field": "DocField",
                "doc_type": doctype,
                "field_name": fieldname,
                "property": property_name,
                "value": str(int(value)),
                "property_type": "Check",
                "is_system_generated": 0,
            }
        ).insert()
    frappe.clear_cache(doctype=doctype)
    return (
        _field_result(field)
        if value == base_value and not setter_name
        else _field_after_change(doctype, fieldname)
    )


def upsert_custom_field(arguments: Mapping[str, JsonValue]) -> JsonValue:
    identity = _require_write_scope()
    doctype = _required_str(arguments, "doctype")
    fieldname = _required_str(arguments, "fieldname")
    if not fieldname.startswith("custom_"):
        raise CustomizationError("Custom Field fieldname must start with custom_")

    frappe.has_permission(doctype, "read", user=identity.user, throw=True)
    fieldtype = _required_str(arguments, "fieldtype")
    values: dict[str, JsonValue] = {"label": _required_str(arguments, "label")}
    for name in CUSTOM_FIELD_STRINGS:
        value = arguments.get(name)
        if value is not None:
            if not isinstance(value, str):
                raise CustomizationError(f"{name} must be a string")
            values[name] = value
    for name in CUSTOM_FIELD_CHECKS:
        if name in arguments:
            values[name] = int(_required_bool(arguments, name))

    custom_field_name = frappe.db.get_value(
        "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
    )
    if custom_field_name:
        custom_field = frappe.get_doc("Custom Field", custom_field_name, for_update=True)
        if custom_field.is_system_generated:
            raise CustomizationError("cannot update a system-generated Custom Field")
        if str(custom_field.fieldtype) != fieldtype:
            raise CustomizationError("Custom Field fieldtype cannot be changed")
        if "options" in arguments and str(custom_field.options or "") != str(arguments["options"]):
            raise CustomizationError("Custom Field options cannot be changed")
        custom_field.check_permission("write")
        custom_field.update(values)
        custom_field.save()
    else:
        frappe.has_permission("Custom Field", "create", user=identity.user, throw=True)
        custom_field = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": doctype,
                "fieldname": fieldname,
                "fieldtype": fieldtype,
                **values,
                "is_system_generated": 0,
            }
        )
        custom_field.insert()
    return _field_after_change(doctype, fieldname)


def _require_write_scope():
    identity = require_identity()
    if "mcp:write" not in identity.scope.split():
        frappe.throw("This token does not have mcp:write scope", frappe.PermissionError)
    return identity


def _readable_fields(meta, user: str):
    if not meta.get_permissions():
        return list(meta.fields)
    permlevels = set(meta.get_permlevel_access(permission_type="read", user=user))
    return [field for field in meta.fields if field.permlevel in permlevels]


def _named_field(fields, fieldname: str):
    field = next((candidate for candidate in fields if candidate.fieldname == fieldname), None)
    if field is None:
        raise CustomizationError(f"Unknown field: {fieldname}")
    return field


def _field_after_change(doctype: str, fieldname: str) -> dict[str, JsonValue]:
    identity = require_identity()
    fields = _readable_fields(frappe.get_meta(doctype, cached=False), identity.user)
    return _field_result(_named_field(fields, fieldname))


def _field_result(field) -> dict[str, JsonValue]:
    return {
        "fieldname": str(field.fieldname),
        "label": str(field.label or field.fieldname),
        "fieldtype": str(field.fieldtype),
        "options": str(field.options) if field.options is not None else None,
        "reqd": bool(field.reqd),
        "hidden": bool(field.hidden),
        "read_only": bool(field.read_only),
        "permlevel": int(field.permlevel or 0),
        "is_custom_field": bool(getattr(field, "is_custom_field", False)),
    }


def _required_str(arguments: Mapping[str, JsonValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise CustomizationError(f"{name} must be a non-empty string")
    return value


def _required_bool(arguments: Mapping[str, JsonValue], name: str) -> bool:
    value = arguments.get(name)
    if not isinstance(value, bool):
        raise CustomizationError(f"{name} must be a boolean")
    return value
