# mcpclover

`mcpclover` is a Python Model Context Protocol (MCP) server for CloverDX.
It lets AI clients (like Claude Desktop) interact with CloverDX Server to browse sandboxes, read and edit graph files, validate graphs, run jobs, and inspect execution/debug output.

## What it includes

- MCP server implementation for CloverDX graph workflows
- SOAP/REST client integration for CloverDX Server operations
- Graph validation utilities
- Local reference resources for CloverDX graph XML, CTL2, and component metadata

## Typical use case

Connect this MCP server to an MCP-compatible client so the model can safely assist with CloverDX development tasks such as graph creation, edits, validation, and execution troubleshooting.

## Quick links

- Setup guide: `MCP_CLIENT_SETUP.md`
- Tool reference: `MCP_TOOLS_README.md`
- Example Claude MCP config: `mcp_config.example.json`
