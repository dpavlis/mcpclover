# CloverDX Workflow Guide — `create_graph`

> LLM-only guide. Execute phases in order. Do not write XML until Phase 1 is complete.

## PHASE 0 — Read authoritative context

### 0.1 Read resources
Always read authoritative MCP resources first:
- Graph XML reference
- CTL2 reference
- Component-specific docs when needed

If the task includes creating a subgraph, also call:

```
read_resource("cloverdx://reference/subgraphs")
```

Use it as the authority for `.sgrf`, `nature="subgraph"`, `SubgraphInput`, `SubgraphOutput`, and subgraph port rules.

Do not rely on training knowledge when a resource exists.

### 0.2 Look for example graphs
Before inventing a pattern, search the sandbox:

```
find_file("*Example*", sandbox)
find_file("*Template*", sandbox)
```

If a working example exists, read it and copy its pattern.

### 0.3 Sandbox rule
Never create or store files in `wrangler_shared_home`.

---

## PHASE 1 — Plan before writing

### 1.1 Identify candidate components
Orient with:

```
list_components()
list_components("transformers")
list_components("readers")
```

For each step, consider at least 2 candidate component types, then choose the most specialized valid one.

| Task | Prefer | Notes |
|---|---|---|
| Basic aggregation | `AGGREGATE` | Prefer over CTL-based options |
| Custom aggregation / exact output control | `DENORMALIZER` or `ROLLUP` | Use when AGGREGATE cannot express it |
| 1 input record -> N output records | `NORMALIZER` | Prefer over REFORMAT |
| Split one flow into multiple flows | `PARTITION` | No `ROUTER`, no `FILTER` |
| Join streams | `JOIN` or `HASH_JOIN` | Confirm requirements via `get_component_info` |
| Declarative validation | `VALIDATOR` | Use when built-in rule model fits |
| Validation mixed with custom transform logic | `REFORMAT` | Use when VALIDATOR rules are insufficient |
| Generic mapping / transform | `REFORMAT` | Fallback only |

### 1.2 Get exact component definitions
Mandatory for every component type used:

```
get_component_info("VALIDATOR")
get_component_info("DENORMALIZER")
get_component_info("PARTITION")
```

Confirm:
- actual component capability
- exact port names and numbering
- valid attributes/properties

### 1.3 Get detailed docs for complex components
After `get_component_info`, call:

```
get_component_details("VALIDATOR")
get_component_details("XML_EXTRACT")
```

If no details exist, continue with `get_component_info`. Never skip `get_component_info`.

### 1.4 Design metadata up front
Include:
- all business fields
- all downstream auxiliary fields

### 1.5 Confirm CTL entry points

| Component / attr | Required CTL form |
|---|---|
| `REFORMAT` | `function integer transform()` |
| `DENORMALIZER` | `function integer append()`, `function integer transform()`, `function void clean()` |
| `NORMALIZER` | `function integer transform()`, `function integer count()` |

User helper functions must be declared as:

```
function <returnType> <name>(<params>) { ... }
```

Not `returnType function name(...)`.

---

## PHASE 2 — Write incrementally

### 2.0 Build as a pipeline
Do not build the full graph in one pass.

1. Configure and validate input reading first.
2. End each unfinished branch with `TRASH`.
3. Configure `TRASH` to log received data.
4. After each added step, keep `TRASH` at the current end and re-validate.
5. Replace terminal `TRASH` nodes with real destinations only after the flow is correct.

### 2.0.1 Runtime checks need consent
If user consent exists, after meaningful steps:
1. call `execute_graph`
2. inspect `get_graph_tracking`
3. confirm expected counts and drops/splits

`validate_graph` checks structure/config. Execution + tracking checks basic logic.

### 2.1 Nested CDATA rule
If `]]>` appears inside an outer CDATA block, escape it as:

```
]]]]><![CDATA[>
```

This is the most common XML breakage source.

### 2.2 Edge `outPort` strings must match exactly
Use the exact strings from `get_component_info`.

| Component | Exact `outPort` |
|---|---|
| Most readers | `Port 0 (output)` |
| REFORMAT / DENORMALIZER / similar | `Port 0 (out)` |

---

## PHASE 3 — Validate immediately

Always call `validate_graph` right after writing the file.

```
validate_graph("graph/MyGraph.grf", sandbox)
```

Interpretation:

| Result | Meaning | Action |
|---|---|---|
| `overall: PASS` | clean | done |
| Stage 1 errors | XML broken | fix before anything else |
| Stage 2 errors | component config invalid | fix all |
| Stage 2 warnings | risk remains | investigate |

Common failures:

| Error | Fix |
|---|---|
| `Attribute 'X' is not allowed to appear in element 'Y'` | remove invalid attribute |
| `element type "X" must be terminated by matching end-tag` | fix malformed XML / nested CDATA escaping |
| `Syntax error on token 'function'` | change to `function returnType name()` |
| `CTL code compilation finished with N errors` | fix CTL syntax |

---

## CHECKLIST

- [ ] Read relevant resources
- [ ] If creating subgraph: read `cloverdx://reference/subgraphs`
- [ ] Checked sandbox for example/template graphs
- [ ] Sandbox is not `wrangler_shared_home`
- [ ] Oriented with `list_components`
- [ ] Considered at least 2 candidate components per step
- [ ] Called `get_component_info` for every component type used
- [ ] Called `get_component_details` for complex components
- [ ] Chose the most specialized valid component
- [ ] Did not invent non-existent components (`ROUTER`, `FILTER`)
- [ ] Designed metadata including downstream auxiliary fields
- [ ] Verified CTL entry points before writing CTL
- [ ] Escaped nested CDATA as `]]]]><![CDATA[>` where needed
- [ ] Matched edge `outPort` strings exactly to component docs
- [ ] Built incrementally with temporary logged `TRASH` terminals
- [ ] If user consented, used `execute_graph` + `get_graph_tracking` for incremental checks
- [ ] Called `validate_graph` after writing
- [ ] Final validation is PASS with no unresolved errors or warnings
