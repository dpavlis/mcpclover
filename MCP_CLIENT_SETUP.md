# MCP Client Setup (macOS)

This guide shows how to configure this server for Claude Desktop and other MCP-compatible clients.

## 1) Prepare values

- Server entrypoint: `/Users/david/git/mcpclover/cloverdx_mcp_server.py`
- Python executable: `/Users/david/git/mcpclover/venv/bin/python`
- Example config in this repo: `mcp_config.example.json`

## 2) Claude Desktop (macOS)

Claude Desktop reads MCP servers from:

`~/Library/Application Support/Claude/claude_desktop_config.json`

Use this `mcpServers` block (or copy from `mcp_config.example.json`):

```json
{
  "mcpServers": {
    "cloverdx-mcp-server": {
      "command": "/Users/david/git/mcpclover/venv/bin/python",
      "args": [
        "/Users/david/git/mcpclover/cloverdx_mcp_server.py"
      ],
      "env": {
        "CLOVERDX_BASE_URL": "http://your-cloverdx-host:8083/clover",
        "CLOVERDX_USERNAME": "clover",
        "CLOVERDX_PASSWORD": "clover",
        "CLOVERDX_VERIFY_SSL": "false",
        "CLOVERDX_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Then restart Claude Desktop.

## 3) Other MCP clients

Most MCP clients use the same structure:

- top-level key: `mcpServers`
- each server has: `command`, `args`, optional `env`

If your client uses a different config path, keep the same server block and place it in that client's config file.

## 4) Quick troubleshooting

- If the server does not appear, verify Python path and script path are absolute.
- If login fails, verify `CLOVERDX_BASE_URL`, `CLOVERDX_USERNAME`, and `CLOVERDX_PASSWORD`.
- For HTTPS with self-signed certs, set `CLOVERDX_VERIFY_SSL` to `false`.
- Increase verbosity with `CLOVERDX_LOG_LEVEL=DEBUG`.
