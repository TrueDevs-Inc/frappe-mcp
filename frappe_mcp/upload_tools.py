from __future__ import annotations

import base64
import binascii
import mimetypes
from collections.abc import Mapping

import frappe

from frappe_mcp.protocol import JsonValue
from frappe_mcp.write_tools import (
    WriteFieldError,
    WriteTarget,
    _json_value,
    _require_write_scope,
    _required_str,
    _write_fields,
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
UPLOAD_FIELDS = (
    "target_doctype",
    "target_name",
    "target_field",
    "file_name",
    "content",
    "is_private",
)
FILE_RESULT_FIELDS = (
    "name",
    "file_name",
    "file_url",
    "is_private",
    "attached_to_doctype",
    "attached_to_name",
    "attached_to_field",
    "content_hash",
)


def upload_file(arguments: Mapping[str, JsonValue]) -> JsonValue:
    _require_write_scope()
    if set(arguments) != set(UPLOAD_FIELDS):
        raise ValueError("Only the required upload fields are accepted")
    doctype = _required_str(arguments, "target_doctype")
    name = _required_str(arguments, "target_name")
    fieldname = _required_str(arguments, "target_field")
    file_name = _required_str(arguments, "file_name")
    if (
        file_name in {".", ".."}
        or file_name != file_name.strip()
        or file_name.endswith(".")
        or any(ord(char) < 32 or ord(char) == 127 or char in '<>:"/\\|?*' for char in file_name)
    ):
        raise ValueError("file_name must be a safe basename")
    is_private = arguments["is_private"]
    if not isinstance(is_private, bool):
        raise ValueError("is_private must be a boolean")
    encoded = _required_str(arguments, "content")
    if len(encoded) > 4 * ((MAX_UPLOAD_BYTES + 2) // 3):
        raise ValueError("File content exceeds 5 MiB")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("content must be standard base64") from error
    if not content or base64.b64encode(content).decode("ascii") != encoded:
        raise ValueError("content must be non-empty canonical standard base64")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("File content exceeds 5 MiB")
    frappe.get_doc(doctype, name).check_permission("write")
    field = frappe.get_meta(doctype).get_field(fieldname)
    if field is None or field.fieldtype not in {"Attach", "Attach Image"}:
        raise WriteFieldError("Target field must be Attach or Attach Image")
    _write_fields({"fields": {fieldname: None}}, WriteTarget(doctype, name))
    from frappe.core.doctype.file.utils import get_content_hash
    from frappe.utils.image import strip_exif_data

    content_type = mimetypes.guess_type(file_name)[0]
    if content_type == "image/jpeg" and frappe.get_system_settings(
        "strip_exif_metadata_from_uploaded_images"
    ):
        content = strip_exif_data(content, content_type)
    content_hash = get_content_hash(content)
    attachment = {
        "attached_to_doctype": doctype,
        "attached_to_name": name,
        "attached_to_field": fieldname,
        "is_private": int(is_private),
    }
    for row in frappe.get_all(
        "File",
        filters={**attachment, "content_hash": content_hash},
        fields=["name"],
        limit_page_length=0,
    ):
        existing = frappe.get_doc("File", row.name)
        prefix = "/private/files/" if is_private else "/files/"
        if not existing.file_url or not existing.file_url.startswith(prefix):
            continue
        if not existing.exists_on_disk():
            continue
        stored = existing.get_content()
        if isinstance(stored, str):
            stored = stored.encode("utf-8")
        if stored == content:
            return _json_value({key: existing.get(key) for key in FILE_RESULT_FIELDS})
    doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file_name,
            "content": content,
            **attachment,
        }
    )
    doc.insert()
    return _json_value({key: doc.get(key) for key in FILE_RESULT_FIELDS})
