# MCP Client Setup (macOS)

This guide covers:

- creating a Python virtual environment (`venv`)
- installing required Python modules
- configuring Claude Desktop to use this MCP server

## 1) Create and activate a virtual environment

From the repo root (`mcpclover/`):

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
```

## 2) Install required Python modules

Install from the pinned dependency list:

```bash
pip install -r requirements.txt
```

Equivalent direct install command (same packages):

```bash
pip install mcp zeep requests python-dotenv urllib3
```

## 3) Confirm absolute paths you will use in Claude config

From the repo root:

```bash
pwd
which python
```

You will need:

- Python executable: `<repo>/venv/bin/python`
- Server script: `<repo>/cloverdx_mcp_server.py`

Example for this workspace:

- Python executable: `/Users/david/git/mcpclover/venv/bin/python`
- Server script: `/Users/david/git/mcpclover/cloverdx_mcp_server.py`

## 4) Add MCP config for Claude Desktop

On macOS, Claude Desktop reads MCP servers from:

`~/Library/Application Support/Claude/claude_desktop_config.json`

If the file does not exist, create it. Add/merge this `mcpServers` block:

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

Notes:

- If `claude_desktop_config.json` already has other MCP servers, keep them and only add `cloverdx-mcp-server` under `mcpServers`.
- Keep paths absolute.
- You can copy this from `mcp_config.example.json` and adjust paths/credentials.

Restart Claude Desktop after saving the file.

## 5) Quick local sanity check (optional)

With your venv activated:

```bash
python cloverdx_mcp_server.py
```

If it starts without import errors, dependencies are installed correctly.

## 6) Troubleshooting

- Server not listed in Claude: verify JSON is valid and the config path is exactly `~/Library/Application Support/Claude/claude_desktop_config.json`.
- Import errors: make sure Claude `command` points to `venv/bin/python`, not system Python.
- Authentication failures: re-check `CLOVERDX_BASE_URL`, `CLOVERDX_USERNAME`, `CLOVERDX_PASSWORD`.
- Self-signed HTTPS certs: set `CLOVERDX_VERIFY_SSL` to `false`.
- More logs: set `CLOVERDX_LOG_LEVEL` to `DEBUG`.

## 7) Maintain `requirements.txt`

When you add or upgrade Python packages in this venv, refresh `requirements.txt`:

```bash
source venv/bin/activate
pip install <new-package>
pip freeze > requirements.txt
```

To upgrade all currently listed dependencies, then re-freeze:

```bash
source venv/bin/activate
pip install --upgrade -r requirements.txt
pip freeze > requirements.txt
```
