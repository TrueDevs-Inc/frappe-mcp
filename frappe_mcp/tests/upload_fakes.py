from __future__ import annotations

import base64
import hashlib
import importlib
import json
import mimetypes
import sys
from types import ModuleType, SimpleNamespace

import pytest

from frappe_mcp.tests.test_write_tools import FakeField, FakeMeta, _set


def strip_exif_data(content: bytes, content_type: str) -> bytes:
    assert content_type == "image/jpeg"
    return content.replace(b"EXIF:camera;", b"")


class PermissionDenied(Exception):
    pass


class ValidationFailed(Exception):
    pass


class FakeFile:
    def __init__(self, values, store):
        self.values = dict(values)
        self.store = store
        self.present = True

    @property
    def file_url(self):
        return self.values.get("file_url")

    def get(self, key):
        return self.values.get(key)

    def insert(self):
        self.store.events.append("insert")
        if self.store.insert_error:
            raise self.store.insert_error
        content_type = mimetypes.guess_type(self.values["file_name"])[0]
        if content_type == "image/jpeg" and self.store.strip_exif_enabled:
            self.values["content"] = strip_exif_data(self.values["content"], content_type)
        prefix = "/private/files/" if self.values["is_private"] else "/files/"
        self.values.update(
            name=f"FILE-{len(self.store.files) + 1}",
            file_url=prefix + self.values["file_name"],
            content_hash=hashlib.md5(self.values["content"], usedforsecurity=False).hexdigest(),
            owner="limited@example.com",
        )
        self.store.files[self.values["name"]] = self
        return self

    def exists_on_disk(self):
        return self.present

    def get_content(self):
        self.store.events.append("read_content")
        return self.values["content"]


class UploadStore:
    def __init__(self):
        self.files = {}
        self.events = []
        self.queries = []
        self.constructed = []
        self.insert_error = None
        self.target_allowed = True
        self.strip_exif_enabled = False
        self.scope = "mcp:read mcp:write"
        self.meta = FakeMeta([FakeField("image", "Attach Image")], ["image"])

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            self.events.append("construct_file")
            self.constructed.append(dict(doctype))
            return FakeFile(doctype, self)
        if doctype == "File":
            return self.files[name]
        if (doctype, name) != ("Lead", "LEAD-1"):
            raise ValidationFailed("Target does not exist")
        return SimpleNamespace(check_permission=self.check_permission)

    def check_permission(self, permission):
        assert permission == "write"
        self.events.append("target_write")
        if not self.target_allowed:
            raise PermissionDenied()

    def get_all(self, doctype, *, filters, fields, limit_page_length):
        assert doctype == "File" and fields == ["name"] and limit_page_length == 0
        self.queries.append(filters)
        return [
            SimpleNamespace(name=name)
            for name, doc in self.files.items()
            if all(doc.get(key) == value for key, value in filters.items())
        ]

    def throw(self, message, exception):
        raise exception(message)


def upload_arguments(**overrides):
    return {
        "target_doctype": "Lead",
        "target_name": "LEAD-1",
        "target_field": "image",
        "file_name": "example.png",
        "content": base64.b64encode(b"attachment bytes\x00\xff").decode("ascii"),
        "is_private": True,
        **overrides,
    }


@pytest.fixture
def upload_env(monkeypatch):
    store = UploadStore()
    frappe = ModuleType("frappe")
    for key, value in {
        "PermissionError": PermissionDenied,
        "ValidationError": ValidationFailed,
        "session": SimpleNamespace(user="limited@example.com"),
        "model": SimpleNamespace(table_fields={"Table", "Table MultiSelect"}),
        "parse_json": json.loads,
        "as_json": json.dumps,
        "get_doc": store.get_doc,
        "get_meta": lambda _doctype: store.meta,
        "get_all": store.get_all,
        "get_system_settings": lambda _name: store.strip_exif_enabled,
        "throw": store.throw,
        "whitelist": lambda **_kwargs: lambda function: function,
    }.items():
        setattr(frappe, key, value)
    auth = ModuleType("frappe_mcp.auth")
    _set(auth, "require_identity", lambda: SimpleNamespace(scope=store.scope, client="client"))
    utils = ModuleType("frappe.core.doctype.file.utils")
    _set(
        utils,
        "get_content_hash",
        lambda content: hashlib.md5(content, usedforsecurity=False).hexdigest(),
    )
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe_mcp.auth", auth)
    monkeypatch.setitem(sys.modules, "frappe.core.doctype.file.utils", utils)
    image = ModuleType("frappe.utils.image")
    _set(image, "strip_exif_data", strip_exif_data)
    monkeypatch.setitem(sys.modules, "frappe.utils.image", image)
    for name in ("write_tools", "upload_tools", "tools", "customization_tools", "api"):
        monkeypatch.delitem(sys.modules, f"frappe_mcp.{name}", raising=False)
    module = importlib.import_module("frappe_mcp.upload_tools")
    return SimpleNamespace(module=module, frappe=frappe, store=store)
