from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
ToolHandler: TypeAlias = Callable[[Mapping[str, JsonValue]], JsonValue]

PROTOCOL_VERSION: Final = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS: Final = frozenset(
    {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"}
)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_schema: JsonObject
    handler: ToolHandler
    read_only: bool = False
    destructive: bool = False

    def descriptor(self) -> JsonObject:
        annotations: JsonObject = {
            "readOnlyHint": self.read_only,
            "destructiveHint": self.destructive,
        }
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": annotations,
        }


def dispatch(request: Mapping[str, JsonValue], tools: tuple[Tool, ...]) -> JsonObject | None:
    request_id = request.get("id")
    method = request.get("method")
    if request_id is None:
        return None
    if not isinstance(method, str):
        return _error(request_id, -32600, "Invalid Request")

    match method:
        case "initialize":
            params = _mapping(request.get("params"))
            requested = params.get("protocolVersion")
            protocol_version = requested if isinstance(requested, str) else PROTOCOL_VERSION
            if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
                return _error(request_id, -32602, "Unsupported protocol version")
            result: JsonObject = {
                "protocolVersion": protocol_version,
                "serverInfo": {"name": "frappe-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {"listChanged": False}},
            }
            return _success(request_id, result)
        case "ping":
            return _success(request_id, {})
        case "tools/list":
            return _success(request_id, {"tools": [tool.descriptor() for tool in tools]})
        case "tools/call":
            return _call_tool(request_id, _mapping(request.get("params")), tools)
        case _:
            return _error(request_id, -32601, "Method not found")


def _call_tool(
    request_id: JsonValue, params: Mapping[str, JsonValue], tools: tuple[Tool, ...]
) -> JsonObject:
    name = params.get("name")
    arguments = _mapping(params.get("arguments"))
    tool = next((candidate for candidate in tools if candidate.name == name), None)
    if tool is None:
        return _error(request_id, -32602, "Unknown tool")
    if not _matches_schema(arguments, tool.input_schema):
        return _error(request_id, -32602, "Invalid params")

    result = tool.handler(arguments)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    return _success(
        request_id,
        {
            "content": [{"type": "text", "text": text}],
            "structuredContent": result,
        },
    )


def _mapping(value: JsonValue) -> dict[str, JsonValue]:
    if isinstance(value, dict):
        return value
    return {}


def _matches_schema(value: JsonValue, schema: Mapping[str, JsonValue]) -> bool:
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _matches_type(value, expected_type):
        return False
    if isinstance(expected_type, list) and not any(
        isinstance(item, str) and _matches_type(value, item) for item in expected_type
    ):
        return False

    if isinstance(value, dict):
        properties = _mapping(schema.get("properties"))
        required = schema.get("required", [])
        if isinstance(required, list) and any(
            isinstance(item, str) and item not in value for item in required
        ):
            return False
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in value
        ):
            return False
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict) and not _matches_schema(item, child_schema):
                return False

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and any(
            not _matches_schema(item, item_schema) for item in value
        ):
            return False

    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(value, int) and not isinstance(value, bool):
        if isinstance(minimum, int | float) and value < minimum:
            return False
        if isinstance(maximum, int | float) and value > maximum:
            return False
    return True


def _matches_type(value: JsonValue, expected: str) -> bool:
    match expected:
        case "object":
            return isinstance(value, dict)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case "null":
            return value is None
        case _:
            return False


def _success(request_id: JsonValue, result: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: JsonValue, code: int, message: str) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
