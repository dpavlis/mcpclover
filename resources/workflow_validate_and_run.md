# CloverDX Workflow Guide — `validate_and_run`

> Use this guide when the graph already exists and the task is to validate it,
> run it, and confirm correct results. Never run a graph that has not first
> passed validation.

---

## PHASE 1 — Validate the graph

### 1.1 Call `validate_graph`

```
validate_graph("graph/MyGraph.grf", sandbox)
```

Validation runs in two stages:
- **Stage 1** — local XML structure check (fast)
- **Stage 2** — server-side checkConfig (deep component check; only runs if Stage 1 passes)

**Validation may not be exhaustive.** Some errors block further checking,
so fixing reported issues and re-validating may reveal additional problems.
Repeat until `overall: PASS` with no problems.

### 1.2 Interpret the result

| Result | Meaning | Action |
|---|---|---|
| `overall: PASS`, no problems | Graph is fully valid | Proceed to execution |
| Stage 1 errors | XML structurally broken — graph won't open | Fix before anything else |
| Stage 2 ERROR | Component configuration invalid | Fix all errors — do not run |
| Stage 2 WARNING | CTL warning, metadata mismatch, etc. | Investigate — do not ignore |

**Do not proceed to execution if any errors or warnings are present.**

### 1.3 Diagnose validation errors using `think`
Before attempting a fix, always reason through the root cause:

```
think("Stage 2 error: 'Attribute customRejectMessage not allowed on expression'.
      This means an <expression> rule element has customRejectMessage which the
      schema doesn't allow. Fix: remove it and use the name attribute as the
      human-readable label instead.")
```

```
think("Stage 1 error at line 176: element type 'attr' must be terminated by
      matching end-tag. This is almost certainly a nested CDATA escaping problem
      in a VALIDATOR rules block — ]]> inside the outer CDATA must be escaped
      as ]]]]><![CDATA[>.")
```

### 1.4 Diagnose CTL-related errors
When validation reports CTL compilation errors, use `validate_CTL` if available
for a more detailed diagnosis. If `validate_CTL` is not available (user may have
disabled it), diagnose manually using the error message, the CTL2 reference
(`cloverdx://reference/ctl2`), and `think`.

**When `validate_CTL` is available:**

```
read_file("graph/MyGraph.grf", sandbox)    -- find the CTL block
validate_CTL(
    code="...extracted CTL...",
    input_metadata="Port 0 (orders):\n<Record name='OrderRecord'>...",
    output_metadata="Port 0 (output):\n<Record name='OutputRecord'>...",
    query="Focus on the compile error reported by validate_graph"
)
```

`validate_CTL` checks field references against metadata, type mismatches,
undeclared variables, scope issues, and logic errors — often pinpointing the
exact line and cause faster than reading the raw compile error.

**When `validate_CTL` is NOT available:**

Read the full compile error from `validate_graph`, extract the CTL block from
the graph file, and use `think` to diagnose. Cross-reference against the CTL2
reference for correct syntax, entry point signatures, and available built-in
functions. Fix the code, re-embed it, and re-validate.

#### Stage 1 — XML errors

| Error | Cause | Fix |
|---|---|---|
| `element type "X" must be terminated by matching end-tag` | Malformed XML | Check nested CDATA — inner `]]>` must be `]]]]><![CDATA[>` |
| `Can't deserialize validation rules` | Invalid XML inside VALIDATOR `rules` CDATA | Check nested CDATA escaping; check for invalid attributes on `<expression>` |
| General XML parse error at line N | Malformed XML | `read_file(..., start_line=N-5, line_count=15)` to inspect surrounding context |

#### Stage 2 — checkConfig errors

| Error | Fix |
|---|---|
| `Attribute 'X' is not allowed to appear in element 'Y'` | Remove that attribute (e.g. `customRejectMessage` not valid on `<expression>`) |
| `Syntax error on token 'function'` | CTL declared as `returnType function name()` — flip to `function returnType name()` |
| `Syntax error on token '('` | Same as above, partially corrected |
| `CTL code compilation finished with N errors` | Read full message, find the line, fix it — or use `validate_CTL` for detailed analysis |
| Port or metadata mismatch | Check edge `inPort`/`outPort` strings against `get_component_info` output |

### 1.5 Apply fixes safely
Back up before any significant fix:
```
copy_file("graph/MyGraph.grf", sandbox, "graph/MyGraph.bak.grf", sandbox)
```

Use `graph_edit_properties` for targeted attribute and CTL changes:
```
graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="ORDER_VALIDATOR",
    attribute_name="attr:rules", value="...corrected rules XML...")

graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="TRANSFORM",
    attribute_name="attr:transform", value="//#CTL2\n...")
```

Use `graph_edit_structure` for adding/deleting elements (Metadata, Node, Edge, Phase, etc.).
Use `patch_file` (with `dry_run=true` first) for non-graph text files.
Use `write_file` for large rewrites or when the file is already malformed.

After every fix, re-read the file before the next change, then re-validate:
```
validate_graph("graph/MyGraph.grf", sandbox)
```

Repeat until `overall: PASS`.

---

## PHASE 2 — Run the graph

### 2.1 Only run after a clean validation
Never call `execute_graph` while any validation error or warning is unresolved.

### 2.2 Find recent runs before executing (optional)
If you want to check whether the graph was already run recently or find a
previous `run_id` without executing again:

```
list_graph_runs(sandbox="DWHExample", job_file="MyGraph.grf")
list_graph_runs(sandbox="DWHExample", status="ERROR")   -- find recent failures
```

### 2.3 Execute the graph and await completion

```
run = execute_graph("graph/MyGraph.grf", sandbox)
await_graph_completion(run.run_id, timeout_seconds=120)
```

`await_graph_completion` blocks until the graph finishes or the timeout is
reached. On completion it returns the final status (`FINISHED_OK`, `ERROR`,
`ABORTED`). On timeout it returns the current status with `timed_out=true`.

For quick progress checks without waiting:
```
get_graph_run_status(run_id)
```
Returns status, elapsed time, and current phase when running.

To abort a graph that is stuck or taking too long:
```
abort_graph_execution(run_id)
```

### 2.4 When to use debug mode
Enable debug mode when you anticipate needing to inspect actual record values
at specific edges — not just counts:

```
run = execute_graph("graph/MyGraph.grf", sandbox, debug=True)
await_graph_completion(run.run_id)
```

Debug mode must be enabled at execution time — it cannot be added retroactively.
Enable it proactively when:
- The graph has complex filtering or routing logic you want to verify
- A previous run produced unexpected counts and you want to inspect the records
- You're running a new or recently edited graph for the first time

---

## PHASE 3 — Verify results

### 3.1 Always check tracking after execution

```
get_graph_tracking(run_id)
```

Check for every component:
- **Input record count** matches expected source volume
- **Output record count** is reasonable relative to input
- **No component shows 0 records unexpectedly** — a join producing 0 matched
  records or a filter dropping everything is almost always a logic error
- **Port split ratios are correct:**
  - VALIDATOR: valid + invalid = total input
  - EXT_FILTER: accepted + rejected = total input
  - PARTITION: sum of all output ports = total input

Use `think` to reason through unexpected counts before acting:
```
think("VALIDATOR shows 1000 input, 0 valid, 1000 invalid. That means every
      record is failing validation. Possible causes: wrong date format in
      the interval rule, wrong field name in a comparison rule, or an
      Order_Date field that arrives as string rather than date type.
      I should check the errorMapping output for the first few rejection
      reasons to understand which rule is failing.")
```

### 3.2 Check the execution log when something is wrong

```
get_graph_execution_log(run_id)
```

Read the log when:
- Run status is not `FINISHED_OK`
- Record counts are unexpected
- Any component reported an error or warning in tracking
- A runtime exception occurred (null dereference, type error, division by zero,
  file not found, DB connection failure)

The log contains per-component messages, full error stack traces, and timing.
Always identify the failing component and root cause before attempting a fix.

### 3.3 Inspect actual data with edge debug
Edge debug is one of the most powerful debugging tools — it lets you peek at the
actual records flowing through any edge, not just counts. Use it to verify that
field values, types, and content are what you expect at each stage of the graph.

**Always run with debug mode when investigating data issues:**
```
run = execute_graph("graph/MyGraph.grf", sandbox, debug=True)
await_graph_completion(run.run_id)
```

**Step 1 — confirm debug data is available on the edge:**
```
get_edge_debug_info(edge_id="Edge2", graph_path, sandbox, run_id)
```
Returns whether data was captured and the writer/reader node IDs.
Requires the graph was executed with `debug=True`.

**Step 2 — check the field schema on the edge:**
```
get_edge_debug_metadata(edge_id="Edge2", graph_path, sandbox, run_id)
```
Returns the metadata XML — field names and types. Use this to confirm the
record structure is what you expected (e.g. verify `rejectReason` is present,
check field types match what CTL code expects).

**Step 3 — fetch and inspect actual record values:**
```
get_edge_debug_data(run_id=run_id, edge_id="Edge2", record_count=20)
```
Returns actual record data from the edge. Use this to:
- Verify field values after a transform (are dates formatted correctly? are nulls
  handled? are computed fields correct?)
- Check what a join or filter is actually receiving and producing
- Inspect rejection reasons on a VALIDATOR's invalid port
- Compare values between two edges to diagnose why a join produces 0 matches
- Verify that CTL logic produces the expected output for real input data

**Typical debug workflow for a failing join:**
```
run = execute_graph("graph/MyGraph.grf", sandbox, debug=True)
await_graph_completion(run.run_id)
get_graph_tracking(run.run_id)                        -- confirm 0 output on join

get_edge_debug_data(run_id, edge_id="Edge0", record_count=5)  -- check master values
get_edge_debug_data(run_id, edge_id="Edge1", record_count=5)  -- check slave values

think("Master has Store_Id values 1,2,3. Slave has store_id values 'S001','S002'.
      The join key types don't match — master is integer, slave is string.
      Fix: either change metadata or add a conversion step.")
```

**When to use edge debug vs other approaches:**

| Need | Best tool |
|---|---|
| How many records flowed through each component | `get_graph_tracking` |
| Why the graph failed (exception, stack trace) | `get_graph_execution_log` |
| What fields and types exist on a specific edge | `get_edge_debug_metadata` |
| Inspect actual record values at a specific edge | `get_edge_debug_data` |
| Quick visual dump in the log | TRASH with `debugPrint="true"` |

### 3.4 Isolate problems by disabling components
When a graph has many components and the failure is hard to localize, disable
components to test parts of the graph in isolation. Every component has an
`enabled` attribute that controls its runtime behaviour.

**Three modes:**

| Mode | XML | Behaviour |
|---|---|---|
| Enabled (default) | `enabled="enabled"` | Component runs normally |
| Disabled (pass-through) | `enabled="disabled"` | Component is skipped; data flows through to the next component via pass-through ports |
| Disabled as Trash | `enabled="trash"` | Component and everything downstream is disabled; incoming data is discarded |

**Disable as Trash — isolate the first half of a graph:**
```
graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="ORDER_VALIDATOR",
    attribute_name="enabled", value="trash")
```
This makes the VALIDATOR and all components downstream of it inactive. The graph
runs only up to that point, so you can validate that the upstream data is correct
using `get_graph_tracking` and `get_edge_debug_data` on the edges before the
disabled component.

**Disable (pass-through) — skip a component but keep downstream running:**
```
graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="MY_FILTER",
    attribute_name="enabled", value="disabled")
```
The component is skipped and data passes straight through. Use this to test
whether a specific component (a filter, a transform, a join) is causing the
problem — if the graph works with it disabled, the issue is in that component.

By default, pass-through uses input port 0 and output port 0. If you need
data to flow through a different port pair, set:
```
graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="MY_COMPONENT",
    attribute_name="passThroughInputPort", value="0")
graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="MY_COMPONENT",
    attribute_name="passThroughOutputPort", value="1")
```

**After debugging, always re-enable the component:**
```
graph_edit_properties(graph_path, sandbox,
    element_type="Node", element_id="ORDER_VALIDATOR",
    attribute_name="enabled", value="enabled")
```

**Step-by-step debugging strategy:**
1. Disable later components as Trash to test the first stage only
2. Execute with debug mode, inspect edge data with `get_edge_debug_data`
3. If the first stage is correct, re-enable it and disable the next stage as Trash
4. Repeat until you find the stage where data goes wrong
5. Re-enable all components when debugging is complete

### 3.5 Diagnose CTL runtime errors
When a runtime error points to a CTL issue (null dereference, type mismatch,
wrong function call), extract the CTL code and diagnose the problem.

**When `validate_CTL` is available:**

```
validate_CTL(
    code="...extracted CTL from the failing component...",
    input_metadata="Port 0 (master):\n<Record>...",
    output_metadata="Port 0 (output):\n<Record>...",
    query="Focus on null handling and type coercions"
)
```

This can catch issues like inverted null checks, missing null guards on slave
ports, and field reference mismatches that cause runtime failures.

**When `validate_CTL` is NOT available:**

Extract the CTL block from the graph, read the runtime error message and stack
trace from `get_graph_execution_log`, and use `think` to reason through the
cause. Cross-reference against the CTL2 reference (`cloverdx://reference/ctl2`)
for correct function signatures, null handling patterns, and type coercion rules.
Fix the code, re-embed with `graph_edit_properties`, re-validate, and re-execute.

### 3.6 Common execution problems and diagnosis paths

| Symptom | Think / investigate |
|---|---|
| `FAILED` status | Log — find first ERROR entry; identify component and exception |
| 0 records on port that should have data | Check upstream component output count in tracking; check edge connectivity; check reader fileURL resolves to an existing file |
| 100% rejection rate (VALIDATOR) | Check errorMapping output file for rejection reasons; verify rule field names match metadata field names; verify field types (date vs string) |
| Join produces 0 matched records | Check joinKey field names on both ports; check that key field types match; verify sample values actually overlap between streams |
| More/fewer records than expected | Check filter conditions; check PARTITION routing logic; check REFORMAT return values |
| Records lost between two components | Tracking shows where count drops — inspect that component's configuration and CTL logic |
| Runtime error mid-stream | Log stack trace identifies component and record; check for null fields, type mismatches, missing sequence/lookup declarations |

### 3.7 Persist new knowledge
If debugging this run revealed a new insight — a component behaviour, a CTL
gotcha, or a configuration pattern worth remembering — store it:

```
kb_store(
    name="validator-date-format-mismatch",
    description="VALIDATOR date interval rules require date-typed fields, not strings parsed as dates",
    tags=["component", "validator", "date"],
    content="When a VALIDATOR interval rule checks a date field, the field must\n
             be typed as date in the metadata. If it arrives as a string,\n
             the comparison silently fails and all records are rejected.\n
             Fix: ensure the upstream component converts string to date,\n
             or use a <function> rule with str2date() instead of <interval>."
)
```

**What to store — generally reusable knowledge only:**
- Component behaviours that are non-obvious or underdocumented
  (e.g. VALIDATOR silently rejects all records when field type is string instead of date)
- CTL patterns, gotchas, or workarounds that apply broadly
  (e.g. multi-step parsing strategy for non-standard CSV with embedded delimiters)
- Correction of a wrong assumption that an LLM would likely make again
- Configuration interactions between component attributes that caused a subtle bug

**What NOT to store:**
- Step-by-step instructions for processing one specific file or dataset
  (e.g. "parse Acme_Orders_2026.csv by splitting on pipe then re-joining columns 3–5")
- Facts already in the reference docs or `get_component_info` output
- Task-specific metadata schemas, file paths, or connection details
- Anything that only applies to one particular graph and would not help in a
  different context

The test: *would this knowledge help someone building a completely different
graph that happens to use the same component or CTL pattern?* If yes, store it.
If it only helps re-build the exact same graph, skip it.

---

## CHECKLIST — validate and run complete

- [ ] `validate_graph` called — result is `overall: PASS` with no errors or warnings
- [ ] Used `think` to diagnose any validation errors before fixing
- [ ] Used `validate_CTL` for CTL compilation errors if available; otherwise diagnosed manually using error messages, CTL2 reference, and `think`
- [ ] All fixes used `graph_edit_properties` for attribute/CTL changes
- [ ] Backed up graph before significant fixes (`copy_file`)
- [ ] Re-read file between multiple fixes — never edited from stale state
- [ ] Re-validated after every fix — repeated until clean PASS
- [ ] `execute_graph` called only after clean validation
- [ ] `await_graph_completion` used to wait for execution result
- [ ] `get_graph_tracking` called after execution
- [ ] Input record count matches expected source size
- [ ] All port split ratios correct (valid + invalid = total, etc.)
- [ ] No component shows 0 records unexpectedly
- [ ] If run status not `FINISHED_OK`: `get_graph_execution_log` consulted and root cause identified
- [ ] Used `think` to reason through unexpected counts before attempting fixes
- [ ] Used `validate_CTL` to diagnose CTL runtime errors if available; otherwise diagnosed manually using execution log, CTL2 reference, and `think`
- [ ] If edge debug used: `get_edge_debug_info` confirmed data available first
- [ ] Used `get_edge_debug_data` to inspect actual record values at edges
- [ ] If isolating a problem: disabled components with `enabled="trash"` or `enabled="disabled"`
- [ ] All disabled components re-enabled after debugging
- [ ] Run status is `FINISHED_OK`
- [ ] Used `kb_store` to persist any new discoveries for future sessions
