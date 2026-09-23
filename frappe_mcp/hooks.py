app_name = "frappe_mcp"
app_title = "Frappe MCP"
app_publisher = "TrueDevs"
app_description = "Permission-aware MCP server for Frappe v15"
app_email = "engineering@truedevs.tech"
app_license = "MIT"

auth_hooks = ["frappe_mcp.auth.validate_mcp_bearer"]
