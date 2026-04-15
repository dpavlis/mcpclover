# MCP Client Setup (macOS and Windows)

This guide covers:

- creating a Python virtual environment (`venv`)
- installing required Python modules
- configuring Claude Desktop to use this MCP server on macOS and Windows

## 1) Create and activate a virtual environment

From the repo root (`mcpclover/`).

macOS:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
```

Windows (PowerShell):

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Windows (Command Prompt):

```bat
py -m venv venv
venv\Scripts\activate.bat
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

From the repo root.

macOS:

```bash
pwd
which python
```

Windows (PowerShell):

```powershell
Get-Location
Get-Command python
```

You will need:

- Python executable: `<repo>/venv/bin/python`
- Server script: `<repo>/cloverdx_mcp_server.py`

Windows equivalents:

- Python executable: `<repo>\\venv\\Scripts\\python.exe`
- Server script: `<repo>\\cloverdx_mcp_server.py`

Example for this workspace:

- Python executable: `/Users/david/git/mcpclover/venv/bin/python`
- Server script: `/Users/david/git/mcpclover/cloverdx_mcp_server.py`

## 4) Add MCP config for Claude Desktop

Claude Desktop reads MCP servers from:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`

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
        "CLOVERDX_SESSION_TIMEOUT": "1500",
        "CLOVERDX_LLM_ALLOW": "false",
        "CLOVERDX_LLM_API_URL": "http://localhost:11434/v1/chat/completions",
        "CLOVERDX_LLM_MODEL": "Qwen35_CTL:latest",
        "CLOVERDX_LLM_TEMPERATURE": "0.2",
        "CLOVERDX_LLM_TOP_P": "0.9",
        "CLOVERDX_LOG_PATH": "/Users/david/git/mcpclover/logs/ctl_tools.log",
        "CLOVERDX_LOG_LEVEL": "INFO",
        "CLOVERDX_SUBAGENT_API_URL": "https://api.openai.com/v1/chat/completions",
        "CLOVERDX_SUBAGENT_MODEL": "gpt-5.4",
        "CLOVERDX_SUBAGENT_API_KEY": "sk-YOUR-KEY-HERE",
        "CLOVERDX_SUBAGENT_TEMPERATURE": "0.2",
        "CLOVERDX_SUBAGENT_MAX_TOKENS": "32768",
        "CLOVERDX_SUBAGENT_TIMEOUT": "240"
      }
    }
  }
}
```

Notes:

- If `claude_desktop_config.json` already has other MCP servers, keep them and only add `cloverdx-mcp-server` under `mcpServers`.
- Keep paths absolute.
- You can copy this from `mcp_config.example.json` and adjust paths/credentials.
- Use a valid OS path for `CLOVERDX_LOG_PATH`.
  - macOS example: `/Users/david/git/mcpclover/logs/ctl_tools.log`
  - Windows example: `C:\\Users\\david\\git\\mcpclover\\logs\\ctl_tools.log`

Environment variable notes:

- Required: `CLOVERDX_BASE_URL`, `CLOVERDX_USERNAME`, `CLOVERDX_PASSWORD`
- Common optional: `CLOVERDX_VERIFY_SSL` (default `false`), `CLOVERDX_LOG_LEVEL` (default `INFO`), `CLOVERDX_SESSION_TIMEOUT` (default `1500` seconds)
- Optional CTL/LLM settings:
  - `CLOVERDX_LLM_ALLOW` enables `validate_CTL`, `generate_CTL`, `run_sub_agent`, and `suggest_components`.
    Enable this only when your configured model endpoint can reliably understand CloverDX CTL2 and produce valid CTL output.
    In practice this usually means a specialized/fine-tuned CTL-capable model.
    Most users should keep this set to `false`.
  - `CLOVERDX_LLM_API_URL`, `CLOVERDX_LLM_MODEL`, `CLOVERDX_LLM_TEMPERATURE`, `CLOVERDX_LLM_TOP_P`
  - `CLOVERDX_LOG_PATH` controls CTL tool file logging path (set empty string to disable file logging)
- Optional sub-agent settings (used by `run_sub_agent` and `suggest_components` when `CLOVERDX_LLM_ALLOW=true`):
  - `CLOVERDX_SUBAGENT_API_URL` — OpenAI-compatible chat completions endpoint (default: `https://api.openai.com/v1/chat/completions`)
  - `CLOVERDX_SUBAGENT_MODEL` — model name to send in requests (default: `gpt-5.4`)
  - `CLOVERDX_SUBAGENT_API_KEY` — API key for the sub-agent endpoint; leave empty for local endpoints (default: `""`)
  - `CLOVERDX_SUBAGENT_TEMPERATURE` — sampling temperature (default: `0.2`)
  - `CLOVERDX_SUBAGENT_MAX_TOKENS` — `max_completion_tokens` cap sent with each request (default: `32768`)
  - `CLOVERDX_SUBAGENT_TIMEOUT` — per-request HTTP timeout in seconds (default: `240`)

Restart Claude Desktop after saving the file.

## 5) IMPORTANT: Install debug DataServices on the target CloverDX server

For the `get_edge_debug_data` MCP tool to work, the target CloverDX server must have two DataServices deployed:

- `debugRead`
- `debugReadCSV`

These are provided in this repository under `data_service/`:

- `data_service/DebugRead.rjob`
- `data_service/DebugReadCSV.rjob`

Install/deploy both jobs as CloverDX DataServices on the target server (same server instance your MCP config points to via `CLOVERDX_BASE_URL`).

Why this is required:

- `get_edge_debug_data` calls `/clover/data-service/debugRead` (JSON) and `/clover/data-service/debugReadCSV` (CSV).
- If those DataServices are not deployed, reading edge debug data from debug runs will fail.

Quick verification after deployment:

- Run a graph with `debug=true`.
- Call `get_edge_debug_data` for one edge.
- If service endpoints are missing, the tool call fails even when debug data was captured.

## 6) IMPORTANT: Create the KB sandbox on the target CloverDX server

The `kb_store`, `kb_search`, and `kb_read` tools persist knowledge-base entries as markdown files inside a dedicated CloverDX sandbox. The sandbox must be installed before those tools can be used.

Create a sandbox named exactly:

```
CLV_MCP_KWBASE
```

Installation steps:

1. Log in to the CloverDX Server web UI.
2. Go to **Sandboxes** → **Add sandbox**.
3. Create a sandbox with code exactly `CLV_MCP_KWBASE`.
4. Unpack the bundled archive from this repository:

```bash
resources/CLV_MCP_KWBASE_sandbox_export.zip
```

5. Upload/move the extracted archive contents into the server sandbox `CLV_MCP_KWBASE`, preserving the folder structure.

This is important because creating the sandbox alone is not sufficient. The bundled content provides the initial knowledge-base/reference material that the LLM and KB tools rely on.

Notes:

- The sandbox name is case-sensitive. `clv_mcp_kwbase` or `CLV_MCP_Kwbase` will not work.
- KB entries are stored as `.md` files under a `kb/` folder inside this sandbox.
- After creating the sandbox, make sure the extracted archive content is actually present on the server in that sandbox before starting the MCP client.
- If the sandbox is missing, any call to `kb_store` will fail with a sandbox-not-found error; `kb_search` and `kb_read` will return empty results.
- If the sandbox exists but the archive content was not uploaded, KB-backed guidance will be incomplete because the initial reference material will be missing.

## 7) Quick local sanity check (optional)

With your venv activated:

```bash
python cloverdx_mcp_server.py
```

If it starts without import errors, dependencies are installed correctly.

## 8) Troubleshooting

- Server not listed in Claude: verify JSON is valid and the config path is exactly `~/Library/Application Support/Claude/claude_desktop_config.json`.
- Import errors: make sure Claude `command` points to `venv/bin/python`, not system Python.
- Authentication failures: re-check `CLOVERDX_BASE_URL`, `CLOVERDX_USERNAME`, `CLOVERDX_PASSWORD`.
- Self-signed HTTPS certs: set `CLOVERDX_VERIFY_SSL` to `false`.
- More logs: set `CLOVERDX_LOG_LEVEL` to `DEBUG`.
- `get_edge_debug_data` fails: confirm `DebugRead.rjob` and `DebugReadCSV.rjob` from `data_service/` are deployed as server DataServices.
- `kb_store` fails / `kb_search` returns nothing: confirm the `CLV_MCP_KWBASE` sandbox exists on the server and that the content from `resources/CLV_MCP_KWBASE_sandbox_export.zip` was unpacked and uploaded into it (see step 6).
- Windows startup issues: verify `command` points to `venv\\Scripts\\python.exe` and that all paths in `args` and `env` use valid Windows absolute paths.

## 9) Maintain `requirements.txt`

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
