# CloverDX EXECUTE_GRAPH — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX EXECUTE_GRAPH (ExecuteGraph).
> Incorporates confirmed working patterns from MiscExamples and BasicFeatures sandboxes.
> EXECUTE_GRAPH is the standard component for launching `.grf` and `.sgrf` child jobs
> from a jobflow. It carries token records (not data records) and returns execution status.
> For launching `.jbf` child jobflows, see the EXECUTE_JOBFLOW reference.

---

## WHEN TO USE EXECUTE_GRAPH VS ALTERNATIVES

| Component | Use when |
|---|---|
| **EXECUTE_GRAPH** | **Default choice for running `.grf` or `.sgrf` from a jobflow.** Passes parameters, captures run status, supports synchronous and asynchronous execution, bounded parallel execution. |
| EXECUTE_JOBFLOW | Semantically identical API, but target is a `.jbf` jobflow. Use for clarity when the child is a jobflow. |
| EXECUTE_SCRIPT | Same port and mapping model. Use when the child is a script (shell, Groovy, Python), not a CloverDX graph. |
| MONITOR_GRAPH | Not a launcher — used to wait for a previously started async EXECUTE_GRAPH child. Accepts `runId` token. |
| KILL_GRAPH | Terminates a running child by `runId` or `executionGroup`. |

**Decision rule:** Use `EXECUTE_GRAPH` for any `.grf`/`.sgrf` child. If `jobURL` is computed dynamically at runtime, set `skipCheckConfig="true"` or validation will fail at design time.

---

## COMPONENT SKELETON

### Minimal — static jobURL, no token enrichment needed

```xml
<Node
  type="EXECUTE_GRAPH"
  id="PREPARE_REPORT"
  guiName="Prepare Report"
  guiX="590" guiY="352"
  jobURL="${GRAPH_DIR}/PrepareReport.grf"/>
```

No input/output port connections required. The component runs the graph and propagates
success or aborts the jobflow (default `stopOnFail="true"`).

### Static jobURL with parameter injection

```xml
<Node
  type="EXECUTE_GRAPH"
  id="LOAD_CUSTOMERS"
  guiName="Load customers"
  guiX="120" guiY="350"
  jobURL="${GRAPH_DIR}/LoadCustomers.grf">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.INPUT_FILE_URL = "${DATAIN_DIR}/Customers.csv";
    return ALL;
}
]]></attr>
</Node>
```

`$out.1` maps to the child's public parameters by name. No input port edge required.

### Dynamic jobURL with bounded parallel execution

```xml
<Node
  type="EXECUTE_GRAPH"
  id="RUN_INTEGRATION"
  guiName="Run integration"
  guiX="995" guiY="450"
  jobURL="${GRAPH_DIR}/Integration_Customers.grf"
  executorsNumber="2"
  skipCheckConfig="true"
  stopOnFail="false">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.jobURL         = "${GRAPH_DIR}/" + $in.0.processor;
    $out.0.executionLabel = $in.0.client + "|" + $in.0.filename;
    map[string,string] params;
    params["CLIENT"]         = $in.0.client;
    params["INPUT_FILE_URL"] = $in.0.fileURL;
    $out.0.jobParameters     = params;
    return ALL;
}
]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.*                 = $in.0.*;
    $out.0.jobStatus         = $in.1.status;
    $out.0.inputRecordCount  = $in.3.outputPort_0_INPUT_totalRecords;
    $out.0.outputRecordCount = $in.3.inputPort_0_OUTPUT_totalRecords;
    $out.0.errorCount        = $in.3.inputPort_0_ERRORS_totalRecords;
    return ALL;
}
]]></attr>
</Node>
```

### Asynchronous execution — launch and capture runId

```xml
<Node
  type="EXECUTE_GRAPH"
  id="START_WORKER"
  guiName="Start worker"
  guiX="345" guiY="225"
  jobURL="${GRAPH_DIR}/Worker.grf"
  executionType="asynchronous">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.INPUT_FILE_URL = "zip:(" + $in.0.URL + ")#log.txt";
    $out.0.executionLabel = $in.0.name;
    return ALL;
}
]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    $out.0.runId = $in.1.runId;
    return ALL;
}
]]></attr>
</Node>
```

Connect port 0 output to a `MONITOR_GRAPH` node to wait for completion.

---

## NODE-LEVEL ATTRIBUTES

### Target

| Attribute (XML) | Required | Description |
|---|---|---|
| `type="EXECUTE_GRAPH"` | yes | Component type |
| `jobURL` | yes* | Path to the target `.grf` or `.sgrf`. Use `${GRAPH_DIR}/...`. *Can be omitted if set dynamically in `inputMapping` — but then `skipCheckConfig="true"` is mandatory. |
| `skipCheckConfig` | no | **Must be `true` whenever `jobURL` is computed in `inputMapping`.** Without it, design-time checkConfig sees an empty URL and fails validation. Default: `false`. |
| `propagateParameters` | no | Auto-pass matching public parameters from parent to child by name. Default: `false`. Prefer explicit `inputMapping` for clarity. |

### Execution

| Attribute (XML) | Default | Description |
|---|---|---|
| `executionType` | `synchronous` | `synchronous`: block until child finishes. `asynchronous`: return immediately with `runId`; pipe to `MONITOR_GRAPH` to wait. |
| `executorsNumber` | `1` | Number of parallel synchronous instances. Token stream is divided across executors — up to N children run concurrently. |
| `timeout` | `0` (unlimited) | Milliseconds before the child is killed. Set whenever a child could hang. |
| `daemon` | `false` | `true`: async child is allowed to outlive the parent jobflow. Required for fire-and-forget async patterns. |
| `executionGroup` | — | Tag string for mass-kill via `KILL_GRAPH`. All children with the same group can be killed together. |
| `executionLabel` | — | Label displayed in Server run history per child instance. **Always set in `inputMapping` for iteration nodes.** Without it, run history is an unreadable wall of identical rows. |
| `clusterNodeId` | — | Pin execution to a specific cluster node. |
| `locale` | — | Override locale for child execution. |
| `timeZone` | — | Override time zone for child execution. |

### Error handling

| Attribute (XML) | Default | Description |
|---|---|---|
| `stopOnFail` | `true` | `true`: child failure aborts the jobflow (error port can be unconnected). `false`: failures flow as tokens to error port (port 1) — required for retry loops, accumulators, and tolerated failures. |
| `redirectErrorOutput` | `false` | `true`: both success and failure tokens flow to port 0. Distinguish by `$in.1.status` in `outputMapping`. Use for try/finally patterns where cleanup must run regardless of child outcome. |

### Mappings

| Attribute (XML) | Description |
|---|---|
| `inputMapping` | CTL2/CDATA. Maps the incoming token to RunConfig (`$out.0`), JobParameters (`$out.1`), and child dictionary inputs (`$out.2`). Executed before the child starts. |
| `outputMapping` | CTL2/CDATA. Maps child RunStatus and dictionary outputs back onto the outgoing token (port 0 — success). **Must begin with `$out.0.* = $in.0.*;`.** |
| `errorMapping` | CTL2/CDATA. Same shape as `outputMapping`. Applied on error port (port 1). If absent, raw RunStatus is forwarded. |

---

## MAPPINGS — THE CORE CONCEPT

EXECUTE_GRAPH has three distinct mapping stages: `inputMapping` (before child starts),
`outputMapping` (after child succeeds), and `errorMapping` (after child fails, when
`stopOnFail="false"`). Each stage has a different set of available `$in` and `$out` records.

### Port numbering in mappings

**inputMapping — `$out` records written by the LLM:**

| Record | Meaning | Key fields |
|---|---|---|
| `$out.0` | RunConfig | `jobURL`, `executionType`, `executionLabel`, `timeout`, `daemon`, `executionGroup`, `skipCheckConfig` |
| `$out.1` | JobParameters | Child's public parameters by name: `$out.1.PARAM_NAME = value` |
| `$out.2` | Dictionary (child input entries) | Child's `input="true"` dictionary entries by name |

**inputMapping — `$in` records available to the LLM:**

| Record | Meaning |
|---|---|
| `$in.0` | Incoming token record — all user-defined fields plus any injected RunConfig fields from upstream |

**outputMapping and errorMapping — `$in` records available to the LLM:**

| Record | Meaning |
|---|---|
| `$in.0` | Incoming token (same record that arrived at the input port) |
| `$in.1` | RunStatus of the completed child (see RunStatus fields below) |
| `$in.2` | Dictionary — child's `output="true"` dictionary entries by name |
| `$in.3` | Tracking — per-port record counts from the child run |

**outputMapping and errorMapping — `$out` records written by the LLM:**

| Record | Meaning |
|---|---|
| `$out.0` | Outgoing token record |

---

## INPUT MAPPING

### Setting child public parameters

```ctl
//#CTL2
function integer transform() {
    $out.1.INPUT_FILE_URL  = "${DATAIN_DIR}/Customers.csv";
    $out.1.CUSTOMER_COUNT  = "5000";
    return ALL;
}
```

`$out.1` fields correspond to public parameter names declared in the child graph.
Values are always strings (parameter type is string in the graph engine).

### Setting parameters as a map (for dynamic sets)

```ctl
//#CTL2
function integer transform() {
    map[string,string] params;
    params["CLIENT"]         = $in.0.client;
    params["INPUT_FILE_URL"] = $in.0.fileURL;
    $out.0.jobParameters     = params;
    return ALL;
}
```

Both approaches (`$out.1.PARAM` and `$out.0.jobParameters`) can be combined in the same mapping.

### Dynamic jobURL with executionLabel

```ctl
//#CTL2
function integer transform() {
    $out.0.jobURL         = "${GRAPH_DIR}/" + $in.0.processor;
    $out.0.executionLabel = $in.0.client + "|" + $in.0.filename;
    return ALL;
}
```

`jobURL` set via `$out.0` takes precedence over the static `jobURL` attribute.
`executionLabel` set here overrides the static attribute and appears per-row in Server history.

### Writing to child dictionary inputs

```ctl
//#CTL2
function integer transform() {
    $out.0.*           = $in.0.*;          // pass RunConfig fields through
    $out.2.startTime   = today();          // child dictionary input entry
    $out.2.runContext  = $in.0.context;
    return ALL;
}
```

---

## OUTPUT MAPPING

### Mandatory pass-through

```ctl
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;    // ALWAYS the first line — silently drops token fields if missing
    return ALL;
}
```

Omitting `$out.0.* = $in.0.*;` is the single most common and silent data-loss bug in jobflows.
Every upstream token field disappears without error.

### Capturing run status and tracking

```ctl
//#CTL2
function integer transform() {
    $out.0.*                  = $in.0.*;
    $out.0.jobStatus          = $in.1.status;
    $out.0.runId              = $in.1.runId;
    $out.0.duration           = $in.1.duration;
    $out.0.inputRecordCount   = $in.3.outputPort_0_INPUT_totalRecords;
    $out.0.outputRecordCount  = $in.3.inputPort_0_OUTPUT_totalRecords;
    $out.0.errorCount         = $in.3.inputPort_0_ERRORS_totalRecords;
    return ALL;
}
```

### `$in.1` RunStatus fields

| Field | Type | Description |
|---|---|---|
| `runId` | long | Child run ID. Required for `MONITOR_GRAPH` in async patterns. |
| `originalJobURL` | string | Resolved path of the job that was executed. |
| `submitTime` | date | Time the child was submitted to the server. |
| `startTime` | date | Time the child actually started executing. |
| `endTime` | date | Time the child finished. |
| `duration` | long | Wall-clock duration in milliseconds. |
| `executionGroup` | string | Execution group tag. |
| `executionLabel` | string | Execution label. |
| `status` | string | `FINISHED_OK`, `ERROR`, `ABORTED`, `TIMEOUT`, … |
| `errException` | string | Exception class name on failure. |
| `errMessage` | string | Human-readable error message on failure. |
| `errComponent` | string | Component ID where the failure occurred. |
| `errComponentType` | string | Component type where the failure occurred. |

### `$in.3` Tracking field naming pattern

Tracking fields follow the pattern: `{direction}Port_{index}_{componentId}_totalRecords`

```ctl
$in.3.outputPort_0_INPUT_totalRecords    // records read at child's INPUT component, port 0
$in.3.inputPort_0_OUTPUT_totalRecords    // records written at child's OUTPUT component, port 0
$in.3.inputPort_0_ERRORS_totalRecords    // error records at child's ERRORS component, port 0
```

The component ID part uses the actual node ID from the child graph (e.g. `DATA_READER`, `DB_OUTPUT`).
Use `get_graph_tracking` on a completed run to inspect the actual field names before hardcoding.

### Reading child dictionary output entries

```ctl
//#CTL2
function integer transform() {
    $out.0.*              = $in.0.*;
    $out.0.jobStatistics  = $in.2.jobStatistics;   // child output="true" dict entry
    return ALL;
}
```

---

## ERROR MAPPING

Same `$in` / `$out` structure as `outputMapping`. Applied when the child fails and
`stopOnFail="false"`. If `errorMapping` is absent, the raw RunStatus is forwarded to port 1.

### Typical error mapping — mark token and preserve context

```ctl
//#CTL2
function integer transform() {
    $out.0.*          = $in.0.*;
    $out.0.jobStatus  = "ERROR";
    $out.0.errorText  = $in.1.errMessage;
    $out.0.errorComp  = $in.1.errComponent;
    return ALL;
}
```

### `redirectErrorOutput="true"` — single output port for both outcomes

When `redirectErrorOutput="true"`, both success and failure tokens flow to port 0.
`outputMapping` handles both — distinguish by `$in.1.status`:

```ctl
//#CTL2
function integer transform() {
    $out.0.*         = $in.0.*;
    $out.0.jobStatus = $in.1.status;
    $out.0.errorText = ($in.1.status != "FINISHED_OK") ? $in.1.errMessage : "";
    return ALL;
}
```

Use this for try/finally patterns — the downstream cleanup node always receives a token
regardless of whether the child succeeded or failed.

---

## PORTS

| Port | Direction | XML string | Description |
|---|---|---|---|
| Port 0 | in (optional) | `Port 0 (in)` | Incoming token. One child execution per token. |
| Port 0 | out (optional) | `Port 0 (out)` | Success token — one per completed child. |
| Port 1 | out (optional) | `Port 1 (error)` | Failure token — only when `stopOnFail="false"`. |

All ports are optional. Without an input port, the component executes once.
Without output ports, success/failure only affects jobflow continuation (`stopOnFail`).

---

## TYPICAL GRAPH PATTERNS

### Sequential pipeline with phases (BasicFeatures/LoadDatabase.jbf)

Each `EXECUTE_GRAPH` node placed in a separate phase with no inter-component edges.
Phases enforce ordering: phase N completes before phase N+1 starts.

```xml
<Phase number="0">
  <Node type="EXECUTE_GRAPH" id="RECREATE_TABLES" jobURL="${GRAPH_DIR}/init/RecreateTables.grf"/>
</Phase>
<Phase number="3">
  <Node type="EXECUTE_GRAPH" id="LOAD_CUSTOMERS" jobURL="${GRAPH_DIR}/LoadCustomers.grf">
    <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.INPUT_FILE_URL = "${DATAIN_DIR}/Customers.csv";
    return ALL;
}
]]></attr>
  </Node>
  <Node type="EXECUTE_GRAPH" id="LOAD_PRODUCTS" jobURL="${GRAPH_DIR}/LoadProducts.grf">
    <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.INPUT_FILE_URL = "${DATAIN_DIR}/Products.csv";
    return ALL;
}
]]></attr>
  </Node>
</Phase>
```

LOAD_CUSTOMERS and LOAD_PRODUCTS run in parallel within phase 3 (no token edge between them).

### File iteration with bounded parallelism (MiscExamples/ProcessMultipleFiles.jbf)

```
LIST_FILES → EXT_FILTER → REFORMAT → EXT_HASH_JOIN → EXECUTE_GRAPH(executorsNumber=2) → AGGREGATE
```

One token per file flows through `EXECUTE_GRAPH` with `executorsNumber="2"`, running up to
2 children concurrently. Dynamic `jobURL` requires `skipCheckConfig="true"`.

```xml
<Node
  type="EXECUTE_GRAPH"
  id="RUN_INTEGRATION"
  jobURL="${GRAPH_DIR}/Integration_Customers.grf"
  executorsNumber="2"
  skipCheckConfig="true"
  stopOnFail="false">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.jobURL         = "${GRAPH_DIR}/" + $in.0.processor;
    $out.0.executionLabel = $in.0.client + "|" + $in.0.filename;
    map[string,string] params;
    params["CLIENT"]         = $in.0.client;
    params["INPUT_FILE_URL"] = $in.0.fileURL;
    $out.0.jobParameters     = params;
    return ALL;
}
]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.*                 = $in.1.*;
    $out.0.inputRecordCount  = $in.3.outputPort_0_INPUT_totalRecords;
    $out.0.outputRecordCount = $in.3.inputPort_0_OUTPUT_totalRecords;
    $out.0.errorCount        = $in.3.inputPort_0_ERRORS_totalRecords;
    $out.0.client            = $in.0.client;
    $out.0.filename          = $in.0.filename;
    $out.0.jobURL            = $in.1.originalJobURL;
    return ALL;
}
]]></attr>
</Node>
```

### Async fan-out + monitor (BasicFeatures/02b - Count visitors async.jbf)

```
LIST_FILES → EXECUTE_GRAPH(asynchronous) → MONITOR_GRAPH → SUCCESS
```

```xml
<Node type="EXECUTE_GRAPH" id="START_WORKERS"
      jobURL="${GRAPH_DIR}/CountVisitors.grf"
      executionType="asynchronous">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.INPUT_FILE_URL  = "zip:(" + $in.0.URL + ")#log.txt";
    $out.0.executionLabel  = $in.0.name;
    return ALL;
}
]]></attr>
</Node>
<Node type="MONITOR_GRAPH" id="MONITOR_WORKERS"
      jobURL="${GRAPH_DIR}/CountVisitors.grf">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.runId = $in.0.runId;
    return ALL;
}
]]></attr>
</Node>
```

`runId` from EXECUTE_GRAPH port 0 flows into MONITOR_GRAPH, which blocks until
each child completes and then emits a RunStatus token.

### Simple sequential chain (MiscExamples/ValidationReport.jbf)

```
EXECUTE_GRAPH(ValidateContacts) → EXECUTE_GRAPH(PrepareReport) → DELETE_FILES → SUCCESS
```

No `outputMapping` required when the token between steps needs no enrichment.
The injected RunStatus fields are available on the token automatically.

---

## EDGE DECLARATIONS

```xml
<!-- Token in -->
<Edge fromNode="UPSTREAM:0" id="Edge0" outPort="Port 0 (out)"
      inPort="Port 0 (in)" toNode="RUN_CHILD:0" metadata="MetaToken"/>

<!-- Success token out -->
<Edge fromNode="RUN_CHILD:0" id="Edge1" outPort="Port 0 (out)"
      inPort="Port 0 (in)" toNode="DOWNSTREAM:0" metadata="MetaToken"/>

<!-- Error token out (requires stopOnFail="false") -->
<Edge fromNode="RUN_CHILD:1" id="Edge2" outPort="Port 1 (error)"
      inPort="Port 0 (in)" toNode="ERROR_HANDLER:0" metadata="MetaToken"/>
```

---

## TOKEN RECORD DESIGN

Token metadata is user-defined. Fields accumulate state across steps. Recommended pattern:

```xml
<Record name="Token" type="delimited" fieldDelimiter="|" recordDelimiter="\n">
    <!-- Identity — fields used to select and label the child job -->
    <Field name="fileURL" type="string"/>
    <Field name="fileName" type="string"/>
    <Field name="client" type="string"/>
    <!-- Execution context — populated from RunStatus in outputMapping -->
    <Field name="runId" type="long" trim="true"/>
    <Field name="jobStatus" type="string"/>
    <Field name="duration" type="long" trim="true"/>
    <Field name="errorText" type="string"/>
    <!-- Metrics — populated from $in.3 tracking fields in outputMapping -->
    <Field name="inputRecordCount" type="long" trim="true"/>
    <Field name="outputRecordCount" type="long" trim="true"/>
    <Field name="errorCount" type="long" trim="true"/>
</Record>
```

---

## GENERATION RULES FOR LLM

Always include:
- `type="EXECUTE_GRAPH"`
- `jobURL` (static) OR dynamic `jobURL` in `inputMapping` — never both
- `skipCheckConfig="true"` whenever `jobURL` is dynamic
- `$out.0.* = $in.0.*;` as the first line of every `outputMapping`
- `executionLabel` set in `inputMapping` for any node that iterates over multiple tokens

When using parallel synchronous execution (`executorsNumber > 1`):
- The token stream is split across executors — each token runs one child instance
- Output order is non-deterministic

When using async execution:
- Set `daemon="true"` if the child must outlive the parent
- Always pipe port 0 to `MONITOR_GRAPH` to wait for completion
- Do not connect port 1 (no error port on async EXECUTE_GRAPH before the child finishes)

Error handling — decide for each node:
- `stopOnFail="true"` (default): unconnected error port, child failure aborts jobflow
- `stopOnFail="false"`: connect error port 1 to handle failures as tokens
- `redirectErrorOutput="true"`: both outcomes to port 0; `outputMapping` handles both

Parameter passing — two mechanisms:
- `$out.1.PARAM_NAME = value` for known, static parameter names
- `$out.0.jobParameters = myMap` for dynamic or computed parameter sets
- Both can coexist in the same `inputMapping`

Do NOT:
- Set `jobURL` statically AND override it in `inputMapping` — mapping wins but creates confusion
- Forget `skipCheckConfig="true"` for dynamic `jobURL` — validation fails at design time
- Omit `$out.0.* = $in.0.*;` in `outputMapping` — all upstream token fields silently disappear
- Leave error port unconnected when `stopOnFail="false"` — token is lost
- Use `EXECUTE_GRAPH` for `.jbf` targets in new code — use `EXECUTE_JOBFLOW` for clarity
- Set `executionLabel` as a static attribute for iteration nodes — it will be the same for every token; always set it in `inputMapping`

---

## COMMON MISTAKES

| Mistake | Correct approach |
|---|---|
| Dynamic `jobURL` without `skipCheckConfig="true"` | Add `skipCheckConfig="true"` whenever `jobURL` is set in `inputMapping` |
| Missing `$out.0.* = $in.0.*;` in `outputMapping` | Always make it the first line — it silently drops all upstream token fields if omitted |
| Static `executionLabel` on iteration node | Set `$out.0.executionLabel` in `inputMapping` — it must be per-token to be useful |
| Error port unconnected with `stopOnFail="true"` | Intentional (jobflow aborts on failure) — make it explicit by connecting to `FAIL` node |
| Error port unconnected with `stopOnFail="false"` | Connect to error handler, `TRASH`, or accumulator — unconnected loses the token |
| Using `$in.1.*` instead of `$in.0.*` in outputMapping pass-through | `$in.0` is the incoming token; `$in.1` is RunStatus — mixing them loses token fields |
| Forgetting `daemon="true"` for async fire-and-forget | Without it, async children are killed when the parent jobflow ends |
| Hardcoding `$in.3` tracking field names without checking | Use `get_graph_tracking` on a completed run to find the actual field names in the child |
| Passing `map[string,string]` to `$out.1` | `$out.1` expects scalar fields by parameter name; use `$out.0.jobParameters` for maps |
