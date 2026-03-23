# Tool Wishlist: What Would Make CloverDX Graph Development Faster

> Analysis of the full development lifecycle from initial request to working graphs,
> identifying every friction point and proposing tools that would eliminate them.

---

## The Process That Actually Happened

### Phase 1: Understanding and Research (~40% of total effort)
1. Read brand skills, workflow guide, reference resources (CTL2, Graph XML)
2. Explored sandbox structure, found example subgraphs
3. Read example .sgrf files to learn the format
4. Called get_component_info for each component type
5. Studied CTL2 capabilities and limitations

### Phase 2: Design (~10%)
6. Designed the subgraph architecture (ports, phases, data flow)
7. Identified that CTL2 cannot read files - redesigned to two-phase approach
8. Identified that evalExpression() has no port context - designed placeholder substitution

### Phase 3: Implementation (~15%)
9. Wrote the subgraph XML
10. Wrote CSV test data and mapping files
11. Wrote the parent test graph

### Phase 4: Debugging and Fixing (~35%)
12. Fixed metadata field names (user manually fixed per-field delimiters)
13. User rewired debugInput nodes (I did not understand the pattern)
14. Fixed regex in ?= and replace() - two separate rounds
15. Fixed CSV quoting (unquoted field with embedded double quotes)
16. Fixed ruleCount vs actual array size mismatch
17. Fixed jobURL vs graphURL attribute name
18. Fought with patch_file leaving orphaned code - at least 3 rounds
19. Did full file rewrites to clean up patch damage - at least 3 times

---

## Friction Points and Dream Tools

### FRICTION 1: I did not know CloverDX metadata idioms

**What happened:** Put delimiter on every field. Did not know about debugInput/debugOutput.

**Root cause:** The reference docs describe what is valid but not what is idiomatic. Example subgraphs showed the right patterns, but I did not extract the principles.

#### Dream Tool: cloverdx://reference/best-practices or cloverdx://reference/idioms

A resource that codifies CloverDX idioms and anti-patterns - not XML schema rules, but "here is how experienced developers do it." Sections like:

- **Metadata design:** field delimiters go on Record, not Field. When to use eofAsDelimiter.
- **Subgraph patterns:** always use debugInput/debugOutput for test harnesses. Explain the stripping behavior. Show the canonical transformer/reader/writer subgraph layouts.
- **CSV handling:** always quote fields containing expressions. Show correct quoting.
- **Common mistakes by LLMs:** a curated list of things that validate but are wrong.

This is fundamentally a documentation/reference improvement for the MCP server.

---

### FRICTION 2: I did not know ?= and replace() are regex-based

**What happened:** Used ?= for string contains check on {field1} - regex crash. Used replace() with curly braces - same class of error.

**Root cause:** The CTL2 reference documents this, but in a table buried among many operators. When writing transform code, I reached for ?= because it seemed like a contains check.

#### Dream Tool: validate_ctl2(code, metadata_context) - a CTL2 linter

A tool that takes a CTL2 code string and validates it before writing to a graph:

- Catches regex-unsafe patterns: "Warning: ?= right operand contains { - use indexOf() instead"
- Catches replace() with unescaped regex special chars
- Validates field references against provided metadata
- Checks evalExpression() usage patterns
- Reports undeclared variables, type mismatches

This would have caught the regex issues, the field name mismatches, and the scope problems from bad patching - all before I wrote the file and ran validate_graph.

**Alternatively (simpler):** Enhance the existing CTL2 reference resource with a prominent "DANGEROUS FUNCTIONS" section at the top listing all regex-based operators and their safe alternatives.

---

### FRICTION 3: I could not test CTL2 code without deploying a full graph

**What happened:** Every CTL2 bug required: write file, validate, read error, fix, rewrite, validate again. Some bugs (like the ruleCount mismatch) only appeared at runtime, not validation.

**Root cause:** No way to test CTL2 code in isolation.

#### Dream Tool: execute_ctl2(code, input_record, output_metadata) - a CTL2 REPL

A tool that executes a CTL2 snippet against sample data without needing a full graph:

```
execute_ctl2(
  code: "function integer transform() { $out.0.name = trim($in.0.name); return ALL; }",
  input: {"name": "  John  ", "id": "123"},
  input_metadata: "SourceMeta",
  output_metadata: "TargetMeta"
)
```

Returns: output record, logs, errors.

This would let me test each transform function before assembling the full graph, debug evalExpression() behavior with actual data, verify placeholder substitution produces valid CTL, and iterate on complex expressions without full deploy cycles.

---

### FRICTION 4: patch_file repeatedly corrupted CTL code in CDATA blocks

**What happened:** Used patch_file to edit CTL transforms. Patches left behind orphaned code at least 3 times, requiring full file rewrites each time.

**Root cause:** patch_file works on line offsets from text anchors. CTL code inside XML CDATA blocks has complex structure. The same anchor text appeared in multiple components. Offset calculations were wrong when patches interacted.

#### Dream Tool: edit_component_transform(graph_path, sandbox, node_id, new_ctl_code)

A tool that replaces just the CTL2 transform code for a specific component, handling the CDATA wrapping automatically:

```
edit_component_transform(
  graph_path: "graph/subgraph/UniversalMapper.sgrf",
  sandbox: "tests",
  node_id: "UNIVERSAL_MAP",
  attribute: "transform",
  code: "//#CTL2\nfunction integer transform() { ... }"
)
```

This would target a specific component by ID (no ambiguous anchors), replace the entire transform atomically (no partial patches), handle CDATA escaping automatically, optionally validate the CTL2 before writing, and never leave orphaned code.

---

### FRICTION 5: Runtime errors required multiple round-trips to diagnose

**What happened:** The CSV quoting error and the ruleCount mismatch only surfaced at runtime. I had to: check run status, read error, read graph, reason about the data flow, fix, rewrite, re-run.

**Root cause:** validate_graph catches structural/config errors but not data-level or logic errors. I could not trigger execution myself.

#### Dream Tool: execute_graph with automatic diagnosis

Wishlist:

1. **execute_graph(path, sandbox)** - ability to run a graph directly. Being able to run the graph myself would have cut the debug loop from minutes to seconds.

2. **get_run_diagnosis(run_id)** - a single-call error analysis. Combines: error message + execution log + tracking data + the CTL code that failed + the data that was flowing when it failed. Returns a structured diagnosis instead of requiring 3-4 tool calls and manual correlation.

3. **get_edge_debug_data for the edges leading to the failing component** - if I could see the actual data that entered the failing component (not just record counts), I could have immediately seen that ruleCount was wrong by inspecting the dictionary value.

---

### FRICTION 6: No way to preview how the mapping CSV would be parsed

**What happened:** The CSV with embedded quotes in CTL expressions broke the parser. I could not predict this without actually running the reader.

#### Dream Tool: preview_reader(component_config, file_path, sandbox, num_records)

A tool that runs just the reader component against the file and shows the parsed output:

```
preview_reader(
  type: "DATA_READER",
  fileURL: "${DATAIN_DIR}/mapping.csv",
  metadata: "Metadata0",
  sandbox: "tests",
  num_records: 3,
  skip_first_line: true,
  quoted_strings: true
)
```

Returns the parsed records or a parse error - catching CSV quoting issues immediately without deploying a full graph.

---

### FRICTION 7: Slow knowledge ramp-up at the start

**What happened:** Spent significant time reading the full CTL2 reference (very long), the full Graph XML reference (very long), example subgraphs, and component info.

#### Dream Tool: get_task_briefing(task_description) - a context-aware knowledge loader

Instead of reading everything, describe the task and get back a focused briefing:

```
get_task_briefing(
  task: "Create a subgraph with 1 input port and 1 output port that reads a CSV
         config file, uses dynamic field access and evalExpression() to apply
         transformations, and passes data through"
)
```

Returns: relevant components, key CTL2 functions, key warnings, subgraph patterns, example graphs, and metadata idioms. Essentially a smart index over the existing reference material, filtered by task relevance.

---

### FRICTION 8: No dry run for the full data flow

**What happened:** Even after fixing all CTL2 and CSV issues, I could not verify that the end-to-end transformation would produce correct output without the user running the graph.

#### Dream Tool: simulate_graph(graph_path, sandbox, max_records) - mock execution

Runs the graph with a limited number of records and returns the output data (or errors) without writing to the actual output file. Shows output preview, warnings, and record counts per component.

---

## Priority Ranking

If I could only have three tools, in order of impact:

### 1. execute_graph + get_run_diagnosis (eliminate the human-in-the-loop debug cycle)
**Impact: Massive.** The biggest time sink was not being able to run the graph myself and having to wait for the user to run it, report the error, and then do multi-step diagnosis. A single execute + diagnose loop would have cut debug time by 80%.

### 2. edit_component_transform (eliminate patch corruption)
**Impact: High.** Patch corruption caused at least 3 full-file rewrites. A component-targeted edit tool would eliminate this entire class of error while keeping edits surgical.

### 3. validate_ctl2 / CTL2 linter (catch code errors before deploy)
**Impact: High.** Would have caught the regex issues, field name mismatches, and scope problems from bad patching before they ever reached validate_graph or runtime.

### Honorable mentions:
4. preview_reader - would have caught CSV parsing issues instantly
5. cloverdx://reference/best-practices - would have prevented the metadata and debugInput mistakes
6. simulate_graph - would have given confidence in correctness before involving the user
7. get_task_briefing - would have cut initial research time significantly

---

## What Already Worked Well

Credit where due - these existing tools and resources were invaluable:

- **get_workflow_guide** - the step-by-step process kept the work structured
- **validate_graph** - caught XML and config errors immediately after every write
- **list_graph_runs + get_graph_tracking** - essential for post-mortem analysis
- **cloverdx://reference/ctl2** - comprehensive (if long) CTL2 reference
- **cloverdx://reference/graph-xml** - excellent graph XML reference with examples
- **get_component_info** - critical for getting port names and attribute details right
- **Example subgraphs in DWHExample** - the single best resource for learning subgraph patterns
- **write_file + validate_graph loop** - reliable when used for full rewrites (not patches)

---

## TL;DR — The Dream Toolbox

| # | Tool | One-liner |
|---|------|-----------|
| 1 | **`execute_graph(path, sandbox)`** | Run a graph directly without waiting for the user to trigger it manually. |
| 2 | **`get_run_diagnosis(run_id)`** | Single-call error analysis combining error message, execution log, tracking, failing CTL code, and flowing data. |
| 3 | **`edit_component_transform(graph, sandbox, node_id, code)`** | Replace a specific component's CTL2 transform by node ID — atomic, no patch corruption, handles CDATA automatically. |
| 4 | **`validate_ctl2(code, metadata_context)`** | Lint CTL2 code before deploying — catches regex-unsafe patterns, field mismatches, undeclared variables. |
| 5 | **`execute_ctl2(code, input_data, metadata)`** | CTL2 REPL — test a transform snippet against sample data without building a full graph. |
| 6 | **`preview_reader(config, file, sandbox, n)`** | Parse the first N records of a file with a given reader config and show results or parse errors. |
| 7 | **`cloverdx://reference/best-practices`** | Curated resource of CloverDX idioms, anti-patterns, and common LLM mistakes (metadata design, debugInput/debugOutput, CSV quoting). |
| 8 | **`simulate_graph(path, sandbox, max_records)`** | Dry-run a graph with limited records, return output preview and per-component record counts without writing output files. |
| 9 | **`get_task_briefing(task_description)`** | Context-aware knowledge loader — describe what you are building, get back only the relevant components, functions, warnings, and examples. |
