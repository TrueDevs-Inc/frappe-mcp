#!/usr/bin/env bash
set -euo pipefail

: "${MCP_ACCESS_TOKEN:?Set MCP_ACCESS_TOKEN without writing it into this file}"

ORIGIN="${MCP_ORIGIN:-https://erp.truedevs.tech}"
MCP_URL="${MCP_URL:-$ORIGIN/api/method/frappe_mcp.api.handle}"
PROTOCOL_VERSION="2025-06-18"

request() {
	local payload="$1"
	curl --fail-with-body --silent --show-error "$MCP_URL" \
		-H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
		-H "Content-Type: application/json" \
		-H "Accept: application/json, text/event-stream" \
		-H "MCP-Protocol-Version: $PROTOCOL_VERSION" \
		--data "$payload"
}

echo "Protected-resource metadata"
curl --fail-with-body --silent --show-error \
	"$ORIGIN/.well-known/oauth-protected-resource" | jq .

echo "Authorization-server metadata"
curl --fail-with-body --silent --show-error \
	"$ORIGIN/.well-known/oauth-authorization-server" | jq .

echo "Initialize"
request '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"frappe-mcp-smoke","version":"1.0"}}}' | jq .

echo "List tools"
request '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | jq .

echo "Call whoami"
request '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"whoami","arguments":{}}}' | jq .
