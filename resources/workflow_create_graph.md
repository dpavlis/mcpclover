# CloverDX Workflow Guide — `create_graph`

> Follow every phase in order. Do not skip steps. Do not start writing XML until Phase 1 is complete.

---

## PHASE 0 — Orient before writing anything

### 0.1 Read reference resources
Fetch available reference resources before writing any XML:
- Graph XML structure and schema
- CTL2 language reference
- Any component-specific reference material

**Do not rely on training knowledge alone.** MCP server resources are authoritative.

### 0.2 Look for reference/example graphs in the sandbox
Before implementing any pattern from scratch, search the sandbox for existing examples:

```
find_file("*Example*", sandbox)
find_file("*Template*", sandbox)
```

A working reference graph is the most reliable source of truth. Read it. Follow its patterns. Do not invent a different approach when a working example exists.

### 0.3 Sandbox safety rule (mandatory)
- **Never create/store graphs or any files in `wrangler_shared_home`.**
- `wrangler_shared_home` is a specialized shared sandbox on CloverDX servers and is not for LLM-generated artifacts.
- Use a normal project sandbox chosen for the task.

---

## PHASE 1 — Plan the graph

### 1.1 Identify candidate components for each processing step
Start by orienting on available components using `list_components` (optionally by category), then identify candidates.

```
list_components()
list_components("transformers")
list_components("readers")
```

For each step, identify **at least two candidate component types**, then select the most appropriate one.

**General rule: prefer specialized components over generic ones.**

| Task | Consider | Guidance |
|---|---|---|
| Basic aggregations (sum, avg, count, min, max) | AGGREGATE, DENORMALIZER, ROLLUP | Prefer **AGGREGATE** — purpose-built, no CTL needed |
| Non-standard aggregations or precise output record control | AGGREGATE, DENORMALIZER, ROLLUP | Use **DENORMALIZER** or **ROLLUP** — full CTL control |
| Splitting one record into many | NORMALIZER, REFORMAT | Prefer **NORMALIZER** — purpose-built for 1→N |
| Splitting a data flow into multiple output streams | PARTITION | **PARTITION** is the only flow-splitting component — no ROUTER or FILTER exists |
| Joining two streams | JOIN, HASH_JOIN | Depends on sort requirements — confirm with `get_component_info` |
| Declarative validation with accept/reject ports | VALIDATOR | Use when rules fit built-in rule types |
| Validation intertwined with complex transformation | REFORMAT | Use when VALIDATOR rules cannot express the logic cleanly |
| Generic field mapping / transformation | REFORMAT | Fallback when no specialized component fits; type=`REFORMAT`, UI name="Map" |

### 1.2 Call `get_component_info` for every component being used
**Mandatory for every component type** — no exceptions, even for familiar components.

```
get_component_info("VALIDATOR")
get_component_info("DENORMALIZER")
get_component_info("PARTITION")
```

Use the returned data to confirm:
- The component does what you think it does
- Exact port names and numbers (use these verbatim in edge declarations)
- Which attributes/properties are available

### 1.3 Call `get_component_details` for complex components
After `get_component_info`, call `get_component_details` for components with complex configuration:

```
get_component_details("VALIDATOR")
get_component_details("XML_EXTRACT")
```

If nothing is returned, that is fine — proceed with `get_component_info` data. Always call `get_component_info` first; never substitute `get_component_details` for it.

### 1.4 Design the metadata
Determine what fields each metadata record needs:
- All business data fields from the source
- Any auxiliary fields required downstream (e.g. `rejectReason` + `recordNo` for VALIDATOR error handling)

One metadata definition is shared across all edges in the same flow. Add auxiliary fields up front — valid records will simply have them null.

### 1.5 Confirm CTL2 entry points for each component

| Component | CTL entry point(s) |
|---|---|
| REFORMAT (Map) | `function integer transform()` |
| DENORMALIZER | `function integer append()`, `function integer transform()`, `function void clean()` |
| NORMALIZER | `function integer transform()`, `function integer count()` |
| VALIDATOR `errorMapping` | `function integer transform()` — `$in.0` = record, `$in.1` = error info (`validationMessage`, `recordNo`) |
| VALIDATOR `rules` `<expression>` | bare boolean expression — no `function`, no `return`, no `//#CTL2` |

User-defined helper functions in CTL2:
```
function <returnType> <functionName>(<params>) { ... }
```
`function` keyword comes **first**, before the return type.

---

## PHASE 2 — Write the graph XML

### 2.0 Build iteratively (LLM execution strategy)
Use an incremental pipeline approach instead of building the final graph in one pass:

1. Configure and validate input reading first.
2. End each current branch with a `TRASH` component as a temporary terminal.
3. Configure `TRASH` to log received data so input/output can be verified.
4. After each new transformation step, keep `TRASH` at the current end of the pipeline and re-validate.
5. Only after the flow is correct, replace final `TRASH` component(s) with the target destination component(s).

### 2.0.1 Iteration test guardrail (with user consent)
When building iteratively, do runtime checks after each meaningful step **only after explicit user consent**:

1. Execute the intermediate graph using `execute_graph`.
2. Inspect `get_graph_tracking` for per-component/edge record counts.
3. Use counts and flow progression for sanity checks (e.g. expected non-zero flow, expected drops after filters, expected splits/joins).

`validate_graph` proves XML/config validity; iterative execution + tracking provides a minimum-level logic check.

### 2.1 Nested CDATA escaping — most common source of errors
Any `]]>` sequence inside an outer CDATA block (e.g. inner `<expression>` CDATA inside the VALIDATOR `rules` CDATA) must be escaped as:
```
]]]]><![CDATA[>
```
Failure produces an XML parse error and the graph will not open. Review every CDATA-within-CDATA occurrence before writing.

### 2.2 VALIDATOR patterns
- Use `errorMapping` to capture rejection reasons — `$in.1.validationMessage` and `$in.1.recordNo`
- Follow with a DENORMALIZER keyed on `recordNo` to consolidate multiple per-rule errors into one output record
- **Never re-implement validation logic in a downstream REFORMAT** to generate rejection messages — this duplicates logic and breaks when rules change
- `customRejectMessage` is **not valid** on `<expression>` rule elements — schema rejects it; use a descriptive `name` attribute instead
- `errorMapping` is a separate `<attr name="errorMapping">` block alongside `<attr name="rules">` — not inside the rules XML

### 2.3 Edge `outPort` names — must be exact
Use names exactly as returned by `get_component_info`:

| Component | outPort string |
|---|---|
| Most readers | `Port 0 (output)` |
| VALIDATOR valid | `Port 0 (valid)` |
| VALIDATOR invalid | `Port 1 (invalid)` |
| REFORMAT, DENORMALIZER, etc. | `Port 0 (out)` |

---

## PHASE 3 — Validate

**Always call `validate_graph` immediately after writing the file.** Never present a graph as done without a passing validation.

```
validate_graph("graph/MyGraph.grf", sandbox)
```

### Interpreting results

| Result | Action |
|---|---|
| `overall: PASS`, no problems | Graph is clean — done |
| Stage 1 errors | XML is broken — graph won't open; fix before anything else |
| Stage 2 ERROR | Component config invalid — fix all errors |
| Stage 2 WARNING | Investigate — do not ignore |

### Common errors and fixes

| Error | Fix |
|---|---|
| `Attribute 'X' is not allowed to appear in element 'Y'` | Remove that attribute — not valid on that element (e.g. `customRejectMessage` on `<expression>`) |
| `element type "X" must be terminated by matching end-tag` | Malformed XML — check nested CDATA escaping |
| `Can't deserialize validation rules` | VALIDATOR `rules` CDATA contains invalid XML — check escaping and invalid attributes |
| `Syntax error on token 'function'` | CTL function declared as `returnType function name()` — flip to `function returnType name()` |
| `CTL code compilation finished with N errors` | CTL syntax error in transform, errorMapping, or denormalize attribute |

---

## CHECKLIST — before presenting the graph as complete

- [ ] Fetched relevant reference resources
- [ ] Checked sandbox for reference/example graphs
- [ ] Confirmed sandbox is not `wrangler_shared_home`
- [ ] Called `list_components` to orient on available component types/categories
- [ ] Identified at least two candidate components per processing step
- [ ] Called `get_component_info` for every component type used
- [ ] Called `get_component_details` for complex components
- [ ] Selected most specialized component for each step
- [ ] No use of non-existent components (no ROUTER, no FILTER — use PARTITION for flow splitting)
- [ ] Metadata includes all auxiliary fields needed downstream
- [ ] All nested CDATA sequences correctly escaped (`]]]]><![CDATA[>`)
- [ ] No `customRejectMessage` on `<expression>` rule elements
- [ ] CTL user-defined functions: `function returnType name(...)` — not `returnType function name(...)`
- [ ] Edge outPort strings match exactly the names from `get_component_info`
- [ ] Graph was built iteratively; `TRASH` used as temporary logged terminal(s) during development
- [ ] For iterative steps, and with user consent, intermediate graph execution was verified using `execute_graph` + `get_graph_tracking`
- [ ] `validate_graph` called after writing
- [ ] Validation result is `overall: PASS` with no errors or warnings
