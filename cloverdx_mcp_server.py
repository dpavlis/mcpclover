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
  grep_files              – Search file contents across one or more sandboxes by plain string or regex
  list_linked_assets      – List externalized/linkable assets by known file types
  get_sandbox_parameters  – Read/resolve sandbox parameters from workspace.prm (+ optional server overlays)
  read_file               – Download a file or byte range (graph, metadata, params, …)
  rename_file             – Rename a file within a sandbox (RenameSandboxFile)
  copy_file               – Copy a file within/across sandboxes
  patch_file              – Patch a sandbox file using anchor-based line ranges
  write_file              – Upload, overwrite, or append to a file
  delete_file             – Delete a file from a sandbox
  create_directory        – Create a directory in a sandbox
  delete_directory        – Delete a directory from a sandbox

  Resource access
  ───────────────
  list_resources          – List available resource URIs with names and descriptions
  read_resource           – Fetch the content of a resource by URI
  get_workflow_guide      – Return the authoritative workflow guide for a CloverDX task

  Graph operations
  ────────────────
  validate_graph          – Two-stage validation (local XML + server checkConfig)
  execute_graph           – Start a graph run and return run_id immediately
  await_graph_completion  – Wait for a graph run to finish or timeout
  abort_graph_execution   – Abort a running graph by run_id
  list_graph_runs         – List recent executions (REST /executions endpoint)
  get_graph_run_status    – Check the status of a single run by run ID
  get_graph_execution_log – Fetch the execution log for a run
  get_graph_tracking      – Fetch graph tracking metrics for a run
  get_edge_debug_data     – Fetch sample records (+ optional field metadata) from an edge of a debug run
  graph_edit_structure     – Add/delete/move whole elements in a graph (Metadata, Phase, Node, Edge, etc.)
  graph_edit_properties    – Set/replace an attribute or <attr> child on an existing graph element (DOM-based)

  Component reference (local, no server round-trip)
  ──────────────────────────────────────────────────
  list_components         – List available component types (by category)
  get_component_info      – Get ports & properties for a component type/name
  get_component_details   – Fetch detailed markdown docs for a complex component

  Reasoning helper
  ────────────────
  think                   – Log a reasoning thought and return acknowledgement
  plan_graph              – Record graph plan input and return acknowledgement
  note_add                – Append a note under a named section
  note_read               – Read all notes or one note section
  note_clear              – Clear one note section or all notes
  kb_store                – Store/update persistent KB entries in CLV_MCP_KWBASE
  kb_search               – Search KB entries or list a catalog of entries
  kb_read                 – Read one KB entry by name

  CTL tools
  ─────────
  validate_CTL            – Lint CTL2 code via an LLM (OpenAI-compatible API)
  generate_CTL            – Generate CTL2 code/snippets via an LLM (OpenAI-compatible API)

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
  CLOVERDX_LLM_ALLOW  false   (optional, default false; enables validate_CTL and generate_CTL tools)

Dependencies
────────────
  pip install mcp zeep requests python-dotenv urllib3
"""

import asyncio
import codecs
from datetime import date
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
from cloverdx_graph_structure import GraphStructureService, VALID_ELEMENT_TYPES
from cloverdx_soap_client import CloverDXSoapClient
from cloverdx_CTL_generate import validate_CTL as _ctl_validate
from cloverdx_CTL_generate import generate_CTL as _ctl_generate
from cloverdx_CTL_generate import LLM_ALLOW

try:
    from charset_normalizer import from_bytes as _charset_from_bytes
except Exception:
    _charset_from_bytes = None

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
READ_FILE_MAX_RESPONSE_BYTES = 1_048_500  # 1 MiB hard cap for read_file responses (actyally a bit less to leave room for error message in the response if file is too large)
KB_SANDBOX = "CLV_MCP_KWBASE"
KB_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ATTR_CDATA_PROPERTY_TYPES = {
    "aggregationMapping",
    "attachments",
    "barrierFilter",
    "beanWriterMapping",
    "copyFilesErrorOutputMapping",
    "copyFilesInputMapping",
    "copyFilesStandardOutputMapping",
    "createFilesErrorOutputMapping",
    "createFilesInputMapping",
    "createFilesStandardOutputMapping",
    "dataSetReaderOutputMapping",
    "dataSetWriterErrorMapping",
    "dataSetWriterInputMapping",
    "dataSetWriterOutputMapping",
    "dbCloverMapping",
    "dbJoinTransform",
    "deleteFilesErrorOutputMapping",
    "deleteFilesInputMapping",
    "deleteFilesStandardOutputMapping",
    "ediReaderMapping",
    "ediVersion",
    "ediWriterMapping",
    "emailMapping",
    "environment",
    "errorActions",
    "executeGraphInputMapping",
    "executeGraphOutputMapping",
    "executeScriptInputMapping",
    "executeScriptOutputMapping",
    "executeWranglerJobInputMapping",
    "executeWranglerJobOutputMapping",
    "failMapping",
    "filter",
    "genericComponentMultiline",
    "getJobInputMapping",
    "hadoopJobSenderErrorOutputMapping",
    "hadoopJobSenderInputMapping",
    "hadoopJobSenderStandardOutputMapping",
    "hl7ReaderErrorMapping",
    "httpConnectorErrorMapping",
    "httpConnectorInputMapping",
    "httpConnectorOutputMapping",
    "insert",
    "javaBeanReaderMapping",
    "jsonMapping",
    "jsonReaderMapping",
    "jsonWriterMapping",
    "kafkaCommitInputMapping",
    "kafkaReaderOutputMapping",
    "kafkaWriterErrorMapping",
    "kafkaWriterInputMapping",
    "kafkaWriterOutputMapping",
    "killGraphInputMapping",
    "killGraphOutputMapping",
    "listFilesErrorOutputMapping",
    "listFilesInputMapping",
    "listFilesStandardOutputMapping",
    "loopWhileCondition",
    "mapWriterMapping",
    "monitorGraphInputMapping",
    "moveFilesErrorOutputMapping",
    "moveFilesInputMapping",
    "moveFilesStandardOutputMapping",
    "multiline",
    "multilineEditableJava",
    "multilineEditableXML",
    "oauth2Connection",
    "objectIntrospector",
    "properties",
    "propertiesAdv",
    "queryParameters",
    "restApiConnectorDefaultOutputMapping",
    "restApiConnectorHeaderParameters",
    "restApiConnectorInputMapping",
    "restApiConnectorRequestMapping",
    "restApiConnectorRequestParameters",
    "restApiConnectorResponseMapping",
    "restJobErrorMapping",
    "salesforceEinsteinMetadata",
    "salesforceObject",
    "salesforceReaderOutputMapping",
    "salesforceReaderSOQLQuery",
    "salesforceWriterErrorMapping",
    "salesforceWriterInputMapping",
    "salesforceWriterOutputMapping",
    "select",
    "setJobOutputMapping",
    "sleepInputMapping",
    "sql",
    "statefulTransform",
    "statefulTransformMetadata",
    "statefulTransformSelectorProperties",
    "stringList",
    "successMapping",
    "transform",
    "transformDenormalize",
    "transformGenerator",
    "transformNormalize",
    "transformPartition",
    "transformPivot",
    "transformRollup",
    "validatorErrorMapping",
    "validatorRules",
    "wsFaultMapping",
    "wsRequestHeaderStructure",
    "wsRequestStructure",
    "wsResponseMapping",
    "xml",
    "xmlFeatures",
    "xmlMapping",
    "xmlReaderMapping",
    "xmlWriterMapping",
    "xsltMapping",
}

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
    def _split_expr(expr: str, separators: str = r",|") -> List[str]:
        return [part.strip() for part in re.split(f"[{separators}]", expr) if part and part.strip()]

    @staticmethod
    def _build_exclusive_required_groups(properties: List[Dict]) -> List[List[str]]:
        """
        Build groups such as transform|transformURL|transformClass from conditional
        required/redundant expressions.
        """
        groups: Dict[tuple, set] = {}

        for prop in properties:
            name = prop.get("name")
            req_expr = prop.get("required")
            if not name or not isinstance(req_expr, str):
                continue

            req_tokens = ComponentCatalog._split_expr(req_expr, separators=r",")
            if not req_tokens or not all(token.startswith("!") and len(token) > 1 for token in req_tokens):
                continue

            members = {name}
            members.update(token[1:] for token in req_tokens)

            red_expr = prop.get("redundant")
            if isinstance(red_expr, str):
                members.update(ComponentCatalog._split_expr(red_expr, separators=r"\|"))

            key = tuple(sorted(members))
            groups.setdefault(key, set()).add(name)

        ordered: List[List[str]] = []
        for key in sorted(groups.keys()):
            ordered.append(list(key))
        return ordered

    @staticmethod
    def _format_conditional_required(req_expr: str) -> str:
        tokens = ComponentCatalog._split_expr(req_expr, separators=r",")
        if not tokens:
            return ""
        clauses = []
        for token in tokens:
            if token.startswith("!") and len(token) > 1:
                clauses.append(f"{token[1:]} is not set")
            else:
                clauses.append(f"{token} is set")
        return " and ".join(clauses)

    @staticmethod
    def _format_port_name(port: Dict, index: int, is_output: bool) -> str:
        name = (port.get("name") or "").strip()
        if name:
            return name
        ptype = (port.get("type") or "").strip()
        if ptype == "multiplePort":
            return "*"
        return str(index)

    @staticmethod
    def format_component(comp: Dict) -> str:
        """Format a single component for display."""
        lines = [
            f"Type:        {comp.get('type', '')}",
            f"Name:        {comp.get('name', '')}",
            f"Category:    {comp.get('category', '')}",
            f"Description: {comp.get('description') or comp.get('shortDescription', '')}",
        ]

        usage = (comp.get("usage") or "").strip()
        if usage:
            usage_lines = usage.splitlines()
            lines.append(f"Usage:       {usage_lines[0]}")
            for usage_line in usage_lines[1:]:
                lines.append(f"             {usage_line}")

        lines.append("")

        in_ports  = comp.get("inputPorts",  []) or []
        out_ports = comp.get("outputPorts", []) or []
        if in_ports:
            lines.append("Input Ports:")
            for index, p in enumerate(in_ports):
                ptype = (p.get("type") or "").strip()
                if ptype == "multiplePort" and p.get("required"):
                    req = "min 1 required"
                else:
                    req = "required" if p.get("required") else "optional"
                port_name = ComponentCatalog._format_port_name(p, index, is_output=False)
                label = (p.get("label") or "").strip()
                label_part = f" {label}" if label else ""
                lines.append(f"  [{port_name}]{label_part} ({req})")
        if out_ports:
            lines.append("Output Ports:")
            for index, p in enumerate(out_ports):
                ptype = (p.get("type") or "").strip()
                if ptype == "multiplePort" and p.get("required"):
                    req = "min 1 required"
                elif ptype == "multiplePort":
                    req = "optional"
                else:
                    req = "required" if p.get("required") else "optional"
                port_name = ComponentCatalog._format_port_name(p, index, is_output=True)
                label = (p.get("label") or "").strip()
                label_part = f" {label}" if label else ""
                lines.append(f"  [{port_name}]{label_part} ({req})")

        properties = comp.get("properties", []) or []
        if properties:
            lines.append("")
            lines.append("Properties:")

            exclusive_groups = ComponentCatalog._build_exclusive_required_groups(properties)
            grouped_members = {name for group in exclusive_groups for name in group}
            if exclusive_groups:
                lines.append("  Conditional required groups:")
                for group in exclusive_groups:
                    lines.append(
                        "    "
                        + " | ".join(group)
                        + " (at least one is required; mutually exclusive)"
                    )
                lines.append("")

            for prop in properties:
                req = ""
                req_expr = prop.get("required")
                prop_name = prop.get("name", "")
                prop_type = prop.get("type", "")
                if req_expr is True:
                    req = " *required*"
                elif isinstance(req_expr, str) and prop_name not in grouped_members:
                    cond = ComponentCatalog._format_conditional_required(req_expr)
                    req = f" *required when {cond}*" if cond else ""

                attr_cdata = " [attr-cdata]" if prop_type in ATTR_CDATA_PROPERTY_TYPES else ""

                dval = f"  (default: {prop['defaultValue']})" if prop.get("defaultValue") else ""
                desc = (prop.get("description") or "")[:100]
                lines.append(f"  {prop_name}{attr_cdata}{req}: [{prop_type}]{dval}  {desc}")
                if prop_type == "enum" and prop.get("values"):
                    vals = ", ".join(v.get("value", "") for v in prop["values"] if isinstance(v, dict))
                    lines.append(f"    values: {vals}")

        return "\n".join(lines)

    @staticmethod
    def format_compact(comps: List[Dict], use_short_description: bool = True) -> str:
        """Compact listing for multiple results."""
        rows = ["Type | Name | Category | Description"]
        rows.append("-" * 80)
        for c in comps:
            if use_short_description:
                desc = c.get("shortDescription") or c.get("description") or ""
            else:
                desc = c.get("description") or ""
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
_task_notes:       Dict[str, List[str]]         = {}


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


def _today_iso() -> str:
    return date.today().isoformat()


def _kb_split_header_body(raw_text: str) -> tuple[List[str], str]:
    lines = raw_text.splitlines()
    separator_index = None
    for idx, line in enumerate(lines):
        if line.strip() == "---":
            separator_index = idx
            break

    if separator_index is None:
        return lines, ""

    header_lines = lines[:separator_index]
    body = "\n".join(lines[separator_index + 1:])
    return header_lines, body


def _kb_parse_entry(raw_text: str) -> Dict[str, Any]:
    header_lines, body = _kb_split_header_body(raw_text)
    if body.startswith("\n"):
        body = body[1:]
    header: Dict[str, str] = {}
    for line in header_lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        header[key.strip().lower()] = value.strip()

    raw_tags = header.get("tags", "none")
    if raw_tags.lower() == "none":
        tags: List[str] = []
    else:
        tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]

    return {
        "tags": tags,
        "description": header.get("description", ""),
        "created": header.get("created", ""),
        "updated": header.get("updated", ""),
        "content": body,
    }


def _kb_build_entry_markdown(
    tags: List[str],
    description: str,
    created: str,
    updated: str,
    content: str,
) -> str:
    tags_line = ", ".join(tags) if tags else "none"
    return (
        f"tags: {tags_line}\n"
        f"description: {description}\n"
        f"created: {created}\n"
        f"updated: {updated}\n"
        "---\n\n"
        f"{content}"
    )


def _sandbox_item_path(item: Dict[str, Any]) -> str:
    return str(
        item.get("path")
        or item.get("filePath")
        or item.get("name")
        or item.get("fileName")
        or ""
    ).strip().lstrip("/")


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
            description="List all sandboxes on the CloverDX server. Returns sandbox codes and names.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="list_files",
            description=(
                "List files and folders in a sandbox directory. "
                "Set folder_only=true to return directories only."
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
                "Recursively find files in a sandbox by shell-style wildcard (* and ?). "
                "Client-side filtering."
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
                "Search file contents across one or more sandboxes (like grep -rn). "
                "Supports literal or regex matching, optional file glob filtering, "
                "optional path scoping, and optional context lines around matches.\n\n"
                "Examples:\n"
                "- Find graphs using a component: search_string='type=\"VALIDATOR\"', sandboxes=['DWH'], path='graph'\n"
                "- Find metadata usage in multiple sandboxes: search_string='metadata=\"MetaOrder\"', sandboxes=['DWH','QA']\n"
                "- Regex search in CTL files: search_string='function\\s+[A-Za-z_]+', match_mode='regex', file_pattern='*.ctl'\n"
                "- Include one line of context around matches: context_lines=1"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_string": {
                        "type": "string",
                        "description": "Exact string or regex pattern to search for.",
                    },
                    "sandboxes": {
                        "type": "array",
                        "description": "Sandbox codes to search in.",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional directory prefix within each sandbox to search recursively under. "
                            "Defaults to sandbox root."
                        ),
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": (
                            "Optional shell-style wildcard to filter files before content search. "
                            "Defaults to '*' (all files)."
                        ),
                    },
                    "match_mode": {
                        "type": "string",
                        "enum": ["literal", "regex"],
                        "description": "Match mode: literal string match or regex. Default: literal.",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Number of lines to include before and after each matched line. Default: 0.",
                        "minimum": 0,
                    },
                    "max_results_per_sandbox": {
                        "type": "integer",
                        "description": "Maximum number of matches to return per sandbox. Default: 25, max: 200.",
                        "minimum": 1,
                        "maximum": 200,
                    },
                },
                "required": ["search_string", "sandboxes"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="list_linked_assets",
            description=(
                "List reusable assets in a sandbox: metadata (.fmt), connections (.cfg), "
                "lookups (.lkp), CTL (.ctl), sequences (.seq), parameters (.prm). "
                "Call early during graph creation to discover shared assets and their fileURL "
                "paths before defining anything inline. Filter by asset_type to narrow results."
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
                        "description": "Filter: metadata(.fmt), connection(.cfg), lookup(.lkp), ctl(.ctl), sequence(.seq), parameters(.prm), or all (default).",
                    },
                },
                "required": ["sandbox"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_sandbox_parameters",
            description=(
                "Resolve sandbox parameter values (${DATAIN_DIR}, ${DATAOUT_DIR}, ${CONN_DIR}, etc.) "
                "from workspace.prm with optional server-side overlay. "
                "Call before writing file paths into graphs. "
                "Returns resolved values with source provenance and any unresolved placeholders."
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
                "Read a file from a sandbox (.grf, .fmt, .prm, .ctl, etc.). "
                "Optionally read a line range via start_line + line_count. "
                "start_line: 1-based; negative counts from end (-1 = last line). "
                "Optional encoding (defaults to utf-8). "
                "Set encoding='detect' to return detected encoding instead of file content. "
                "Max response: 1 MiB."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path"],
                "properties": {
                    "sandbox": {"type": "string", "description": "Sandbox code"},
                    "path":    {"type": "string", "description": "Full file path within the sandbox (e.g. 'graph/MyGraph.grf')"},
                    "start_line": {
                        "type": "integer",
                        "description": "Optional starting line number. 1-based for positive values; negative values count from end (-1 is last line). Must be provided together with line_count.",
                    },
                    "line_count": {
                        "type": "integer",
                        "description": "Optional number of lines to read. Must be provided together with start_line.",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "Optional text encoding used to decode file content (default: utf-8). Use 'detect' to return only the detected encoding information.",
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="rename_file",
            description=(
                "Rename a file in a sandbox (same directory only). "
                "To move to a different directory, use copy_file + delete_file."
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
                "Copy a file within or across sandboxes. Overwrites destination if it exists. "
                "Always back up a graph (e.g. 'graph/MyGraph.bak.grf') before large edits."
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
                "Patch a sandbox file using anchor-based line replacements. "
                "Each patch locates an anchor string, applies from_offset/to_offset to define the "
                "replacement range, then all patches are applied bottom-up. "
                "Anchor matching is literal against the raw file content after UTF-8 decode; no HTML/XML entity decoding or escaping is applied. "
                "Supports dry_run=true for preview.\n\n"
                "USE FOR: non-graph text files (.ctl, .prm, .csv, .sql, etc.).\n"
                "DO NOT USE FOR graph (.grf) files -- use the graph_edit_* tools instead:\n"
                "  graph_edit_structure  - add/delete/move whole elements (Metadata, Node, Edge, Phase, ...)\n"
                "  graph_edit_properties - set attributes, CTL code, metadata records on existing elements\n"
                "The graph_edit_* tools operate on the XML DOM and are far more reliable for graph edits."
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
                                "anchor": {"type": "string", "description": "Unique literal substring used to locate the target line. Matching is trim-insensitive and does not perform HTML/XML entity decoding."},
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
            name="graph_edit_structure",
            description=(
                "Add, delete, or move whole structural elements in a graph (.grf) via XML DOM.\n"
                "Companion to graph_edit_properties (which sets values on existing elements).\n\n"
                "USE FOR: adding new Metadata/Node/Edge/Phase/Connection/etc., deleting elements,\n"
                "  moving a Node or Edge between Phases.\n"
                "DO NOT USE FOR: changing attribute values, CTL code, or metadata records on\n"
                "  existing elements -- use graph_edit_properties for that.\n\n"
                "Actions:\n"
                "  add    - Insert a new element. Provide full element XML in element_xml.\n"
                "           The tool handles placement and ID uniqueness.\n"
                "  delete - Remove an element by its identity attribute (id or name).\n"
                "  edit   - Move a Node or Edge to a different Phase (target_phase_number).\n\n"
                "Supported element_type values:\n"
                "  Metadata, Phase, Node, Edge, Connection, GraphParameter,\n"
                "  RichTextNote, LookupTable, DictionaryEntry, Sequence\n\n"
                "For add Node/Edge: provide phase_number for the target Phase.\n"
                "For edit (move): provide element_id and target_phase_number.\n"
                "For delete: cascade=true auto-removes dependent elements where supported\n"
                "  (Node -> edges, Metadata -> edges, Connection -> dbConnection attrs,\n"
                "   Phase -> nodes+edges).\n"
                "  LookupTable and Sequence deletions require manual ref cleanup first.\n\n"
                "dry_run=true previews changes without writing the file.\n"
                "Always call validate_graph after structural changes."
            ),
            inputSchema={
                "type": "object",
                "required": ["graph_path", "sandbox", "action", "element_type"],
                "additionalProperties": False,
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to the .grf file within the sandbox (e.g. 'graph/MyGraph.grf').",
                    },
                    "sandbox": {
                        "type": "string",
                        "description": "Sandbox code.",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["add", "delete", "edit"],
                        "description": "Operation: add inserts a new element, delete removes one, edit moves a Node or Edge to another Phase.",
                    },
                    "element_type": {
                        "type": "string",
                        "enum": [
                            "Metadata", "Phase", "Node", "Edge", "Connection",
                            "GraphParameter", "RichTextNote", "LookupTable",
                            "DictionaryEntry", "Sequence",
                        ],
                        "description": "Type of graph element to operate on.",
                    },
                    "element_xml": {
                        "type": "string",
                        "description": (
                            "[add only] Full XML string of the element to insert. "
                            "Must be well-formed XML with the correct root tag for element_type. "
                            "DictionaryEntry expects <Entry .../>. "
                            "The LLM constructs this XML; the tool inserts it as-is."
                        ),
                    },
                    "element_id": {
                        "type": "string",
                        "description": (
                            "[delete and edit] Value of the element's identity attribute. "
                            "For most types this is the 'id' attribute; "
                            "for GraphParameter it is 'name'; "
                            "for Phase it is the 'number' value; "
                            "for DictionaryEntry it is the Entry 'name'."
                        ),
                    },
                    "phase_number": {
                        "type": "integer",
                        "description": "[add Node/Edge only] Phase number to insert into. Required for Node and Edge.",
                    },
                    "target_phase_number": {
                        "type": "integer",
                        "description": "[edit Node/Edge only] Phase number to move the element into.",
                    },
                    "cascade": {
                        "type": "boolean",
                        "description": (
                            "[delete only] When true, automatically remove dependent elements "
                            "(edges when deleting a Node, edges when deleting Metadata, "
                            "dbConnection attrs when deleting a Connection, "
                            "contained nodes+edges when deleting a Phase). Default: false."
                        ),
                    },
                    "validate": {
                        "type": "boolean",
                        "description": "Run Stage 1 local validation after the operation. Default: true. Set false for batch edits.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview what would change without writing the graph file. Default: false.",
                    },
                },
            },
        ),
        types.Tool(
            name="graph_edit_properties",
            description=(
                "Set or update a property value on an existing graph element via XML DOM.\n"
                "Companion to graph_edit_structure (which adds/deletes/moves whole elements).\n\n"
                "USE FOR: changing attributes, CTL code, SQL, join keys, metadata records\n"
                "  on elements that already exist in the graph.\n"
                "DO NOT USE FOR: adding or removing whole elements (Metadata, Node, Edge, Phase, ...)\n"
                "  -- use graph_edit_structure for that.\n\n"
                "Two modes via attribute_name:\n"
                "1. Plain name (e.g. 'recordsNumber', 'joinType', 'fileURL') -> sets XML attribute.\n"
                "   USE THIS for short, simple values. This is the DEFAULT and preferred mode.\n"
                "2. 'attr:' prefix (e.g. 'attr:transform', 'attr:sqlQuery') -> sets <attr> child\n"
                "   with auto CDATA wrapping. Use ONLY when the value is multi-line code\n"
                "   (CTL, SQL, XML) or contains characters unsafe in XML attributes (<, >, &, \").\n"
                "   Do NOT use attr: for short single-value properties like 'enabled', 'joinType',\n"
                "   'recordsNumber', 'fileURL', 'sortKey', etc. -- plain name is correct for those.\n\n"
                "For Metadata: attribute_name='record', value=full <Record>...</Record> XML.\n"
                "External metadata (.fmt files) cannot be modified here.\n"
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
                        "description": "Element type. GraphParameter matches by 'name' attribute; all others match by 'id'.",
                    },
                    "element_id": {
                        "type": "string",
                        "description": "Element identifier. Matches 'id' attribute (or 'name' for GraphParameter).",
                    },
                    "attribute_name": {
                        "type": "string",
                        "description": (
                            "Plain name -> XML attribute. Use for short, simple values -- this is the default. "
                            "Examples: 'recordsNumber', 'fileURL', 'joinType', 'enabled', 'sortKey', 'joinKey'.\n"
                            "'attr:X' -> <attr> CDATA child. Use ONLY for multi-line code (CTL/SQL) or values "
                            "containing XML-unsafe characters (<, >, &, \"). Examples: 'attr:transform', 'attr:sqlQuery'.\n"
                            "For Metadata: use 'record'."
                        ),
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "New value. For plain attributes: simple string. "
                            "For 'attr:': multi-line code or XML-unsafe content -- CDATA auto-wrapped, "
                            "do NOT wrap yourself. "
                            "For Metadata 'record': full <Record>...</Record> XML."
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
                "Create or overwrite a file in a sandbox. "
                "Set append=true to append content to an existing file (useful for chunked large writes). "
                "Append mode adds raw content — no automatic separators or newlines."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path", "filename", "content"],
                "properties": {
                    "sandbox":  {"type": "string", "description": "Sandbox code"},
                    "path":     {"type": "string", "description": "Directory path within the sandbox (e.g. 'graph')"},
                    "filename": {"type": "string", "description": "File name including extension (e.g. 'MyGraph.grf')"},
                    "content":  {"type": "string", "description": "UTF-8 text to write. In overwrite mode this is the full file content; in append mode this chunk is appended as-is."},
                    "append":   {"type": "boolean", "description": "If true, append content to the target file instead of overwriting it (default: false)."},
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
        types.Tool(
            name="create_directory",
            description=(
                "Create a directory in a CloverDX sandbox. "
                "Parent directory must already exist."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path"],
                "properties": {
                    "sandbox": {"type": "string", "description": "Sandbox code"},
                    "path":    {"type": "string", "description": "Directory path to create (e.g. 'graph/archive')."},
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="delete_directory",
            description=(
                "Delete a directory from a CloverDX sandbox. "
                "Use with caution — this is irreversible and may remove nested content."
            ),
            inputSchema={
                "type": "object",
                "required": ["sandbox", "path"],
                "properties": {
                    "sandbox": {"type": "string", "description": "Sandbox code"},
                    "path":    {"type": "string", "description": "Directory path to delete (e.g. 'graph/archive')."},
                },
                "additionalProperties": False,
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
                "Fetch resource content by URI. "
                "URIs: 'cloverdx://reference/graph-xml', 'cloverdx://reference/ctl2', "
                "'cloverdx://reference/subgraphs', 'cloverdx://reference/components'. "
                "Call list_resources first to see all available URIs."
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
                "MUST call at the start of any CloverDX task. Returns the step-by-step workflow "
                "guide with mandatory phases, rules, error fixes, and completion checklist.\n\n"
                "Task types:\n"
                "- 'create_graph': Design and create a new graph (component selection, metadata, XML rules, validation).\n"
                "- 'edit_graph': Modify an existing graph (read-first, patch vs rewrite, re-read between patches).\n"
                "- 'validate_and_run': Validate, execute, verify a graph (Stage 1/2 errors, tracking, logs).\n"
                "Defaults to 'create_graph' if omitted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "enum": ["create_graph", "edit_graph", "validate_and_run"],
                        "description": "Task type. Defaults to 'create_graph'.",
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
                "Validate a graph in two stages:\n"
                "Stage 1: Local XML + metadata check (fast, offline).\n"
                "Stage 2: Server-side checkConfig (deep; runs only if Stage 1 passes).\n"
                "Graph must exist on server (write_file first).\n"
                "IMPORTANT: Errors may not be exhaustive — some block further checks. "
                "Fix reported issues and re-validate until clean."
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
                "Submit a graph for async execution. Returns run_id immediately.\n"
                "Follow-up tools: await_graph_completion (wait), "
                "get_graph_execution_log (logs), get_graph_tracking (record counts).\n"
                "Set debug=true for edge debug data capture."
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
                },
            },
        ),
        types.Tool(
            name="await_graph_completion",
            description=(
                "Block until a graph run completes or timeout is reached. "
                "Returns final status, or current status with timed_out=true on timeout. "
                "Safe to re-call with the same run_id after a timeout."
            ),
            inputSchema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "Run ID returned by execute_graph or list_graph_runs.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Max seconds to wait for completion before returning current status with timed_out=true (default: 600).",
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="abort_graph_execution",
            description=(
                "Abort a running graph execution. "
                "Returns current status if already finished."
            ),
            inputSchema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "Run ID returned by execute_graph or list_graph_runs.",
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="list_graph_runs",
            description=(
                "List recent graph executions. Filter by sandbox, job_file (substring), or status. "
                "Returns run_id, status, timestamps, duration, errors. "
                "Use to find run_ids for other graph tools."
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
                "Quick status check for a graph run (no log fetch). "
                "Statuses: RUNNING, SUCCESS, FAILED, ABORTED, WAITING. "
                "RUNNING includes elapsed time and phase number. "
                "For completed runs, use get_graph_tracking or get_graph_execution_log."
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
                "List available component types, optionally filtered by category and search string. "
                "Search is case-insensitive and supports literal or regex mode."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter",
                        "enum": ["readers", "writers", "transformers", "joiners", "others", "jobControl"],
                    },
                    "search_string": {
                        "type": "string",
                        "description": "Optional case-insensitive search value.",
                    },
                    "match_mode": {
                        "type": "string",
                        "enum": ["literal", "regex"],
                        "description": "Search mode for search_string. Default: literal.",
                    },
                },
            },
        ),
        types.Tool(
            name="get_component_info",
            description=(
                "Get a component's port definitions and configurable properties. "
                "Search by type (e.g. 'EXT_HASH_JOIN') or name (e.g. 'Map'). "
                "Case-insensitive partial match."
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
        *([
            types.Tool(
                name="validate_CTL",
                description=(
                    "Lint CTL2 code via LLM. Optionally provide input/output port metadata for "
                    "field-reference validation ($in.N / $out.N). Label each port by role "
                    "(e.g. 'Port 0 (master)'), not just direction.\n\n"
                    "Checks: regex safety, field reference mismatches, undeclared variables, "
                    "type mismatches, missing returns, unreachable code.\n"
                    "Returns structured ISSUES / SUGGESTIONS / VERDICT."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["code"],
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "CTL2 code to validate (plain text, not XML-escaped).",
                        },
                        "input_metadata": {
                            "type": "string",
                            "description": (
                                "Input port metadata in CloverDX XML format. Must be one or more "
                                "<Metadata id=\"...\"><Record ...><Field .../></Record></Metadata> blocks, "
                                "labeled by port role (e.g. 'Port 0 (master): <Metadata ...>'). "
                                "Used for $in.N field-reference validation."
                            ),
                        },
                        "output_metadata": {
                            "type": "string",
                            "description": (
                                "Output port metadata in CloverDX XML format. Must be one or more "
                                "<Metadata id=\"...\"><Record ...><Field .../></Record></Metadata> blocks, "
                                "labeled by port role (e.g. 'Port 0 (rejected): <Metadata ...>'). "
                                "Used for $out.N field-reference validation."
                            ),
                        },
                        "query": {
                            "type": "string",
                            "description": "Optional focus instruction for the LLM (e.g. 'Focus on the replace() calls').",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "LLM request timeout in seconds (default: 120).",
                        },
                    },
                },
            ),
            types.Tool(
                name="generate_CTL",
                description=(
                    "Generate CTL2 code via LLM from a functional description. "
                    "Produces full transforms, expressions, or snippets. "
                    "Provide input/output port metadata labeled by role for $in.N/$out.N mapping."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["description"],
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "What to generate: full transform, expression, or snippet. Include intended functionality.",
                        },
                        "input_metadata": {
                            "type": "string",
                            "description": (
                                "Input port metadata in CloverDX XML format. Must be one or more "
                                "<Metadata id=\"...\"><Record ...><Field .../></Record></Metadata> blocks, "
                                "labeled by port role (e.g. 'Port 0 (master): <Metadata ...>'). "
                                "Maps to $in.N references."
                            ),
                        },
                        "output_metadata": {
                            "type": "string",
                            "description": (
                                "Output port metadata in CloverDX XML format. Must be one or more "
                                "<Metadata id=\"...\"><Record ...><Field .../></Record></Metadata> blocks, "
                                "labeled by port role (e.g. 'Port 0 (rejected): <Metadata ...>'). "
                                "Maps to $out.N references."
                            ),
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "LLM request timeout in seconds (default: 120).",
                        },
                    },
                },
            ),
        ] if LLM_ALLOW else []),
        types.Tool(
            name="think",
            description=(
                "Log explicit reasoning before acting. Returns acknowledgement only.\n\n"
                "MUST use before:\n"
                "- Choosing between components (reason through criteria)\n"
                "- Writing/editing a graph (plan components, edges, metadata)\n"
                "- Fixing validation errors (diagnose root cause first)\n"
                "- Following a reference graph pattern"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Your reasoning, plan, hypothesis, or decision rationale.",
                    }
                },
                "required": ["thought"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="plan_graph",
            description=(
                "Record a structured graph design plan before writing XML. "
                "Validates internal consistency and surfaces issues before implementation.\n\n"
                "WHEN: After get_workflow_guide + component lookups, BEFORE write_file. "
                "Call list_linked_assets() first to discover existing shared assets.\n\n"
                "Validates:\n"
                "- Edge source/target IDs exist in components[]\n"
                "- CTL components have ctl_entry_points declared\n"
                "- Sort-requiring components (DENORMALIZER, MERGE, DEDUP, EXT_MERGE_JOIN) have upstream sort\n"
                "- Edge metadata_ids exist in metadata[]\n"
                "- Referenced connections/lookups/sequences exist in global_assets\n"
                "Returns plan with consistency warnings."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_name": {
                        "type": "string",
                        "description": "Name of the graph being designed (becomes the 'name' attribute on <Graph>).",
                    },
                    "sandbox": {
                        "type": "string",
                        "description": "Target sandbox code.",
                    },
                    "graph_path": {
                        "type": "string",
                        "description": "Intended file path within the sandbox (e.g. 'graph/MyGraph.grf').",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Brief: source, transformation, and target. Used as graph description.",
                    },
                    "phases": {
                        "type": "array",
                        "description": "Execution phases. Most graphs use single phase 0. Add phases only for sequential dependencies.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "number": {
                                    "type": "integer",
                                    "description": "Phase number (0-based, must be non-decreasing).",
                                },
                                "purpose": {
                                    "type": "string",
                                    "description": "Why this phase is separate from the previous one.",
                                },
                            },
                            "required": ["number"],
                        },
                    },
                    "components": {
                        "type": "array",
                        "description": "All component nodes. Call get_component_info for each type before filling.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Node ID — unique within the graph, ALLCAPS_N convention (e.g. 'ORDER_VALIDATOR').",
                                },
                                "type": {
                                    "type": "string",
                                    "description": "Canonical component type string (e.g. 'REFORMAT', 'VALIDATOR', 'EXT_HASH_JOIN').",
                                },
                                "phase": {
                                    "type": "integer",
                                    "description": "Phase number this component belongs to (default 0).",
                                },
                                "purpose": {
                                    "type": "string",
                                    "description": "What this component does in this specific graph.",
                                },
                                "key_config": {
                                    "type": "string",
                                    "description": (
                                        "The most important configuration note for this component — "
                                        "e.g. 'joinType=leftOuter, joinKey=$0.orderId=$1.id', "
                                        "'sortKey=recordNo(a)', "
                                        "'errorMapping captures $in.1.validationMessage + recordNo'."
                                    ),
                                },
                                "ctl_entry_points": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Required CTL functions (e.g. ['transform()'], ['generate()']). Must declare for any CTL component.",
                                },
                                "debug_input": {
                                    "type": "boolean",
                                    "description": (
                                        "Set true for test-data source nodes in subgraphs "
                                        "(debugInput='true' — disabled when run from parent graph)."
                                    ),
                                },
                                "debug_output": {
                                    "type": "boolean",
                                    "description": (
                                        "Set true for test-data sink nodes in subgraphs "
                                        "(debugOutput='true' — disabled when run from parent graph)."
                                    ),
                                },
                            },
                            "required": ["id", "type", "purpose"],
                        },
                    },
                    "metadata": {
                        "type": "array",
                        "description": "All metadata definitions. Every edge must reference one. Check list_linked_assets() for existing .fmt files first.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Metadata ID referenced on edges (e.g. 'MetaOrder').",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "What records this metadata describes.",
                                },
                                "source": {
                                    "type": "string",
                                    "enum": ["inline", "external", "propagated"],
                                    "description": "'inline'=in-graph <Record>, 'external'=.fmt fileURL (preferred), 'propagated'=auto from connected component.",
                                },
                                "file_url": {
                                    "type": "string",
                                    "description": "Path to .fmt file when source='external' (e.g. 'meta/dwh-loader/input/OrderFileInput.fmt').",
                                },
                                "key_fields": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Key field:type pairs for planning (e.g. ['Order_Id:long', 'recordNo:long']). Not exhaustive.",
                                },
                            },
                            "required": ["id", "description", "source"],
                        },
                    },
                    "edges": {
                        "type": "array",
                        "description": "All edges. Use exact port strings from get_component_info — wrong names cause validation failures.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Edge ID — unique within the graph (e.g. 'Edge0').",
                                },
                                "from_node": {
                                    "type": "string",
                                    "description": "Source component ID.",
                                },
                                "from_port": {
                                    "type": "string",
                                    "description": "outPort string from get_component_info (e.g. 'Port 0 (out)', 'Port 0 (valid)', 'Port 1 (invalid)').",
                                },
                                "to_node": {
                                    "type": "string",
                                    "description": "Target component ID.",
                                },
                                "to_port": {
                                    "type": "string",
                                    "description": "inPort string from get_component_info (e.g. 'Port 0 (in)').",
                                },
                                "metadata_id": {
                                    "type": "string",
                                    "description": "ID of the metadata record flowing on this edge. Must exist in metadata[].",
                                },
                            },
                            "required": ["id", "from_node", "to_node"],
                        },
                    },
                    "global_assets": {
                        "type": "object",
                        "description": "<Global> section assets beyond metadata. Missing declarations cause validation/runtime failures. Call list_linked_assets() first.",
                        "properties": {
                            "connections": {
                                "type": "array",
                                "description": "Database/service connections referenced by component dbConnection attributes.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "Connection ID as used in component dbConnection attribute (e.g. 'DWHConn').",
                                        },
                                        "source": {
                                            "type": "string",
                                            "enum": ["external", "inline"],
                                            "description": "'external'=.cfg fileURL (preferred); 'inline'=embedded in graph.",
                                        },
                                        "file_url": {
                                            "type": "string",
                                            "description": "Path to .cfg file when source='external' (e.g. 'conn/DWHConnection.cfg').",
                                        },
                                        "used_by": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Component IDs that reference this connection.",
                                        },
                                    },
                                    "required": ["id", "source"],
                                },
                            },
                            "lookup_tables": {
                                "type": "array",
                                "description": "Lookup tables for LOOKUP_JOIN or CTL lookup('id').get(...).",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "Lookup table ID as referenced in CTL and LOOKUP_JOIN (e.g. 'ProductLookup').",
                                        },
                                        "type": {
                                            "type": "string",
                                            "enum": ["simpleLookup", "dbLookup", "rangeLookup", "persistentLookup"],
                                            "description": "Lookup table type.",
                                        },
                                        "source": {
                                            "type": "string",
                                            "enum": ["external", "inline"],
                                            "description": "'external' = fileURL to .lkp file; 'inline' = defined in graph.",
                                        },
                                        "file_url": {
                                            "type": "string",
                                            "description": "Path to .lkp file when source='external'.",
                                        },
                                        "used_by": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Component IDs or CTL locations referencing this lookup.",
                                        },
                                    },
                                    "required": ["id", "type", "source"],
                                },
                            },
                            "sequences": {
                                "type": "array",
                                "description": "Sequences for CTL sequence('id').next(). Missing declaration fails at runtime.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "Sequence ID as referenced in CTL (e.g. 'RecordSeq').",
                                        },
                                        "source": {
                                            "type": "string",
                                            "enum": ["external", "inline"],
                                            "description": "'external' = fileURL to .seq file; 'inline' = defined in graph.",
                                        },
                                        "file_url": {
                                            "type": "string",
                                            "description": "Path to .seq file when source='external'.",
                                        },
                                        "start": {
                                            "type": "integer",
                                            "description": "Start value when source='inline' (default 1).",
                                        },
                                        "step": {
                                            "type": "integer",
                                            "description": "Step when source='inline' (default 1).",
                                        },
                                        "used_by": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Component IDs whose CTL calls this sequence.",
                                        },
                                    },
                                    "required": ["id", "source"],
                                },
                            },
                            "ctl_imports": {
                                "type": "array",
                                "description": "External .ctl files via import or transformURL. Check list_linked_assets(asset_type='ctl') first.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "file_url": {
                                            "type": "string",
                                            "description": "Path to .ctl file (e.g. '${TRANS_DIR}/orderValidationRules.ctl').",
                                        },
                                        "provides": {
                                            "type": "string",
                                            "description": "Brief note on what functions this file provides (e.g. 'checkTotalPrice(), campaignChronology()').",
                                        },
                                        "used_by": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Component IDs whose CTL imports this file.",
                                        },
                                    },
                                    "required": ["file_url"],
                                },
                            },
                            "subgraphs": {
                                "type": "array",
                                "description": "SUBGRAPH components. Verify port counts and required parameters before filling.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "component_id": {
                                            "type": "string",
                                            "description": "Node ID of the SUBGRAPH component (e.g. 'EXTRACT').",
                                        },
                                        "job_url": {
                                            "type": "string",
                                            "description": "Path to the .sgrf file (e.g. '${SUBGRAPH_DIR}/readers/OrderFileReader.sgrf').",
                                        },
                                        "input_ports": {
                                            "type": "integer",
                                            "description": "Number of input ports this subgraph exposes (0 for Reader pattern).",
                                        },
                                        "output_ports": {
                                            "type": "integer",
                                            "description": "Number of output ports this subgraph exposes (0 for Writer pattern).",
                                        },
                                        "param_values": {
                                            "type": "object",
                                            "additionalProperties": {"type": "string"},
                                            "description": "__PARAM overrides on the Node (e.g. {'__FILE_URL': '${INPUT_FILE_URL}'}). Required params must appear.",
                                        },
                                    },
                                    "required": ["component_id", "job_url"],
                                },
                            },
                            "parameters": {
                                "type": "array",
                                "description": "Additional graph parameters beyond workspace.prm (which is always linked).",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {
                                            "type": "string",
                                            "description": "Parameter name (e.g. 'INPUT_FILE').",
                                        },
                                        "default_value": {
                                            "type": "string",
                                            "description": "Default value (e.g. '${DATAIN_DIR}/input.xlsx').",
                                        },
                                        "public": {
                                            "type": "boolean",
                                            "description": "Whether exposed as a public parameter (visible in Server UI / parent graph).",
                                        },
                                        "required": {
                                            "type": "boolean",
                                            "description": "Whether a value must be supplied at runtime.",
                                        },
                                        "component_reference": {
                                            "type": "string",
                                            "description": "Component property this param drives (e.g. 'READER.fileURL'). Generates <ComponentReference>.",
                                        },
                                    },
                                    "required": ["name"],
                                },
                            },
                        },
                        "additionalProperties": False,
                    },
                    "risks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Known risks to verify before writing (e.g. sort requirements, CDATA nesting, existing assets to reuse).",
                    },
                    "reference_graphs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Paths to existing graphs consulted as patterns before designing.",
                    },
                },
                "required": ["graph_name", "sandbox", "graph_path", "purpose", "components", "edges"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="note_add",
            description=(
                "Append a note under a named section. "
                "Creates the section when it does not exist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Required section name (e.g. 'metadata', 'assumptions').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Note text to append under the section.",
                    },
                },
                "required": ["section", "content"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="note_read",
            description=(
                "Read notes from working memory. "
                "When section is provided, returns only that section; otherwise returns all sections."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Optional section name to read.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="note_clear",
            description=(
                "Clear notes from working memory. "
                "When section is provided, clears only that section; otherwise clears all sections."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Optional section name to clear.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="kb_store",
            description=(
                "Store a persistent knowledge-base entry. Overwrites existing entries with the same name "
                "so corrections can be recorded across sessions."
            ),
            inputSchema={
                "type": "object",
                "required": ["name", "description", "content"],
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Entry identifier (lowercase kebab-case). Becomes filename without .md.",
                    },
                    "description": {
                        "type": "string",
                        "description": "One-line summary used by catalog and search.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional lowercase tags for categorization.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown body of the knowledge entry.",
                    },
                },
            },
        ),
        types.Tool(
            name="kb_search",
            description=(
                "Search KB entries by query (tags, description, content) or list catalog when query is omitted."
            ),
            inputSchema={
                "type": "object",
                "required": [],
                "additionalProperties": False,
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term. Omit for catalog mode.",
                    },
                    "match_mode": {
                        "type": "string",
                        "enum": ["literal", "regex"],
                        "description": "Search mode. Default: literal.",
                    },
                },
            },
        ),
        types.Tool(
            name="kb_read",
            description="Read a full knowledge-base entry by name.",
            inputSchema={
                "type": "object",
                "required": ["name"],
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Entry name (without .md extension), typically from kb_search results.",
                    },
                },
            },
        ),

        # ── Tracking + edge debug tools ────────────────────────────────────
        types.Tool(
            name="get_graph_tracking",
            description=(
                "Get execution metrics for a completed run: phase timings, per-component "
                "record/byte counts. No debug mode required. "
                "Use to verify data flow (e.g. filter passed expected record count). "
                "Set detailed=false for summary only."
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
            name="get_edge_debug_data",
            description=(
                "Fetch sample records that flowed through an edge during a debug run. "
                "Use to inspect mid-graph data for diagnosing transformation logic — e.g. checking what values reached a component's reject port. "
                "Requires the graph to have been executed with debug=true. "
                "Optionally includes field metadata (names and types) when sandbox and graph_path are provided."
            ),
            inputSchema={
                "type": "object",
                "required": ["run_id", "edge_id"],
                "properties": {
                    "run_id":           {"type": "string",  "description": "Run ID returned by execute_graph"},
                    "edge_id":          {"type": "string",  "description": "Edge ID as defined in the graph XML"},
                    "record_count":     {"type": "integer", "description": "Max number of records to return (default: 50)."},
                    "from_rec":         {"type": "integer", "description": "Zero-based index of the first record to return (default: 0)."},
                    "sandbox":          {"type": "string",  "description": "Sandbox code. When provided together with graph_path, field metadata (names/types) is included in the response."},
                    "graph_path":       {"type": "string",  "description": "Path to the .grf file. When provided together with sandbox, field metadata (names/types) is included in the response."},
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
    try:
        search_string = str(args["search_string"])
        sandboxes = args["sandboxes"]
        if not isinstance(sandboxes, list) or not sandboxes:
            return _text("ERROR: 'sandboxes' must be a non-empty list of sandbox codes")

        sandbox_codes = [str(sb).strip() for sb in sandboxes if str(sb).strip()]
        if not sandbox_codes:
            return _text("ERROR: 'sandboxes' must contain at least one non-empty sandbox code")

        path = str(args.get("path") or "").strip()
        file_pattern = str(args.get("file_pattern") or "*").strip() or "*"
        match_mode = str(args.get("match_mode") or "literal").strip().lower() or "literal"
        if match_mode not in {"literal", "regex"}:
            return _text("ERROR: 'match_mode' must be either 'literal' or 'regex'")

        context_lines = max(int(args.get("context_lines", 0)), 0)
        max_results_per_sandbox = min(max(int(args.get("max_results_per_sandbox", 25)), 1), 200)

        client = get_soap_client()

        compiled_pattern = None
        if match_mode == "regex":
            try:
                compiled_pattern = re.compile(search_string)
            except re.error as rx:
                return _text(f"ERROR: Invalid regex in search_string: {rx}")

        all_results: List[Dict[str, Any]] = []
        total_matches = 0
        truncated = False
        for sandbox in sandbox_codes:
            candidate_files = client.find_files(
                sandbox=sandbox,
                pattern=file_pattern,
                path=path,
            )

            sandbox_match_count = 0

            for item in candidate_files:
                if sandbox_match_count >= max_results_per_sandbox:
                    truncated = True
                    break

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

                for lineno, line in enumerate(lines, start=1):
                    is_match = False
                    if match_mode == "regex":
                        if compiled_pattern and compiled_pattern.search(line):
                            is_match = True
                    else:
                        if search_string in line:
                            is_match = True

                    if not is_match:
                        continue

                    start_index = max(0, lineno - 1 - context_lines)
                    end_index = min(len(lines), lineno + context_lines)

                    context: List[Dict[str, Any]] = []
                    for i in range(start_index, end_index):
                        context_item: Dict[str, Any] = {
                            "line": i + 1,
                            "content": lines[i],
                        }
                        if i + 1 == lineno:
                            context_item["match"] = True
                        context.append(context_item)

                    all_results.append({
                        "sandbox": sandbox,
                        "file_path": file_path,
                        "line_number": lineno,
                        "context": context,
                    })

                    sandbox_match_count += 1
                    total_matches += 1

                    if sandbox_match_count >= max_results_per_sandbox:
                        truncated = True
                        break

        payload = {
            "total_matches": total_matches,
            "truncated": truncated,
            "results": all_results,
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
    def _canonical_detect_label(name: str) -> Optional[str]:
        normalized = re.sub(r"[^a-z0-9]", "", (name or "").lower())
        aliases = {
            "utf8": "utf-8",
            "utf8sig": "utf-8-sig",
            "utf16": "utf-16",
            "utf16le": "utf-16-le",
            "utf16be": "utf-16-be",
            "utf32": "utf-32",
            "utf32le": "utf-32-le",
            "utf32be": "utf-32-be",
            "iso88591": "ISO-8859-1",
            "latin1": "ISO-8859-1",
            "l1": "ISO-8859-1",
            "iso88592": "ISO-8859-2",
            "latin2": "ISO-8859-2",
            "l2": "ISO-8859-2",
            "windows1250": "Windows-1250",
            "cp1250": "Windows-1250",
            "windows1252": "Windows-1252",
            "cp1252": "Windows-1252",
            "iso88595": "ISO-8859-5",
            "windows1251": "Windows-1251",
            "cp1251": "Windows-1251",
            "cp500": "EBCDIC-CP500",
            "ibm500": "EBCDIC-CP500",
            "cp037": "EBCDIC-CP500",
            "ibm037": "EBCDIC-CP500",
            "ebcdiccp500": "EBCDIC-CP500",
        }
        return aliases.get(normalized)

    def _looks_ebcdic(raw_bytes: bytes) -> bool:
        if not raw_bytes:
            return False
        ascii_printable = sum(1 for b in raw_bytes if b in (9, 10, 13) or 32 <= b <= 126)
        ascii_ratio = ascii_printable / len(raw_bytes)
        space_40 = raw_bytes.count(0x40)
        space_20 = raw_bytes.count(0x20)
        try:
            ebcdic_text = raw_bytes.decode("cp500", errors="ignore")
        except Exception:
            return False
        if not ebcdic_text:
            return False
        ebcdic_printable = sum(1 for ch in ebcdic_text if ch in "\r\n\t" or ch.isprintable())
        ebcdic_ratio = ebcdic_printable / len(ebcdic_text)
        return ascii_ratio < 0.2 and ebcdic_ratio > 0.9 and space_40 > 0 and space_40 > (space_20 * 2)

    def _decoded_quality_score(text: str) -> float:
        if not text:
            return 0.0
        controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
        non_printable = sum(1 for ch in text if not (ch in "\r\n\t" or ch.isprintable()))
        replacement = text.count("\ufffd")
        nul_count = text.count("\x00")
        return controls * 8.0 + non_printable * 6.0 + replacement * 10.0 + nul_count * 8.0

    def _count_chars(text: str, chars: str) -> int:
        bag = set(chars)
        return sum(1 for ch in text if ch in bag)

    def _detect_text_encoding(raw_bytes: bytes) -> str:
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if raw_bytes.startswith(b"\xff\xfe\x00\x00"):
            return "utf-32-le"
        if raw_bytes.startswith(b"\x00\x00\xfe\xff"):
            return "utf-32-be"
        if raw_bytes.startswith(b"\xff\xfe"):
            return "utf-16-le"
        if raw_bytes.startswith(b"\xfe\xff"):
            return "utf-16-be"

        if not raw_bytes:
            return "utf-8"

        try:
            raw_bytes.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass

        # Heuristic for UTF-16 without BOM using NUL byte distribution.
        even_nuls = raw_bytes[0::2].count(0)
        odd_nuls = raw_bytes[1::2].count(0)
        nul_threshold = max(1, len(raw_bytes) // 10)
        if odd_nuls > even_nuls and odd_nuls >= nul_threshold:
            return "utf-16-le"
        if even_nuls > odd_nuls and even_nuls >= nul_threshold:
            return "utf-16-be"

        if _looks_ebcdic(raw_bytes):
            return "EBCDIC-CP500"

        detector_hint: Optional[str] = None
        if _charset_from_bytes is not None:
            try:
                best = _charset_from_bytes(raw_bytes).best()
                if best and best.encoding:
                    mapped = _canonical_detect_label(best.encoding)
                    if mapped:
                        detector_hint = mapped
            except Exception:
                pass

        # Best-effort scoring for common legacy single-byte encodings.
        candidates = [
            ("ISO-8859-1", "iso-8859-1"),
            ("ISO-8859-2", "iso-8859-2"),
            ("Windows-1250", "cp1250"),
            ("Windows-1252", "cp1252"),
            ("ISO-8859-5", "iso-8859-5"),
            ("Windows-1251", "cp1251"),
            ("EBCDIC-CP500", "cp500"),
        ]

        cyrillic_pref = "оеаинтсрвлкмдпуяыьгзбчйхжшюцщэфъё"
        latin2_pref = "ąćęłńóśźżčďěňřšťůžĄĆĘŁŃÓŚŹŻČĎĚŇŘŠŤŮŽ"
        latin1_pref = "àáâãäåæçèéêëìíîïñòóôõöøùúûüýþÿÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝÞ"

        best_label = "ISO-8859-1"
        best_score = float("inf")
        has_c1_bytes = any(0x80 <= b <= 0x9F for b in raw_bytes)
        ascii_alpha = sum(1 for b in raw_bytes if 65 <= b <= 90 or 97 <= b <= 122)
        ascii_alpha_ratio = ascii_alpha / max(1, len(raw_bytes))
        cp1252_signature_bytes = {
            0x80, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
            0x8B, 0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9B,
        }
        cp1250_signature_bytes = {0x8A, 0x8C, 0x8D, 0x8E, 0x9A, 0x9C, 0x9D, 0x9E, 0x9F}
        cp1252_signature_count = sum(1 for b in raw_bytes if b in cp1252_signature_bytes)
        cp1250_signature_count = sum(1 for b in raw_bytes if b in cp1250_signature_bytes)

        for label, codec_name in candidates:
            try:
                text = raw_bytes.decode(codec_name)
            except Exception:
                continue

            score = _decoded_quality_score(text)

            cyr_score = _count_chars(text.lower(), cyrillic_pref)
            latin2_score = _count_chars(text, latin2_pref)
            latin1_score = _count_chars(text, latin1_pref)

            if label in {"Windows-1251", "ISO-8859-5"} and cyr_score > 0:
                score -= min(6.0, cyr_score / 3.0)
            if label in {"Windows-1250", "ISO-8859-2"} and latin2_score > 0:
                score -= min(6.0, latin2_score / 3.0)
            if label == "ISO-8859-1" and latin1_score > 0:
                score -= min(4.0, latin1_score / 4.0)

            if ascii_alpha_ratio > 0.28 and label in {"Windows-1251", "ISO-8859-5"}:
                score += 4.0
            if ascii_alpha_ratio < 0.12 and label in {"ISO-8859-1", "ISO-8859-2", "Windows-1250", "Windows-1252"}:
                score += 2.0

            if has_c1_bytes:
                if label == "Windows-1252" and cp1252_signature_count > 0:
                    score -= min(3.0, cp1252_signature_count * 0.7)
                if label == "Windows-1250" and cp1250_signature_count > 0:
                    score -= min(3.0, cp1250_signature_count * 0.7)
                if label == "Windows-1251" and cp1252_signature_count == 0 and cp1250_signature_count == 0 and ascii_alpha_ratio < 0.18:
                    score -= 1.5
            else:
                if label == "ISO-8859-2" and latin2_score > 0:
                    score -= 0.8
                if label == "ISO-8859-5" and cyr_score > 0:
                    score -= 0.8

            if has_c1_bytes and label in {"ISO-8859-1", "ISO-8859-2", "ISO-8859-5"}:
                # C1 bytes often indicate Windows code pages rather than ISO-8859 variants.
                score += 1.5

            if detector_hint and label == detector_hint:
                score -= 0.5

            if score < best_score:
                best_score = score
                best_label = label

        return best_label

    try:
        raw_content = get_soap_client().download_file_bytes(args["sandbox"], args["path"])

        def _is_over_limit(text: str) -> bool:
            return len(text.encode("utf-8")) > READ_FILE_MAX_RESPONSE_BYTES

        encoding = str(args.get("encoding", "utf-8"))
        if not encoding:
            encoding = "utf-8"

        if encoding.lower() == "detect":
            return _text(_detect_text_encoding(raw_content))

        try:
            codecs.lookup(encoding)
        except LookupError:
            return _text(f"ERROR: unknown encoding '{encoding}'.")

        try:
            content = raw_content.decode(encoding)
        except UnicodeDecodeError as e:
            return _text(
                "ERROR: could not decode file with encoding "
                f"'{encoding}': {e}. Try encoding='detect' to inspect the file encoding."
            )

        start_line = args.get("start_line")
        line_count = args.get("line_count")
        partial_requested = start_line is not None or line_count is not None

        if partial_requested:
            if start_line is None or line_count is None:
                return _text("ERROR: start_line and line_count must both be provided when requesting a partial read.")

            start_line = int(start_line)
            line_count = int(line_count)

            if start_line == 0:
                return _text("ERROR: start_line cannot be 0. Use 1-based values or negative values to count from end.")
            if line_count < 0:
                return _text("ERROR: line_count must be a non-negative integer.")

            lines = content.splitlines(keepends=True)
            total_lines = len(lines)

            if start_line > 0:
                start_index = start_line - 1
            else:
                start_index = total_lines + start_line

            start_index = max(0, min(start_index, total_lines))
            end_index = min(start_index + line_count, total_lines)

            partial_content = "".join(lines[start_index:end_index])
            if _is_over_limit(partial_content):
                return _text(
                    "<!ERROR>: read_file response exceeds 1 MiB limit. "
                    "Request fewer lines using start_line/line_count."
                )

            return _text(partial_content)

        if _is_over_limit(content):
            return _text(
                "<!ERROR>: read_file response exceeds 1 MiB limit. "
                "Use start_line and line_count for a partial read."
            )

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

    client = get_soap_client()

    try:
        if hasattr(client, "download_file_bytes"):
            original_bytes = client.download_file_bytes(sandbox, path)
            original_content = original_bytes.decode("utf-8", errors="surrogateescape")
        else:
            original_content = client.download_file(sandbox, path)
            original_bytes = original_content.encode("utf-8")
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

    line_sep = "\r\n" if b"\r\n" in original_bytes else "\n"
    had_trailing_newline = original_bytes.endswith((b"\n", b"\r"))
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
        client.upload_file(
            sandbox=sandbox,
            dir_path=dir_path,
            filename=filename,
            content=updated_content.encode("utf-8", errors="surrogateescape"),
        )
    except Exception as e:
        return _text(f"ERROR: {e}")

    result["status"] = "ok"
    return _json_result(result)


async def tool_write_file(args: Dict) -> List[types.TextContent]:
    try:
        append = bool(args.get("append", False))
        client = get_soap_client()
        if append:
            client.append_file(
                sandbox=args["sandbox"],
                dir_path=args["path"],
                filename=args["filename"],
                content=args["content"],
            )
            return _text(
                f"OK: Content appended to '{args['path']}/{args['filename']}' in sandbox '{args['sandbox']}'."
            )

        client.upload_file(
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


async def tool_create_directory(args: Dict) -> List[types.TextContent]:
    try:
        get_soap_client().create_directory(args["sandbox"], args["path"])
        return _text(f"OK: Directory '{args['path']}' created in sandbox '{args['sandbox']}'.")
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_delete_directory(args: Dict) -> List[types.TextContent]:
    try:
        get_soap_client().delete_directory(args["sandbox"], args["path"])
        return _text(f"OK: Directory '{args['path']}' deleted from sandbox '{args['sandbox']}'.")
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

    # ── Pre-flight: extract graph parameters ───────────────────────────────
    xml_defaults: Dict[str, str] = {}
    required_missing: List[str]  = []
    no_value_params: List[str] = []
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
        payload = {
            "run_id": str(run_id),
            "status": "SUBMITTED",
            "sandbox": sandbox,
            "graph_path": graph_path,
            "debug": bool(args.get("debug", False)),
            "parameters_supplied": sorted(exec_params.keys()) if exec_params else [],
        }
        return _text(json.dumps(payload, indent=2))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_await_graph_completion(args: Dict) -> List[types.TextContent]:
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return _text("ERROR: 'run_id' is required")

    timeout_s = int(args.get("timeout_seconds") or 600)
    try:
        payload = get_soap_client().await_graph_completion(run_id=run_id, timeout_s=timeout_s)
        return _text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        return _text(f"ERROR: {e}")


async def tool_abort_graph_execution(args: Dict) -> List[types.TextContent]:
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return _text("ERROR: 'run_id' is required")

    try:
        payload = get_soap_client().abort_graph_execution(run_id=run_id)
        return _text(json.dumps(payload, indent=2, default=str))
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
        category = args.get("category")
        comps = get_catalog().list_by_category(category)

        search_string = str(args.get("search_string") or "").strip()
        match_mode = str(args.get("match_mode") or "literal").strip().lower() or "literal"
        if match_mode not in {"literal", "regex"}:
            return _text("ERROR: 'match_mode' must be either 'literal' or 'regex'")

        if search_string:
            filtered: List[Dict] = []
            compiled = None
            if match_mode == "regex":
                try:
                    compiled = re.compile(search_string, flags=re.IGNORECASE)
                except re.error as rx:
                    return _text(f"ERROR: Invalid regex in search_string: {rx}")

            for comp in comps:
                fields = [
                    str(comp.get("type") or ""),
                    str(comp.get("name") or ""),
                    str(comp.get("category") or ""),
                    str(comp.get("shortDescription") or ""),
                    str(comp.get("description") or ""),
                ]
                if match_mode == "regex":
                    if compiled and any(compiled.search(field) for field in fields):
                        filtered.append(comp)
                else:
                    needle = search_string.lower()
                    if any(needle in field.lower() for field in fields):
                        filtered.append(comp)

            comps = filtered

        # For category-filtered output, always show full description field.
        use_short_description = category is None
        return _text(ComponentCatalog.format_compact(comps, use_short_description=use_short_description))
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


async def tool_validate_CTL(args: Dict) -> List[types.TextContent]:
    code = str(args.get("code") or "").strip()
    if not code:
        return _text("ERROR: 'code' is required")
    input_metadata = args.get("input_metadata") or None
    output_metadata = args.get("output_metadata") or None
    query = args.get("query") or None
    timeout = int(args.get("timeout") or 120)
    try:
        result = _ctl_validate(
            code=code,
            input_metadata=input_metadata,
            output_metadata=output_metadata,
            query=query,
            timeout=timeout,
        )
        return _text(result)
    except RuntimeError as exc:
        return _text(f"ERROR: {exc}")


async def tool_generate_CTL(args: Dict) -> List[types.TextContent]:
    description = str(args.get("description") or "").strip()
    if not description:
        return _text("ERROR: 'description' is required")
    input_metadata = args.get("input_metadata") or None
    output_metadata = args.get("output_metadata") or None
    timeout = int(args.get("timeout") or 120)
    try:
        result = _ctl_generate(
            description=description,
            input_metadata=input_metadata,
            output_metadata=output_metadata,
            timeout=timeout,
        )
        return _text(result)
    except RuntimeError as exc:
        return _text(f"ERROR: {exc}")


async def tool_think(args: Dict) -> List[types.TextContent]:
    thought = str(args.get("thought") or "").strip()
    if not thought:
        return _text("ERROR: 'thought' is required")
    logger.info("think tool received thought (%d chars)", len(thought))
    return _text("Acknowledged. Thought received.")


async def tool_plan_graph(args: Dict) -> List[types.TextContent]:
    graph_name = str(args.get("graph_name") or "").strip()
    if not graph_name:
        return _text("ERROR: 'graph_name' is required")
    logger.info("plan_graph tool received plan for graph '%s'", graph_name)
    #TODO: implement actual validation of the graph plan structure and content
    return _text("Graph plan received. No obvious issues detected.")


async def tool_note_add(args: Dict) -> List[types.TextContent]:
    section = str(args.get("section") or "").strip()
    if not section:
        return _text("ERROR: 'section' is required")

    content = str(args.get("content") or "").strip()
    if not content:
        return _text("ERROR: 'content' is required")

    notes_in_section = _task_notes.setdefault(section, [])
    notes_in_section.append(content)
    logger.info("note_add section='%s' notes_in_section=%d", section, len(notes_in_section))

    return _text(json.dumps({
        "status": "ok",
        "section": section,
        "notes_in_section": len(notes_in_section),
    }, indent=2))


async def tool_note_read(args: Dict) -> List[types.TextContent]:
    section_arg = args.get("section")
    if section_arg is not None:
        section = str(section_arg).strip()
        if not section:
            return _text("ERROR: 'section' must be non-empty when provided")

        notes = list(_task_notes.get(section, []))
        return _text(json.dumps({
            "section": section,
            "notes": notes,
            "count": len(notes),
        }, indent=2))

    note_count = sum(len(notes) for notes in _task_notes.values())
    return _text(json.dumps({
        "sections": _task_notes,
        "section_count": len(_task_notes),
        "note_count": note_count,
    }, indent=2))


async def tool_note_clear(args: Dict) -> List[types.TextContent]:
    section_arg = args.get("section")
    if section_arg is not None:
        section = str(section_arg).strip()
        if not section:
            return _text("ERROR: 'section' must be non-empty when provided")

        cleared = section in _task_notes
        _task_notes.pop(section, None)
        logger.info("note_clear section='%s' cleared=%s", section, cleared)

        return _text(json.dumps({
            "status": "ok",
            "scope": "section",
            "section": section,
            "cleared": cleared,
        }, indent=2))

    sections_cleared = len(_task_notes)
    notes_cleared = sum(len(notes) for notes in _task_notes.values())
    _task_notes.clear()
    logger.info("note_clear all sections=%d notes=%d", sections_cleared, notes_cleared)

    return _text(json.dumps({
        "status": "ok",
        "scope": "all",
        "sections_cleared": sections_cleared,
        "notes_cleared": notes_cleared,
    }, indent=2))


async def tool_kb_store(args: Dict) -> List[types.TextContent]:
    name = str(args.get("name") or "").strip()
    if not name:
        return _text(json.dumps({"status": "error", "message": "'name' is required"}, indent=2))
    if not KB_NAME_RE.fullmatch(name):
        return _text(json.dumps({
            "status": "error",
            "message": f"Invalid name: '{name}'. Use lowercase kebab-case (a-z, 0-9, hyphens only).",
        }, indent=2))

    description = str(args.get("description") or "").strip()
    if not description:
        return _text(json.dumps({"status": "error", "message": "'description' is required"}, indent=2))

    content = str(args.get("content") or "")
    if not content:
        return _text(json.dumps({"status": "error", "message": "'content' is required"}, indent=2))

    tags_value = args.get("tags")
    if tags_value is None:
        tags: List[str] = []
    elif isinstance(tags_value, list):
        tags = [str(tag).strip().lower() for tag in tags_value if str(tag).strip()]
    else:
        return _text(json.dumps({"status": "error", "message": "'tags' must be an array when provided"}, indent=2))

    file_name = f"{name}.md"
    client = get_soap_client()
    created = _today_iso()
    updated = _today_iso()
    action = "created"
    previous_created: Optional[str] = None

    try:
        existing_raw = client.download_file(KB_SANDBOX, file_name)
        existing_entry = _kb_parse_entry(existing_raw)
        if existing_entry.get("created"):
            created = str(existing_entry["created"])
        action = "updated"
        previous_created = created
    except Exception:
        pass

    entry_text = _kb_build_entry_markdown(
        tags=tags,
        description=description,
        created=created,
        updated=updated,
        content=content,
    )

    try:
        client.upload_file(
            sandbox=KB_SANDBOX,
            dir_path="",
            filename=file_name,
            content=entry_text,
        )
    except Exception as e:
        return _text(f"ERROR: {e}")

    payload: Dict[str, Any] = {
        "status": "ok",
        "name": name,
        "action": action,
        "sandbox": KB_SANDBOX,
        "path": file_name,
    }
    if previous_created is not None:
        payload["previous_created"] = previous_created
    return _text(json.dumps(payload, indent=2))


async def tool_kb_search(args: Dict) -> List[types.TextContent]:
    query = str(args.get("query") or "").strip()
    match_mode = str(args.get("match_mode") or "literal").strip().lower() or "literal"
    if match_mode not in {"literal", "regex"}:
        return _text(json.dumps({"status": "error", "message": "'match_mode' must be 'literal' or 'regex'"}, indent=2))

    client = get_soap_client()

    if not query:
        try:
            files = client.list_files(sandbox=KB_SANDBOX, path="", folder_only=False)
        except Exception as e:
            return _text(f"ERROR: {e}")

        entries: List[Dict[str, Any]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            if bool(item.get("isFolder") or item.get("folder")):
                continue

            file_path = _sandbox_item_path(item)
            base_name = os.path.basename(file_path)
            if not base_name.endswith(".md"):
                continue

            try:
                raw_text = client.download_file(KB_SANDBOX, file_path)
            except Exception:
                continue

            parsed = _kb_parse_entry(raw_text)
            entries.append({
                "name": os.path.splitext(base_name)[0],
                "tags": parsed["tags"],
                "description": parsed["description"],
                "created": parsed["created"],
                "updated": parsed["updated"],
            })

        entries.sort(key=lambda entry: entry["name"])
        return _text(json.dumps({
            "mode": "catalog",
            "entries": entries,
            "entry_count": len(entries),
        }, indent=2))

    compiled_pattern = None
    if match_mode == "regex":
        try:
            compiled_pattern = re.compile(query)
        except re.error as rx:
            return _text(json.dumps({"status": "error", "message": f"Invalid regex in query: {rx}"}, indent=2))

    try:
        candidates = client.find_files(sandbox=KB_SANDBOX, pattern="*.md", path="")
    except Exception as e:
        return _text(f"ERROR: {e}")

    grouped: Dict[str, Dict[str, Any]] = {}
    match_count = 0
    max_results_per_sandbox = 50

    for item in candidates:
        if match_count >= max_results_per_sandbox:
            break

        if not isinstance(item, dict):
            continue
        file_path = _sandbox_item_path(item)
        if not file_path.endswith(".md"):
            continue

        try:
            raw_text = client.download_file(KB_SANDBOX, file_path)
        except Exception:
            continue

        parsed = _kb_parse_entry(raw_text)
        lines = raw_text.splitlines()

        for line_idx, line in enumerate(lines, start=1):
            if match_count >= max_results_per_sandbox:
                break

            if match_mode == "regex":
                is_match = bool(compiled_pattern and compiled_pattern.search(line))
            else:
                is_match = query in line
            if not is_match:
                continue

            entry_name = os.path.splitext(os.path.basename(file_path))[0]
            if entry_name not in grouped:
                grouped[entry_name] = {
                    "name": entry_name,
                    "tags": parsed["tags"],
                    "description": parsed["description"],
                    "matches": [],
                }

            context: List[Dict[str, Any]] = []
            prev_idx = line_idx - 2
            next_idx = line_idx
            if prev_idx >= 0:
                context.append({"line": prev_idx + 1, "content": lines[prev_idx]})
            if next_idx < len(lines):
                context.append({"line": next_idx + 1, "content": lines[next_idx]})

            grouped[entry_name]["matches"].append({
                "line_number": line_idx,
                "content": line,
                "context": context,
            })
            match_count += 1

    results = sorted(grouped.values(), key=lambda entry: entry["name"])
    return _text(json.dumps({
        "mode": "search",
        "query": query,
        "match_mode": match_mode,
        "results": results,
        "result_count": len(results),
    }, indent=2))


async def tool_kb_read(args: Dict) -> List[types.TextContent]:
    name = str(args.get("name") or "").strip()
    if not name:
        return _text(json.dumps({"status": "error", "message": "'name' is required"}, indent=2))

    file_name = f"{name}.md"
    try:
        raw_text = get_soap_client().download_file(KB_SANDBOX, file_name)
    except Exception:
        return _text(json.dumps({
            "status": "error",
            "message": f"Knowledge entry '{name}' not found. Use kb_search() to list available entries.",
        }, indent=2))

    parsed = _kb_parse_entry(raw_text)
    return _text(json.dumps({
        "name": name,
        "tags": parsed["tags"],
        "description": parsed["description"],
        "created": parsed["created"],
        "updated": parsed["updated"],
        "content": parsed["content"],
    }, indent=2))


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


async def tool_get_edge_debug_data(args: Dict) -> List[types.TextContent]:
    """Combined edge debug tool: fetches sample records and optionally field metadata."""
    run_id   = args["run_id"]
    edge_id  = args["edge_id"]
    sandbox    = (args.get("sandbox") or "").strip()
    graph_path = (args.get("graph_path") or "").strip()
    record_count = int(args.get("record_count", 50))
    from_rec     = int(args.get("from_rec", 0))

    parts: List[str] = []

    # ── Optional: fetch field metadata when sandbox + graph_path given ──
    if sandbox and graph_path:
        try:
            meta_xml = get_soap_client().get_edge_debug_metadata(
                sandbox, graph_path, run_id, edge_id
            )
            if meta_xml and meta_xml.strip() and not meta_xml.startswith("No edge debug"):
                parts.append("## Field Metadata\n")
                parts.append(meta_xml.strip())
                parts.append("")
        except Exception as meta_err:
            parts.append(f"(metadata unavailable: {meta_err})\n")

    # ── Fetch actual records ───────────────────────────────────────────
    try:
        data = get_soap_client().get_edge_debug_data(
            run_id=run_id,
            edge_id=edge_id,
            record_count=max(1, record_count),
            from_rec=max(0, from_rec),
            data_format="json",
        )
    except Exception as e:
        if parts:
            parts.append(f"ERROR fetching records: {e}")
            return _text("\n".join(parts))
        return _text(
            f"ERROR: {e}\n"
            "Ensure the graph was executed with debug=true and that the "
            "debug DataServices (DebugRead) are deployed on the server."
        )

    if parts:
        parts.append("## Records\n")
        parts.append(data)
        return _text("\n".join(parts))
    return _text(data)


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


async def tool_modify_graph_structure(args: Dict) -> List[types.TextContent]:
    graph_path   = args.get("graph_path", "")
    sandbox      = args.get("sandbox", "")
    action       = args.get("action", "")
    element_type = args.get("element_type", "")

    if action not in ("add", "delete", "edit"):
        return _text(json.dumps({"status": "error", "message": f"action must be 'add', 'delete', or 'edit', got '{action}'"}))
    if element_type not in VALID_ELEMENT_TYPES:
        return _text(json.dumps({"status": "error",
                                 "message": f"Unknown element_type '{element_type}'. "
                                            f"Valid: {', '.join(sorted(VALID_ELEMENT_TYPES))}"}))

    # Download graph
    try:
        xml_text = get_soap_client().download_file(sandbox, graph_path)
    except Exception as exc:
        return _text(json.dumps({"status": "error",
                                 "message": f"Could not download graph: {exc}"}))

    svc = GraphStructureService(xml_text)
    dry_run  = bool(args.get("dry_run", False))
    validate = bool(args.get("validate", True))

    if action == "add":
        element_xml = args.get("element_xml")
        if not element_xml:
            return _text(json.dumps({"status": "error",
                                     "message": "element_xml is required for action='add'"}))
        phase_number = args.get("phase_number")
        if phase_number is not None:
            try:
                phase_number = int(phase_number)
            except (TypeError, ValueError):
                return _text(json.dumps({"status": "error",
                                         "message": "phase_number must be an integer"}))
        result = svc.add_element(
            element_type=element_type,
            element_xml=element_xml,
            phase_number=phase_number,
            validate=validate,
            dry_run=dry_run,
        )
    elif action == "edit":
        element_id = args.get("element_id")
        if not element_id:
            return _text(json.dumps({"status": "error",
                                     "message": "element_id is required for action='edit'"}))
        target_phase_number = args.get("target_phase_number")
        if target_phase_number is None:
            return _text(json.dumps({"status": "error",
                                     "message": "target_phase_number is required for action='edit'"}))
        try:
            target_phase_number = int(target_phase_number)
        except (TypeError, ValueError):
            return _text(json.dumps({"status": "error",
                                     "message": "target_phase_number must be an integer"}))
        result = svc.move_element(
            element_type=element_type,
            element_id=str(element_id),
            target_phase_number=target_phase_number,
            validate=validate,
            dry_run=dry_run,
        )
    else:  # delete
        element_id = args.get("element_id")
        if not element_id:
            return _text(json.dumps({"status": "error",
                                     "message": "element_id is required for action='delete'"}))
        cascade = bool(args.get("cascade", False))
        result = svc.delete_element(
            element_type=element_type,
            element_id=str(element_id),
            cascade=cascade,
            validate=validate,
            dry_run=dry_run,
        )

    if not result.ok:
        return _text(json.dumps({
            "status": "error",
            "element_type": element_type,
            "errors": result.errors,
            "warnings": result.warnings,
            "changes": result.changes,
        }, indent=2))

    # Upload result (unless dry-run)
    if not dry_run and result.xml_out is not None:
        dir_path, filename = os.path.split(graph_path)
        try:
            get_soap_client().upload_file(
                sandbox=sandbox,
                dir_path=dir_path,
                filename=filename,
                content=result.xml_out,
            )
        except Exception as exc:
            return _text(json.dumps({"status": "error",
                                     "message": f"Graph modified in memory but upload failed: {exc}",
                                     "changes": result.changes}))

    return _text(json.dumps({
        "status": "dry_run" if dry_run else "ok",
        "action": action,
        "element_type": element_type,
        "graph_path": graph_path,
        "sandbox": sandbox,
        "changes": result.changes,
        "warnings": result.warnings,
    }, indent=2))


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
    "create_directory":        tool_create_directory,
    "delete_directory":        tool_delete_directory,
    "validate_graph":          tool_validate_graph,
    "execute_graph":           tool_execute_graph,
    "await_graph_completion":  tool_await_graph_completion,
    "abort_graph_execution":   tool_abort_graph_execution,
    "get_graph_run_status":    tool_get_graph_run_status,
    "list_graph_runs":         tool_list_graph_runs,
    "get_graph_execution_log": tool_get_graph_execution_log,
    "list_components":         tool_list_components,
    "get_component_info":      tool_get_component_info,
    "get_component_details":   tool_get_component_details,
    "think":                   tool_think,
    "plan_graph":              tool_plan_graph,
    "note_add":                tool_note_add,
    "note_read":               tool_note_read,
    "note_clear":              tool_note_clear,
    "kb_store":                tool_kb_store,
    "kb_search":               tool_kb_search,
    "kb_read":                 tool_kb_read,
    "get_graph_tracking":      tool_get_graph_tracking,
    "get_edge_debug_data":     tool_get_edge_debug_data,
    "graph_edit_structure":     tool_modify_graph_structure,
    "graph_edit_properties":     tool_set_graph_element_attribute,
    "list_resources":          tool_list_resources,
    "read_resource":           tool_read_resource,
    "get_workflow_guide":      tool_get_workflow_guide,
}

if LLM_ALLOW:
    _TOOL_MAP["validate_CTL"] = tool_validate_CTL
    _TOOL_MAP["generate_CTL"] = tool_generate_CTL


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
