from __future__ import annotations

import importlib
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from frappe_mcp.protocol import dispatch
from frappe_mcp.tests.test_write_tools import _set
from frappe_mcp.tests.upload_fakes import (
    FakeField,
    FakeMeta,
    PermissionDenied,
    ValidationFailed,
    upload_arguments,
)
from frappe_mcp.tests.upload_fakes import upload_env as upload_env


@pytest.fixture
def upload_api(upload_env, monkeypatch):
    request = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {"name": "upload_file", "arguments": upload_arguments()},
    }
    rolled_back = []
    config = ModuleType("frappe_mcp.config")
    settings = SimpleNamespace(write_enabled=True)
    _set(config, "enabled", lambda: True)
    _set(config, "write_enabled", lambda: settings.write_enabled)
    _set(config, "bearer_challenge", lambda: "Bearer")
    monkeypatch.setitem(sys.modules, "frappe_mcp.config", config)
    _set(upload_env.frappe, "get_request_header", lambda _name: "")
    _set(upload_env.frappe, "request", SimpleNamespace(get_json=lambda **_kwargs: request))
    _set(
        upload_env.frappe,
        "db",
        SimpleNamespace(
            get_value=lambda *_args: "",
            rollback=lambda: rolled_back.append(True),
        ),
    )
    api = importlib.import_module("frappe_mcp.api")
    return SimpleNamespace(
        api=api,
        env=upload_env,
        request=request,
        rolled_back=rolled_back,
        settings=settings,
    )


def test_registry_exposes_closed_upload_schema_when_registered(upload_api):
    tools = upload_api.api.registered_tools()

    tool = next(tool for tool in tools if tool.name == "upload_file")

    assert tool.handler is upload_api.env.module.upload_file
    assert tool.descriptor()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
    }
    assert tool.input_schema == {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "target_doctype",
            "target_name",
            "target_field",
            "file_name",
            "content",
            "is_private",
        ],
        "properties": {
            "target_doctype": {"type": "string"},
            "target_name": {"type": "string"},
            "target_field": {"type": "string"},
            "file_name": {"type": "string"},
            "content": {"type": "string"},
            "is_private": {"type": "boolean"},
        },
    }


def test_dispatch_returns_safe_metadata_when_upload_succeeds(upload_api):
    response = upload_api.api.handle()

    payload = json.loads(response.get_data(as_text=True))

    assert response.status_code == 200
    result = payload["result"]
    metadata = result["structuredContent"]
    assert metadata["name"] == "FILE-1"
    assert set(metadata) == {
        "name",
        "file_name",
        "file_url",
        "is_private",
        "attached_to_doctype",
        "attached_to_name",
        "attached_to_field",
        "content_hash",
    }
    assert json.loads(result["content"][0]["text"]) == metadata
    assert upload_api.rolled_back == []


@pytest.mark.parametrize(
    "forbidden",
    [
        "owner",
        "name",
        "ignore_permissions",
        "file_url",
        "url",
        "path",
        "file_path",
        "attached_to_doctype",
        "attached_to_name",
        "attached_to_field",
    ],
)
def test_dispatch_rejects_input_when_forbidden_argument_present(upload_api, forbidden):
    upload_api.request["params"]["arguments"][forbidden] = "forbidden"

    response = upload_api.api.handle()

    assert json.loads(response.get_data(as_text=True))["error"]["code"] == -32602
    assert upload_api.env.store.constructed == []


@pytest.mark.parametrize(
    "field", ["target_doctype", "target_name", "target_field", "file_name", "content", "is_private"]
)
def test_dispatch_rejects_input_when_required_argument_missing(upload_api, field):
    upload_api.request["params"]["arguments"].pop(field)

    response = upload_api.api.handle()

    assert json.loads(response.get_data(as_text=True))["error"]["code"] == -32602
    assert upload_api.env.store.constructed == []


def test_api_filters_upload_when_writes_disabled(upload_api):
    upload_api.settings.write_enabled = False

    response = upload_api.api.handle()

    assert json.loads(response.get_data(as_text=True))["error"] == {
        "code": -32602,
        "message": "Unknown tool",
    }
    upload_api.request.update(method="tools/list", params={})
    listing = json.loads(upload_api.api.handle().get_data(as_text=True))
    assert "upload_file" not in [tool["name"] for tool in listing["result"]["tools"]]
    assert upload_api.env.store.constructed == []


@pytest.mark.parametrize("failure", ["base64", "field", "scope", "permission", "insert"])
def test_api_rolls_back_upload_when_handler_fails(upload_api, failure):
    if failure == "base64":
        upload_api.request["params"]["arguments"]["content"] = "not-base64"
    elif failure == "field":
        upload_api.env.store.meta = FakeMeta([FakeField("image", read_only=True)], ["image"])
    elif failure == "scope":
        upload_api.env.store.scope = "mcp:read"
    elif failure == "permission":
        upload_api.env.store.insert_error = PermissionDenied()
    else:
        upload_api.env.store.insert_error = ValidationFailed("File validation failed")

    response = upload_api.api.handle()

    code = -32003 if failure in {"scope", "permission"} else -32602
    assert json.loads(response.get_data(as_text=True))["error"]["code"] == code
    assert response.status_code == (403 if code == -32003 else 200)
    assert upload_api.rolled_back == [True]
    assert upload_api.env.store.files == {}


def test_protocol_reuses_upload_when_called_twice(upload_api):
    first = dispatch(upload_api.request, upload_api.api.registered_tools())

    second = dispatch(upload_api.request, upload_api.api.registered_tools())

    assert second == first
    assert len(upload_api.env.store.files) == 1
