# CloverDX Workflow Guide — `edit_graph`

> LLM-only guide. Core rule: read current server state before editing; validate immediately after every write.

## PHASE 0 — Subgraph-first rules

### 0.1 If the edit touches subgraphs, read the subgraph reference first
Call:

```
read_resource("cloverdx://reference/subgraphs")
```

Do this before editing when any of these are true:
- the file being edited is a `.sgrf`
- a `.grf` edit adds/removes/reconfigures a `SUBGRAPH` component
- subgraph ports, public parameters, `jobURL`, `SubgraphInput`, or `SubgraphOutput` are affected

### 0.2 Subgraph edit rules
- subgraph files are `.sgrf` and require `<Graph nature="subgraph">`
- `SUBGRAPH_INPUT` and `SUBGRAPH_OUTPUT` rules are structural, not optional conventions
- port numbering and `<Port name="N"/>` declarations are the source of truth for parent-graph edges
- `debugInput="true"` and `debugOutput="true"` are only for standalone test-only nodes
- parent graph should reference subgraphs via `${SUBGRAPH_DIR}/.../*.sgrf`
- public subgraph parameters are passed as `__PARAM_NAME` attributes on the parent `SUBGRAPH` node

Do not guess subgraph structure from generic graph rules alone.

---

## PHASE 1 — Read current state

### 1.1 Read the current file first
Always read the current server copy before changing anything:

```
read_file("graph/MyGraph.grf", sandbox)
```

After any successful write, patch, or rename, the in-context copy is stale.

### 1.2 Read only the references relevant to the edit
Read:
- Graph XML reference if structure changes
- CTL2 reference if CTL changes
- component detail docs for complex components being added or reconfigured

### 1.3 Look for working examples if introducing a new pattern

```
find_file("*Example*", sandbox)
find_file("*Template*", sandbox)
```

If an example exists, copy its pattern instead of inventing a new one.

### 1.4 Sandbox rule
Never create or store files in `wrangler_shared_home`.

---

## PHASE 2 — Plan the exact delta

### 2.1 Enumerate the change precisely
Before editing, identify:
- affected components
- affected attributes / metadata / edges / CTL blocks
- new dependencies introduced by the change
- broken dependencies that will result if a node/edge/metadata item is removed

### 2.2 If adding or reconfiguring components, re-check definitions
Orient first if needed:

```
list_components()
list_components("transformers")
list_components("readers")
```

Then verify with:

```
get_component_info("DENORMALIZER")
get_component_details("XML_EXTRACT")
```

Do not rely on memory for port names, attribute names, or CTL entry points.

### 2.3 CTL declaration rule
User helper functions must use:

```
function <returnType> <name>(<params>) { ... }
```

Not `returnType function name(...)`.

---

## PHASE 3 — Apply changes safely

### 3.1 Pipeline edits must stay incremental
For edits that change data flow:
1. keep or add temporary `TRASH` terminals
2. re-validate after each meaningful step
3. replace `TRASH` with final destinations only after the branch is correct

### 3.2 Runtime checks require user consent
If user consent exists, after meaningful steps:
1. call `execute_graph`
2. inspect `get_graph_tracking`
3. confirm expected counts and flow behavior

### 3.3 Choose `patch_file` vs `write_file`
Use `patch_file` for small, isolated edits.
Use `write_file` for:
- larger structural rewrites
- many nearby edits
- already malformed files

If using `patch_file`:
- run `dry_run: true` first
- use unique anchors
- if a patch succeeds and another patch is needed, re-read the file first

### 3.4 Never patch from stale state
After every successful `patch_file` or `write_file`, re-read before computing another change.

### 3.5 If patching corrupted the file, stop patching
Switch to a clean full rewrite with `write_file`.

### 3.6 Nested CDATA rule
If `]]>` appears inside outer CDATA, escape it as:

```
]]]]><![CDATA[>
```

### 3.7 Edge port names must match exact component docs
Use the exact strings returned by `get_component_info`.

Typical examples:

| Component | Exact `outPort` |
|---|---|
| Most readers | `Port 0 (output)` |
| REFORMAT / DENORMALIZER / similar | `Port 0 (out)` |

---

## PHASE 4 — Validate after every write

Always call:

```
validate_graph("graph/MyGraph.grf", sandbox)
```

immediately after each `write_file` or `patch_file`.

Interpretation:

| Result | Meaning | Action |
|---|---|---|
| `overall: PASS` | clean | proceed / done |
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

Do not present the edit as complete while validation errors or warnings remain unexplained.

---

## CHECKLIST

- [ ] If subgraph-related: read `cloverdx://reference/subgraphs` first
- [ ] Read the current server file before editing
- [ ] Read only the references relevant to the change
- [ ] Checked sandbox for example/template graphs when introducing a new pattern
- [ ] Sandbox is not `wrangler_shared_home`
- [ ] Enumerated exact components / attributes / metadata / edges being changed
- [ ] Called `list_components` when introducing new component types
- [ ] Called `get_component_info` for added or reconfigured components
- [ ] Called `get_component_details` for complex components
- [ ] Did not invent non-existent components (`ROUTER`, `FILTER`)
- [ ] Updated metadata if the edit requires new fields
- [ ] Used correct CTL declaration form: `function returnType name(...)`
- [ ] Escaped nested CDATA as `]]]]><![CDATA[>` where needed
- [ ] Matched edge port names exactly to component docs
- [ ] Re-read between multiple patches
- [ ] Used incremental verification with temporary `TRASH` terminals for pipeline edits
- [ ] If user consented, used `execute_graph` + `get_graph_tracking` for runtime checks
- [ ] Called `validate_graph` after the most recent write or patch
- [ ] Final validation is PASS with no unresolved issues
