from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace

import pytest

from frappe_mcp.tests.upload_fakes import upload_arguments
from frappe_mcp.tests.upload_fakes import upload_env as upload_env


def test_native_file_transforms_jpeg_when_exif_stripping_enabled(
    upload_env: SimpleNamespace,
) -> None:
    upload_env.store.strip_exif_enabled = True
    doc = upload_env.store.get_doc(
        {
            "doctype": "File",
            "file_name": "camera.jpg",
            "is_private": 1,
            "content": b"\xff\xd8EXIF:camera;pixels\xff\xd9",
        }
    )

    doc.insert()

    assert doc.get_content() == b"\xff\xd8pixels\xff\xd9"
    assert (
        doc.get("content_hash")
        == hashlib.md5(
            b"\xff\xd8pixels\xff\xd9",
            usedforsecurity=False,
        ).hexdigest()
    )


@pytest.mark.parametrize("file_name", ["camera.jpg", "camera.jpeg", "camera.JPG"])
@pytest.mark.parametrize("is_private", [True, False])
def test_upload_reuses_jpeg_when_native_file_strips_exif(
    upload_env: SimpleNamespace,
    file_name: str,
    is_private: bool,
) -> None:
    upload_env.store.strip_exif_enabled = True
    arguments = upload_arguments(
        file_name=file_name,
        is_private=is_private,
        content=base64.b64encode(b"\xff\xd8EXIF:camera;pixels\xff\xd9").decode("ascii"),
    )
    original = upload_env.module.upload_file(arguments)

    result = upload_env.module.upload_file(arguments)

    assert result == original
    assert len(upload_env.store.files) == 1
    assert upload_env.store.files[original["name"]].get_content() == b"\xff\xd8pixels\xff\xd9"


@pytest.mark.parametrize("file_name,enabled", [("camera.jpg", False), ("camera.png", True)])
def test_upload_preserves_bytes_when_native_exif_transform_is_inactive(
    upload_env: SimpleNamespace,
    file_name: str,
    enabled: bool,
) -> None:
    upload_env.store.strip_exif_enabled = enabled
    arguments = upload_arguments(
        file_name=file_name,
        content=base64.b64encode(b"\xff\xd8EXIF:camera;pixels\xff\xd9").decode("ascii"),
    )

    result = upload_env.module.upload_file(arguments)

    assert (
        upload_env.store.files[result["name"]].get_content()
        == b"\xff\xd8EXIF:camera;pixels\xff\xd9"
    )


def test_upload_reuses_file_when_target_field_privacy_and_bytes_match(upload_env):
    original = upload_env.module.upload_file(upload_arguments())
    upload_env.store.events.clear()

    result = upload_env.module.upload_file(upload_arguments(file_name="renamed.png"))

    assert result == original
    assert upload_env.store.events == ["target_write", "read_content"]
    assert len(upload_env.store.files) == 1
    assert upload_env.store.queries[-1] == {
        "attached_to_doctype": "Lead",
        "attached_to_name": "LEAD-1",
        "attached_to_field": "image",
        "is_private": 1,
        "content_hash": original["content_hash"],
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"attached_to_doctype": "Other"},
        {"attached_to_name": "LEAD-2"},
        {"attached_to_field": "other_image"},
        {"is_private": 0},
        {"content_hash": "different hash"},
    ],
)
def test_upload_preserves_file_when_not_exact_attachment_match(upload_env, changed):
    upload_env.module.upload_file(upload_arguments())
    existing = upload_env.store.files["FILE-1"]
    existing.values.update(changed)
    snapshot = dict(existing.values)

    result = upload_env.module.upload_file(upload_arguments())

    assert result["name"] == "FILE-2"
    assert existing.values == snapshot
    assert len(upload_env.store.files) == 2


@pytest.mark.parametrize("invalid", ["missing", "different_bytes", "remote", "privacy_url"])
def test_upload_creates_file_when_hash_match_has_invalid_content(upload_env, invalid):
    upload_env.module.upload_file(upload_arguments())
    existing = upload_env.store.files["FILE-1"]
    if invalid == "missing":
        existing.present = False
    elif invalid == "different_bytes":
        existing.values["content"] = b"different bytes"
    elif invalid == "remote":
        existing.values["file_url"] = "https://example.com/file"
    else:
        existing.values["file_url"] = "/files/public.png"
    snapshot = dict(existing.values)
    upload_env.store.events.clear()

    result = upload_env.module.upload_file(upload_arguments())

    assert result["name"] == "FILE-2"
    assert existing.values == snapshot
    if invalid != "different_bytes":
        assert "read_content" not in upload_env.store.events


def test_upload_reuses_text_file_when_native_content_is_string(upload_env):
    original = upload_env.module.upload_file(upload_arguments(content="YQ=="))
    upload_env.store.files["FILE-1"].values["content"] = "a"

    result = upload_env.module.upload_file(upload_arguments(content="YQ=="))

    assert result == original


def test_upload_checks_target_permission_when_duplicate_exists(upload_env):
    upload_env.module.upload_file(upload_arguments())
    upload_env.store.target_allowed = False
    upload_env.store.events.clear()

    with pytest.raises(upload_env.frappe.PermissionError):
        upload_env.module.upload_file(upload_arguments())

    assert upload_env.store.events == ["target_write"]
