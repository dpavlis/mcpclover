# CloverDX Workflow Guide — `edit_graph`

> Follow every phase in order. The most critical rule for editing: always read before writing, and always validate after writing.

---

## PHASE 0 — Read and understand the current state

### 0.1 Read the graph file from the server first
**Always read the current file before making any changes.** Never work from memory or from an earlier version in context.

```
read_file("graph/MyGraph.grf", sandbox)
```

The file on the server is the only source of truth. Your in-context copy becomes stale the moment any write occurs.

### 0.2 Read reference resources relevant to the change
Fetch MCP reference resources for any component or pattern touched by the edit:
- Graph XML structure if the change affects structure
- CTL2 reference if the change involves CTL2 code
- Component-specific documentation for any component being added or reconfigured

### 0.3 Look for reference/example graphs if adding a new pattern
If the edit introduces a pattern that doesn't exist in the graph yet (e.g. adding error handling, adding a new component type), search the sandbox for a working example first:

```
find_file("*Example*", sandbox)
find_file("*Template*", sandbox)
```

---

## PHASE 1 — Plan the change

### 1.1 Identify exactly what needs to change
Before touching the file, enumerate precisely:
- Which component(s) are affected?
- Which attributes, CTL2 code blocks, metadata fields, or edges need to change?
- Does the change require adding new components? New metadata fields? New edges?
- Does removing or changing a component break any existing edge or metadata dependency?

### 1.2 Look up any components being added or modified
Call `get_component_info` for any component type you are adding or significantly reconfiguring — even if it already exists in the graph:

```
get_component_info("DENORMALIZER")
```

Then call `get_component_details` for complex components:

```
get_component_details("VALIDATOR")
```

Do not assume you remember the correct attribute names, port numbers, or CTL entry points from earlier in the session. Verify.

### 1.3 Identify CTL2 entry points for any CTL being written or changed

| Component | CTL entry point(s) |
|---|---|
| REFORMAT (Map) | `function integer transform()` |
| DENORMALIZER | `function integer append()`, `function integer transform()`, `function void clean()` |
| NORMALIZER | `function integer transform()`, `function integer count()` |
| VALIDATOR `errorMapping` | `function integer transform()` — `$in.0` = record, `$in.1` = error info (`validationMessage`, `recordNo`) |
| VALIDATOR `rules` `<expression>` | bare boolean expression — no `function`, no `return`, no `//#CTL2` |

User-defined helper functions: `function` keyword comes **first**:
```
function <returnType> <functionName>(<params>) { ... }
```

---

## PHASE 2 — Apply the change

### 2.1 Choose between `patch_file` and `write_file`

**Use `patch_file` for small, targeted changes (1–5 lines):**
- Always run with `dry_run: true` first to verify the patch before applying it
- Anchor string must uniquely identify the target line — if ambiguous, use `anchor_occurrence`
- Use a longer surrounding context string if a short anchor is not unique

**Use `write_file` for:**
- Large structural changes affecting many parts of the file
- Any situation where the file is already malformed
- When multiple patches would be needed in close proximity

**Never patch a file you haven't just re-read.** After any successful `write_file` or `patch_file`, your in-context copy is stale. Re-read before making further changes.

### 2.2 After patching — re-read before a second patch
A successful patch changes the file on the server. If you need to apply more than one patch, re-read the file after each patch before computing the next one. Patching based on a stale mental model causes structural corruption.

### 2.3 When patching has corrupted the file — stop patching, rewrite
If the file has become malformed due to incorrect patches, do not attempt further patches. Switch to a clean `write_file` with fully correct content. Incremental patching of a broken file makes the situation worse.

### 2.4 Nested CDATA escaping — check every change involving CDATA
If the change touches any CDATA block that contains nested CDATA (e.g. VALIDATOR `rules` containing `<expression>` elements), ensure inner `]]>` sequences are escaped as:
```
]]]]><![CDATA[>
```
This is the most common source of "Cannot load graph" errors.

### 2.5 VALIDATOR-specific rules (if editing a VALIDATOR)
- `customRejectMessage` is **not valid** on `<expression>` rule elements — use a descriptive `name` attribute instead
- `errorMapping` is a separate `<attr name="errorMapping">` block — not inside `<attr name="rules">`
- For rejection reasons: `errorMapping` captures `$in.1.validationMessage` + `$in.1.recordNo`; a DENORMALIZER keyed on `recordNo` consolidates multiple errors per record
- **Never add a downstream REFORMAT that re-implements validation logic** to produce rejection messages

### 2.6 Edge outPort names — must be exact
If the change adds or modifies edges, use port names exactly as returned by `get_component_info`:

| Component | outPort string |
|---|---|
| Most readers | `Port 0 (output)` |
| VALIDATOR valid | `Port 0 (valid)` |
| VALIDATOR invalid | `Port 1 (invalid)` |
| REFORMAT, DENORMALIZER, etc. | `Port 0 (out)` |

---

## PHASE 3 — Validate

**Always call `validate_graph` immediately after every `write_file` or `patch_file`.** Never present the edit as done without a passing validation.

```
validate_graph("graph/MyGraph.grf", sandbox)
```

### Interpreting results

| Result | Action |
|---|---|
| `overall: PASS`, no problems | Edit is clean — done |
| Stage 1 errors | XML is broken — graph won't open; fix before anything else |
| Stage 2 ERROR | Component config invalid — fix all errors |
| Stage 2 WARNING | Investigate — do not ignore |

### Common errors and fixes

| Error | Fix |
|---|---|
| `Attribute 'X' is not allowed to appear in element 'Y'` | Remove that attribute — not valid on that element |
| `element type "X" must be terminated by matching end-tag` | Malformed XML — check nested CDATA escaping |
| `Can't deserialize validation rules` | VALIDATOR `rules` CDATA contains invalid XML — check escaping and invalid attributes |
| `Syntax error on token 'function'` | CTL function declared as `returnType function name()` — flip to `function returnType name()` |
| `CTL code compilation finished with N errors` | CTL syntax error in transform, errorMapping, or denormalize attribute |

If validation fails, fix all errors and re-validate before proceeding. Do not present the graph as done while errors remain.

---

## CHECKLIST — before presenting the edit as complete

- [ ] Read the current graph file from the server before making any changes
- [ ] Fetched reference resources relevant to the change
- [ ] Checked sandbox for reference/example graphs if adding a new pattern
- [ ] Called `get_component_info` for any component being added or modified
- [ ] Called `get_component_details` for any complex component being added or modified
- [ ] No new non-existent components introduced (no ROUTER, no FILTER)
- [ ] All nested CDATA sequences correctly escaped (`]]]]><![CDATA[>`)
- [ ] No `customRejectMessage` on `<expression>` rule elements
- [ ] CTL user-defined functions: `function returnType name(...)` — not `returnType function name(...)`
- [ ] Edge outPort strings match exactly the names from `get_component_info`
- [ ] Metadata updated if the change requires new fields
- [ ] Re-read the file between multiple patches (never patch a stale copy)
- [ ] `validate_graph` called after the most recent write or patch
- [ ] Validation result is `overall: PASS` with no errors or warnings
