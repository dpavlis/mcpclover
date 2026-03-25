# CloverDX MCP Tools Reference

This document describes all 30 tools exposed by the CloverDX Graph Builder MCP server.
Each tool maps to one or more CloverDX Server operations (SOAP WebService or REST API).

---

## Sandbox & File Operations

### `list_sandboxes`
Lists all sandboxes (projects) available on the CloverDX server.  
**Why:** An LLM needs to know what sandboxes exist before it can do anything — e.g. to pick the right sandbox code for subsequent calls.  
**Backend:** SOAP `GetSandboxes`

---

### `list_files`
Lists files and folders inside a directory within a sandbox.  
**Why:** Lets the LLM browse the sandbox file tree to locate graphs, metadata, data files, etc. Supports `folder_only` to list just subdirectories.  
**Backend:** SOAP `ListFiles`

---

### `find_file`
Finds files in a sandbox using shell-style wildcards (`*`, `?`). Searches recursively.  
**Why:** When the LLM knows a filename but not its exact location (e.g. `*.grf`), a wildcard search is faster than manually traversing the tree with `list_files`.  
**Backend:** SOAP `ListFiles` + client-side wildcard filtering

---

### `grep_files`
#### TODO:
- *Implement server-side content search to avoid downloading large files for client-side filtering. This would require a new SOAP method that accepts a search string and optional filename pattern, and returns matching file metadata and lines. The current client-side approach is inefficient for large sandboxes with many files.*

Searches files in a sandbox whose **content** matches a given query. By default, `search_string` is treated as plain text; set `is_regex=true` to treat it as a regex. In regex mode, matching is performed against the full file text and supports cross-line matches; results include `matching_ranges` with `start_line`/`end_line` for each regex hit. When `include_matching_lines=true`, regex results also include `matching_samples` where each sample contains the full multi-line matched snippet (`start_line`, `end_line`, `content`). Returns the path, size, and last-modified date of each matching file. Optionally returns matching lines with line numbers (like `grep -n`). Supports optional filename pattern filter (`file_pattern`) and case-insensitive mode.  
**Why:** Lets the LLM find all graphs that use a specific component type, reference a particular subgraph or connection, call a named CTL function, or define a particular metadata ID — without reading every file manually. Much faster than individually reading files when the target string could appear in many places.  
**Key use cases:**
- Find all graphs using a component: `search_string='type="VALIDATOR"'`, `path='graph'`
- Find all graphs referencing a subgraph: `search_string='OrderFileReader.sgrf'`
- Find graphs referencing a metadata ID: `search_string='metadata="MetaOrder"'`
- Find example graphs for a component: `file_pattern='*.grf'`, `search_string='type="DENORMALIZER"'`
- Regex search for multiple component types: `search_string='type="(VALIDATOR|DENORMALIZER)"'`, `is_regex=true`
- Regex search for metadata IDs by prefix: `search_string='metadata="Meta[A-Za-z0-9_]+"'`, `is_regex=true`
- Regex across line breaks: `search_string='ORDER_VALIDATOR.*?type="VALIDATOR"'`, `is_regex=true`

Combine with `find_file` when both name pattern and content filtering are needed.  
**Backend:** SOAP `ListFiles` (file discovery) + `GetSandboxFile` (content read); filtering runs client-side

---

### `list_linked_assets`
Lists all externalisable/linkable assets in a sandbox: metadata definitions (`.fmt`), connection definitions (`.cfg`), lookup tables (`.lkp`), CTL2 transforms (`.ctl`), sequences (`.seq`), and parameter files (`.prm`). Optional `asset_type` filter.  
**Why:** CloverDX graphs reference shared assets by `fileURL`. Before writing a graph, the LLM must know what assets already exist to use their correct paths rather than redefining them inline.  
**Backend:** SOAP `ListFiles` (by extension pattern)

---

### `get_sandbox_parameters`
Reads and resolves graph parameters for a sandbox from `workspace.prm` (CloverDX XML `<GraphParameters>` format), optionally overlaying server-side defaults and system properties. Returns each parameter's resolved value and its source provenance.  
**Why:** Graphs use `${DATAIN_DIR}`, `${CONN_DIR}`, etc. as path prefixes. The LLM needs to know what these resolve to before writing file paths into a graph — otherwise connections and data paths will be wrong.  
**Backend:** SOAP `GetSandboxFile` (for `workspace.prm`) + `GetDefaults` + `GetSystemProperties`; `${...}` references resolved iteratively client-side

---

### `read_file`
Downloads the text content of any file from a sandbox (`.grf`, `.fmt`, `.prm`, `.ctl`, etc.). Optionally supports line-based partial reads via `start_line` + `line_count`. `start_line` is 1-based for positive values; negative values count from the end (`-1` is the last line). If partial read is requested, both parameters must be provided.  
**Why:** The LLM must read a file before modifying it, but large files do not always need to be fetched in full. Line-based partial reads reduce token usage when only a specific section is needed.  
**Backend:** SOAP `GetSandboxFile`

---

### `rename_file`
Renames a file within a sandbox. Only the filename changes — the file stays in the same directory. For cross-directory moves, use `copy_file` + `delete_file`.  
**Why:** Allows in-place renames without a download/re-upload cycle (e.g. finalising a draft graph name, or correcting a typo).  
**Backend:** SOAP `RenameSandboxFile`

---

### `copy_file`
Copies a file within a sandbox or from one sandbox to another. The copy overwrites the destination if it already exists.  
**Why:** Primary use is creating a safe backup before large edits (`graph/MyGraph.bak.grf`). Also useful for deploying a graph to another sandbox.  
**Backend:** SOAP `CopySandboxFile` (server-side copy — no content round-trip)

---

### `patch_file`
Applies anchor-based line-range replacements to a sandbox file. Each patch specifies an anchor substring, line offsets from that anchor, and replacement text. Supports `dry_run` preview mode.  
**Why:** Surgical edits to large `.grf` files are much safer than full rewrites — the LLM changes only the targeted lines and cannot accidentally corrupt the rest of the file. `dry_run` lets the LLM verify anchor resolution before writing.  
**Backend:** SOAP `GetSandboxFile` + `UploadSandboxFile`; patching logic runs client-side

---

### `write_file`
Creates or overwrites a file in a sandbox with supplied content.  
**Why:** Required for writing new graphs, metadata files, parameter files, and CTL2 scripts onto the server. Always use `copy_file` to back up an existing file before a full rewrite.  
**Backend:** SOAP `UploadSandboxFile`

---

### `delete_file`
Deletes a file from a sandbox. Irreversible.  
**Why:** Needed to clean up temporary files, obsolete graph versions, or backups after a successful migration.  
**Backend:** SOAP `DeleteFile`

---

## Resource Access

### `list_resources`
Lists all reference resource URIs exposed by this MCP server, with their name, description, and MIME type.  
**Why:** Lets the LLM discover what reference material is available without hardcoding URIs.  
**Backend:** Local in-memory registry (no server call)

---

### `read_resource`
Fetches the full content of a reference resource by its URI.  
**Available resources:**
- `cloverdx://reference/graph-xml` — Authoritative guide for CloverDX graph XML (`.grf` format)
- `cloverdx://reference/ctl2` — CloverDX CTL2 transformation language reference
- `cloverdx://reference/subgraphs` — Authoritative reference for CloverDX subgraphs (`.sgrf` format)

**Why:** Gives the LLM access to CloverDX-specific domain knowledge (XML structure rules, CTL2 syntax) at any point during a task.  
**Backend:** Local file read from `resources/` directory

---

### `get_workflow_guide`
Returns the authoritative step-by-step workflow guide for a CloverDX task type.  
**Available tasks:** `create_graph`, `edit_graph`, `validate_and_run`  
**Why:** Ensures the LLM follows the correct sequence of tool calls, applies the right validation steps, and avoids common mistakes. Should be called at the start of every CloverDX task.  
**Backend:** Local file read from `resources/` directory

---

## Graph Operations

### `set_graph_element_attribute`
Sets or replaces a value on a specific element within a CloverDX graph XML file (`.grf`). Operates on the parsed DOM — no text anchoring, no line numbers, no regex. Loads the file, finds the target element, modifies it, and writes it back.

**Element types:** `Node`, `Edge`, `Metadata`, `GraphParameter`, `Connection`

**Two modification modes (selected via `attribute_name`):**
- **Plain XML attribute** — e.g. `attribute_name='recordsNumber'`, `value='50'`. Sets the attribute directly on the element tag. Use for `recordsNumber`, `joinType`, `enabled`, `guiX`, `guiY`, `fileURL`, `metadata`, `value`, etc.
- **`attr:X` child element** — e.g. `attribute_name='attr:transform'`. Finds or creates an `<attr name='X'>` child element and stores the value as CDATA (wrapping applied automatically). Use for CTL2 transforms, SQL queries, `joinKey`, mapping XML, `rules`, `errorMapping`, etc.

**Metadata elements:** supply the full replacement `<Record>...</Record>` XML as `value`; set `attribute_name='record'` by convention. The entire child content of `<Metadata id='X'>` is replaced. External metadata (`fileURL`-style) cannot be modified here — edit the `.fmt` file directly with `write_file`.

**GraphParameter:** matched by `name` attribute (not `id`). Only plain XML attributes are supported — no `attr:` prefix.

**Why:** More reliable than `patch_file` for graph element modifications — immune to whitespace/formatting differences, works on any element regardless of how the XML is laid out. Always follow with `validate_graph`.

**Backend:** SOAP `GetSandboxFile` + `UploadSandboxFile`; DOM manipulation via lxml (preferred) or stdlib `xml.etree.ElementTree` fallback

---

### `validate_graph`
Validates a graph in two stages:
1. **Stage 1 (local):** XML structure check — graph/phase/node/edge/metadata conformance.
2. **Stage 2 (server):** `checkConfig` — deep component configuration check (field types, connection strings, etc.).

Stage 2 only runs if Stage 1 passes. Errors may not be exhaustive — repeat until clean.  
**Why:** Validation must happen before execution. Stage 1 catches structural issues without a server round-trip; Stage 2 validates component-level configuration.  
**Backend:** Client-side XML parsing (Stage 1) + SOAP `StartCheckConfig` / `GetCheckConfigStatus` (Stage 2)

---

### `execute_graph`
Executes a graph on the server and polls until completion. Returns final status and elapsed time. Supports parameter overrides and optional debug mode (required for `get_edge_debug_data`).  
**Why:** Core execution tool. Pre-flight checks ensure required parameters are provided before submission. Debug mode enables post-run data inspection on any edge.  
**Backend:** SOAP `ExecuteGraph` + polling `GetJobExecutionStatus`

---

### `list_graph_runs`
#### TODO:
*Add SOAP 'ListExecutions' to avoid REST API dependency*

Lists recent graph and jobflow executions, with optional filters for sandbox, job file path substring, and status. Supports paging.  
**Why:** Lets the LLM look up execution history without needing a run ID in advance — useful for checking if a graph ran successfully recently, or finding a failed run to diagnose.  
**Backend:** REST `GET /api/rest/v1/executions`

---

### `get_graph_run_status`
Returns the current status of a single run by its run ID, without fetching the full log. When the run is `RUNNING`, also returns elapsed time and current phase number.  
**Why:** Efficient status polling for long-running graphs. Avoids the overhead of `get_graph_execution_log` when all that's needed is a pass/fail check.  
**Backend:** SOAP `GetJobExecutionStatus` (with `GetGraphExecutionStatus` fallback)

---

### `get_graph_execution_log`
Fetches the full text execution log for a completed run.  
**Why:** When a graph fails, the log contains the error message, stack trace, and component-level diagnostics needed to fix the problem.  
**Backend:** SOAP `GetGraphExecutionLog`

---

### `get_graph_tracking`
Returns per-phase and per-component execution metrics for a completed run: timing, and record/byte counts on each input and output port.  
**Why:** Verifies that data flowed correctly through the graph — e.g. confirms a filter passed the expected number of records, or identifies a bottleneck component.  
**Backend:** SOAP `GetGraphTracking`

---

### `get_edge_debug_info`
Lists edge debug data availability for a specific edge of a debug run. Returns whether data was captured and the writer/reader node IDs.  
**Why:** Before calling `get_edge_debug_data`, the LLM must confirm that debug data was captured for the specific edge.  
**Backend:** SOAP `GetEdgeDebugDetails` (with retry)

---

### `get_edge_debug_metadata`
Returns the field schema (names and types) for data flowing through a specific edge of a debug run.  
**Why:** The actual edge data is binary (CLVI format) and cannot be read as text. The metadata schema tells the LLM what fields exist so it can reason about the data structure.  
**Backend:** SOAP `GetEdgeDebugMetadata`

---

### `get_edge_debug_data`
#### TODO:
*consider merging `get_edge_debug_info` + `get_edge_debug_metadata` into this single call, since they are always used together and both require retry logic. Instead of binary CLVI, return the debug data as JSON with an array of records (up to a reasonable max, e.g. 100) and their field values as strings. This would simplify LLM usage and remove the need for separate metadata fetching.*

Fetches a paginated summary of records that flowed through an edge during a debug run. Supports optional CTL2 `filter_expression` and `field_selection`.  
**Why:** Allows the LLM to inspect mid-graph data to diagnose transformation logic errors — e.g. checking what values reached a Lookup component's reject port.  
**Backend:** SOAP `GetEdgeDebugData`

---

## Component Reference

These tools operate entirely locally against the bundled `components.json` catalog — no server round-trip.

### `list_components`
Lists available CloverDX component types, optionally filtered by category (`readers`, `writers`, `transformers`, `joiners`, `others`, `jobControl`).  
**Why:** Lets the LLM discover what components are available before deciding which to use in a graph.  
**Backend:** Local `components.json`

---

### `get_component_info`
Returns the input/output port definitions and configurable properties for a component type or display name. Case-insensitive, partial match supported.  
**Why:** The LLM needs exact port indices, required vs optional properties, and property types to write correct graph XML. This is the primary lookup tool during graph design.  
**Backend:** Local `components.json`

---

### `get_component_details`
Returns extended markdown documentation for complex components that require deeper explanation (e.g. `XML_EXTRACT`, `VALIDATOR`).  
**Why:** `get_component_info` covers ports and property names, but complex components like `XML_EXTRACT` have non-obvious mapping syntax, mode options, and edge cases that require a full reference document.  
**Backend:** Local `.md` files from `comp_details/` directory

---

## Reasoning Helper

### `think`
Accepts a single `thought` string and returns acknowledgement only (the thought is logged, not executed).  
**Why:** Encourages explicit reasoning before action for CloverDX workflows — especially before component selection, graph authoring/editing strategy decisions, and root-cause diagnosis after validation failures.  
**Backend:** Local acknowledgement response + server log entry (no CloverDX SOAP/REST call)

---

### `plan_graph`
Accepts a structured graph-design plan payload (graph identity, phases, components, metadata, edges, global assets, risks, references) and returns acknowledgement only.  
**Why:** Forces explicit, reviewable design before writing graph XML so inconsistencies are surfaced early and planning context is recorded. Intended to be called after workflow/reference/component lookups and before `write_file` or `set_graph_element_attribute`.  
**Backend:** Local acknowledgement response + server log entry (no CloverDX SOAP/REST call)

---

## TO BE IMPLEMENTED (suggestions)
### `validate_ctl`

These are genuinely different tools with different use cases, not one tool with a mode flag:

**Standalone** — "I'm assembling a CTL snippet and want fast syntax + type checking before I even have a graph. I know my metadata, I'll supply it."

### `in_graph_validate_ctl`
**In-graph** — "I have a working graph. I want to iterate on just the CTL of one component without running validate_graph on the whole thing every time. The graph provides all context."


### Other potential tools:
- ?? list_subgraphs 
- ?? get_subgraph_info

