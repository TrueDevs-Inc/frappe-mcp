from __future__ import annotations

from collections.abc import Mapping

from frappe_mcp.protocol import JsonValue, Tool, dispatch


def echo(arguments: Mapping[str, JsonValue]) -> JsonValue:
    return {"echo": arguments.get("value")}


TOOLS = (
    Tool(
        name="echo",
        description="Return the supplied value.",
        input_schema={
            "type": "object",
            "properties": {"value": {}},
            "additionalProperties": False,
        },
        handler=echo,
        read_only=True,
    ),
)


def require_object(value: JsonValue | None) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    return value


def test_initialize_negotiates_supported_protocol() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"},
    }

    response = require_object(dispatch(request, TOOLS))
    result = require_object(response["result"])

    assert response["id"] == 1
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}


def test_initialize_negotiates_chatgpt_protocol() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25"},
    }

    response = require_object(dispatch(request, TOOLS))
    result = require_object(response["result"])

    assert result["protocolVersion"] == "2025-11-25"


def test_tools_list_exposes_schema_and_annotations() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": "tools",
        "method": "tools/list",
        "params": {},
    }

    response = require_object(dispatch(request, TOOLS))
    result = require_object(response["result"])

    assert result["tools"] == [
        {
            "name": "echo",
            "description": "Return the supplied value.",
            "inputSchema": {
                "type": "object",
                "properties": {"value": {}},
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        }
    ]


def test_write_tools_expose_action_annotations() -> None:
    create_tool = Tool(
        name="create_document",
        description="Create a document.",
        input_schema={"type": "object"},
        handler=echo,
    )
    delete_tool = Tool(
        name="delete_document",
        description="Delete a document.",
        input_schema={"type": "object"},
        handler=echo,
        destructive=True,
    )

    assert create_tool.descriptor()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
    }
    assert delete_tool.descriptor()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
    }


def test_initialize_rejects_unsupported_protocol() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"},
    }

    response = require_object(dispatch(request, TOOLS))

    assert response["error"] == {"code": -32602, "message": "Unsupported protocol version"}


def test_tools_call_returns_structured_and_text_content() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"value": "hello"}},
    }

    response = require_object(dispatch(request, TOOLS))
    result = require_object(response["result"])

    assert result["structuredContent"] == {"echo": "hello"}
    assert result["content"] == [{"type": "text", "text": '{"echo":"hello"}'}]


def test_unknown_method_returns_json_rpc_error() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "missing",
        "params": {},
    }

    response = require_object(dispatch(request, TOOLS))

    assert response["error"] == {"code": -32601, "message": "Method not found"}


def test_tool_arguments_are_validated_before_handler_runs() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"unexpected": True}},
    }

    response = require_object(dispatch(request, TOOLS))

    assert response["error"] == {"code": -32602, "message": "Invalid params"}


def test_notification_returns_no_response() -> None:
    request: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }

    response = dispatch(request, TOOLS)

    assert response is None
