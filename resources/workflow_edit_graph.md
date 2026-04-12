# CloverDX Workflow Guide — `edit_graph`

> LLM-only guide. Core rules: read current server state before editing;
> think before acting; validate AND execute after every meaningful change.

> **MANDATORY COMPLETION RULE — `validate_graph` loop:**
> The task is **never finished** until `validate_graph` has been called and returns
> `overall: PASS` with no unresolved errors. If validation reports problems, you
> **must** fix every issue and re-run `validate_graph`. Repeat this fix → re-validate
> cycle until the result is clean. Do **not** present the edit as complete, summarise
> results to the user, or move on while any validation errors remain outstanding.
> This applies after every write — not just at the end.

---

## PHASE 0 — Read authoritative context and check knowledge base

### 0.1 Check the knowledge base
Start by reviewing what you already know from previous sessions:

```
kb_search()                               -- catalog of all knowledge entries
kb_read("ctl2-isnull-vs-isNull")          -- load entries relevant to this edit
```

Skim the catalog; load any entries whose name or description relates to the
components, CTL patterns, or data structures involved in the edit.

### 0.2 Read resources relevant to the edit
Read only what the edit actually touches — do not skip this step:

```
read_resource("cloverdx://reference/graph-xml")   -- if structure changes
read_resource("cloverdx://reference/ctl2")         -- if any CTL changes
read_resource("cloverdx://reference/subgraphs")    -- if edit touches a .sgrf,
                                                   -- adds/removes a SUBGRAPH component,
                                                   -- or changes subgraph ports/parameters
```

Do not rely on training knowledge when a resource exists.

### 0.3 Read the current file from the server
**Always read the current server copy before changing anything.**
Never work from memory or a previous version in context:

```
read_file("graph/MyGraph.grf", sandbox)
```

Your in-context copy becomes stale the moment any write succeeds.
For large graphs, use line-range reading to focus on the relevant section:

```
read_file("graph/MyGraph.grf", sandbox, start_line=40, line_count=30)
read_file("graph/MyGraph.grf", sandbox, start_line=-20, line_count=20)  -- last 20 lines
```

### 0.4 Clear session notes and record initial context
Start with a clean scratchpad, then note key facts from the file you just read:

```
note_clear()
note_add("current_state", "Graph has 8 components, VALIDATOR on port 0/1, output to XLSX writer")
note_add("edit_scope", "User wants to add date range filtering before the VALIDATOR")
```

### 0.5 Sandbox rule
Never create or store files in `wrangler_shared_home`.

---

## PHASE 1 — Understand the change

### 1.1 Think through the change before touching anything
Before any lookup or edit, call `think` to reason explicitly:

```
think("What exactly needs to change? Which components, attributes, edges,
      or CTL blocks are affected? What are the dependencies — does removing
      or changing this component break any downstream edge or metadata?
      Is this a small targeted fix (graph_edit_properties / patch_file)
      or a structural change (graph_edit_structure / write_file)?")
```

**If the edit is large** — adding multiple new components, designing new metadata,
choosing between component types, writing substantial new CTL logic — consult the
`create_graph` workflow guide for those aspects:

```
get_workflow_guide("create_graph")
```

The `create_graph` guide covers component selection rules, CTL entry point
signatures, metadata design, `list_components` usage, and the incremental
build-and-verify loop. Use it as a reference for the new-build portions of
a large edit, while following this guide for the overall edit process
(read-first, backup, re-read between changes, validate after every write).

### 1.2 Enumerate the exact delta
Before editing, identify:
- Which component IDs, edge IDs, metadata IDs, or parameter names change
- Which `[attr-cdata]` blocks (CTL, SQL, mapping XML) are affected
- New dependencies introduced (new component needs a connection, sequence, CTL import)
- Dependencies broken if a node/edge/metadata item is removed
- Whether metadata needs new fields for the change to work end-to-end

Record the delta in session notes:
```
note_add("delta", "Add EXT_FILTER between READER and VALIDATOR. New edge Edge1a. Filter CTL needed.")
note_add("delta", "Metadata unchanged — filter passes same record structure through.")
```

### 1.3 Research any components being added or reconfigured
If the edit introduces a new component type or significantly changes an existing one,
do not rely on memory.

If the exact component type is not known, use `list_components` to find candidates:
```
list_components(search_string="compare two datasets")   -- task-oriented search
list_components(category="joiners", search_string="hash")  -- category + search
```

Then call `get_component_info` for each candidate:
```
get_component_info("DENORMALIZER")    -- ports, attributes, Usage: selection guidance
get_component_info("EXT_HASH_JOIN")
```

**Call `get_component_details` for complex components** — not just when adding them
from scratch, but also when changing their configuration in ways that involve
interacting attributes:

```
get_component_details("VALIDATOR")   -- when changing rules, errorMapping, or both
get_component_details("XML_EXTRACT") -- when changing mapping XML
```

Call `get_component_details` whenever:
- The component has `[attr-cdata]` properties containing XML (not just CTL)
- Multiple attributes interact (e.g. VALIDATOR `rules` + `errorMapping`)
- The `get_component_info` output shows opaque type labels like `[validatorRules]`,
  `[xmlMapping]`, `[hashJoinKey]`

### 1.4 Find reference graphs for new patterns
If the edit introduces a pattern not already in the graph, find graphs that
already use it — use `grep_files`, not `find_file`, to search by component type:

```
grep_files(search_string='type="VALIDATOR"', sandboxes=[sandbox], file_pattern="*.grf", path="graph")
grep_files(search_string='type="DENORMALIZER"', sandboxes=[sandbox], file_pattern="*.grf")
```

Use `think` to evaluate whether to follow the reference pattern:
```
think("The reference graph uses errorMapping + DENORMALIZER for rejection reasons.
      This is exactly the pattern I need. I should follow it rather than
      inventing a different approach.")
```

### 1.5 Check for reusable assets when adding new components
If the change adds components that use connections, CTL logic, or metadata
that might already exist as shared assets:

```
list_linked_assets(sandbox, asset_type="ctl")        -- before writing CTL inline
list_linked_assets(sandbox, asset_type="connection") -- before defining a DB connection
list_linked_assets(sandbox, asset_type="metadata")   -- before defining metadata inline
```

---

## PHASE 2 — Apply changes safely

### 2.1 Back up before significant edits
Before any edit that could corrupt the graph or is hard to reverse:

```
copy_file("graph/MyGraph.grf", sandbox, "graph/MyGraph.bak.grf", sandbox)
```

For small targeted changes (one attribute, one CTL block), backup is optional
but recommended whenever the file contains complex CDATA nesting.

### 2.2 Write or update CTL code
If the `generate_CTL` and `validate_CTL` tools are available, use them.
If they are not available (user may have disabled them), write CTL manually
following the CTL2 reference from `read_resource("cloverdx://reference/ctl2")`.

**When `generate_CTL` / `validate_CTL` are available:**

```
generate_CTL(
    description="Reformat: filter orders where order_date is within the last 30 days",
    input_metadata="Port 0 (orders):\n<Record name='OrderRecord'>...",
    output_metadata="Port 0 (filtered orders):\n<Record name='OrderRecord'>..."
)
```

Always validate CTL before embedding it in the graph:
```
validate_CTL(
    code="...generated or hand-written CTL...",
    input_metadata="Port 0 (orders):\n<Record name='OrderRecord'>...",
    output_metadata="Port 0 (filtered orders):\n<Record name='OrderRecord'>..."
)
```

This catches field name mismatches, type issues, and logic errors before they
become runtime failures. Fix any issues before proceeding.

**When `generate_CTL` / `validate_CTL` are NOT available:**

Write CTL code manually, strictly following the CTL2 reference document
(`cloverdx://reference/ctl2`). Pay special attention to:
- Correct entry point signatures for the component type
- `$in.N` / `$out.N` port variable syntax for field access
- `function returnType name(...)` ordering — not `returnType function name(...)`
- Null handling — use `isnull()` before accessing nullable fields
- Return codes: `OK`, `SKIP`, `STOP` constants

Rely on `validate_graph` and `execute_graph` to catch CTL compilation and
runtime errors in lieu of `validate_CTL`.

### 2.3 Choose the right editing tool

**`graph_edit_properties` -- default for all attribute and CTL changes:**
```
graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="ORDER_VALIDATOR",
    attribute_name="enabled", value="disabled")

graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="TRANSFORM",
    attribute_name="attr:transform",
    value="//#CTL2\nfunction integer transform() {...}")

graph_edit_properties(graph_path, sandbox,
    element_type="Metadata", element_id="MetaOrder",
    attribute_name="record",
    value='<Record fieldDelimiter="," ...>...</Record>')

graph_edit_properties(graph_path, sandbox,
    element_type="GraphParameter", element_id="INPUT_FILE",
    attribute_name="value", value="${DATAIN_DIR}/NewInput.xlsx")
```

This is DOM-based -- no line numbers, no anchor ambiguity, no CDATA escaping
accidents. Use it for any change to an existing element's attribute or content.

**`graph_edit_structure` -- for adding, deleting, or moving elements:**
Use when adding a new Metadata, Node, Edge, Phase, Connection, etc.
or when deleting/moving existing elements.

**`patch_file` -- for non-graph text files only:**
Use for .ctl, .prm, .csv, .sql, etc. Do NOT use for .grf files.
Always run `dry_run=true` first. Anchor strings must be unique -- use
`anchor_occurrence` if the same string appears multiple times.

**`write_file` — for large structural rewrites:**
Use when adding multiple new components and edges, or when the file is already
malformed. A clean full rewrite guarantees no orphaned content.

### 2.4 Re-read between changes
After every successful `write_file`, `patch_file`, or `graph_edit_properties`/`graph_edit_structure`,
your in-context copy is stale. **Re-read before computing the next change.**
Editing from a stale mental model causes structural corruption.

### 2.5 If patching has corrupted the file — stop patching
Switch to a clean full rewrite with `write_file`. Incremental patching of a
malformed file makes things worse.

### 2.6 Nested CDATA escaping
If any CDATA block contains content with its own CDATA (e.g. VALIDATOR `rules`
containing `<expression>` elements), inner `]]>` must be escaped as:
```
]]]]><![CDATA[>
```
Note: `graph_edit_properties` handles CDATA wrapping automatically for
`attr:` child elements — you do NOT need to wrap the value yourself.
This escaping rule applies when writing raw XML via `write_file` or `patch_file`.

### 2.7 CTL function declaration syntax
User-defined helper functions: `function` keyword comes **first**:
```
function <returnType> <functionName>(<params>) { ... }
```
Not `returnType function name(...)`.

### 2.8 Update the RichTextNote if present
After applying changes, check whether the graph contains a `RichTextNote`.
If it does, update its content to reflect the current business logic of the
graph — incorporating what the edit changed.

Read the graph to find existing notes, then update:
```
graph_edit_properties(graph_path, sandbox,
    element_type="RichTextNote", element_id="Note0",
    attribute_name="content",
    value="Reads daily order data, validates required fields and date ranges, "
          "filters by region (added: excludes inactive regions), enriches with "
          "customer tier from the lookup table, and writes valid orders to the "
          "DWH staging table. Rejected records are logged with rejection reasons "
          "to an error file.")
```

**Guidelines for updated note text:**
- Keep the same business-level style — what data flows in, what rules apply, what comes out
- Reflect the full current graph logic, not just the delta
- One short paragraph (2–4 sentences)
- No component names, edge IDs, or technical XML/CTL details

If no `RichTextNote` exists in the graph, skip this step.

### 2.9 Edge port names must match component docs exactly
Use exact strings from `get_component_info` — not guesses:

| Component | Exact `outPort` |
|---|---|
| Most readers | `Port 0 (output)` |
| VALIDATOR valid | `Port 0 (valid)` |
| VALIDATOR invalid | `Port 1 (invalid)` |
| REFORMAT, DENORMALIZER, etc. | `Port 0 (out)` |

---

## PHASE 3 — Validate and verify after every change

### 3.1 Validate immediately after every write — MANDATORY
Always call `validate_graph` right after every `write_file`, `patch_file`,
or `graph_edit_properties`/`graph_edit_structure`. **The edit is not complete
until `validate_graph` returns `overall: PASS` with zero errors.** If validation
reports problems, fix them and call `validate_graph` again. Repeat until the
result is clean. Never present the edit as done, summarise results, or stop
working while validation errors remain.

```
validate_graph("graph/MyGraph.grf", sandbox)
```

| Result | Action |
|---|---|
| `overall: PASS`, no problems | Proceed to execution |
| Stage 1 errors | XML broken — fix before anything else |
| Stage 2 ERROR | Component config invalid — fix all errors |
| Stage 2 WARNING | Investigate — do not ignore |

**Validation may not be exhaustive.** Fix reported issues and re-validate —
additional problems may surface only after earlier ones are resolved.

Use `think` to diagnose before attempting a fix:
```
think("Error: 'Attribute customRejectMessage not allowed on expression'.
      The expression rule element doesn't support this attribute.
      Fix: remove customRejectMessage and use the name attribute instead.")
```

Common failures and fixes:

| Error | Fix |
|---|---|
| `Attribute 'X' is not allowed in element 'Y'` | Remove invalid attribute |
| `element type "X" must be terminated by matching end-tag` | Fix malformed XML / nested CDATA escaping |
| `Can't deserialize validation rules` | VALIDATOR rules CDATA broken — check escaping and invalid attributes |
| `Syntax error on token 'function'` | Flip to `function returnType name()` |
| `CTL code compilation finished with N errors` | Read full message, find the line, fix it |

### 3.2 Execute and verify runtime behaviour
`validate_graph` only catches structural and configuration errors. Runtime errors
and logic errors are invisible until execution. After every meaningful change
that affects data flow, execute and check tracking:

```
run = execute_graph("graph/MyGraph.grf", sandbox)
await_graph_completion(run.run_id, timeout_seconds=120)
get_graph_tracking(run.run_id)
```

Use `await_graph_completion` instead of manual polling — it blocks until the
graph finishes or times out. If it times out, check progress with
`get_graph_run_status(run_id)`, wait again, or abort:
```
abort_graph_execution(run_id)
```

**Check for each component:**
- Input and output record counts are sensible
- No component shows 0 records unexpectedly
- Port split ratios are correct: valid + invalid = total (VALIDATOR),
  accepted + rejected = total (EXT_FILTER)
- Counts are consistent with the intent of the change — if you added a filter,
  verify the split is reasonable, not 0/all or all/0

Use `think` to reason through unexpected counts before fixing:
```
think("After adding the EXT_HASH_JOIN, output is 0 records. Input to port 0
      was 1000, input to port 1 was 500, joinType=inner. Possible causes:
      wrong joinKey field names, type mismatch on key fields, or no actual
      matching values between streams. I should check the joinKey config
      and verify sample values exist in both streams.")
```

### 3.3 Use debug mode when tracking counts are insufficient
Enable debug mode when you need to inspect actual record values, not just counts:

```
run = execute_graph("graph/MyGraph.grf", sandbox, debug=True)
await_graph_completion(run.run_id)
get_edge_debug_info(edge_id="Edge2", graph_path, sandbox, run.run_id)
get_edge_debug_metadata(edge_id="Edge2", ...)
get_edge_debug_data(run_id=run.run_id, edge_id="Edge2", record_count=50)
```

Use debug mode when:
- Tracking shows unexpected counts and you need to see actual values
- A runtime error occurs mid-stream and you need to identify the failing record
- You want to verify field values at a specific edge after a CTL change

**For deeper debugging** — inspecting actual record values at multiple edges,
isolating failures by disabling components (`enabled="trash"` or `enabled="disabled"`),
or diagnosing complex runtime errors — consult the `validate_and_run` workflow guide:
```
get_workflow_guide("validate_and_run")
```

### 3.4 For pipeline edits — use TRASH terminals during incremental work
When the edit restructures or extends a data flow branch, keep or add a temporary
TRASH terminal (with `debugPrint="true"`) at the current end of the incomplete flow.
Only replace it with the real destination after the branch is validated and
executing correctly with sensible record counts.

### 3.5 Persist new knowledge
If you discovered something new during this edit — a CTL gotcha, a component
pattern, a correction — store it for future sessions:

```
kb_store(
    name="ctl2-some-discovery",
    description="Brief summary of what was learned",
    tags=["ctl2", "relevant-tag"],
    content="Detailed explanation with code examples..."
)
```

**What to store — generally reusable knowledge only:**
- Component behaviours that are non-obvious or underdocumented
- CTL patterns, gotchas, or workarounds that apply broadly
- Correction of a wrong assumption that an LLM would likely make again
- Configuration interactions between component attributes that caused a subtle bug

**What NOT to store:**
- Step-by-step instructions for processing one specific file or dataset
- Facts already in the reference docs or `get_component_info` output
- Task-specific metadata schemas, file paths, or connection details
- Anything that only applies to one particular graph and would not help in a
  different context

The test: *would this knowledge help someone building a completely different
graph that happens to use the same component or CTL pattern?* If yes, store it.
If it only helps re-build the exact same graph, skip it.

---

## CHECKLIST — before presenting the edit as complete

- [ ] Called `kb_search()` and loaded relevant knowledge entries
- [ ] Read `cloverdx://reference/subgraphs` if edit touches .sgrf or SUBGRAPH component
- [ ] Read `cloverdx://reference/graph-xml` / `ctl2` for relevant change types
- [ ] Read the current server file before making any changes
- [ ] Cleared session notes and recorded initial context with `note_add`
- [ ] Used `think` to reason through what changes and what the dependencies are
- [ ] For large edits (multiple new components, new metadata, new CTL): consulted `create_graph` workflow guide
- [ ] Enumerated exact components / attributes / CTL blocks / edges / metadata being changed
- [ ] Called `get_component_info` for any component being added or significantly reconfigured
- [ ] Used `list_components(search_string=...)` when the exact component type was not known
- [ ] Called `get_component_details` for complex components and when interacting attributes are involved
- [ ] Used `grep_files` (not `find_file`) to find reference graphs for new patterns
- [ ] Used `think` to evaluate reference graph patterns before deciding to follow them
- [ ] Called `list_linked_assets` before writing new CTL, connections, or metadata inline
- [ ] Backed up graph before significant edits (`copy_file`)
- [ ] Used `generate_CTL` + `validate_CTL` if available; otherwise wrote CTL manually per the CTL2 reference and verified via `validate_graph` + `execute_graph`
- [ ] Used `graph_edit_properties` for attribute/CTL/metadata changes (not patch_file)
- [ ] Used `graph_edit_structure` for adding/deleting/moving graph elements
- [ ] Used `patch_file` (dry_run first) only for non-graph text files
- [ ] Re-read file between multiple changes — never edited from stale state
- [ ] No non-existent components introduced (no ROUTER, no FILTER)
- [ ] CTL user-defined functions: `function returnType name(...)` not `returnType function name(...)`
- [ ] Escaped nested CDATA as `]]]]><![CDATA[>` for raw XML writes (not needed for graph_edit_properties)
- [ ] Edge outPort strings match exactly the names from `get_component_info`
- [ ] Updated `RichTextNote` content to reflect current business logic (if note exists in the graph)
- [ ] **`validate_graph` called after every write — if not `overall: PASS`, kept fixing and re-validating until it passed**
- [ ] `execute_graph` + `await_graph_completion` + `get_graph_tracking` called after changes affecting data flow
- [ ] Record counts and port split ratios verified as sensible
- [ ] No component shows 0 records unexpectedly after the change
- [ ] No unresolved Stage 2 errors or warnings
- [ ] Used `kb_store` to persist any new discoveries for future sessions
