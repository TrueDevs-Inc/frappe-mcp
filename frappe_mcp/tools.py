from __future__ import annotations

from collections.abc import Mapping

import frappe

from frappe_mcp.auth import require_identity
from frappe_mcp.protocol import JsonValue, Tool

PROTECTED_FIELDS = frozenset(
    {
        "creation",
        "docstatus",
        "doctype",
        "idx",
        "modified",
        "modified_by",
        "name",
        "owner",
        "parent",
        "parentfield",
        "parenttype",
    }
)


def registered_tools() -> tuple[Tool, ...]:
    return (
        Tool(
            "whoami",
            "Return the current Frappe identity and roles.",
            _object_schema({}),
            whoami,
            True,
        ),
        Tool(
            "list_documents",
            "List documents using Frappe permissions.",
            _list_schema(),
            list_documents,
            True,
        ),
        Tool(
            "get_document",
            "Read one document using Frappe permissions.",
            _document_schema(),
            get_document,
            True,
        ),
        Tool(
            "create_document",
            "Create a document using Frappe permissions and validation.",
            _fields_schema(),
            create_document,
        ),
        Tool(
            "update_document",
            "Update a document using Frappe permissions and validation.",
            _fields_schema(require_name=True),
            update_document,
        ),
        Tool(
            "delete_document",
            "Delete a document using Frappe permissions.",
            _document_schema(),
            delete_document,
            destructive=True,
        ),
        Tool(
            "submit_document",
            "Submit a document using Frappe permissions and validation.",
            _document_schema(),
            submit_document,
        ),
        Tool(
            "cancel_document",
            "Cancel a document using Frappe permissions and validation.",
            _document_schema(),
            cancel_document,
            destructive=True,
        ),
        Tool(
            "amend_document",
            "Create a draft amendment of a cancelled document.",
            _fields_schema(require_name=True),
            amend_document,
        ),
        Tool(
            "apply_workflow",
            "Apply an available workflow action to a document.",
            _workflow_schema(),
            apply_workflow,
        ),
        Tool(
            "run_report",
            "Run a Frappe report using report permissions.",
            _report_schema(),
            run_report,
            True,
        ),
    )


def whoami(_arguments: Mapping[str, JsonValue]) -> JsonValue:
    identity = require_identity()
    return {
        "user": identity.user,
        "client": identity.client,
        "roles": frappe.get_roles(identity.user),
    }


def list_documents(arguments: Mapping[str, JsonValue]) -> JsonValue:
    doctype = _required_str(arguments, "doctype")
    fields = arguments.get("fields", ["name", "modified"])
    filters = arguments.get("filters", {})
    limit = min(max(_integer(arguments.get("limit", 20)), 1), 100)
    rows = frappe.get_list(
        doctype,
        fields=fields,
        filters=filters,
        limit_start=max(_integer(arguments.get("offset", 0)), 0),
        limit_page_length=limit,
        order_by=str(arguments.get("order_by") or "modified desc"),
    )
    return _json_value(rows)


def get_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    doc = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    doc.check_permission("read")
    doc.apply_fieldlevel_read_permissions()
    return _json_value(doc.as_dict())


def create_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    fields = _write_fields(arguments)
    doc = frappe.get_doc({"doctype": _required_str(arguments, "doctype"), **fields})
    doc.insert()
    return _json_value(doc.as_dict())


def update_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doc = frappe.get_doc(
        _required_str(arguments, "doctype"), _required_str(arguments, "name"), for_update=True
    )
    doc.update(_write_fields(arguments))
    doc.save()
    return _json_value(doc.as_dict())


def delete_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doctype = _required_str(arguments, "doctype")
    name = _required_str(arguments, "name")
    frappe.delete_doc(doctype, name)
    return {"deleted": True, "doctype": doctype, "name": name}


def submit_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doc = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    doc.submit()
    return _json_value(doc.as_dict())


def cancel_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    doc = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    doc.cancel()
    return _json_value(doc.as_dict())


def amend_document(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    source = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    source.check_permission("read")
    amended = frappe.copy_doc(source)
    amended.name = None
    amended.docstatus = 0
    amended.amended_from = source.name
    amended.update(_write_fields(arguments))
    amended.insert()
    return _json_value(amended.as_dict())


def apply_workflow(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    from frappe.model.workflow import apply_workflow as frappe_apply_workflow

    doc = frappe.get_doc(_required_str(arguments, "doctype"), _required_str(arguments, "name"))
    result = frappe_apply_workflow(doc, _required_str(arguments, "action"))
    return _json_value(result.as_dict() if result else {"queued": True})


def run_report(arguments: Mapping[str, JsonValue]) -> JsonValue:
    from frappe.desk.query_report import run

    result = run(
        report_name=_required_str(arguments, "report_name"),
        filters=arguments.get("filters", {}),
        ignore_prepared_report=True,
    )
    return _json_value(result)


def _require_write_scope() -> None:
    if "mcp:write" not in require_identity().scope.split():
        frappe.throw("This token does not have mcp:write scope", frappe.PermissionError)


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


def _write_fields(arguments: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    fields = _required_mapping(arguments, "fields")
    if PROTECTED_FIELDS.intersection(fields):
        raise ValueError("fields contains protected document metadata")
    return fields


def _integer(value: JsonValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("pagination values must be integers")
    return value


def _json_value(value: object) -> JsonValue:
    return frappe.parse_json(frappe.as_json(value))


def _object_schema(
    properties: dict[str, JsonValue], required: list[str] | None = None
) -> dict[str, JsonValue]:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        required_values: list[JsonValue] = []
        required_values.extend(required)
        schema["required"] = required_values
    return schema


def _document_schema() -> dict[str, JsonValue]:
    return _object_schema(
        {"doctype": {"type": "string"}, "name": {"type": "string"}}, ["doctype", "name"]
    )


def _fields_schema(require_name: bool = False) -> dict[str, JsonValue]:
    properties: dict[str, JsonValue] = {
        "doctype": {"type": "string"},
        "fields": {"type": "object"},
    }
    required = ["doctype", "fields"]
    if require_name:
        properties["name"] = {"type": "string"}
        required.append("name")
    return _object_schema(properties, required)


def _list_schema() -> dict[str, JsonValue]:
    return _object_schema(
        {
            "doctype": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "string"}},
            "filters": {"type": ["object", "array"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "offset": {"type": "integer", "minimum": 0},
            "order_by": {"type": "string"},
        },
        ["doctype"],
    )


def _workflow_schema() -> dict[str, JsonValue]:
    return _object_schema(
        {"doctype": {"type": "string"}, "name": {"type": "string"}, "action": {"type": "string"}},
        ["doctype", "name", "action"],
    )


def _report_schema() -> dict[str, JsonValue]:
    return _object_schema(
        {"report_name": {"type": "string"}, "filters": {"type": "object"}}, ["report_name"]
    )
