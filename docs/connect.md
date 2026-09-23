# Connect Claude or ChatGPT

Use the full public MCP endpoint supplied by your administrator. For the
TrueDevs ERP deployment it is:

```text
https://erp.truedevs.tech/api/method/frappe_mcp.api.handle
```

## What happens when you connect

1. Claude or ChatGPT opens the ERP login page.
2. Sign in with your normal ERP account and complete two-factor authentication
   if it is enabled.
3. Approve the requested MCP access.
4. The client receives an MCP-only token tied to your ERP user.

The client does not receive your ERP password. Every tool call still follows
your Frappe roles, User Permissions, workflows, and document permissions.

## Claude

1. Open **Customize → Connectors**.
2. Select **+ → Add custom connector**.
3. Enter a name and the full HTTPS MCP endpoint.
4. If your administrator supplied an OAuth Client ID and Client Secret, enter
   them under **Advanced settings**.
5. Select **Add**, then **Connect**.
6. Sign in to ERP and approve access.

For Team and Enterprise organizations, an Owner first adds the connector under
**Organization settings → Connectors → Add → Custom → Web**. Each user then
connects their own ERP account from **Customize → Connectors**.

Claude's documented callback URLs are:

```text
https://claude.ai/api/mcp/auth_callback
https://claude.com/api/mcp/auth_callback
```

## ChatGPT

Custom remote MCP apps currently require a supported ChatGPT plan and workspace
configuration. Full MCP, including write tools, is documented for Business and
Enterprise/Edu. Pro supports more limited read/fetch connections.

1. In ChatGPT web, open **Settings → Security and login**.
2. Enable **Developer mode** if your workspace allows it.
3. Open **Apps** or **ChatGPT Plugins**, then select **+**.
4. Enter the full HTTPS MCP endpoint and choose OAuth.
5. Create the app and complete the ERP sign-in when prompted.
6. Wait for the tool scan, then add the app to a new conversation.

If access expires, open the app under **Settings → Apps/Plugins** and choose
**Reconnect**. If that option is absent, disconnect and connect again.

## Disconnect

Disconnect the app in Claude or ChatGPT. An ERP administrator can also revoke
the corresponding MCP token or disable the OAuth client.

## Official references

- [OpenAI: Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [OpenAI: Developer mode and MCP apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
- [Anthropic: Custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
