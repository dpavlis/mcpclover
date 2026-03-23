# CloverDX Workflow Guide — `validate_and_run`

> Use this guide when the graph already exists and the task is to validate it, run it, and confirm correct results. Never run a graph that has not first passed validation.

---

## PHASE 1 — Validate the graph

### 1.1 Call `validate_graph`

```
validate_graph("graph/MyGraph.grf", sandbox)
```

Validation runs in two stages:
- **Stage 1** — local XML structure check (fast)
- **Stage 2** — server-side checkConfig (deep component check; only runs if Stage 1 passes)

### 1.2 Interpret the result

| Result | Meaning | Action |
|---|---|---|
| `overall: PASS`, no problems | Graph is fully valid | Proceed to execution |
| Stage 1 errors | XML is structurally broken — graph won't even open | Fix before anything else |
| Stage 2 ERROR | A component's configuration is invalid | Fix all errors — do not run |
| Stage 2 WARNING | Minor issue (CTL warning, metadata mismatch, etc.) | Investigate before running |

**Do not proceed to execution if any errors or warnings are present.**

### 1.3 Diagnose and fix validation errors

#### Stage 1 — XML errors
These are structural XML problems. Common causes and fixes:

| Error | Cause | Fix |
|---|---|---|
| `element type "X" must be terminated by matching end-tag` | Malformed XML | Check nested CDATA escaping — inner `]]>` must be written as `]]]]><![CDATA[>` |
| `Can't deserialize validation rules` | Invalid XML inside VALIDATOR `rules` CDATA | Check nested CDATA escaping; check for invalid attributes on `<expression>` elements |
| General XML parse error at line N | Malformed XML | Read the file, find line N, inspect surrounding context |

#### Stage 2 — checkConfig errors

| Error | Fix |
|---|---|
| `Attribute 'X' is not allowed to appear in element 'Y'` | Remove that attribute (e.g. `customRejectMessage` is not valid on `<expression>` elements) |
| `Syntax error on token 'function'` | CTL user-defined function declared as `returnType function name()` — flip to `function returnType name()` |
| `Syntax error on token '('` | Same as above, partially fixed |
| `CTL code compilation finished with N errors` | CTL syntax error — read the full error, find the line, fix the code |
| Port or metadata mismatch | Edge connects incompatible ports or mismatched metadata — check edge declarations and metadata definitions |

### 1.4 After fixing — always re-validate
After every `write_file` or `patch_file` fix, call `validate_graph` again. Repeat until `overall: PASS` with no problems.

If patching has corrupted the file further, switch to a clean `write_file` rather than continuing to patch.

---

## PHASE 2 — Run the graph

### 2.1 Only run after a clean validation
Never call `execute_graph` while any validation error or warning is unresolved.

### 2.2 Execute the graph

```
execute_graph("graph/MyGraph.grf", sandbox)
```

Note the `run_id` returned — it is needed for tracking and log retrieval.

---

## PHASE 3 — Verify results

### 3.1 Always check tracking after execution

```
get_graph_tracking(run_id)
```

Review record and byte counts on every port. Check:
- Input record count matches the expected source size
- For VALIDATOR graphs: valid count + rejected count = input count (no records lost)
- No component shows 0 input or output records unexpectedly
- No component shows significantly fewer records than expected without explanation

### 3.2 Check the execution log if anything looks wrong

```
get_graph_execution_log(run_id)
```

Read the log when:
- Run status is not SUCCESS
- Record counts are unexpected (e.g. more rejections than expected, 0 records somewhere)
- Any component reported an error or warning in the tracking output

The log contains per-component messages, error stack traces, and timing. Identify the failing component and the root cause before attempting a fix.

### 3.3 Edge-debug diagnostics (use with caution)

If tracking and execution log are not enough, you may inspect edge-debug metadata:

```
get_edge_debug_info(...)
get_edge_debug_metadata(...)
```

**Avoid `get_edge_debug_data` for now.** It returns CloverDX binary payload (CLVI format), which is not currently readable/interpretable by the LLM.
Prefer `get_graph_tracking` + `get_graph_execution_log` as the primary diagnostics path until a readable decoder is available.

### 3.4 Common execution problems and where to look

| Symptom | Where to investigate |
|---|---|
| Run status FAILED | Execution log — find the first ERROR entry |
| 0 records on a port that should have data | Check the upstream component's output count in tracking; check edge connectivity |
| More rejections than expected (VALIDATOR) | Check `rejectReason` field in the rejected output file; review VALIDATOR rules |
| Fewer records than expected at output | Check for unexpected filtering — review PARTITION logic, VALIDATOR rules, or REFORMAT return values |
| Records lost between components | Tracking will show where the count drops — inspect that component's configuration |

---

## CHECKLIST — validate and run complete

- [ ] `validate_graph` called and result is `overall: PASS` with no errors or warnings
- [ ] All Stage 1 and Stage 2 errors resolved before running
- [ ] `execute_graph` called only after clean validation
- [ ] `get_graph_tracking` called after execution
- [ ] Input record count matches expected source size
- [ ] Record counts across all ports are consistent and sensible
- [ ] If VALIDATOR is present: valid + rejected = total input
- [ ] If any counts are unexpected: `get_graph_execution_log` consulted and root cause identified
- [ ] `get_edge_debug_data` avoided for now (binary CLVI payload not LLM-readable)
- [ ] Run status is SUCCESS
