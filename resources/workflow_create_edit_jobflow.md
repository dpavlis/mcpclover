# CloverDX Workflow Guide — `jobflow`

> LLM-only guide for authoring and editing CloverDX jobflows (`.jbf`).
> Jobflows are distinct from graphs: they are **token-driven orchestrators**
> where components execute **sequentially by default** — a token triggers A,
> A completes, the token passes to B. Parallelism is explicit (via `SIMPLE_COPY`
> or asynchronous execution), never implicit.

> **Completion rule:** the task is not done until `validate_graph` returns
> `overall: PASS` on the `.jbf` file. Fix every issue and re-validate until
> clean. This applies after every write, not just at the end.

> **Tooling note:** jobflows reuse the graph tooling. `validate_graph`,
> `execute_graph`, `get_graph_tracking`, `get_graph_execution_log`,
> `get_edge_debug_data`, `graph_edit_properties`, `graph_edit_structure`,
> `plan_graph`, and `generate_CTL` all accept `.jbf` paths. There is no
> separate jobflow-specific tool surface.

---

## PHASE 0 — Context

Before touching anything:

- **Read `cloverdx://reference/jobflow`.** This is mandatory for every jobflow
  task — training-data knowledge of jobflow semantics is usually wrong.
- Read `cloverdx://reference/graph-xml` and `cloverdx://reference/ctl2` as
  needed. Read `cloverdx://reference/subgraphs` if the jobflow runs subgraphs.
- Check the knowledge base (`kb_search`, `kb_read`) for prior jobflow-specific
  findings — CLO-8807, LOOP/BARRIER deadlock patterns, `skipCheckConfig`
  gotchas, dictionary handling.
- Resolve sandbox parameters up front — jobflows reference many path
  parameters (`${JOBFLOW_DIR}`, `${GRAPH_DIR}`, `${DATATMP_DIR}`, lock-file
  locations, working-dir roots).
- Clear session notes (`note_clear`).
- For non-trivial jobflows, delegate sandbox research to a sub-agent: the
  complexity of a jobflow comes from its interaction with its child graphs,
  so the sub-agent should gather the child graphs' public parameters,
  dictionary contracts, and any existing reference jobflows in the same
  sandbox. Avoid pulling raw jobflow XML into the main agent's context.

Never write into `wrangler_shared_home`.

---

## PHASE 1 — Identify the orchestration shape

Reason explicitly about the control flow before looking up components.
The questions that matter:

- What starts the flow? A single parameter-driven token (`GET_JOB_INPUT`),
  a file listing (`LIST_FILES`), a DB query, an incoming event?
- Is the work per-token iteration, parallel fan-out, a retry loop, or
  a fire-and-monitor?
- Where do failures go? Abort immediately, accumulate and abort at the end,
  retry, or log-and-continue?
- What must survive across steps on the token? What belongs in dictionary?
- What must be isolated in its own phase (locks, cleanup, late failure)?

Common shapes — use the closest match rather than inventing a new structure:

- **Sequential pipeline** — one token flows through N `EXECUTE_*` nodes in
  series, terminating at `SUCCESS`; error ports converge on `FAIL`.
- **File iteration** — `LIST_FILES` emits one token per file; `EXECUTE_GRAPH`
  runs per token, optionally with `executorsNumber > 1` for bounded parallel
  synchronous execution.
- **Async + monitor** — `EXECUTE_GRAPH` with `executionType="asynchronous"`
  starts children and returns immediately; `MONITOR_GRAPH` waits for each
  `runId` to complete.
- **Parallel + barrier** — `SIMPLE_COPY` forks the token; branches run
  independently; `BARRIER` waits for all to deliver exactly one token.
- **Retry loop** — `LOOP` body calls `EXECUTE_GRAPH` with
  `stopOnFail="false"` and `redirectErrorOutput="true"` so failures flow
  as data; a condition on the return edge exits when done or retries exhausted.
- **Lock-file mutual exclusion** — phase 0 `CREATE_FILES(lock, stopOnFail=false)`,
  work phases in between, last phase `DELETE_FILES(lock)` with error port to
  `TRASH` so a missing lock never blocks unlock.
- **Pre-flight check** — `LIST_FILES(lock, stopOnFail=false)`: found → `FAIL`,
  not found → proceed.
- **Dynamic routing** — child `jobURL` chosen per token from config; requires
  `skipCheckConfig="true"` on the `EXECUTE_*` node.
- **Logged wrapper** — `GET_JOB_INPUT → LOG_START → EXECUTE_GRAPH → LOG_FINISH → SUCCESS`
  with error branch to `LOG_ERROR → FAIL`.
- **Working-dir staging** — create a run-scoped working directory
  (`${WORKING_DIR}/wd_${RUN_ID}`), move inputs in, run the work, archive,
  then delete the directory.

Search the current sandbox for existing jobflows that use the same shape
(`grep_files` with `file_pattern="*.jbf"`, looking for component types or
distinctive attributes like `executionType="asynchronous"`). Read one or two
that match the pattern, then follow them — do not reinvent a solution that
already exists in the sandbox.

Call `get_component_info` for every orchestration component you plan to use.
Port names and default attribute values matter and are easy to get wrong from
memory. Record non-obvious decisions in notes so they survive into Phase 2.

### Orchestration components worth a reminder

| Task | Component | Notes |
|---|---|---|
| Run a child `.grf` / `.sgrf` | `EXECUTE_GRAPH` | Identical API to `EXECUTE_JOBFLOW` |
| Run a child `.jbf` | `EXECUTE_JOBFLOW` | Semantically clearer for jobflow targets |
| Wait for an async child | `MONITOR_GRAPH` / `MONITOR_JOBFLOW` | Only direct children are monitorable |
| Run a script per token | `EXECUTE_SCRIPT` | Same port pattern as `EXECUTE_GRAPH` |
| Fork one token into N | `SIMPLE_COPY` | Never `PARTITION` — that is a data-splitting component |
| Merge N branches into one | `SIMPLE_GATHER` / `TOKEN_GATHER` | Non-deterministic order; `TOKEN_GATHER` copies to all outputs |
| Wait for parallel branches | `BARRIER` | Every branch must deliver exactly one token or it deadlocks |
| Route by condition | `CONDITION` | Same semantics as `EXT_FILTER` |
| Retry / while | `LOOP` | Every token from output 1 must return to input 1 |
| Unconditional abort | `FAIL` | No input port — fires when its phase starts |
| Terminal success | `SUCCESS` | Optional mapping for log / output dict |
| Emit token from params | `GET_JOB_INPUT` | Prefer over `DATA_GENERATOR` when driven by params or input dict |
| Write to output dict | `SET_JOB_OUTPUT` | Later records overwrite earlier ones |
| Pause token | `SLEEP` | Unconnected in its own phase = phase-level pause |
| Kill by runId / group | `KILL_GRAPH` / `KILL_JOBFLOW` | Mass-kill requires `executionGroup` |
| Combine parallel tokens record-by-record | `COMBINE` | Use `incompleteTuples="true"` when branches can fail |

Components that do **not** exist and will fail validation: `ROUTER`, `FORK`,
`JOIN`, `WAIT`, `SCHEDULER`, `TRIGGER`, or any built-in `RETRY`. Retries are
built from `LOOP` plus error handling.

---

## PHASE 2 — Design

### Phases

Phases are control barriers: all components in phase *N* must finish before
any component in phase *N+1* starts. Use them when ordering matters across
parallel branches or when you need `finally`-like cleanup semantics.

A common shape is **phase 0 initialization / lock / pre-flight → middle
phases for the main work → last phase for cleanup** (delete temp files,
release lock, finalize statistics). A dedicated late-phase `FAIL` is another
useful idiom — it lets parallel work reach a clean stopping point before the
jobflow aborts.

Simple jobflows can legitimately use a single phase. Add phases deliberately,
not reflexively.

### Token record

Most edges carry a token record — user-defined metadata whose fields
accumulate state across steps. A few principles:

- Carry pass-through fields (filenames, IDs, timestamps, `runId`) that every
  step preserves via `$out.0.* = $in.0.*;` at the top of `outputMapping`.
- Include an accumulator (`map[string,long] jobStatistics` or similar) if
  counts / metrics need to be rolled up across steps on the token. This is
  often simpler than routing everything through dictionary.
- Include `runId` if you start async children and monitor them later.
- Don't over-engineer. Very simple jobflows can carry a one-field token.

### Dictionary — parent/child exchange

Parameters configure a child; dictionary passes values. For the jobflow you
are authoring, declare what it exposes upward. For every child you call, be
aware of its dictionary contract: an `input="true"` entry on the child is
addressable as `$out.2.<n>` in your `inputMapping`; an `output="true"`
entry is addressable as `$in.2.<n>` in your `outputMapping`.

**CLO-8807 — known bug.** Writing to a `map` dictionary entry that was
populated from upstream causes random crashes. Always copy a map input entry
into a separate output entry before modifying. Declare two entries
(`jobStatistics` with `input="true"`, `__jobStatistics` with `output="true"`)
and copy at the first opportunity.

### `EXECUTE_*` attribute defaults are often wrong

For every `EXECUTE_GRAPH` / `EXECUTE_JOBFLOW` / `EXECUTE_SCRIPT` node, make a
conscious decision about each of:

- `executionType` — synchronous by default; asynchronous when you want the
  parent to continue immediately and monitor later.
- `stopOnFail` — true by default; false when errors must be visible as data
  downstream (retry loops, accumulators, `redirectErrorOutput`).
- `executorsNumber` — 1 by default; set higher for bounded parallel
  synchronous execution.
- `timeout` — unlimited by default; set whenever a child could hang.
- `daemon` — false by default; true (with async) when the child must outlive
  the parent.
- `redirectErrorOutput` — false by default; true for try/finally (success
  and failure both reach port 0, distinguished via `$in.1.status`).
- `skipCheckConfig` — false by default; **true whenever `jobURL` is
  dynamically computed in inputMapping**, otherwise `checkConfig` will fail
  because the URL is empty at design time.
- `propagateParameters` — false by default; true to auto-pass matching
  public params to the child.
- `executionGroup` — set a tag when the child should be mass-killable.
- `executionLabel` — **set in `inputMapping` for every node that runs
  multiple iterations.** Without it, the Server execution history is an
  unreadable wall of identical rows.

### inputMapping / outputMapping shape

`inputMapping` has three output records: `$out.0` RunConfig, `$out.1`
JobParameters, `$out.2` Dictionary (child input entries).

`outputMapping` (and `errorMapping` if present) has four input records:
`$in.0` the incoming token, `$in.1` RunStatus, `$in.2` Dictionary (child
output entries), `$in.3` Tracking.

**Always begin `outputMapping` with `$out.0.* = $in.0.*;`.** Missing
pass-through is the single most common jobflow authoring mistake — upstream
token fields silently disappear.

### Error handling strategy

Every `EXECUTE_*` error port must be reasoned about. An unconnected error
port with `stopOnFail="true"` aborts the whole jobflow on any child failure,
which may leave locks, temp files, or partially-loaded tables behind. Pick
deliberately among the common patterns:

- Error port → `FAIL` (simple fail-fast).
- Error ports of parallel branches → `SIMPLE_GATHER` / `TOKEN_GATHER` →
  `FAIL` (collective abort).
- `stopOnFail="false"` + error port → `TRASH` (tolerate missing / non-critical
  failure, e.g. unlock that may find no lock).
- `redirectErrorOutput="true"` (try/finally — cleanup runs regardless).
- `stopOnFail="false"` + `redirectErrorOutput="true"` (retry loops — errors
  are data, not exceptions).
- Error port → log graph → `FAIL` (production wrapper with audit trail).

### Produce a plan

Call `plan_graph` with the jobflow layout — components, edges with
port-names taken from `get_component_info`, metadata for the token record,
global assets (parameters, any connections/lookups used by helper components),
and `risks[]`. `plan_graph` catches structural inconsistencies (dangling
edges, missing metadata, missing CTL entry points for mappings) before any
XML is written. It does **not** catch LOOP/BARRIER deadlock shapes, missing
`nature="jobflow"`, dictionary-direction mismatches, or the CLO-8807
workaround — those are your responsibility.

---

## PHASE 3 — Build and verify incrementally

The core principle: never build the whole jobflow and only then test.
Add one step, validate it, execute it, check token flow, then add the next.

A few points that matter specifically for jobflows:

- **`nature="jobflow"` on `<Graph>` is mandatory.** Without it, the file is
  treated as a regular graph and orchestration semantics are wrong. This is
  the single most common structural mistake.
- During incremental work, terminate the current in-progress branch at a
  `SUCCESS` node so the jobflow has a clean endpoint. Connect every
  in-progress error port somewhere (a temporary `FAIL`, or `stopOnFail="false"`)
  — unconnected error ports with `stopOnFail="true"` silently abort branches.
- After each incremental change: `validate_graph` (fix to `PASS`), then
  `execute_graph` + `await_graph_completion`, then `get_graph_tracking`.
- Tracking is how you catch token-flow errors. For every `EXECUTE_*` node:
  input count should equal `success-port count + error-port count`. If a
  token is missing, the child neither succeeded nor failed — usually an
  unhandled error route with `stopOnFail="true"` that aborted silently.
- Prefer `graph_edit_properties` / `graph_edit_structure` over raw patching
  for all jobflow modifications. CDATA auto-wrapping for `attr:*` changes
  avoids most escaping mistakes.
- Re-read the file between writes. Your in-context copy is stale the moment
  any write succeeds — jobflows are structurally complex enough that editing
  from a stale mental model creates orphaned edges and duplicated IDs.
- Use generous `timeout_seconds` on `await_graph_completion` — jobflows run
  every child end-to-end, so their wall-clock time is the sum of children
  plus overhead.
- For stuck runs (deadlocked LOOP or BARRIER), `abort_graph_execution` is
  the recovery path.

### Interpreting tracking for jobflows

In a jobflow, "records" are tokens and the failure modes are different from
a graph's. Things to look for:

- Token sources — does the count match expected iterations?
- BARRIER input ports — each branch must deliver exactly one token; otherwise
  BARRIER deadlocks.
- LOOP port 1 return — every token from output 1 must come back to input 1;
  mismatched counts mean token loss or duplication.
- SIMPLE_GATHER / TOKEN_GATHER fan-in — does the total match the sum of
  feeding branches?
- SUCCESS / FAIL — at least one must receive the final token.

When tracking is insufficient, run with `debug=True` and inspect actual
records via `get_edge_debug_data`. Debug mode is especially valuable for
diagnosing deadlocks (you can see which tokens reached which edges) and for
confirming dynamic `jobURL` values resolved correctly.

### Edge `outPort` strings

Use the exact strings from `get_component_info`. Jobflow orchestration
components use distinctive port names (`Port 0 (success)`, `Port 1 (error)`,
`Port 0 (true)`, `Port 1 (false)`, `Port 0 (exit)`, `Port 1 (body)`,
`Port 0 (return)`). `LIST_FILES` used as a lock-presence check has inverted
semantics: port 0 = found, port 1 = not found.

---

## PHASE 4 — Finalize

Replace scaffolding (temporary `SUCCESS` / `FAIL` terminals, `stopOnFail="false"`
placeholders) with the real routing, then run the full validate + execute +
tracking cycle one more time on the complete jobflow.

Add a `RichTextNote` with a short business-level description — what the
jobflow orchestrates, the phase breakdown if meaningful, and concurrency /
retry semantics if present. No component IDs or XML details; a couple of
sentences is enough.

If this task surfaced any reusable insight (a non-obvious orchestration
gotcha, a correction to a likely-wrong assumption, a pattern worth
remembering), persist it with `kb_store`. Prefer generality — store only
what would help on a different jobflow, not task-specific paths or schemas.

---

## Common pitfalls (not exhaustive)

- Missing `nature="jobflow"` on `<Graph>`.
- Missing `skipCheckConfig="true"` when `jobURL` is computed in inputMapping.
- Missing `$out.0.* = $in.0.*;` in `outputMapping` → token fields lost
  downstream.
- Missing `executionLabel` in inputMapping → unreadable Server run history.
- Unconnected error port with `stopOnFail="true"` → silent aborts.
- BARRIER / LOOP deadlock from asymmetric token flow.
- CLO-8807 — writing to a `map` dict entry populated from upstream without
  copying first.
- Dictionary direction mismatch (`input`/`output` flags) between parent
  jobflow and child graph.
- Async child killed when parent ends — needs `daemon="true"` or an explicit
  `MONITOR_GRAPH`.
- `COMBINE` deadlock when one parallel branch fails and exits via the error
  port — needs `incompleteTuples="true"`.

---

## Mapping skeletons

A few reusable patterns. Adapt rather than copying verbatim.

**Generic pass-through `outputMapping`:**
```ctl
//#CTL2
function integer transform() {
    $out.0.*         = $in.0.*;
    $out.0.jobStatus = $in.1.status;
    $out.0.runId     = $in.1.runId;
    return ALL;
}
```

**Dynamic `jobURL` with `executionLabel` and a passed child parameter:**
```ctl
//#CTL2
function integer transform() {
    $out.0.jobURL         = $in.0.workerUrl;
    $out.0.executionLabel = $in.0.fileName;
    $out.1.INPUT_FILE_URL = $in.0.fileUrl;
    $out.2.jobStartedAt   = $in.0.jobStartTime;
    return ALL;
}
```

**`errorMapping` that marks the token as ERROR and records message:**
```ctl
//#CTL2
function integer transform() {
    $out.0.*          = $in.0.*;
    $out.0.jobStatus  = "ERROR";
    $out.0.jobEndTime = today();
    $out.0.errorText  = join("\n", ["Child failed:", $in.1.errMessage]);
    return ALL;
}
```

**Capture `runId` from async start for later `MONITOR_GRAPH`:**
```ctl
//#CTL2
function integer transform() {
    $out.0.*     = $in.0.*;
    $out.0.runId = $in.1.runId;
    return ALL;
}
```

**LOOP retry condition on a retry counter:**
```ctl
//#CTL2
function integer transform() {
    $out.0.*                    = $in.0.*;
    $out.0.shouldContinue       = $in.0.currentRetryCounter < ${RETRY_COUNT}
                                  && $in.0.status != "FINISHED_OK";
    $out.0.currentRetryCounter  = $in.0.currentRetryCounter
                                  + ($out.0.shouldContinue ? 1 : 0);
    return ALL;
}
```

**CLO-8807 copy workaround (first CTL that touches the map dict entry):**
```ctl
//#CTL2
function integer transform() {
    $out.0.*                   = $in.0.*;
    dictionary.__jobStatistics = dictionary.jobStatistics;
    return ALL;
}
```

**`GET_JOB_INPUT` generating the initial token from parameters:**
```ctl
//#CTL2
function integer generate() {
    $out.0.fileName   = getParamValue("INPUT_FILE_NAME");
    $out.0.workingDir = getParamValue("WORKING_DIR") + "/wd_${RUN_ID}";
    $out.0.runId      = str2long(getParamValue("RUN_ID"));
    $out.0.startTime  = today();
    return OK;
}
```
