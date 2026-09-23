# Frappe MCP

A permission-aware remote Model Context Protocol server for Frappe v15.

Each person connects with their own Frappe account. The server issues MCP-only
tokens and executes tools under that person's normal Frappe roles and User
Permissions. Client applications never receive the person's ERP password.

## Endpoints

- MCP: `/api/method/frappe_mcp.api.handle`
- Authorization: `/api/method/frappe_mcp.oauth.authorize`
- Token exchange: `/api/method/frappe_mcp.oauth.token`
- Protected-resource metadata: `/.well-known/oauth-protected-resource`
- Authorization-server metadata: `/.well-known/oauth-authorization-server`

## Install

```bash
cd /home/frappe/frappe-bench
bench get-app https://github.com/TrueDevs-Inc/frappe-mcp.git
bench --site your-site.example install-app frappe_mcp
bench --site your-site.example set-config frappe_mcp_enabled true
bench --site your-site.example migrate
bench build --app frappe_mcp
```

The two `/.well-known` URLs must be routed to the corresponding Frappe methods
by the site's reverse proxy. See [`docs/operations.md`](docs/operations.md).

## Connect

See [`docs/connect.md`](docs/connect.md) for Claude and ChatGPT setup.

## Security

- Tokens are accepted only by the MCP endpoint.
- Authorization codes and access tokens are stored as hashes.
- Authorization Code with PKCE S256 is mandatory.
- The OAuth `resource` must exactly match the configured MCP endpoint.
- Frappe permissions are re-applied to every tool call.

This project is experimental. Test with non-administrator accounts and harmless
records before enabling it for production workflows.

Write tools are hidden and `mcp:write` authorization is rejected unless an
operator explicitly sets `frappe_mcp_write_enabled` to `true`. Keep the default
read-only mode until cross-user permission tests pass.
