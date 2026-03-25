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
| `CTL code compilation finished with N errors` | Read full message, find the line, fix it |
| Port or metadata mismatch | Check edge `inPort`/`outPort` strings against `get_component_info` output |

### 1.4 Apply fixes safely
Back up before any significant fix:
```
copy_file("graph/MyGraph.grf", sandbox, "graph/MyGraph.bak.grf", sandbox)
```

Use `set_graph_element_attribute` for targeted attribute and CTL changes:
```
set_graph_element_attribute(graph_path, sandbox,
    element_type="Node", element_id="ORDER_VALIDATOR",
    attribute_name="attr:rules", value="...corrected rules XML...")

set_graph_element_attribute(graph_path, sandbox,
    element_type="Node", element_id="TRANSFORM",
    attribute_name="attr:transform", value="//#CTL2\n...")
```

Use `patch_file` (with `dry_run=true` first) for structural additions.
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

### 2.3 Execute the graph

```
result = execute_graph("graph/MyGraph.grf", sandbox)
```

Note the `run_id` — needed for tracking, log retrieval, and debug data.

For long-running graphs, poll status without fetching the full log:
```
get_graph_run_status(run_id)
```
Returns status (`RUNNING`, `FINISHED_OK`, `ERROR`, `ABORTED`) plus elapsed time
and current phase when running. Use to assess progress before committing to a
full log fetch.

### 2.4 When to use debug mode
Enable debug mode when you anticipate needing to inspect actual record values
at specific edges — not just counts:

```
result = execute_graph("graph/MyGraph.grf", sandbox, debug=True)
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

### 3.3 Edge debug diagnostics — when and how
When tracking counts and the execution log don't pinpoint the problem and you
need to inspect actual record values at a specific edge:

**Step 1 — confirm debug data is available:**
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

**Step 3 — fetch record count and summary:**
```
get_edge_debug_data(run_id=run_id, edge_id="Edge2", record_count=20)
```

`get_edge_debug_data` calls `/data-service/debugRead` using `runID` and `edgeID`
and returns the JSON output from that endpoint.

**When to use edge debug vs other approaches:**

| Need | Best tool |
|---|---|
| How many records flowed through each component | `get_graph_tracking` |
| Why the graph failed | `get_graph_execution_log` |
| What fields exist on a specific edge | `get_edge_debug_metadata` |
| Read sample values from a specific edge | `get_edge_debug_data` |
| Debug output file inspection fallback | Read output file, or re-run with `TRASH debugPrint=true` on the edge |

### 3.4 Common execution problems and diagnosis paths

| Symptom | Think / investigate |
|---|---|
| `FAILED` status | Log — find first ERROR entry; identify component and exception |
| 0 records on port that should have data | Check upstream component output count in tracking; check edge connectivity; check reader fileURL resolves to an existing file |
| 100% rejection rate (VALIDATOR) | Check errorMapping output file for rejection reasons; verify rule field names match metadata field names; verify field types (date vs string) |
| Join produces 0 matched records | Check joinKey field names on both ports; check that key field types match; verify sample values actually overlap between streams |
| More/fewer records than expected | Check filter conditions; check PARTITION routing logic; check REFORMAT return values |
| Records lost between two components | Tracking shows where count drops — inspect that component's configuration and CTL logic |
| Runtime error mid-stream | Log stack trace identifies component and record; check for null fields, type mismatches, missing sequence/lookup declarations |

---

## CHECKLIST — validate and run complete

- [ ] `validate_graph` called — result is `overall: PASS` with no errors or warnings
- [ ] Used `think` to diagnose any validation errors before fixing
- [ ] All fixes used `set_graph_element_attribute` for attribute/CTL changes
- [ ] Backed up graph before significant fixes (`copy_file`)
- [ ] Re-read file between multiple fixes — never edited from stale state
- [ ] Re-validated after every fix — repeated until clean PASS
- [ ] `execute_graph` called only after clean validation
- [ ] `get_graph_tracking` called after execution
- [ ] Input record count matches expected source size
- [ ] All port split ratios correct (valid + invalid = total, etc.)
- [ ] No component shows 0 records unexpectedly
- [ ] If run status not `FINISHED_OK`: `get_graph_execution_log` consulted and root cause identified
- [ ] Used `think` to reason through unexpected counts before attempting fixes
- [ ] If edge debug used: `get_edge_debug_info` confirmed data available first
- [ ] Used `get_edge_debug_data` to inspect edge records decoded by `debugRead`
- [ ] Run status is `FINISHED_OK`
