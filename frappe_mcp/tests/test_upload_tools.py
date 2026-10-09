from __future__ import annotations

import base64

import pytest

from frappe_mcp.tests.upload_fakes import (
    FakeField,
    FakeMeta,
    PermissionDenied,
    ValidationFailed,
    upload_arguments,
)
from frappe_mcp.tests.upload_fakes import upload_env as upload_env


@pytest.mark.parametrize("is_private", [True, False])
@pytest.mark.parametrize("fieldtype", ["Attach", "Attach Image"])
def test_upload_creates_native_file_when_target_is_writable(upload_env, is_private, fieldtype):
    upload_env.store.meta = FakeMeta([FakeField("image", fieldtype)], ["image"])
    arguments = upload_arguments(is_private=is_private)

    result = upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == [
        {
            "doctype": "File",
            "file_name": "example.png",
            "content": base64.b64decode(arguments["content"]),
            "is_private": int(is_private),
            "attached_to_doctype": "Lead",
            "attached_to_name": "LEAD-1",
            "attached_to_field": "image",
        }
    ]
    assert upload_env.store.events == ["target_write", "construct_file", "insert"]
    assert result == {
        "name": "FILE-1",
        "file_name": "example.png",
        "file_url": ("/private/files/" if is_private else "/files/") + "example.png",
        "is_private": int(is_private),
        "attached_to_doctype": "Lead",
        "attached_to_name": "LEAD-1",
        "attached_to_field": "image",
        "content_hash": upload_env.store.files["FILE-1"].get("content_hash"),
    }


@pytest.mark.parametrize(
    "content",
    [
        "",
        " ",
        "%%%%",
        "YQ",
        "YQ===",
        "YQ==\n",
        "YR==",
        "====",
        "éééé",
        "data:image/png;base64,YQ==",
        "https://example.com/file",
        "http://example.com/file",
        "/etc/passwd",
        "../file",
        "file:///etc/passwd",
        "__8=",
        12,
        None,
    ],
)
def test_upload_rejects_content_when_not_strict_standard_base64(upload_env, content):
    arguments = upload_arguments(content=content)

    with pytest.raises(ValueError):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


@pytest.mark.parametrize("size", [5 * 1024 * 1024 + 1, 5 * 1024 * 1024 + 3])
def test_upload_rejects_content_when_decoded_limit_exceeded(upload_env, size):
    arguments = upload_arguments(content=base64.b64encode(b"x" * size).decode("ascii"))

    with pytest.raises(ValueError, match="5 MiB"):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


def test_upload_accepts_content_when_at_decoded_limit(upload_env):
    content = b"x" * (5 * 1024 * 1024)
    arguments = upload_arguments(content=base64.b64encode(content).decode("ascii"))

    upload_env.module.upload_file(arguments)

    assert upload_env.store.files["FILE-1"].get_content() == content


@pytest.mark.parametrize(
    "file_name",
    [
        "",
        ".",
        "..",
        "../x",
        "dir/x",
        "dir\\x",
        "C:\\x",
        "/x",
        "a\x00b",
        "a\nb",
        "https://host/x",
        "file:///tmp/x",
        " x",
        "x ",
        "x.",
        "a:b",
    ],
)
def test_upload_rejects_filename_when_unsafe(upload_env, file_name):
    arguments = upload_arguments(file_name=file_name)

    with pytest.raises(ValueError):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


@pytest.mark.parametrize(
    "key", ["target_doctype", "target_name", "target_field", "file_name", "content", "is_private"]
)
def test_upload_rejects_arguments_when_required_key_missing(upload_env, key):
    arguments = upload_arguments()
    arguments.pop(key)

    with pytest.raises(ValueError):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


@pytest.mark.parametrize(
    "extra",
    [
        "owner",
        "name",
        "doctype",
        "ignore_permissions",
        "file_url",
        "url",
        "path",
        "file_path",
        "attached_to_doctype",
        "attached_to_name",
        "attached_to_field",
        "decode",
    ],
)
def test_upload_rejects_arguments_when_extra_input_supplied(upload_env, extra):
    arguments = upload_arguments(**{extra: "forbidden"})

    with pytest.raises(ValueError):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


@pytest.mark.parametrize("is_private", [None, 0, 1, "true"])
def test_upload_rejects_privacy_when_not_boolean(upload_env, is_private):
    arguments = upload_arguments(is_private=is_private)

    with pytest.raises(ValueError):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


@pytest.mark.parametrize("key", ["target_doctype", "target_name", "target_field"])
@pytest.mark.parametrize("value", ["", None, 1])
def test_upload_rejects_target_when_not_nonempty_string(upload_env, key, value):
    arguments = upload_arguments(**{key: value})

    with pytest.raises(ValueError):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


@pytest.mark.parametrize("overrides", [{"target_doctype": "Missing"}, {"target_name": "MISSING"}])
def test_upload_rejects_target_when_missing(upload_env, overrides):
    arguments = upload_arguments(**overrides)

    with pytest.raises(ValidationFailed):
        upload_env.module.upload_file(arguments)

    assert upload_env.store.constructed == []


@pytest.mark.parametrize(
    "meta",
    [
        FakeMeta([], []),
        FakeMeta([FakeField("image", "Data")], ["image"]),
        FakeMeta([FakeField("image", "Table", "Child")], ["image"]),
        FakeMeta([FakeField("image", "Attach", read_only=True)], ["image"]),
        FakeMeta([FakeField("image", "Attach", permlevel=1)], []),
    ],
)
def test_upload_rejects_field_when_missing_wrong_type_or_unwritable(upload_env, meta):
    upload_env.store.meta = meta

    with pytest.raises(upload_env.module.WriteFieldError):
        upload_env.module.upload_file(upload_arguments())

    assert upload_env.store.constructed == []


@pytest.mark.parametrize("denial", ["scope", "target", "file"])
def test_upload_rejects_request_when_permission_denied(upload_env, denial):
    if denial == "scope":
        upload_env.store.scope = "mcp:read"
    elif denial == "target":
        upload_env.store.target_allowed = False
    else:
        upload_env.store.insert_error = PermissionDenied()

    with pytest.raises(PermissionDenied):
        upload_env.module.upload_file(upload_arguments())

    assert upload_env.store.files == {}
    if denial != "file":
        assert upload_env.store.constructed == []
