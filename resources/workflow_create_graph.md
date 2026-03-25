# CloverDX Workflow Guide — `create_graph`

> LLM-only guide. Execute phases in order. Do not write XML until Phase 2 is complete.

---

## PHASE 0 — Read authoritative context

### 0.1 Read resources
Always read authoritative MCP resources before any other work:

```
read_resource("cloverdx://reference/graph-xml")
read_resource("cloverdx://reference/ctl2")
```

If creating a subgraph, also read:
```
read_resource("cloverdx://reference/subgraphs")
```

Do not rely on training knowledge when a resource exists. These are the authoritative
source — they override anything you think you know.

### 0.2 Resolve sandbox parameters
Check what the standard path parameters resolve to in this sandbox:

```
get_sandbox_parameters(sandbox)       -- resolved ${DATAIN_DIR}, ${CONN_DIR} etc.
```

This is needed before writing any file paths into graph XML.

### 0.3 Sandbox rule
Never create or store files in `wrangler_shared_home`.

---

## PHASE 1 — Identify and research components

### 1.1 Think through candidate components
Before looking anything up, call `think` to reason through the processing steps:

```
think("What are the processing steps? For each step, what are 2+ candidate
      component types? Which is most specialized for this task?")
```

Use `list_components(category)` to orient if the component name is not known:
```
list_components("transformers")
list_components("joiners")
```

Selection rules — prefer the most specialized valid component:

| Task | Prefer | Notes |
|---|---|---|
| Basic aggregation (sum/avg/count/min/max) | `AGGREGATE` | No CTL needed |
| Custom aggregation / exact output control | `DENORMALIZER` or `ROLLUP` | When AGGREGATE insufficient |
| 1 record → N records | `NORMALIZER` | Prefer over REFORMAT for this pattern |
| Split flow into multiple flows | `PARTITION` | No ROUTER or FILTER exists |
| Equality join, unsorted, slave fits in memory | `EXT_HASH_JOIN` | Most common join |
| Equality join, both inputs pre-sorted | `EXT_MERGE_JOIN` | Add sort upstream if needed |
| Join against static reference table | `LOOKUP_JOIN` | Table declared in Global |
| Join against DB per record | `DBJOIN` | Slow for large drivers — consider EXT_HASH_JOIN instead |
| Merge N unsorted streams | `SIMPLE_GATHER` | Non-deterministic order |
| Merge N streams preserving port order | `CONCATENATE` | All from port 0 first, then port 1, etc. |
| Merge N pre-sorted streams into one sorted | `MERGE` | Inputs MUST be sorted |
| Declarative validation with accept/reject | `VALIDATOR` | When built-in rule types fit |
| Validation mixed with transform logic | `REFORMAT` | When VALIDATOR rules insufficient |
| Generic mapping / transform | `REFORMAT` | Fallback only |

### 1.2 Call `get_component_info` for every candidate
Mandatory for every component type being considered — no exceptions:

```
get_component_info("VALIDATOR")
get_component_info("DENORMALIZER")
get_component_info("EXT_HASH_JOIN")
```

Use the returned data to:
- Confirm the component does what you think it does (check `Usage:` field)
- Get exact port names and numbers for edge declarations
- Identify which properties are `[attr-cdata]` vs plain XML attributes
- Make final component selection

### 1.3 Call `get_component_details` for complex components
After `get_component_info`, call `get_component_details` for any component with
complex configuration — mapping XML, errorMapping patterns, rule schemas, etc.:

```
get_component_details("VALIDATOR")    -- errorMapping pattern, rules XML schema,
                                      -- customRejectMessage limitations,
                                      -- errorMapping CTL port semantics ($in.1.validationMessage)
get_component_details("XML_EXTRACT")  -- mapping XML, parentKey/generatedKey syntax
```

**Call `get_component_details` whenever:**
- The component has a `[attr-cdata]` property containing XML (not just CTL)
- The component has multiple interacting attributes (e.g. VALIDATOR rules + errorMapping)
- You are unsure about the correct CTL entry point signatures for the component
- The `get_component_info` output contains opaque type labels like `[validatorRules]`,
  `[xmlMapping]`, `[hashJoinKey]` — these signal that extended docs may exist

If no details are returned, proceed with `get_component_info` data alone.
Always call `get_component_info` first — never substitute `get_component_details` for it.

### 1.4 Find reference graphs using grep_files
Now that you know which components you will use, search for existing graphs
that use the same components — these are your canonical pattern references.
Use `grep_files` not `find_file` — it searches inside files, not just filenames:

```
grep_files(sandbox, search_string='type="VALIDATOR"', file_pattern="*.grf", path="graph")
grep_files(sandbox, search_string='type="DENORMALIZER"', file_pattern="*.grf", path="graph")
```

Read any promising reference graph before designing your own:
```
read_file("graph/ValidateOrderInput_withErrors.grf", sandbox)
```

Use `think` to reason about the reference pattern before deciding whether to follow it:
```
think("The reference graph uses errorMapping + DENORMALIZER for rejection reasons.
      My task is the same pattern. I should follow it exactly rather than
      inventing a different approach.")
```

If a working reference exists that matches your pattern, copy it — do not invent
a different solution.

---

## PHASE 2 — Design the graph

### 2.1 Design metadata
Determine the metadata structure for each stage of the data flow:
- All business fields from the source
- Auxiliary fields needed downstream (e.g. `rejectReason:string`, `recordNo:long`
  for VALIDATOR error handling)
- Whether to reuse existing `.fmt` files (from `list_linked_assets`) or define inline

One metadata definition is shared across all edges at the same stage.
Valid records will simply have auxiliary fields null.

### 2.2 Confirm CTL entry points
Before planning any CTL code, confirm the required function signatures:

| Component / attr | Required CTL entry points |
|---|---|
| `REFORMAT` `transform` | `function integer transform()` |
| `DENORMALIZER` `denormalize` | `function integer append()`, `function integer transform()`, `function void clean()` |
| `NORMALIZER` `normalize` | `function integer count()`, `function integer transform(integer idx)` |
| `ROLLUP` `transform` | `function boolean initGroup(GroupAccMeta g)`, `function boolean updateGroup(GroupAccMeta g)`, `function boolean finishGroup(GroupAccMeta g)`, `function integer transform(integer counter, GroupAccMeta g)` |
| `DATA_GENERATOR` `generate` | `function integer generate()` — return `OK` to continue, `STOP` to terminate |
| `VALIDATOR` `errorMapping` | `function integer transform()` — `$in.0`=record, `$in.1.validationMessage`, `$in.1.recordNo` |
| `VALIDATOR` `rules` `<expression>` | bare boolean — no `function`, no `return`, no `//#CTL2` |
| `PARTITION` `partitionSource` | `function integer getOutputPort()` |

User-defined helper functions: `function` keyword comes **first**:
```
function <returnType> <functionName>(<params>) { ... }
```

### 2.3 Discover reusable assets for the planned components
Now that you know which components you need and what data flows between them,
check what shared assets already exist in the sandbox:

```
list_linked_assets(sandbox)               -- all asset types
list_linked_assets(sandbox, asset_type="metadata")   -- if you need specific .fmt files
list_linked_assets(sandbox, asset_type="ctl")        -- before writing any CTL logic inline
list_linked_assets(sandbox, asset_type="connection") -- before defining a DB connection
```

At this point you have enough context to evaluate the results meaningfully:
- Does a `.fmt` file already exist for the record structure you need?
  → Use `source="external"` in metadata[], reference the fileURL
- Does a `.ctl` file already exist with functions you were about to write?
  → Import it via `ctl_imports[]` instead of duplicating logic inline
- Does a `.cfg` connection already exist for the DB you need?
  → Reference it by ID in `connections[]`
- Do relevant `.lkp` or `.seq` files exist?
  → Reference them rather than defining inline

Calling this too early (before knowing what components and data structures are
needed) produces a list you cannot meaningfully evaluate. Calling it here,
after Phase 1 and 2.1–2.2, gives you the context to use it effectively.

### 2.4 Produce a formal plan with plan_graph
Before writing any XML, call `plan_graph` to document the intended layout and
catch basic structural inconsistencies early:

```
plan_graph(
    graph_name, sandbox, graph_path, purpose,
    phases=[...],
    components=[{id, type, purpose, key_config, ctl_entry_points}, ...],
    metadata=[{id, description, source, file_url?, key_fields}, ...],
    edges=[{id, from_node, from_port, to_node, to_port, metadata_id}, ...],
    global_assets={
        connections=[...],    -- .cfg references for DB components
        lookup_tables=[...],  -- .lkp references
        sequences=[...],      -- .seq references
        ctl_imports=[...],    -- .ctl files to import (check list_linked_assets first!)
        subgraphs=[...],      -- jobURL + __PARAM values
        parameters=[...]      -- beyond workspace.prm
    },
    risks=[...],
    reference_graphs=[...]
)
```

**What `plan_graph` checks (basic layout validation only):**
- Every edge references component IDs that exist in components[]
- Every metadata_id on an edge exists in metadata[]
- CTL-bearing components have ctl_entry_points declared
- Required subgraph parameters are in param_values
- DENORMALIZER / MERGE / DEDUP / EXT_MERGE_JOIN have a sort-type component
  somewhere upstream in the edge chain

**What `plan_graph` does NOT and CANNOT check — your responsibility:**
- Whether data actually arrives sorted — a sort component upstream is not the
  only way data can be sorted. `DB_INPUT_TABLE` with `ORDER BY` in the SQL
  produces sorted output without any sort component. `plan_graph` will falsely
  warn about a missing sort in this case — use `risks[]` to document that
  sorting is handled by the query, and suppress the warning consciously.
- Whether optional ports need to be connected based on component configuration —
  some components conditionally require optional ports depending on settings
  (e.g. `dataPolicy=controlled` on a reader activates port 1 for error records).
  `plan_graph` treats optional ports as always optional.
- CTL logic correctness — entry points being declared does not mean the code
  is correct. Logic errors only surface at runtime.
- Metadata field type compatibility across edges — two edges both labelled
  `MetaOrder` are assumed compatible; actual field mismatches only surface
  during execute.
- Whether connections, lookups, or sequences actually work — declarations are
  checked but connectivity and correctness are not.

**Treat `plan_graph` as a layout sanity check, not as a correctness authority.**
Its value is catching obvious structural mistakes (wrong edge target, missing
metadata ID, undeclared sequence) before writing XML — not as a substitute for
the incremental execute + tracking verification in Phase 3.

Review consistency warnings returned. Fix genuine ERRORs. For warnings that
reflect intentional design decisions (e.g. pre-sorted DB output), document
the rationale in `risks[]` and proceed consciously.

---

## PHASE 3 — Build and verify incrementally

The core principle: **never build the full graph in one pass and only then test it.**
Add one stage at a time, validate structurally, then execute and verify runtime
behaviour before adding the next stage. Structural validity (validate_graph) and
runtime correctness (execute + tracking) are both required at each step.

### 3.1 Back up before writing
Before writing any graph file that already exists, create a backup:
```
copy_file("graph/MyGraph.grf", sandbox, "graph/MyGraph.bak.grf", sandbox)
```

### 3.2 The incremental build loop
Repeat this loop for each stage added to the graph:

```
1. Write the stage (reader / transform / join / etc.) + TRASH terminal
2. validate_graph  →  fix all errors before proceeding
3. execute_graph   →  confirm no runtime errors
4. get_graph_tracking  →  verify record counts are sensible
5. If counts are wrong: diagnose with think(), fix, repeat from step 2
6. Move TRASH to the next stage and continue
```

**Step 2 catches:** XML errors, invalid attributes, CTL compile errors, wrong port names.
**Step 3 catches:** Runtime failures — file not found, DB connection failure, CTL
runtime exception (null dereference, type mismatch, division by zero), wrong date
format, sequence not declared.
**Step 4 catches:** Logic errors — filter drops all records, join produces 0 matches,
wrong branch taken, unexpected null propagation.

Neither validate nor execute alone is sufficient. Both are required.

### 3.3 TRASH configuration for incremental testing
Always attach TRASH at the current end of the incomplete pipeline with debug printing
enabled so records are visible in the execution log:

```xml
<Node debugPrint="true" guiName="Trash" guiX="..." guiY="..."
      id="TRASH_DEBUG" type="TRASH"/>
```

Or set it via:
```
set_graph_element_attribute(..., element_id="TRASH_DEBUG",
    attribute_name="debugPrint", value="true")
```

This confirms records are actually flowing and lets you inspect values without
writing output files.

### 3.4 Interpreting tracking results
After `execute_graph`, always call:
```
run = execute_graph("graph/MyGraph.grf", sandbox)
get_graph_tracking(run.run_id)
```

Check for each component:
- **Input record count** — matches the expected source volume
- **Output record count** — reasonable relative to input (a filter that passes 0% of
  records is almost always wrong)
- **Port split ratios** — for VALIDATOR: valid + invalid = total input;
  for EXT_FILTER: accepted + rejected = total input
- **No component shows 0 records unexpectedly** — a join producing 0 matched records
  usually means a wrong join key or metadata type mismatch on the key field

Use `think` to reason through unexpected counts before attempting a fix:
```
think("The EXT_HASH_JOIN shows 0 output records. Input to port 0 was 1000 records,
      input to port 1 was 500 records. The join key is Store_Id (integer) on port 0
      and customerId (integer) on port 1. joinType=inner. Possible causes:
      1) No matching keys between the two streams — check actual data values
      2) Type mismatch on the key field — both are integer so this is unlikely
      3) Wrong joinKey format — should be $0.Store_Id=$1.customerId
      I should check the joinKey attribute and verify a few sample values exist
      in both streams.")
```

### 3.5 When to use debug mode
For most incremental testing, plain `execute_graph` + `get_graph_tracking` is
sufficient. Enable debug mode (`execute_graph(debug=true)`) when:
- Tracking shows unexpected counts and you need to inspect actual record values
- You want to verify field values at a specific edge, not just counts
- A runtime error occurs mid-stream and you need to see the records at the
  point of failure

Debug mode workflow:
```
run = execute_graph("graph/MyGraph.grf", sandbox, debug=True)
get_edge_debug_info(edge_id="Edge2", graph_path, sandbox, run_id)
get_edge_debug_metadata(edge_id="Edge2", ...)   -- confirm field schema
get_edge_debug_data(run_id=run_id, edge_id="Edge2", record_count=50)
```

### 3.6 Use `set_graph_element_attribute` for targeted changes
Prefer `set_graph_element_attribute` over `patch_file` for all graph modifications:

```
set_graph_element_attribute(graph_path, sandbox,
    element_type="Node", element_id="DATA_GENERATOR",
    attribute_name="recordsNumber", value="100")

set_graph_element_attribute(graph_path, sandbox,
    element_type="Node", element_id="TRANSFORM",
    attribute_name="attr:transform",
    value="//#CTL2\nfunction integer transform() {...}")
```

Use `patch_file` only for structural changes that `set_graph_element_attribute`
cannot handle (e.g. adding a new Node or Edge element). Always use `dry_run=true` first.

### 3.7 Nested CDATA escaping — most common breakage source
Any `]]>` inside an outer CDATA block must be escaped as:
```
]]]]><![CDATA[>
```
This is required in VALIDATOR `rules` CDATA blocks that contain `<expression>`
elements with their own CDATA. Always review before writing.

### 3.8 Edge `outPort` strings must match exactly
Use the exact strings from `get_component_info` — not guesses.

| Component | Exact `outPort` |
|---|---|
| Most readers | `Port 0 (output)` |
| VALIDATOR valid | `Port 0 (valid)` |
| VALIDATOR invalid | `Port 1 (invalid)` |
| REFORMAT, DENORMALIZER, etc. | `Port 0 (out)` |

---

## PHASE 4 — Final validation and cleanup

### 4.1 Replace TRASH terminals with real destinations
Only after all stages are verified do you replace TRASH nodes with real output
components. After replacement, run the full validate + execute + tracking cycle
one final time on the complete graph.

### 4.2 Validate after every write
Always call `validate_graph` immediately after every write. Never present a
graph as done without a clean pass.

```
validate_graph("graph/MyGraph.grf", sandbox)
```

| Result | Action |
|---|---|
| `overall: PASS`, no problems | Done for this step |
| Stage 1 errors | XML broken — fix before anything else |
| Stage 2 ERROR | Component config invalid — fix all errors |
| Stage 2 WARNING | Investigate — do not ignore |

**Validation may not be exhaustive.** Fix reported issues and re-validate —
additional problems may surface only after earlier ones are resolved.

When validation fails, use `think` to diagnose before attempting a fix:
```
think("Error: 'Attribute customRejectMessage not allowed on expression'.
      This means I put customRejectMessage on an <expression> rule element.
      Fix: remove it and use name attribute as the human-readable label instead.")
```

Common failures and fixes:

| Error | Fix |
|---|---|
| `Attribute 'X' is not allowed in element 'Y'` | Remove invalid attribute (e.g. `customRejectMessage` on `<expression>`) |
| `element type "X" must be terminated by matching end-tag` | Fix malformed XML / nested CDATA escaping |
| `Can't deserialize validation rules` | VALIDATOR rules CDATA broken — check nested CDATA and invalid attributes |
| `Syntax error on token 'function'` | CTL declared as `returnType function name()` — flip to `function returnType name()` |
| `CTL code compilation finished with N errors` | CTL syntax error — read full message, find the line, fix it |

---

## CHECKLIST — before presenting the graph as complete

- [ ] Read `cloverdx://reference/graph-xml` and `cloverdx://reference/ctl2`
- [ ] Read `cloverdx://reference/subgraphs` if creating a subgraph
- [ ] Called `get_sandbox_parameters` — know what ${DATAIN_DIR} etc. resolve to
- [ ] Sandbox is not `wrangler_shared_home`
- [ ] Used `think` to reason through component candidates before looking them up
- [ ] Called `list_components` to orient if component names were uncertain
- [ ] Considered at least 2 candidate components per processing step
- [ ] Called `get_component_info` for every component type used
- [ ] Called `get_component_details` for complex components (VALIDATOR, XML_EXTRACT, etc.)
- [ ] Used `grep_files` with component type strings to find reference graphs — not find_file
- [ ] Read relevant reference graphs and used `think` to evaluate their patterns
- [ ] Designed metadata including all downstream auxiliary fields
- [ ] Confirmed CTL entry points for every CTL-bearing component
- [ ] Called `list_linked_assets` after component/metadata design — checked for reusable .fmt/.cfg/.ctl/.lkp/.seq before defining anything inline
- [ ] Called `plan_graph` — reviewed layout warnings; genuine errors fixed; false-positive warnings (e.g. sort handled by DB query ORDER BY) documented in risks[] and consciously accepted
- [ ] Backed up any existing graph before overwriting
- [ ] Built incrementally: each stage validated (validate_graph) AND executed (execute_graph) before adding the next
- [ ] After each execution: get_graph_tracking called and record counts verified as sensible
- [ ] No stage produces 0 records unexpectedly
- [ ] Port split ratios are correct (valid + invalid = total, accepted + rejected = total, etc.)
- [ ] Used `set_graph_element_attribute` for targeted attribute/CTL changes
- [ ] Escaped nested CDATA as `]]]]><![CDATA[>` where needed
- [ ] Edge outPort strings match exactly the names from `get_component_info`
- [ ] No non-existent components used (no ROUTER, no FILTER)
- [ ] CTL user-defined functions: `function returnType name(...)` not `returnType function name(...)`
- [ ] TRASH terminals replaced with real destinations for final graph
- [ ] Final full graph: validate_graph PASS + execute_graph SUCCESS + tracking verified
