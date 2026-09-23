# Operations

## Required site configuration

```bash
bench --site your-site.example set-config frappe_mcp_enabled true
bench --site your-site.example set-config frappe_mcp_resource \
  https://your-site.example/api/method/frappe_mcp.api.handle
bench --site your-site.example set-config frappe_mcp_issuer \
  https://your-site.example
```

Restart the web workers after changing configuration.

The server is read-only by default. Do not enable write tools until the
two-user permission tests pass. Enabling them is explicit:

```bash
bench --site your-site.example set-config frappe_mcp_write_enabled true
```

## Discovery routes

Route these public paths through the reverse proxy:

| Public path | Frappe method |
| --- | --- |
| `/.well-known/oauth-protected-resource` | `/api/method/frappe_mcp.discovery.protected_resource` |
| `/.well-known/oauth-authorization-server` | `/api/method/frappe_mcp.discovery.authorization_server` |

Both responses must be reachable without authentication over HTTPS.

## Deployment

Before installation, take a site backup. Install a reviewed commit rather than
an unpinned branch when operating a production site.

```bash
cd /home/frappe/frappe-bench
bench --site your-site.example backup --with-files --compress
bench get-app https://github.com/TrueDevs-Inc/frappe-mcp.git
bench --site your-site.example install-app frappe_mcp
bench --site your-site.example migrate
bench build --app frappe_mcp
sudo supervisorctl restart frappe-bench-web:
```

## Release checks

Before enabling business use:

1. Confirm both discovery documents over HTTPS.
2. Complete OAuth with a non-administrator user.
3. Call `initialize`, `tools/list`, and `whoami` through the MCP endpoint.
4. Verify a second user cannot read or modify the first user's restricted data.
5. Verify expired and revoked tokens return `401`.
6. Verify a token is rejected on every non-MCP Frappe API endpoint.

The repository includes a GPT-like HTTP smoke client for steps 1 through 3:

```bash
read -rsp 'MCP access token: ' MCP_ACCESS_TOKEN
export MCP_ACCESS_TOKEN
scripts/mcp-smoke.sh
unset MCP_ACCESS_TOKEN
```

The script reads the token from the environment and never prints it.

## Emergency disable

```bash
bench --site your-site.example set-config frappe_mcp_enabled false
sudo supervisorctl restart frappe-bench-web:
```

Disabling tool dispatch does not revoke existing tokens. Revoke token records or
disable the relevant `Frappe MCP OAuth Client` when credentials are compromised.
