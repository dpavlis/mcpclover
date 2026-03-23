#!/usr/bin/env python3
"""
CloverDX MCP Server
==================================
A Model Context Protocol server that enables an LLM to create and modify
CloverDX transformation graphs.  It connects to a CloverDX Server via SOAP
WebServices and exposes the following tools:

  File / sandbox operations
  ─────────────────────────
  list_sandboxes          – List all available sandboxes on the server
  list_files              – List files/folders inside a sandbox directory
  find_file               – Find files in a sandbox using * and ? wildcards
  grep_files              – Search file contents in a sandbox for a string (like grep -r)
  list_linked_assets      – List externalized/linkable assets by known file types
  get_sandbox_parameters  – Read/resolve sandbox parameters from workspace.prm (+ optional server overlays)
    read_file               – Download a file or byte range (graph, metadata, params, …)
  rename_file             – Rename a file within a sandbox (RenameSandboxFile)
  copy_file               – Copy a file within/across sandboxes
  patch_file              – Patch a sandbox file using anchor-based line ranges
  write_file              – Upload / overwrite a file
  delete_file             – Delete a file from a sandbox

  Resource access
  ───────────────
  list_resources          – List available resource URIs with names and descriptions
  read_resource           – Fetch the content of a resource by URI
  get_workflow_guide      – Return the authoritative workflow guide for a CloverDX task

  Graph operations
  ────────────────
  validate_graph          – Two-stage validation (local XML + server checkConfig)
  execute_graph           – Run a graph and wait for completion
  list_graph_runs         – List recent executions (REST /executions endpoint)
  get_graph_run_status    – Check the status of a single run by run ID
  get_graph_execution_log – Fetch the execution log for a run
  get_graph_tracking      – Fetch graph tracking metrics for a run
  get_edge_debug_info     – List edge debug availability/details for a run edge
  get_edge_debug_metadata – Fetch edge debug metadata XML for a run edge
  get_edge_debug_data     – Fetch edge debug data summary for a run edge
  set_graph_element_attribute – Set/replace an attribute or <attr> child on a graph element (DOM-based)

  Component reference (local, no server round-trip)
  ──────────────────────────────────────────────────
  list_components         – List available component types (by category)
  get_component_info      – Get ports & properties for a component type/name
  get_component_details   – Fetch detailed markdown docs for a complex component

Resources exposed
─────────────────
  cloverdx://reference/graph-xml   – cloverdx-llm-reference.md
  cloverdx://reference/ctl2        – CTL2_Reference_for_LLM_compact.md
    cloverdx://reference/subgraphs   – CLOVERDX_SUBGRAPHS.md
  cloverdx://reference/components  – components.json (non-deprecated)

Configuration (.env)
────────────────────
  CLOVERDX_BASE_URL   http://host:port/clover
  CLOVERDX_USERNAME   clover
  CLOVERDX_PASSWORD   clover
  CLOVERDX_VERIFY_SSL false   (optional, default false)

Dependencies
────────────
  pip install mcp zeep requests python-dotenv urllib3
"""

import asyncio
import glob as _glob
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import urllib3
from dotenv import load_dotenv
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types
from cloverdx_graph_validator import GraphValidator
from cloverdx_soap_client import CloverDXSoapClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Logging ────────────────────────────────────────────────────────────────────
# Log level is controlled by CLOVERDX_LOG_LEVEL (DEBUG | INFO | WARNING | ERROR).
# Default is INFO.  Set to DEBUG to see full tool arguments and response sizes.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SERVER_NAME    = "cloverdx-mcp-server"
SERVER_VERSION = "1.0.0"

POLL_TIMEOUT_S  = 120
SERVER_WAIT_MS  = 10_000
EXEC_POLL_S     = 2      # seconds between execution status polls

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Stage 1 validator (copied from validate_graph.py) ─────────────────────────



# ── Component Catalog ──────────────────────────────────────────────────────────

class ComponentCatalog:
    """In-memory index over components.json."""

    def __init__(self, json_path: str):
        self._path       = json_path
        self._components: List[Dict] = []
        self._by_type:    Dict[str, Dict] = {}
        self._by_name_lower: Dict[str, Dict] = {}
        self._by_category:   Dict[str, List[Dict]] = {}

    def load(self):
        with open(self._path, encoding="utf-8") as f:
            self._components = json.load(f)
        for comp in self._components:
            t = (comp.get("type") or "").upper()
            n = (comp.get("name") or "").lower()
            c = (comp.get("category") or "").lower()
            if t:
                self._by_type[t] = comp
            if n:
                self._by_name_lower[n] = comp
            self._by_category.setdefault(c, []).append(comp)

    def _is_deprecated(self, comp: Dict) -> bool:
        return (comp.get("category") or "").lower() == "deprecated"

    def search(self, query: str, include_deprecated: bool = False) -> List[Dict]:
        q_upper = query.strip().upper()
        q_lower = query.strip().lower()

        # 1. Exact type match
        if q_upper in self._by_type:
            comp = self._by_type[q_upper]
            if include_deprecated or not self._is_deprecated(comp):
                return [comp]

        # 2. Exact name match
        if q_lower in self._by_name_lower:
            comp = self._by_name_lower[q_lower]
            if include_deprecated or not self._is_deprecated(comp):
                return [comp]

        # 3. Substring match
        results = []
        for comp in self._components:
            if not include_deprecated and self._is_deprecated(comp):
                continue
            if (q_lower in (comp.get("type")  or "").lower() or
                    q_lower in (comp.get("name") or "").lower()):
                results.append(comp)
            if len(results) >= 5:
                break
        return results

    def list_by_category(self, category: Optional[str] = None) -> List[Dict]:
        if category:
            return [c for c in self._by_category.get(category.lower(), [])
                    if not self._is_deprecated(c)]
        return [c for c in self._components if not self._is_deprecated(c)]

    @staticmethod
    def format_component(comp: Dict) -> str:
        """Format a single component for display."""
        lines = [
            f"Type:        {comp.get('type', '')}",
            f"Name:        {comp.get('name', '')}",
            f"Category:    {comp.get('category', '')}",
            f"Description: {comp.get('description') or comp.get('shortDescription', '')}",
            "",
        ]

        in_ports  = comp.get("inputPorts",  []) or []
        out_ports = comp.get("outputPorts", []) or []
        if in_ports:
            lines.append("Input Ports:")
            for p in in_ports:
                req = "required" if p.get("required") else "optional"
                lines.append(f"  [{p.get('name', '')}] {p.get('label', '')} ({req})")
        if out_ports:
            lines.append("Output Ports:")
            for p in out_ports:
                req = "required" if p.get("required") else "optional"
                lines.append(f"  [{p.get('name', '')}] {p.get('label', '')} ({req})")

        properties = comp.get("properties", []) or []
        if properties:
            lines.append("")
            lines.append("Properties:")
            for prop in properties:
                req  = " *required*" if prop.get("required") else ""
                dval = f"  (default: {prop['defaultValue']})" if prop.get("defaultValue") else ""
                desc = (prop.get("description") or "")[:100]
                lines.append(f"  {prop.get('name', '')}{req}: [{prop.get('type', '')}]{dval}  {desc}")
                if prop.get("type") == "enum" and prop.get("values"):
                    vals = ", ".join(v.get("value", "") for v in prop["values"] if isinstance(v, dict))
                    lines.append(f"    values: {vals}")

        return "\n".join(lines)

    @staticmethod
    def format_compact(comps: List[Dict]) -> str:
        """Compact listing for multiple results."""
        rows = ["Type | Name | Category | Description"]
        rows.append("-" * 80)
        for c in comps:
            desc = c.get("description") or c.get("shortDescription") or ""
            rows.append(
                f"{c.get('type', '')} | {c.get('name', '')} | {c.get('category', '')} | {desc}"
            )
        return "\n".join(rows)


# ── comp_details scanner ───────────────────────────────────────────────────────

def _scan_comp_details(comp_details_dir: str) -> Dict[str, str]:
    """Return a dict mapping uppercase component type to its .md file path."""
    result: Dict[str, str] = {}
    if not os.path.isdir(comp_details_dir):
        return result
    for md_path in _glob.glob(os.path.join(comp_details_dir, "*.md")):
        basename = os.path.splitext(os.path.basename(md_path))[0].upper()
        result[basename] = md_path
    return result


# ── Graph parameter helpers ────────────────────────────────────────────────────

def _parse_graph_params(xml_text: str):
    """
    Extract <GraphParameter> elements from graph XML.
    Returns:
      with_value : dict[name -> default_value]  — params that have a non-empty default
      no_value   : list[name]                   — params with no default (must be supplied)
    """
    with_value: Dict[str, str] = {}
    no_value:   List[str]      = []
    try:
        root      = ET.fromstring(xml_text)
        global_el = root.find("Global")
        if global_el is not None:
            params_el = global_el.find("GraphParameters")
            if params_el is not None:
                for param in params_el.findall("GraphParameter"):
                    name  = param.get("name")
                    value = param.get("value")
                    if not name:
                        continue
                    if value is not None and value != "":
                        with_value[name] = value
                    else:
                        no_value.append(name)
    except Exception:
        pass
    return with_value, no_value


_PARAM_REF_RE = re.compile(r"\$\{([^}]+)\}")


def _parse_workspace_prm_xml(xml_text: str) -> tuple[Dict[str, str], Dict[str, str]]:
    """
    Parse workspace.prm XML in CloverDX GraphParameters format.
    Returns:
      params:       dict[name -> value]
      descriptions: dict[name -> description text]
    """
    params: Dict[str, str] = {}
    descriptions: Dict[str, str] = {}

    root = ET.fromstring(xml_text)
    for param in root.findall(".//GraphParameter"):
        name = (param.get("name") or "").strip()
        if not name:
            continue
        params[name] = str(param.get("value") or "")

        for attr in param.findall("attr"):
            if (attr.get("name") or "").strip() == "description":
                desc = (attr.text or "").strip()
                if desc:
                    descriptions[name] = desc
                break

    return params, descriptions


def _resolve_parameter_references(params: Dict[str, str], max_passes: int = 12) -> tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Resolve ${PARAM_NAME} references against provided parameter dictionary.
    Returns:
      resolved_params, unresolved_refs (param -> missing referenced names)
    """
    resolved = dict(params)

    for _ in range(max_passes):
        changed = False
        for key, value in list(resolved.items()):
            if not isinstance(value, str) or "${" not in value:
                continue

            def _replace(match: re.Match[str]) -> str:
                ref_name = match.group(1)
                ref_value = resolved.get(ref_name)
                return str(ref_value) if ref_value is not None else match.group(0)

            updated = _PARAM_REF_RE.sub(_replace, value)
            if updated != value:
                resolved[key] = updated
                changed = True

        if not changed:
            break

    unresolved: Dict[str, List[str]] = {}
    for key, value in resolved.items():
        if not isinstance(value, str):
            continue
        refs = [m.group(1) for m in _PARAM_REF_RE.finditer(value)]
        if refs:
            unresolved[key] = sorted(set(refs))

    return resolved, unresolved


# ── Singletons ─────────────────────────────────────────────────────────────────

soap_client:       Optional[CloverDXSoapClient] = None
component_catalog: Optional[ComponentCatalog]   = None
_comp_details_map: Dict[str, str]               = {}
_reference_cache:  Dict[str, str]               = {}


def get_soap_client() -> CloverDXSoapClient:
    if soap_client is None:
        raise RuntimeError("SOAP client not initialized")
    return soap_client


def get_catalog() -> ComponentCatalog:
    if component_catalog is None:
        raise RuntimeError("Component catalog not initialized")
    return component_catalog


def _load_reference(uri_key: str, file_path: str) -> str:
    if uri_key not in _reference_cache:
        try:
            with open(file_path, encoding="utf-8") as f:
                _reference_cache[uri_key] = f.read()
        except FileNotFoundError:
            _reference_cache[uri_key] = f"[Reference file not found: {file_path}]"
    return _reference_cache[uri_key]


# ── MCP Server ─────────────────────────────────────────────────────────────────

app = Server(SERVER_NAME)

# ── Resource Registry ─────────────────────────────────────────────────────────
# Single source of truth for all exposed resources.  To add a new resource:
#   1. Add an entry here (uri → name / description / mimeType).
#   2. Handle its URI in handle_read_resource() below.
# The list_resources *tool* reads this dict automatically, so the tool output
# stays in sync with whatever is registered here.
_RESOURCE_REGISTRY: Dict[str, Dict[str, str]] = {
    "cloverdx://reference/graph-xml": {
        "name":        "CloverDX Graph XML Reference",
        "description": "Authoritative guide for creating CloverDX transformation graph XML (.grf files)",
        "mimeType":    "text/markdown",
    },
    "cloverdx://reference/ctl2": {
        "name":        "CloverDX CTL2 Transformation Language Reference",
        "description": "Authoritative reference for CTL2, the scripting language used inside CloverDX transformations",
        "mimeType":    "text/markdown",
    },
    "cloverdx://reference/subgraphs": {
        "name":        "CloverDX Subgraphs Reference",
        "description": "Authoritative reference for CloverDX subgraphs.",
        "mimeType":    "text/markdown",
    },
    # "cloverdx://reference/components": {
    #     "name":        "CloverDX Component Catalog",
    #     "description": "All available CloverDX component types with their ports and properties (non-deprecated)",
    #     "mimeType":    "application/json",
    # },
}

_WORKFLOW_GUIDE_FILES: Dict[str, str] = {
    "create_graph": os.path.join(_SCRIPT_DIR, "resources/workflow_create_graph.md"),
    "edit_graph": os.path.join(_SCRIPT_DIR, "resources/workflow_edit_graph.md"),
    "validate_and_run": os.path.join(_SCRIPT_DIR, "resources/workflow_validate_and_run.md"),
}

# ── Resources ──────────────────────────────────────────────────────────────────

@app.list_resources()
async def handle_list_resources() -> List[types.Resource]:
    from pydantic import AnyUrl
    return [
        types.Resource(
            uri=AnyUrl(uri),
            name=meta["name"],
            description=meta["description"],
            mimeType=meta["mimeType"],
        )
        for uri, meta in _RESOURCE_REGISTRY.items()
    ]


@app.read_resource()
async def handle_read_resource(uri) -> str:
    uri_str = str(uri)

    if uri_str.endswith("graph-xml"):
        return _load_reference(
            "graph-xml",
            os.path.join(_SCRIPT_DIR, "resources/cloverdx-llm-reference.md")
        )

    if uri_str.endswith("ctl2"):
        return _load_reference(
            "ctl2",
            os.path.join(_SCRIPT_DIR, "resources/CTL2_Reference_for_LLM_compact.md")
        )

    if uri_str.endswith("subgraphs"):
        return _load_reference(
            "subgraphs",
            os.path.join(_SCRIPT_DIR, "resources/CLOVERDX_SUBGRAPHS.md")
        )

    if uri_str.endswith("components"):
        cat    = get_catalog()
        non_dep = [c for c in cat._components if not cat._is_deprecated(c)]
        return json.dumps(non_dep, indent=2)

    raise ValueError(f"Unknown resource URI: {uri_str}")


# ── Tools ──────────────────────────────────────────────────────────────────────

@app.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return [
        # ── Sandbox / File tools ───────────────────────────────────────────
        types.Tool(
            name="list_sandboxes",
            description="List all sandboxes (projects) available on the CloverDX server.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="list_files",
            description=(
                "List files and folders inside a directory within a CloverDX sandbox. "
                "Use folder_only=true to list only subdirectories."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path"],
                "properties": {
                    "sandbox":     {"type": "string", "description": "Sandbox code (e.g. MySandbox)"},
                    "path":        {"type": "string", "description": "Directory path within the sandbox (e.g. 'graph', 'data/in')"},
                    "folder_only": {"type": "boolean", "description": "List only subdirectories (default: false)"},
                },
            },
        ),
        types.Tool(
            name="find_file",
            description=(
                "Find files in a CloverDX sandbox using shell-style wildcards. "
                "Supports '*' and '?'. Searches recursively by listing files and filtering client-side."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "pattern"],
                "properties": {
                    "sandbox": {"type": "string", "description": "Sandbox code"},
                    "pattern": {"type": "string", "description": "Wildcard pattern, for example '*.grf', 'graph/*.grf', or 'data/file?.csv'"},
                    "path": {"type": "string", "description": "Optional starting directory within the sandbox (default: root)"},
                },
            },
        ),
        types.Tool(
            name="grep_files",
            description=(
                "Search for files in a CloverDX sandbox whose content contains a given string. "
                "Returns the path, size, and last-modified date of each matching file. "
                "Optionally also returns the matching lines with line numbers (like grep -n). "
                "\n\n"
                "Primary use cases:\n"
                "- Find all graphs that use a specific component type: "
                "search_string='type=\"VALIDATOR\"', path='graph'\n"
                "- Find all graphs that reference a specific subgraph: "
                "search_string='OrderFileReader.sgrf'\n"
                "- Find all files that reference a specific metadata id: "
                "search_string='metadata=\"MetaOrder\"'\n"
                "- Find all CTL files that call a specific function: "
                "search_string='checkTotalPrice'\n"
                "- Find all graphs that reference a specific connection: "
                "search_string='DWHConnection'\n"
                "- Find example graphs to use as reference before authoring a new one: "
                "file_pattern='*.grf', search_string='type=\"DENORMALIZER\"'\n"
                "\n"
                "Combine with find_file when you need both name pattern AND content filtering: "
                "first call find_file to get the candidate file list, then call grep_files "
                "with a path scope to filter by content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sandbox": {
                        "type": "string",
                        "description": "Sandbox code to search in.",
                    },
                    "search_string": {
                        "type": "string",
                        "description": (
                            "The string to search for in file contents. "
                            "Plain string — not a regex. Case-sensitive by default."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Directory to search under (recursive). "
                            "Defaults to sandbox root. "
                            "Examples: 'graph', 'graph/subgraph', 'trans'."
                        ),
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": (
                            "Optional shell-style wildcard to filter filenames before content search. "
                            "Examples: '*.grf', '*.sgrf', '*.ctl'. "
                            "Defaults to '*' (all files)."
                        ),
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether the search is case-sensitive. Default: true.",
                    },
                    "include_matching_lines": {
                        "type": "boolean",
                        "description": (
                            "If true, each result includes the matching lines with line numbers. "
                            "If false, returns only file paths and metadata. "
                            "Default: false. "
                            "Set true when you need to understand how the string is used "
                            "(e.g. verifying which component ID uses a given attribute), "
                            "false when you only need to know which files to read next."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matching files to return. Default: 20, max: 100.",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["sandbox", "search_string"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="list_linked_assets",
            description=(
                "Lists all linkable/externalised assets available in a CloverDX sandbox — "
                "metadata definitions (.fmt), connection definitions (.cfg), lookup table "
                "definitions (.lkp), CTL2 transformation files (.ctl), sequence files (.seq), "
                "and parameter files (.prm). "
                "Call this early during graph creation to discover reusable shared assets before "
                "defining new ones inline, and to confirm the correct fileURL paths to reference "
                "in the graph XML. "
                "Optionally filter by asset type to narrow results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sandbox": {
                        "type": "string",
                        "description": "Sandbox code to inspect.",
                    },
                    "asset_type": {
                        "type": "string",
                        "enum": ["metadata", "connection", "lookup", "ctl", "sequence", "parameters", "all"],
                        "description": (
                            "Type of asset to list. "
                            "'metadata' → .fmt files; "
                            "'connection' → .cfg files; "
                            "'lookup' → .lkp files; "
                            "'ctl' → .ctl transformation files; "
                            "'sequence' → .seq files; "
                            "'parameters' → .prm files; "
                            "'all' → all of the above (default)."
                        ),
                    },
                },
                "required": ["sandbox"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_sandbox_parameters",
            description=(
                "Returns best-effort resolved graph parameter values for a CloverDX sandbox by "
                "reading workspace.prm and optionally overlaying server-side defaults/properties. "
                "Use this before writing file paths into a graph to know what ${DATAIN_DIR}, "
                "${DATAOUT_DIR}, ${CONN_DIR} and related parameters resolve to in this sandbox context. "
                "Response includes source provenance and unresolved placeholders."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sandbox": {
                        "type": "string",
                        "description": "Sandbox code to inspect.",
                    },
                    "workspace_param_path": {
                        "type": "string",
                        "description": "Path to workspace parameter file within sandbox (default: 'workspace.prm').",
                    },
                    "include_defaults": {
                        "type": "boolean",
                        "description": "Overlay values from GetDefaults operation (default: true).",
                    },
                    "include_system_properties": {
                        "type": "boolean",
                        "description": "Overlay matching keys from GetSystemProperties (default: true).",
                    },
                    "include_all_server_properties": {
                        "type": "boolean",
                        "description": "Include server properties not present in workspace.prm (default: false).",
                    },
                },
                "required": ["sandbox"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="read_file",
            description=(
                "Read the content of a file from a CloverDX sandbox. "
                "Use this to fetch .grf graph files, .fmt metadata files, .prm parameter files, etc. "
                "Optionally read only a byte range by specifying both offset and byte_count."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path"],
                "properties": {
                    "sandbox": {"type": "string", "description": "Sandbox code"},
                    "path":    {"type": "string", "description": "Full file path within the sandbox (e.g. 'graph/MyGraph.grf')"},
                    "offset": {
                        "type": "integer",
                        "description": "Optional zero-based byte offset from which to start reading. Must be provided together with byte_count.",
                    },
                    "byte_count": {
                        "type": "integer",
                        "description": "Optional number of bytes to read. Must be provided together with offset.",
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="rename_file",
            description=(
                "Renames a file within a CloverDX sandbox. "
                "Only the filename changes — the file stays in the same directory. "
                "To move a file to a different directory, use copy_file + delete_file."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path", "new_name"],
                "properties": {
                    "sandbox": {
                        "type": "string",
                        "description": "Sandbox code containing the file.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Full current file path within the sandbox (e.g. 'graph/MyGraph.grf').",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New filename only — no directory component (e.g. 'MyGraphV2.grf').",
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="copy_file",
            description=(
                "Copies a file within a CloverDX sandbox, or from one sandbox to another. "
                "Primary use: create a safe backup of a graph or any other file before making "
                "significant edits. The copy overwrites the destination if it already exists. "
                "Always copy a graph to a backup path (e.g. 'graph/MyGraph.bak.grf') before "
                "a large edit so the original can be restored if patching corrupts the file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Full source file path within the source sandbox (e.g. 'graph/MyGraph.grf').",
                    },
                    "source_sandbox": {
                        "type": "string",
                        "description": "Sandbox code containing the source file.",
                    },
                    "dest_path": {
                        "type": "string",
                        "description": (
                            "Full destination file path (e.g. 'graph/MyGraph.bak.grf'). "
                            "Directory must already exist."
                        ),
                    },
                    "dest_sandbox": {
                        "type": "string",
                        "description": (
                            "Sandbox code for the destination. "
                            "Omit or set to the same value as source_sandbox for an intra-sandbox copy."
                        ),
                    },
                },
                "required": ["source_path", "source_sandbox", "dest_path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="patch_file",
            description=(
                "Patch a file in a CloverDX sandbox using anchor-based replacements. "
                "Each patch locates an anchor string, computes a line range from from_offset/to_offset, "
                "checks for conflicts, and applies all replacements bottom-up. "
                "Supports dry_run preview mode."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path", "patches"],
                "properties": {
                    "sandbox": {"type": "string", "description": "Sandbox code"},
                    "path": {"type": "string", "description": "Full file path within the sandbox (for example 'graph/MyGraph.grf')"},
                    "dry_run": {"type": "boolean", "description": "Validate and preview patches without writing the file (default: false)"},
                    "patches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["anchor", "from_offset", "to_offset", "new_content"],
                            "properties": {
                                "anchor": {"type": "string", "description": "Unique substring used to locate the target line. Matching is trim-insensitive."},
                                "from_offset": {"type": "integer", "description": "Line offset from anchor line to start of replacement"},
                                "to_offset": {"type": "integer", "description": "Line offset from anchor line to end of replacement (inclusive)"},
                                "new_content": {"type": "string", "description": "Replacement text. Empty string deletes the target range."},
                                "anchor_occurrence": {"type": "integer", "description": "Optional 1-based occurrence index if anchor appears multiple times"},
                            },
                        },
                    },
                },
            },
        ),
        types.Tool(
            name="set_graph_element_attribute",
            description=(
                "Sets or updates a value on a specific element within a CloverDX graph XML file. "
                "Operates on the parsed DOM — no text anchoring or line numbers required. "
                "More reliable than patch_file for graph modifications. "
                "\n\n"
                "Supports two modification modes, selected via the 'attribute_name' parameter:\n"
                "1. XML attribute — plain attribute on the element tag. "
                "Use for: recordsNumber, joinType, enabled, guiX, guiY, fileURL, metadata, etc. "
                "Example: attribute_name='recordsNumber', value='100'\n"
                "2. <attr> child element — multi-line content stored as a CDATA child of a Node. "
                "Prefix attribute_name with 'attr:' to select this mode. "
                "Use for: CTL transforms, SQL queries, joinKey, mapping XML, rules, errorMapping, etc. "
                "The value is stored as CDATA — do NOT wrap it yourself. "
                "Example: attribute_name='attr:transform', value='//#CTL2\\nfunction integer transform() {...}'\n"
                "\n"
                "For Metadata elements: supply the full replacement <Record>...</Record> XML as value. "
                "attribute_name is ignored for Metadata — set it to 'record' by convention. "
                "The entire child content of <Metadata id='X'> is replaced. "
                "External metadata (fileURL-style) cannot be modified with this tool — edit the .fmt file directly.\n"
                "\n"
                "Always call validate_graph after using this tool."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to the .grf file within the sandbox (e.g. 'graph/MyGraph.grf').",
                    },
                    "sandbox": {
                        "type": "string",
                        "description": "Sandbox code.",
                    },
                    "element_type": {
                        "type": "string",
                        "enum": ["Node", "Edge", "Metadata", "GraphParameter", "Connection"],
                        "description": (
                            "The type of graph element to modify. "
                            "Node: a processing component. "
                            "Edge: a connection between components. "
                            "Metadata: a record structure definition. "
                            "GraphParameter: a graph parameter (matched by 'name' attribute, not 'id'). "
                            "Connection: a database or service connection definition."
                        ),
                    },
                    "element_id": {
                        "type": "string",
                        "description": (
                            "The unique identifier of the target element. "
                            "For Node, Edge, Metadata, Connection: matches the 'id' XML attribute. "
                            "For GraphParameter: matches the 'name' XML attribute."
                        ),
                    },
                    "attribute_name": {
                        "type": "string",
                        "description": (
                            "What to set on the element. Two forms:\n"
                            "- Plain name (e.g. 'recordsNumber', 'joinType', 'enabled', 'guiX', "
                            "'fileURL', 'value') → sets an XML attribute directly on the element tag.\n"
                            "- 'attr:X' prefix (e.g. 'attr:transform', 'attr:generate', "
                            "'attr:sqlQuery', 'attr:joinKey', 'attr:rules', 'attr:errorMapping', "
                            "'attr:denormalize', 'attr:mapping') → sets the content of an "
                            "<attr name='X'> child element, CDATA-wrapped automatically.\n"
                            "For Metadata elements: set to 'record' (ignored by implementation)."
                        ),
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "The new value. "
                            "For plain XML attributes: a simple string (e.g. '100', 'leftOuter', 'true'). "
                            "For 'attr:' child elements: raw content, any length, any format "
                            "(CTL code, SQL, XML) — CDATA wrapping is applied automatically. "
                            "Do NOT wrap in <![CDATA[...]]> yourself. "
                            "For Metadata: the full replacement <Record>...</Record> XML block."
                        ),
                    },
                },
                "required": [
                    "graph_path",
                    "sandbox",
                    "element_type",
                    "element_id",
                    "attribute_name",
                    "value",
                ],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="write_file",
            description=(
                "Write (create or overwrite) a file in a CloverDX sandbox. "
                "Use this to save a new or modified graph, metadata file, or parameter file."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path", "filename", "content"],
                "properties": {
                    "sandbox":  {"type": "string", "description": "Sandbox code"},
                    "path":     {"type": "string", "description": "Directory path within the sandbox (e.g. 'graph')"},
                    "filename": {"type": "string", "description": "File name including extension (e.g. 'MyGraph.grf')"},
                    "content":  {"type": "string", "description": "Full file content as a UTF-8 string"},
                },
            },
        ),
        types.Tool(
            name="delete_file",
            description=(
                "Delete a file from a CloverDX sandbox. "
                "Use with caution — this is irreversible."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path"],
                "properties": {
                    "sandbox": {"type": "string", "description": "Sandbox code"},
                    "path":    {"type": "string", "description": "Full file path to delete (e.g. 'graph/OldGraph.grf')"},
                },
            },
        ),

        # ── Resource tools ─────────────────────────────────────────────────
        types.Tool(
            name="list_resources",
            description=(
                "List all resource URIs exposed by this MCP server, with their name, "
                "description, and MIME type. "
                "Use this to discover what reference material is available before "
                "calling read_resource."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="read_resource",
            description=(
                "Fetch the full content of a resource by its URI. "
                "Call list_resources first to see available URIs. "
                "Examples: 'cloverdx://reference/graph-xml', "
                "'cloverdx://reference/ctl2', 'cloverdx://reference/subgraphs', "
                "'cloverdx://reference/components'."
            ),
            inputSchema={
                "type": "object",
                "required": ["uri"],
                "properties": {
                    "uri": {"type": "string", "description": "Resource URI (e.g. 'cloverdx://reference/graph-xml')"},
                },
            },
        ),
        types.Tool(
            name="get_workflow_guide",
            description=(
                "Returns the authoritative step-by-step workflow guide for a given CloverDX task. "
                "Always call this at the start of any CloverDX task before doing any work. "
                "The guide contains mandatory phases, component selection rules, common error fixes, "
                "and a checklist to verify the task is complete. "
                "Available task types:\n"
                "  - 'create_graph'      — Full guide for designing and creating a new graph from scratch. "
                "Covers component selection, get_component_info/get_component_details usage, metadata design, "
                "XML authoring rules (including nested CDATA escaping), and validation.\n"
                "  - 'edit_graph'        — Guide for modifying an existing graph. "
                "Covers read-before-edit discipline, patch vs rewrite decisions, re-read-between-patches rule, "
                "and validation after every write.\n"
                "  - 'validate_and_run'  — Guide for validating, executing, and verifying a graph. "
                "Covers interpreting Stage 1/Stage 2 validation results, fixing common errors, "
                "running the graph, and verifying results via tracking and execution log.\n"
                "If no task is specified, returns the guide most appropriate for general graph work ('create_graph')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "enum": ["create_graph", "edit_graph", "validate_and_run"],
                        "description": (
                            "The type of task being performed. "
                            "'create_graph' for building a new graph from scratch; "
                            "'edit_graph' for modifying an existing graph; "
                            "'validate_and_run' for validating, executing, and verifying an existing graph. "
                            "Defaults to 'create_graph' if omitted."
                        ),
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        ),

        # ── Graph tools ────────────────────────────────────────────────────
        types.Tool(
            name="validate_graph",
            description=(
                "Validate a CloverDX graph in two stages:\n"
                "  Stage 1 — Local XML structure + metadata check (fast, no extra server round-trip)\n"
                "  Stage 2 — Server-side checkConfig (deep component check; only runs if Stage 1 passes)\n"
                "The graph must already exist on the server — write it first with write_file.\n"
                "IMPORTANT: The returned error list may not be exhaustive. Some errors block further "
                "validation, so fixing reported issues and calling validate_graph again may reveal "
                "additional problems. Repeat until validation returns no errors."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "graph_path"],
                "properties": {
                    "sandbox":    {"type": "string", "description": "Sandbox code"},
                    "graph_path": {"type": "string", "description": "Path to the .grf file (e.g. 'graph/MyGraph.grf')"},
                    "timeout_seconds": {"type": "integer", "description": "Max seconds to wait for checkConfig (default: 120)"},
                },
            },
        ),
        types.Tool(
            name="execute_graph",
            description=(
                "Execute a CloverDX transformation graph on the server and wait for it to complete. "
                "Returns the final status and elapsed time. "
                "Use get_graph_execution_log to fetch detailed logs. "
                "Use get_graph_tracking to see per-component record/byte counts. "
                "Set debug=true to enable edge debug data capture (required for get_edge_debug_data)."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "graph_path"],
                "properties": {
                    "sandbox":    {"type": "string", "description": "Sandbox code"},
                    "graph_path": {"type": "string", "description": "Path to the .grf file"},
                    "params": {
                        "type": "object",
                        "description": "Optional graph parameter overrides as key-value pairs",
                        "additionalProperties": {"type": "string"},
                    },
                    "debug":    {"type": "boolean", "description": "Enable edge debug data capture (default: false). Required to use get_edge_debug_data afterwards."},
                    "timeout_seconds": {"type": "integer", "description": "Max seconds to wait for completion (default: 120)"},
                },
            },
        ),
        types.Tool(
            name="list_graph_runs",
            description=(
                "List recent graph/jobflow executions from CloverDX Server. "
                "Filter by sandbox, job_file (substring), or status. "
                "Returns run_id, status, submit/start/stop times, duration, and error details. "
                "Use this to find run IDs for get_graph_run_status, get_graph_execution_log, "
                "or get_graph_tracking. "
                "Statuses: N_A, ENQUEUED, READY, RUNNING, WAITING, FINISHED_OK, ERROR, ABORTED, TIMEOUT."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sandbox": {
                        "type": "string",
                        "description": "Filter by sandbox code (exact match).",
                    },
                    "job_file": {
                        "type": "string",
                        "description": "Filter by job file path substring (e.g. 'GenerateData.grf').",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by execution status (e.g. 'FINISHED_OK', 'ERROR', 'RUNNING').",
                        "enum": ["N_A", "ENQUEUED", "READY", "RUNNING", "WAITING",
                                 "FINISHED_OK", "ERROR", "ABORTED", "TIMEOUT"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 25).",
                        "default": 25,
                    },
                    "start_index": {
                        "type": "integer",
                        "description": "Zero-based offset for paging (default: 0).",
                        "default": 0,
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_graph_run_status",
            description=(
                "Returns the current status of a graph run by its run ID — without fetching "
                "the full execution log. "
                "Possible statuses: RUNNING, SUCCESS, FAILED, ABORTED, WAITING. "
                "Use this to poll the status of a long-running graph, or to quickly check "
                "whether a specific run succeeded before deciding whether to fetch logs or "
                "tracking data. "
                "When status is RUNNING, also returns elapsed time and current phase number "
                "so progress can be assessed. "
                "For completed runs, use get_graph_tracking for record counts and "
                "get_graph_execution_log for detailed diagnostics."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "Run ID as returned by execute_graph or list_graph_runs.",
                    },
                },
                "required": ["run_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_graph_execution_log",
            description="Fetch the execution log for a graph run by its run ID.",
            inputSchema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string", "description": "Run ID returned by execute_graph"},
                },
            },
        ),

        # ── Component reference tools ──────────────────────────────────────
        types.Tool(
            name="list_components",
            description=(
                "List available CloverDX component types. "
                "Optionally filter by category: readers, writers, transformers, joiners, others, jobControl."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter",
                        "enum": ["readers", "writers", "transformers", "joiners", "others", "jobControl"],
                    },
                },
            },
        ),
        types.Tool(
            name="get_component_info",
            description=(
                "Look up a CloverDX component's input/output ports and configurable properties. "
                "Search by component type (e.g. 'EXT_HASH_JOIN') or display name (e.g. 'Map'). "
                "Case-insensitive, partial match supported."
            ),
            inputSchema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Component type or name to search for"},
                    "include_deprecated": {"type": "boolean", "description": "Include deprecated components (default: false)"},
                },
            },
        ),
        types.Tool(
            name="get_component_details",
            description=(
                "Fetch extended documentation for a complex CloverDX component. "
                "Currently available: XML_EXTRACT. "
                "Returns full markdown with mapping syntax, configuration examples, and usage notes."
            ),
            inputSchema={
                "type": "object",
                "required": ["component_type"],
                "properties": {
                    "component_type": {"type": "string", "description": "Component type string (e.g. 'XML_EXTRACT')"},
                },
            },
        ),

        # ── Tracking + edge debug tools ────────────────────────────────────
        types.Tool(
            name="get_graph_tracking",
            description=(
                "Get execution metrics for a completed graph run: phases, component timings, "
                "and record/byte counts per input and output port. "
                "Set detailed=false for summary-only output. "
                "Available for any run — no debug mode required. "
                "Use this to verify data flowed correctly (e.g. check that a filter passed the expected number of records)."
            ),
            inputSchema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string", "description": "Run ID returned by execute_graph"},
                    "detailed": {
                        "type": "boolean",
                        "description": "If true (default), include per-phase/node/port details. If false, return summary-only payload.",
                    },
                },
            },
        ),
        types.Tool(
            name="get_edge_debug_info",
            description=(
                "List edge debug data locations available for a specific edge of a completed graph run. "
                "The graph must have been executed with debug=true. "
                "Returns whether data is available for the edge, and writer/reader node IDs."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "graph_path", "run_id", "edge_id"],
                "properties": {
                    "sandbox":    {"type": "string", "description": "Sandbox code"},
                    "graph_path": {"type": "string", "description": "Path to the .grf file"},
                    "run_id":     {"type": "string", "description": "Run ID returned by execute_graph"},
                    "edge_id":    {"type": "string", "description": "Edge ID as defined in the graph XML (the 'id' attribute of an <Edge> element)"},
                },
            },
        ),
        types.Tool(
            name="get_edge_debug_metadata",
            description=(
                "Get the field schema (names and types) for data flowing through a specific edge. "
                "The graph must have been executed with debug=true. "
                "Returns the metadata XML for the edge."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "graph_path", "run_id", "edge_id"],
                "properties": {
                    "sandbox":    {"type": "string", "description": "Sandbox code"},
                    "graph_path": {"type": "string", "description": "Path to the .grf file"},
                    "run_id":     {"type": "string", "description": "Run ID returned by execute_graph"},
                    "edge_id":    {"type": "string", "description": "Edge ID as defined in the graph XML"},
                },
            },
        ),
        types.Tool(
            name="get_edge_debug_data",
            description=(
                "Fetch summary information about data records that flowed through a specific graph edge during a debug run. "
                "Returns the record count captured on the edge and whether more pages are available. "
                "The payload itself is CloverDX binary (CLVI format) and is not returned as text — "
                "use get_edge_debug_metadata to inspect the field schema instead. "
                "The graph must have been executed with debug=true. "
                "Use get_edge_debug_info first to confirm data is available and obtain writerRunId/readerRunId. "
                "filter_expression must be a CTL2 boolean expression (e.g. '$in.amount > 100'). "
                "It is automatically prefixed with //#CTL2 — do NOT include the language marker yourself. "
                "Omit or leave blank for no filtering (all records)."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "graph_path", "run_id", "edge_id"],
                "properties": {
                    "sandbox":          {"type": "string",  "description": "Sandbox code"},
                    "graph_path":       {"type": "string",  "description": "Path to the .grf file"},
                    "run_id":           {"type": "string",  "description": "Run ID returned by execute_graph"},
                    "edge_id":          {"type": "string",  "description": "Edge ID as defined in the graph XML"},
                    "start_record":     {"type": "integer", "description": "Zero-based index of the first record to fetch (default: 0). Use for paging."},
                    "record_count":     {"type": "integer", "description": "Max number of records to fetch per page (default: 100)"},
                    "filter_expression":{"type": "string",  "description": "CTL2 boolean expression to filter records (e.g. '$in.amount > 100'). Omit for all records."},
                    "field_selection":  {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of field names to include (default: all fields)",
                    },
                },
            },
        ),
    ]


# ── Tool implementations ───────────────────────────────────────────────────────

def _text(content: str) -> List[types.TextContent]:
    return [types.TextContent(type="text", text=content)]


async def tool_list_sandboxes(_args: Dict) -> List[types.TextContent]:
    try:
        sandboxes = get_soap_client().get_sandboxes()
        return _text(json.dumps(sandboxes, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_list_files(args: Dict) -> List[types.TextContent]:
    try:
        files = get_soap_client().list_files(
            sandbox=args["sandbox"],
            path=args["path"],
            folder_only=args.get("folder_only", False),
        )
        return _text(json.dumps(files, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_find_file(args: Dict) -> List[types.TextContent]:
    try:
        files = get_soap_client().find_files(
            sandbox=args["sandbox"],
            pattern=args["pattern"],
            path=args.get("path", ""),
        )
        return _text(json.dumps(files, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_grep_files(args: Dict) -> List[types.TextContent]:
    import fnmatch as _fnmatch
    try:
        sandbox         = args["sandbox"]
        search_string   = args["search_string"]
        path            = str(args.get("path") or "").strip()
        file_pattern    = str(args.get("file_pattern") or "*").strip() or "*"
        case_sensitive  = bool(args.get("case_sensitive", True))
        include_lines   = bool(args.get("include_matching_lines", False))
        max_results     = min(int(args.get("max_results") or 20), 100)

        client = get_soap_client()

        # Collect candidate files matching file_pattern under path
        candidate_files = client.find_files(
            sandbox=sandbox,
            pattern=file_pattern,
            path=path,
        )

        needle = search_string if case_sensitive else search_string.lower()

        results = []
        for item in candidate_files:
            if not isinstance(item, dict):
                continue
            file_path = str(
                item.get("path") or item.get("filePath") or
                item.get("name") or item.get("fileName") or ""
            ).strip().lstrip("/")
            if not file_path:
                continue

            try:
                content = client.download_file(sandbox, file_path)
            except Exception:
                continue

            lines = content.splitlines()
            matching_lines = []
            for lineno, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matching_lines.append((lineno, line))

            if not matching_lines:
                continue

            entry: Dict[str, Any] = {
                "path": file_path,
            }
            # Include whatever metadata the server returned
            for meta_key in ("size", "lastModified", "isFolder"):
                if meta_key in item:
                    entry[meta_key] = item[meta_key]
            entry["match_count"] = len(matching_lines)

            if include_lines:
                entry["matching_lines"] = [
                    {"line": lineno, "content": text}
                    for lineno, text in matching_lines
                ]

            results.append(entry)
            if len(results) >= max_results:
                break

        payload = {
            "sandbox": sandbox,
            "search_string": search_string,
            "path": path or "/",
            "file_pattern": file_pattern,
            "case_sensitive": case_sensitive,
            "include_matching_lines": include_lines,
            "result_count": len(results),
            "truncated": len(results) == max_results and len(results) < len(candidate_files),
            "results": results,
        }
        return _text(json.dumps(payload, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_list_linked_assets(args: Dict) -> List[types.TextContent]:
    try:
        sandbox = args["sandbox"]
        asset_type = str(args.get("asset_type", "all")).strip().lower() or "all"

        asset_patterns: Dict[str, str] = {
            "metadata": "*.fmt",
            "connection": "*.cfg",
            "lookup": "*.lkp",
            "ctl": "*.ctl",
            "sequence": "*.seq",
            "parameters": "*.prm",
        }

        if asset_type != "all" and asset_type not in asset_patterns:
            allowed = ", ".join([*asset_patterns.keys(), "all"])
            return _text(f"ERROR: Unknown asset_type '{asset_type}'. Allowed values: {allowed}")

        selected_types = list(asset_patterns.keys()) if asset_type == "all" else [asset_type]
        client = get_soap_client()

        by_type: Dict[str, List[str]] = {}
        all_assets: List[str] = []

        for kind in selected_types:
            pattern = asset_patterns[kind]
            found = client.find_files(sandbox=sandbox, pattern=pattern, path="")

            paths: List[str] = []
            for item in found:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or item.get("filePath") or item.get("name") or item.get("fileName") or "").strip()
                if path:
                    paths.append(path.lstrip("/"))

            deduped = sorted(set(paths))
            by_type[kind] = deduped
            all_assets.extend(deduped)

        payload = {
            "sandbox": sandbox,
            "asset_type": asset_type,
            "count": len(set(all_assets)),
            "assets": by_type if asset_type == "all" else by_type[selected_types[0]],
        }
        return _text(json.dumps(payload, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_sandbox_parameters(args: Dict) -> List[types.TextContent]:
    try:
        sandbox = args["sandbox"]
        workspace_param_path = str(args.get("workspace_param_path") or "workspace.prm").strip() or "workspace.prm"
        include_defaults = bool(args.get("include_defaults", True))
        include_system_properties = bool(args.get("include_system_properties", True))
        include_all_server_properties = bool(args.get("include_all_server_properties", False))

        client = get_soap_client()

        workspace_prm_content = client.download_file(sandbox, workspace_param_path)
        workspace_params, descriptions = _parse_workspace_prm_xml(workspace_prm_content)

        merged = dict(workspace_params)
        sources: Dict[str, str] = {k: "workspace_prm" for k in workspace_params.keys()}
        applied_overrides: Dict[str, Dict[str, str]] = {}

        server_defaults: Dict[str, str] = {}
        if include_defaults:
            server_defaults = client.get_defaults()
            for key, value in server_defaults.items():
                if not include_all_server_properties and key not in merged:
                    continue
                old_value = merged.get(key)
                merged[key] = value
                sources[key] = "server_defaults"
                if old_value is not None and old_value != value:
                    applied_overrides[key] = {
                        "from": old_value,
                        "to": value,
                        "source": "server_defaults",
                    }

        system_properties: Dict[str, str] = {}
        if include_system_properties:
            system_properties = client.get_system_properties()
            for key, value in system_properties.items():
                if not include_all_server_properties and key not in merged:
                    continue
                old_value = merged.get(key)
                merged[key] = value
                sources[key] = "system_properties"
                if old_value is not None and old_value != value:
                    applied_overrides[key] = {
                        "from": old_value,
                        "to": value,
                        "source": "system_properties",
                    }

        resolved, unresolved_refs = _resolve_parameter_references(merged)

        payload = {
            "sandbox": sandbox,
            "workspace_param_path": workspace_param_path,
            "resolution_scope": "best_effort",
            "counts": {
                "workspace_params": len(workspace_params),
                "server_defaults": len(server_defaults),
                "system_properties": len(system_properties),
                "merged": len(merged),
                "resolved": len(resolved),
                "unresolved": len(unresolved_refs),
                "applied_overrides": len(applied_overrides),
            },
            "resolved_parameters": resolved,
            "parameter_sources": sources,
            "workspace_descriptions": descriptions,
            "applied_overrides": applied_overrides,
            "unresolved_references": unresolved_refs,
        }
        return _text(json.dumps(payload, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_read_file(args: Dict) -> List[types.TextContent]:
    try:
        content = get_soap_client().download_file(args["sandbox"], args["path"])

        offset = args.get("offset")
        byte_count = args.get("byte_count")
        partial_requested = offset is not None or byte_count is not None

        if partial_requested:
            if offset is None or byte_count is None:
                return _text("ERROR: offset and byte_count must both be provided when requesting a partial read.")

            offset = int(offset)
            byte_count = int(byte_count)

            if offset < 0 or byte_count < 0:
                return _text("ERROR: offset and byte_count must be non-negative integers.")

            content_bytes = content.encode("utf-8")
            sliced_bytes = content_bytes[offset:offset + byte_count]
            return _text(sliced_bytes.decode("utf-8", errors="replace"))

        return _text(content)
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_rename_file(args: Dict) -> List[types.TextContent]:
    try:
        get_soap_client().rename_file(
            sandbox=args["sandbox"],
            path=args["path"],
            new_name=args["new_name"],
        )
        dir_part = os.path.dirname(args["path"])
        new_path = os.path.join(dir_part, args["new_name"]) if dir_part else args["new_name"]
        return _text(f"OK: '{args['path']}' renamed to '{new_path}' in sandbox '{args['sandbox']}'.")
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_copy_file(args: Dict) -> List[types.TextContent]:
    source_sandbox = args["source_sandbox"]
    source_path = args["source_path"]
    dest_sandbox = args.get("dest_sandbox") or source_sandbox
    dest_path = args["dest_path"]

    try:
        get_soap_client().copy_file(
            source_sandbox=source_sandbox,
            source_path=source_path,
            dest_sandbox=dest_sandbox,
            dest_path=dest_path,
        )
        return _text(
            f"OK: File copied from '{source_sandbox}:{source_path}' to '{dest_sandbox}:{dest_path}'."
        )
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_patch_file(args: Dict) -> List[types.TextContent]:
    sandbox = args["sandbox"]
    path = args["path"]
    patch_specs = args.get("patches") or []
    dry_run = bool(args.get("dry_run", False))

    def _json_result(payload: Dict[str, Any]) -> List[types.TextContent]:
        return _text(json.dumps(payload, indent=2))

    def _is_file_not_found_error(exc: Exception) -> bool:
        err = str(exc).lower()
        return any(token in err for token in ("not found", "does not exist", "no such"))

    def _anchor_matches(line: str, anchor: str) -> bool:
        if not anchor:
            return False
        return anchor in line or anchor.strip() in line.strip()

    try:
        original_content = get_soap_client().download_file(sandbox, path)
    except Exception as e:
        if _is_file_not_found_error(e):
            return _json_result({
                "status": "error",
                "patches_applied": 0,
                "errors": [
                    {
                        "error": "file_not_found",
                        "path": path,
                    }
                ],
            })
        return _text(f"ERROR: {e}")

    line_sep = "\r\n" if "\r\n" in original_content else "\n"
    had_trailing_newline = original_content.endswith("\n") or original_content.endswith("\r")
    lines = original_content.splitlines()

    resolved_patches: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for patch_index, patch in enumerate(patch_specs, start=1):
        anchor = str(patch["anchor"])
        matches = [idx for idx, line in enumerate(lines) if _anchor_matches(line, anchor)]

        if not matches:
            errors.append({
                "patch_index": patch_index,
                "anchor": anchor,
                "error": "anchor_not_found",
            })
            continue

        occurrence = patch.get("anchor_occurrence")
        if occurrence is None:
            if len(matches) > 1:
                errors.append({
                    "patch_index": patch_index,
                    "anchor": anchor,
                    "error": "anchor_ambiguous",
                    "match_count": len(matches),
                    "hint": "Set anchor_occurrence to select a specific match, or use a longer anchor string",
                })
                continue
            anchor_index = matches[0]
        else:
            occurrence_int = int(occurrence)
            if occurrence_int < 1 or occurrence_int > len(matches):
                errors.append({
                    "patch_index": patch_index,
                    "anchor": anchor,
                    "error": "anchor_occurrence_out_of_range",
                    "match_count": len(matches),
                })
                continue
            anchor_index = matches[occurrence_int - 1]

        from_offset = int(patch["from_offset"])
        to_offset = int(patch["to_offset"])
        start = anchor_index + from_offset
        end = anchor_index + to_offset

        if start < 0 or start > len(lines) or end < -1 or end >= len(lines) or start > end + 1:
            errors.append({
                "patch_index": patch_index,
                "anchor": anchor,
                "error": "offset_out_of_bounds",
            })
            continue

        insert_lines = [] if patch["new_content"] == "" else str(patch["new_content"]).splitlines()
        replaced_lines = lines[start:end + 1] if start <= end else []

        resolved_patches.append({
            "patch_index": patch_index,
            "anchor": anchor,
            "anchor_line": anchor_index + 1,
            "start": start,
            "end": end,
            "end_exclusive": end + 1 if start <= end else start,
            "new_content": str(patch["new_content"]),
            "insert_lines": insert_lines,
            "replaced_lines": replaced_lines,
        })

    if not errors:
        sorted_ranges = sorted(resolved_patches, key=lambda patch: (patch["start"], patch["end_exclusive"], patch["patch_index"]))
        for idx in range(1, len(sorted_ranges)):
            prev = sorted_ranges[idx - 1]
            curr = sorted_ranges[idx]
            if curr["start"] < prev["end_exclusive"]:
                errors.append({
                    "patch_index": curr["patch_index"],
                    "anchor": curr["anchor"],
                    "error": "patch_conflict",
                    "conflicts_with_patch_index": prev["patch_index"],
                })

    if errors:
        return _json_result({
            "status": "error",
            "patches_applied": 0,
            "errors": errors,
        })

    updated_lines = list(lines)
    for patch in sorted(resolved_patches, key=lambda item: (item["start"], item["patch_index"]), reverse=True):
        if patch["start"] <= patch["end"]:
            updated_lines[patch["start"]:patch["end"] + 1] = patch["insert_lines"]
        else:
            updated_lines[patch["start"]:patch["start"]] = patch["insert_lines"]

    result: Dict[str, Any] = {
        "patches_applied": len(resolved_patches),
        "lines_before": len(lines),
        "lines_after": len(updated_lines),
    }

    if dry_run:
        result["status"] = "dry_run"
        result["preview"] = [
            {
                "anchor": patch["anchor"],
                "anchor_line": patch["anchor_line"],
                "lines_replaced": patch["replaced_lines"],
                "lines_inserted": patch["insert_lines"],
            }
            for patch in resolved_patches
        ]
        return _json_result(result)

    updated_content = line_sep.join(updated_lines)
    if had_trailing_newline:
        updated_content += line_sep

    dir_path, filename = os.path.split(path)
    try:
        get_soap_client().upload_file(
            sandbox=sandbox,
            dir_path=dir_path,
            filename=filename,
            content=updated_content,
        )
    except Exception as e:
        return _text(f"ERROR: {e}")

    result["status"] = "ok"
    return _json_result(result)


async def tool_write_file(args: Dict) -> List[types.TextContent]:
    try:
        get_soap_client().upload_file(
            sandbox=args["sandbox"],
            dir_path=args["path"],
            filename=args["filename"],
            content=args["content"],
        )
        return _text(f"OK: File '{args['path']}/{args['filename']}' written to sandbox '{args['sandbox']}'.")
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_delete_file(args: Dict) -> List[types.TextContent]:
    try:
        get_soap_client().delete_file(args["sandbox"], args["path"])
        return _text(f"OK: File '{args['path']}' deleted from sandbox '{args['sandbox']}'.")
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_validate_graph(args: Dict) -> List[types.TextContent]:
    sandbox    = args["sandbox"]
    graph_path = args["graph_path"]
    timeout_s  = int(args.get("timeout_seconds", POLL_TIMEOUT_S))

    try:
        xml_text = get_soap_client().download_file(sandbox, graph_path)
    except Exception as e:
        return _text(f"ERROR: Could not download graph — {e}")

    # Stage 1
    validator          = GraphValidator(xml_text)
    s1_errors, s1_warns = validator.validate()

    result: Dict[str, Any] = {
        "stage1": {"errors": s1_errors, "warnings": s1_warns},
        "stage2": {"ran": False, "problems": []},
    }

    if s1_errors:
        result["overall"] = "FAIL"
        return _text(json.dumps(result, indent=2))

    # Stage 2
    try:
        handle     = get_soap_client().start_check_config(sandbox, graph_path)
        poll_result = get_soap_client().poll_check_config(handle, timeout_s)
        problems    = get_soap_client().extract_problems(poll_result)
        result["stage2"] = {"ran": True, "problems": problems}
        result["overall"] = "FAIL" if problems else "PASS"
    except TimeoutError as e:
        result["stage2"] = {"ran": True, "error": f"TIMEOUT: {e}", "problems": []}
        result["overall"] = "FAIL"
    except Exception as e:
        result["stage2"] = {"ran": True, "error": str(e), "problems": []}
        result["overall"] = "FAIL"

    return _text(json.dumps(result, indent=2))


async def tool_execute_graph(args: Dict) -> List[types.TextContent]:
    sandbox    = args["sandbox"]
    graph_path = args["graph_path"]
    user_params: Dict[str, str] = args.get("params") or {}
    timeout_s  = int(args.get("timeout_seconds", POLL_TIMEOUT_S))

    # ── Pre-flight: extract graph parameters ───────────────────────────────
    xml_defaults: Dict[str, str] = {}
    required_missing: List[str]  = []
    try:
        graph_xml = get_soap_client().download_file(sandbox, graph_path)
        xml_defaults, no_value_params = _parse_graph_params(graph_xml)
        # Required params: those with no default that the caller also didn't supply
        required_missing = [p for p in no_value_params if p not in user_params]
    except Exception:
        pass  # non-fatal; proceed without param pre-check

    if required_missing:
        # Tell the LLM exactly what's missing and what parameters the graph has
        param_table = []
        for name, val in xml_defaults.items():
            param_table.append(f"  {name} = {val!r}  (has default)")
        for name in (no_value_params if 'no_value_params' in dir() else []):
            supplied = "(supplied by caller)" if name in user_params else "(NO DEFAULT — must be supplied)"
            param_table.append(f"  {name}  {supplied}")
        return _text(
            f"ERROR: Cannot execute graph — {len(required_missing)} required parameter(s) have no value:\n"
            + "\n".join(f"  - {p}" for p in required_missing)
            + "\n\nAll graph parameters:\n"
            + "\n".join(param_table)
            + "\n\nRe-call execute_graph with a 'params' dict supplying the missing values."
        )

    # Merge: XML defaults first, then caller overrides on top
    exec_params = {**xml_defaults, **user_params} if (xml_defaults or user_params) else None

    try:
        run_id = get_soap_client().execute_graph(
            sandbox=sandbox,
            graph_path=graph_path,
            params=exec_params,
            debug=args.get("debug", False),
        )
        status = get_soap_client().poll_execution_status(run_id=run_id, timeout_s=timeout_s)
        return _text(json.dumps(status, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_graph_execution_log(args: Dict) -> List[types.TextContent]:
    try:
        log = get_soap_client().get_execution_log(args["run_id"])
        return _text(log)
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_graph_run_status(args: Dict) -> List[types.TextContent]:
    try:
        status = get_soap_client().get_graph_run_status(args["run_id"])
        return _text(json.dumps(status, indent=2, default=str))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_list_graph_runs(args: Dict) -> List[types.TextContent]:
    try:
        result = get_soap_client().list_graph_runs(
            sandbox=args.get("sandbox"),
            job_file=args.get("job_file"),
            status=args.get("status"),
            limit=int(args.get("limit", 25)),
            start_index=int(args.get("start_index", 0)),
        )
        return _text(json.dumps(result, indent=2, default=str))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_list_components(args: Dict) -> List[types.TextContent]:
    try:
        comps = get_catalog().list_by_category(args.get("category"))
        return _text(ComponentCatalog.format_compact(comps))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_component_info(args: Dict) -> List[types.TextContent]:
    try:
        results = get_catalog().search(
            args["query"],
            include_deprecated=args.get("include_deprecated", False),
        )
        if not results:
            return _text(f"No component found matching '{args['query']}'. "
                         "Use list_components to browse all available types.")
        if len(results) == 1:
            return _text(ComponentCatalog.format_component(results[0]))
        # Multiple matches — compact list
        return _text(
            f"Found {len(results)} components matching '{args['query']}':\n\n"
            + ComponentCatalog.format_compact(results)
            + "\n\nRe-query with an exact type or name to get full details."
        )
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_component_details(args: Dict) -> List[types.TextContent]:
    try:
        key = args["component_type"].strip().upper()
        if not _comp_details_map:
            return _text("No detailed component documentation is available in the comp_details/ directory.")
        if key not in _comp_details_map:
            available = ", ".join(sorted(_comp_details_map.keys()))
            return _text(
                f"No detailed documentation found for '{key}'. "
                f"Available: {available}."
            )
        with open(_comp_details_map[key], encoding="utf-8") as f:
            return _text(f.read())
    except Exception as e:
        return _text(f"ERROR: {e}")


# ── Tool dispatcher ────────────────────────────────────────────────────────────

async def tool_get_graph_tracking(args: Dict) -> List[types.TextContent]:
    try:
        payload = get_soap_client().get_graph_tracking(
            args["run_id"],
            detailed=bool(args.get("detailed", True)),
        )
        return _text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_edge_debug_info(args: Dict) -> List[types.TextContent]:
    try:
        items = get_soap_client().get_edge_debug_info(
            args["sandbox"], args["graph_path"], args["run_id"], args["edge_id"]
        )
        if not items:
            return _text(
                f"No edge debug data found for edge '{args['edge_id']}' in run {args['run_id']}.\n"
                "Ensure the graph was executed with debug=true."
            )
        return _text(json.dumps(items, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_edge_debug_metadata(args: Dict) -> List[types.TextContent]:
    try:
        xml = get_soap_client().get_edge_debug_metadata(
            args["sandbox"], args["graph_path"], args["run_id"], args["edge_id"]
        )
        return _text(xml)
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_list_resources(_args: Dict) -> List[types.TextContent]:
    lines = []
    for uri, meta in _RESOURCE_REGISTRY.items():
        lines.append(f"{uri}")
        lines.append(f"  Name:     {meta['name']}")
        lines.append(f"  Desc:     {meta['description']}")
        lines.append(f"  MimeType: {meta['mimeType']}")
        lines.append("")
    return _text("\n".join(lines).rstrip())


async def tool_read_resource(args: Dict) -> List[types.TextContent]:
    uri = (args.get("uri") or "").strip()
    if not uri:
        return _text("ERROR: 'uri' is required")
    if uri not in _RESOURCE_REGISTRY:
        known = "\n".join(f"  {u}" for u in _RESOURCE_REGISTRY)
        return _text(f"ERROR: Unknown resource URI '{uri}'.\nAvailable URIs:\n{known}")
    try:
        content = await handle_read_resource(uri)
        return _text(content)
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_get_workflow_guide(args: Dict) -> List[types.TextContent]:
    task = str(args.get("task") or "create_graph").strip() or "create_graph"
    guide_path = _WORKFLOW_GUIDE_FILES.get(task)
    if guide_path is None:
        allowed = ", ".join(_WORKFLOW_GUIDE_FILES.keys())
        return _text(f"ERROR: Unknown task '{task}'. Allowed values: {allowed}")

    cache_key = f"workflow:{task}"
    return _text(_load_reference(cache_key, guide_path))


async def tool_get_edge_debug_data(args: Dict) -> List[types.TextContent]:
    try:
        data = get_soap_client().get_edge_debug_data(
            sandbox=args["sandbox"],
            graph_path=args["graph_path"],
            run_id=args["run_id"],
            edge_id=args["edge_id"],
            start_record=int(args.get("start_record", 0)),
            record_count=int(args.get("record_count", 100)),
            filter_expression=args.get("filter_expression", ""),
            field_selection=args.get("field_selection"),
        )
        return _text(data)
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_set_graph_element_attribute(args: Dict) -> List[types.TextContent]:
    graph_path     = args["graph_path"]
    sandbox        = args["sandbox"]
    element_type   = args["element_type"]
    element_id     = args["element_id"]
    attribute_name = args["attribute_name"]
    value          = args["value"]

    # --- Validation ---
    if not attribute_name:
        return _text(json.dumps({"status": "error", "message": "attribute_name must not be empty"}))
    if element_type == "GraphParameter" and attribute_name.startswith("attr:"):
        return _text(json.dumps({
            "status": "error",
            "message": "GraphParameter elements do not have <attr> children. Use plain attribute_name='value'.",
        }))

    _ID_ATTR: Dict[str, str] = {
        "Node": "id", "Edge": "id", "Metadata": "id",
        "Connection": "id", "GraphParameter": "name",
    }
    id_attr = _ID_ATTR[element_type]

    # --- Step 1: Download graph file ---
    try:
        xml_text = get_soap_client().download_file(sandbox, graph_path)
    except Exception:
        return _text(json.dumps({
            "status": "error",
            "message": f"Graph file not found: {graph_path} in sandbox {sandbox}",
        }))

    # --- Steps 2-6: Parse, find, modify, serialize ---
    try:
        from lxml import etree as _lxml  # type: ignore
        _use_lxml = True
    except ImportError:
        _use_lxml = False

    output: str

    if _use_lxml:
        try:
            _parser = _lxml.XMLParser(strip_cdata=False)
            _root = _lxml.fromstring(xml_text.encode("utf-8"), _parser)
        except Exception as exc:
            return _text(json.dumps({"status": "error", "message": f"Graph file is not valid XML: {exc}"}))

        _target = None
        for _elem in _root.iter(element_type):
            if _elem.get(id_attr) == element_id:
                _target = _elem
                break

        if _target is None:
            return _text(json.dumps({"status": "error", "message": (
                f"Element <{element_type} {id_attr}='{element_id}'> not found in {graph_path}"
            )}))

        if element_type == "Metadata":
            if _target.get("fileURL") is not None:
                return _text(json.dumps({"status": "error", "message": (
                    "This Metadata element is external (fileURL). Edit the .fmt file directly."
                )}))
            try:
                _new_record = _lxml.fromstring(value.encode("utf-8"))
            except Exception as exc:
                return _text(json.dumps({"status": "error", "message": (
                    f"value must be a valid <Record>...</Record> XML block: {exc}"
                )}))
            _metadata_inner_indent = _target.text
            _metadata_closing_indent = None
            _existing_children = list(_target)
            if _existing_children:
                _metadata_closing_indent = _existing_children[-1].tail
            for _child in list(_target):
                _target.remove(_child)
            _target.append(_new_record)
            if _metadata_inner_indent is not None:
                _target.text = _metadata_inner_indent
            _new_record.tail = _metadata_closing_indent if _metadata_closing_indent else "\n"

        elif attribute_name.startswith("attr:"):
            _attr_name = attribute_name[len("attr:"):]
            _attr_elem = None
            for _child in _target:
                if _child.tag == "attr" and _child.get("name") == _attr_name:
                    _attr_elem = _child
                    break
            if _attr_elem is None:
                _attr_elem = _lxml.SubElement(_target, "attr")
                _attr_elem.set("name", _attr_name)
            _attr_elem.text = _lxml.CDATA(value)

        else:
            _target.set(attribute_name, value)

        output = _lxml.tostring(
            _root,
            pretty_print=False,
            xml_declaration=True,
            encoding="UTF-8",
        ).decode("UTF-8")

    else:
        # stdlib fallback (lxml not installed)
        import io as _io
        try:
            _root_et = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            return _text(json.dumps({"status": "error", "message": f"Graph file is not valid XML: {exc}"}))

        _target_et = None
        for _elem_et in _root_et.iter(element_type):
            if _elem_et.get(id_attr) == element_id:
                _target_et = _elem_et
                break

        if _target_et is None:
            return _text(json.dumps({"status": "error", "message": (
                f"Element <{element_type} {id_attr}='{element_id}'> not found in {graph_path}"
            )}))

        _cdata_sentinels: Dict[str, str] = {}

        if element_type == "Metadata":
            if _target_et.get("fileURL") is not None:
                return _text(json.dumps({"status": "error", "message": (
                    "This Metadata element is external (fileURL). Edit the .fmt file directly."
                )}))
            try:
                _new_rec_et = ET.fromstring(value)
            except ET.ParseError as exc:
                return _text(json.dumps({"status": "error", "message": (
                    f"value must be a valid <Record>...</Record> XML block: {exc}"
                )}))
            _metadata_inner_indent_et = _target_et.text
            _metadata_closing_indent_et = None
            _existing_children_et = list(_target_et)
            if _existing_children_et:
                _metadata_closing_indent_et = _existing_children_et[-1].tail
            for _child_et in list(_target_et):
                _target_et.remove(_child_et)
            _target_et.append(_new_rec_et)
            if _metadata_inner_indent_et is not None:
                _target_et.text = _metadata_inner_indent_et
            _new_rec_et.tail = _metadata_closing_indent_et if _metadata_closing_indent_et else "\n"

        elif attribute_name.startswith("attr:"):
            _attr_name_et = attribute_name[len("attr:"):]
            _attr_elem_et = None
            for _child_et in _target_et:
                if _child_et.tag == "attr" and _child_et.get("name") == _attr_name_et:
                    _attr_elem_et = _child_et
                    break
            if _attr_elem_et is None:
                _attr_elem_et = ET.SubElement(_target_et, "attr")
                _attr_elem_et.set("name", _attr_name_et)
            _sentinel = f"CDATA_PLACEHOLDER_{id(_attr_elem_et):x}"
            _attr_elem_et.text = _sentinel
            _cdata_sentinels[_sentinel] = value

        else:
            _target_et.set(attribute_name, value)

        _buf = _io.BytesIO()
        ET.ElementTree(_root_et).write(_buf, xml_declaration=True, encoding="UTF-8")
        output = _buf.getvalue().decode("UTF-8")

        for _sentinel, _cdata_val in _cdata_sentinels.items():
            output = output.replace(_sentinel, f"<![CDATA[{_cdata_val}]]>")

    # --- Step 7: Write back ---
    # Both lxml and stdlib ET emit single-quoted XML declarations; normalise to double quotes.
    output = output.replace(
        "<?xml version='1.0' encoding='UTF-8'?>",
        '<?xml version="1.0" encoding="UTF-8"?>',
        1,
    )
    # Preserve original trailing newline (lxml/ET never emit root-element tail).
    if xml_text.endswith("\n") and not output.endswith("\n"):
        output += "\n"
    _dir_path, _filename = os.path.split(graph_path)
    try:
        get_soap_client().upload_file(
            sandbox=sandbox,
            dir_path=_dir_path,
            filename=_filename,
            content=output,
        )
    except Exception as exc:
        return _text(f"ERROR: {exc}")

    return _text(json.dumps({
        "status": "ok",
        "element_type": element_type,
        "element_id": element_id,
        "attribute_name": attribute_name,
        "graph_path": graph_path,
        "sandbox": sandbox,
    }))


_TOOL_MAP = {
    "list_sandboxes":          tool_list_sandboxes,
    "list_files":              tool_list_files,
    "find_file":               tool_find_file,
    "grep_files":              tool_grep_files,
    "list_linked_assets":      tool_list_linked_assets,
    "get_sandbox_parameters":  tool_get_sandbox_parameters,
    "read_file":               tool_read_file,
    "rename_file":             tool_rename_file,
    "copy_file":               tool_copy_file,
    "patch_file":              tool_patch_file,
    "write_file":              tool_write_file,
    "delete_file":             tool_delete_file,
    "validate_graph":          tool_validate_graph,
    "execute_graph":           tool_execute_graph,
    "get_graph_run_status":    tool_get_graph_run_status,
    "list_graph_runs":         tool_list_graph_runs,
    "get_graph_execution_log": tool_get_graph_execution_log,
    "list_components":         tool_list_components,
    "get_component_info":      tool_get_component_info,
    "get_component_details":   tool_get_component_details,
    "get_graph_tracking":      tool_get_graph_tracking,
    "get_edge_debug_info":     tool_get_edge_debug_info,
    "get_edge_debug_metadata": tool_get_edge_debug_metadata,
    "get_edge_debug_data":     tool_get_edge_debug_data,
    "set_graph_element_attribute": tool_set_graph_element_attribute,
    "list_resources":          tool_list_resources,
    "read_resource":           tool_read_resource,
    "get_workflow_guide":      tool_get_workflow_guide,
}


# Keys whose values should never appear in logs (secrets / bulk data).
_LOG_MASKED_KEYS = frozenset({"password", "content", "new_content"})


def _sanitize_log_value(value: Any, key: Optional[str] = None) -> Any:
    if key is not None and key.lower() in _LOG_MASKED_KEYS:
        return "***"
    if isinstance(value, dict):
        return {k: _sanitize_log_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_log_value(item) for item in value]
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + f"…[{len(value)} chars total]"
    return value


def _sanitize_log_args(args: Optional[Dict]) -> Dict:
    """Return a copy of args safe to write to logs."""
    if not args:
        return {}
    return {k: _sanitize_log_value(v, k) for k, v in args.items()}


@app.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    handler = _TOOL_MAP.get(name)
    if handler is None:
        logger.error("Unknown tool '%s'", name)
        return _text(f"ERROR: Unknown tool '{name}'")

    logger.info("Tool call: %s", name)
    logger.debug("Tool call: %s  args=%s", name, _sanitize_log_args(arguments))

    try:
        result = await handler(arguments or {})
        total_chars = sum(len(c.text) for c in result if hasattr(c, "text"))
        logger.debug("Tool result: %s  response_chars=%d", name, total_chars)
        # Log ERROR-level if the tool itself returned an error string
        if result and hasattr(result[0], "text") and result[0].text.startswith("ERROR:"):
            logger.error("Tool %s returned error: %s", name, result[0].text[:200])
        return result
    except Exception as e:
        logger.exception("Unexpected error in tool '%s'", name)
        return _text(f"ERROR: Unexpected error — {e}")


# ── Entry point ────────────────────────────────────────────────────────────────

async def main():
    global soap_client, component_catalog, _comp_details_map

    load_dotenv()

    # ── Configure log level ────────────────────────────────────────────────
    _log_level_str = os.getenv("CLOVERDX_LOG_LEVEL", "INFO").upper()
    _log_level = getattr(logging, _log_level_str, logging.INFO)
    logging.getLogger().setLevel(_log_level)
    for _h in logging.getLogger().handlers:
        _h.setLevel(_log_level)
    logger.info("Log level: %s", _log_level_str)

    base_url   = os.getenv("CLOVERDX_BASE_URL")
    username   = os.getenv("CLOVERDX_USERNAME")
    password   = os.getenv("CLOVERDX_PASSWORD")
    verify_ssl = os.getenv("CLOVERDX_VERIFY_SSL", "false").lower() == "true"

    if not all([base_url, username, password]):
        raise RuntimeError(
            "Missing required environment variables: "
            "CLOVERDX_BASE_URL, CLOVERDX_USERNAME, CLOVERDX_PASSWORD"
        )

    soap_client       = CloverDXSoapClient(str(base_url), str(username), str(password), verify_ssl)
    component_catalog = ComponentCatalog(os.path.join(_SCRIPT_DIR, "resources", "components.json"))
    component_catalog.load()
    _comp_details_map = _scan_comp_details(os.path.join(_SCRIPT_DIR, "comp_details"))

    logger.info(f"Component catalog loaded: {len(component_catalog._components)} components")
    logger.info(f"Component detail docs: {list(_comp_details_map.keys())}")

    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name=SERVER_NAME,
                    server_version=SERVER_VERSION,
                    capabilities=app.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    finally:
        if soap_client:
            soap_client.logout()


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
